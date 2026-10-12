"""
仔仔猫 Web UI — 下载引擎

从 app.py 提取的批量下载逻辑，增强容错重试和暂停控制。

核心改进:
- 单集失败不中断整个任务，自动跳到下一集
- 全部完成后自动重试失败项（最多 3 次，递增延迟）
- 通过 TaskSignal.pause_event 支持暂停/恢复
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

from zaizaimao.models.config import resolve_download_dir
from zaizaimao.utils import detect_platform, parse_episode_range, sanitize_filename, URLParseError

if TYPE_CHECKING:
    from zaizaimao.webui.task_manager import TaskSignal

# ── 平台信息 ──

PLATFORM_INFO = {
    "dramashorts": {"name": "DramaShorts", "domain": "dramashorts.io", "accent": "#4ade80"},
    "shortmax": {"name": "ShortMax", "domain": "shorttv.live", "accent": "#4ade80"},
    "tiktok": {"name": "TikTok", "domain": "tiktok.com", "accent": "#60a5fa"},
}

# 重试退避延迟（秒）
RETRY_BACKOFF = [5, 15, 30]


def _is_cancelled(task_id: str) -> bool:
    """检查任务是否已被取消（供下载引擎内部轮询）"""
    from zaizaimao.webui.task_manager import TaskManager
    return TaskManager.get().is_cancelled(task_id)


# ═══════════════════════════════════════════════════════════
#  下载入口
# ═══════════════════════════════════════════════════════════

async def execute_download(
    task_id: str,
    urls: list[str],
    out_dir: str,
    episode_range: str,
    signal: TaskSignal,
    max_retries: int = 3,
) -> None:
    """执行一个下载任务（被 TaskManager worker 调用）。

    处理流程:
    1. 遍历每个 URL，对每个 URL 执行批量下载
    2. 单个剧集失败 → 收集到失败列表，继续下一个
    3. 全部完成后 → 重试失败剧集（max_retries 次）
    4. 最终更新任务状态
    """
    log = signal.log_callback
    progress = signal.progress_callback
    ep_cb = signal.episode_callback
    pause = signal.pause_event

    if not urls:
        log("error", "没有可下载的链接")
        return

    log("info", f"任务开始 — 共 {len(urls)} 个链接")

    # 全局失败收集: {url_index: [episode_number, ...]}
    all_failed: dict[int, list[int]] = {}
    all_completed = 0
    all_total = 0

    # ── 剧集去重: 「全部」+ 多个链接 → 只发现/下载一次（所有平台）──
    ep_range_lower = episode_range.strip().lower() if episode_range else ""
    skip_indices: set[int] = set()  # 已通过去重处理的 URL 索引，主循环跳过

    if ep_range_lower in ("全部", "all", ""):
        # 短剧平台（DramaShorts / ShortMax）: 按 movie_id 直接去重
        seen_dramas: dict[tuple[str, str], int] = {}  # (platform, movie_id) -> first_idx
        tiktok_idxs: list[int] = []

        for i, u in enumerate(urls):
            try:
                p = detect_platform(u)
            except URLParseError:
                continue

            if p == "tiktok":
                tiktok_idxs.append(i)
            else:
                mid = _extract_movie_id(u, p) or u
                key = (p, mid)
                if key in seen_dramas:
                    skip_indices.add(i)  # 同剧重复链接，跳过
                else:
                    seen_dramas[key] = i

        if len(tiktok_idxs) > 1:
            first_tiktok_url = urls[tiktok_idxs[0]]
            log("info",
                f"检测到 {len(tiktok_idxs)} 条 TikTok 链接 + 全部模式，"
                f"将用第一条发现整部剧并跳过其余 {len(tiktok_idxs)-1} 条重复链接")

            from zaizaimao.core.tiktok_dl import (
                TikTokDownloader as _TDedup,
                detect_proxy as _detect_proxy_dedup,
                extract_tiktok_series,
            )

            proxy_dedup = await _detect_proxy_dedup()
            dl_dedup = _TDedup(proxy=proxy_dedup, auto_cdp=True)
            await dl_dedup.ensure_cookies()
            ck = dl_dedup.cookies_file if dl_dedup.has_cookies else None

            try:
                discovered = await extract_tiktok_series(
                    first_tiktok_url, cookies_file=ck, proxy=proxy_dedup
                )
            except Exception as exc:
                log("warn", f"去重剧集发现失败: {exc}")
                discovered = None

            if discovered and len(discovered) > 1:
                selected = parse_episode_range(
                    ep_range_lower, len(discovered), default_ep=1
                )
                dedup_urls = [discovered[i - 1] for i in selected]
                log("success", f"发现短剧系列 {len(discovered)} 集")

                completed, failed_eps = await _tiktok_download(
                    first_tiktok_url, out_dir, episode_range, signal, 0, 1,
                    pre_discovered_urls=dedup_urls,
                )
                all_completed += completed
                if failed_eps:
                    # 保留第一条 URL 的索引供后续重试段使用
                    all_failed[tiktok_idxs[0]] = failed_eps

                # 标记所有 TikTok URL 已处理（保留列表不动，供重试段查询原始 URL）
                skip_indices.update(tiktok_idxs)

        # 日志：短剧平台去重（TikTok 去重已在上面单独日志）
        drama_skipped = sum(
            1 for i in skip_indices if i not in set(tiktok_idxs)
        )
        if drama_skipped > 0:
            log("info", f"短剧平台去重: 跳过 {drama_skipped} 条同剧重复链接")

    for idx, url in enumerate(urls):
        if idx in skip_indices:
            continue  # 已通过去重一次性处理
        # ── 暂停检查 ──
        await pause.wait()
        # ── 取消检查 ──
        if _is_cancelled(task_id):
            log("warn", "任务已取消，停止下载")
            return

        log("info", f"===== [{idx+1}/{len(urls)}] {url[:80]}... =====")

        try:
            platform = detect_platform(url)
        except URLParseError as e:
            log("error", str(e))
            continue

        if platform == "tiktok":
            completed, failed_eps = await _tiktok_download(
                url, out_dir, episode_range, signal, idx, len(urls)
            )
        else:
            completed, failed_eps, total = await _drama_download(
                url, platform, out_dir, episode_range, signal, idx, len(urls)
            )

        if failed_eps:
            all_failed[idx] = failed_eps
        all_completed += completed
        if platform != "tiktok":
            all_total += total

    # ── 重试失败剧集 ──
    if all_failed:
        total_failed = sum(len(v) for v in all_failed.values())
        log("warn", f"===== 第一轮完成，共 {total_failed} 集失败，开始重试 =====")

        for retry in range(max_retries):
            if not all_failed:
                break
            delay = RETRY_BACKOFF[min(retry, len(RETRY_BACKOFF) - 1)]
            log("info", f"重试第 {retry+1}/{max_retries} 轮（等待 {delay}s）...")
            await asyncio.sleep(delay)

            # ── 暂停检查 ──
            await pause.wait()
            # ── 取消检查 ──
            if _is_cancelled(task_id):
                log("warn", "任务已取消，停止重试")
                return

            for url_idx in list(all_failed.keys()):
                if not all_failed[url_idx]:
                    del all_failed[url_idx]
                    continue

                url = urls[url_idx]
                platform = detect_platform(url)
                failed_eps = all_failed[url_idx]

                if platform == "tiktok":
                    # TikTok 重试简化处理
                    still_failed = []
                    for ep_num in failed_eps:
                        await pause.wait()
                        # ── 取消检查 ──
                        if _is_cancelled(task_id):
                            log("warn", "任务已取消，停止重试")
                            return
                        try:
                            await _tiktok_single_download(url, out_dir, ep_num, signal)
                            # 重试成功后也执行响度归一化
                            tiktok_name = "tiktok"
                            m = re.search(r'@([^/?]+)', url)
                            if m:
                                tiktok_name = sanitize_filename(m.group(1), max_len=30)
                            retry_out = Path(out_dir) / f"{tiktok_name}-{ep_num:02d}.mp4"
                            if retry_out.exists():
                                await _normalize_audio_if_enabled(retry_out, log)
                            log("success", f"重试成功: 第 {ep_num} 集")
                            all_completed += 1
                        except Exception as e:
                            log("warn", f"重试失败: 第 {ep_num} 集 — {e}")
                            still_failed.append(ep_num)
                    all_failed[url_idx] = still_failed
                else:
                    still_failed = await _drama_retry_failed(
                        url, platform, out_dir, failed_eps, signal
                    )
                    for ep in failed_eps:
                        if ep not in still_failed:
                            all_completed += 1
                    all_failed[url_idx] = still_failed

                # 更新进度
                remaining = sum(len(v) for v in all_failed.values())
                ep_cb(all_completed, all_total, remaining, _flatten_failed(all_failed))

        # 最终报告
        final_failed = sum(len(v) for v in all_failed.values())
        if final_failed > 0:
            log("warn", f"===== 重试完成: {final_failed} 集最终失败 =====")
            for url_idx, eps in all_failed.items():
                if eps:
                    log("error", f"链接 [{url_idx+1}]: 第 {', '.join(str(e) for e in eps)} 集 下载失败")

    # ── 更新最终状态 ──
    final_failed = sum(len(v) for v in all_failed.values())
    ep_cb(all_completed, all_total, final_failed, _flatten_failed(all_failed))

    if final_failed > 0 and all_completed > 0:
        status = "partial"
        log("info", f"===== 任务完成 (部分成功): 成功 {all_completed}, 失败 {final_failed} =====")
    elif final_failed > 0 and all_completed == 0:
        status = "failed"
        log("error", f"===== 任务失败: 全部 {final_failed} 集下载失败 =====")
    else:
        status = "completed"
        log("success", f"===== 任务完成: 全部 {all_completed} 集下载成功 =====")

    # 更新数据库状态
    from zaizaimao.webui import history_store
    history_store.update_task(task_id, status=status)
    progress(1.0)


# ═══════════════════════════════════════════════════════════
#  短剧平台下载（DramaShorts / ShortMax）
# ═══════════════════════════════════════════════════════════

async def _drama_download(
    url: str,
    platform: str,
    out_dir: str,
    episode_range: str,
    signal: TaskSignal,
    url_idx: int = 0,
    total_urls: int = 1,
) -> tuple[int, list[int], int]:
    """下载短剧平台的剧集。

    Returns:
        (completed_count, failed_episode_numbers, total_episodes)
    """
    log = signal.log_callback
    progress = signal.progress_callback
    ep_cb = signal.episode_callback
    pause = signal.pause_event

    AdapterClass = _import_adapter(platform)
    adapter = AdapterClass()

    await pause.wait()

    try:
        first_ep = await adapter.parse_url(url)
    except Exception as e:
        log("error", f"解析 URL 失败: {e}")
        return 0, [], 0

    movie_id = first_ep.movie_id
    log("info", "正在获取剧集列表...")

    await pause.wait()

    try:
        all_episodes = await adapter.get_episode_list(movie_id)
    except Exception as e:
        log("error", f"获取剧集列表失败: {e}")
        return 0, [], 0

    if not all_episodes:
        log("error", "未找到任何剧集")
        return 0, [], 0

    total_available = len(all_episodes)
    movie_title = all_episodes[0].movie_title or movie_id
    log("info", f"剧名: {movie_title}  |  共 {total_available} 集")

    selected = parse_episode_range(episode_range, total_available, first_ep.episode_number)
    total = len(selected)
    desc = f"将下载 {total} 集 (第 {selected[0]}-{selected[-1]} 集)" if total > 1 else f"将下载第 {selected[0]} 集"
    log("info", desc)

    progress(0.03)
    ep_cb(0, total, 0, [])

    from zaizaimao.core.hls import HLSEngine
    out_path = Path(out_dir)
    safe_title = sanitize_filename(movie_title, max_len=50)

    hls_proxy = getattr(adapter, '_proxy_url', None) or None
    if hls_proxy:
        log("info", f"HLS 代理: {hls_proxy}")

    ok = 0
    failed_eps: list[int] = []

    for idx, ep_num in enumerate(selected):
        # ── 暂停检查 ──
        await pause.wait()
        # ── 取消检查 ──
        if _is_cancelled(signal.task_id):
            log("warn", "任务已取消，停止下载")
            break

        target = next((e for e in all_episodes if e.episode_number == ep_num), None)
        if not target:
            log("warn", f"[{idx+1}/{total}] 第 {ep_num} 集不存在，跳过")
            failed_eps.append(ep_num)
            continue

        prefix = f"[{idx+1}/{total}]"
        log("info", f"{prefix} 第 {ep_num} 集 — 获取播放信息...")

        try:
            playback = await adapter.get_playback(target)
        except Exception as e:
            log("error", f"{prefix} 第 {ep_num} 集 — {e}")
            failed_eps.append(ep_num)
            ep_cb(ok, total, len(failed_eps), failed_eps)
            continue

        if not playback.manifest_url:
            log("error", f"{prefix} 第 {ep_num} 集 — 无播放地址")
            failed_eps.append(ep_num)
            ep_cb(ok, total, len(failed_eps), failed_eps)
            continue

        out_file = out_path / f"{safe_title}-{ep_num:02d}.mp4"
        log("info", f"{prefix} 第 {ep_num} 集 — 下载中: {out_file.name}")

        base = 0.03 + (idx / total) * 0.92

        def make_cb(b, t):
            def cb(cur: int, tot: int):
                if tot > 0:
                    progress(min(b + (cur / tot) * (0.92 / t), 0.98))
            return cb

        # ── 创建 pause_check 回调 ──
        async def _pause_check():
            await pause.wait()

        engine = HLSEngine(progress_callback=make_cb(base, total))
        try:
            result = await engine.download(
                playback.manifest_url, str(out_file),
                headers=playback.headers,
                proxy=hls_proxy,
                pause_check=_pause_check,
            )
            mb = Path(result).stat().st_size / 1024 / 1024
            await _normalize_audio_if_enabled(Path(result), log)
            log("success", f"{prefix} 第 {ep_num} 集 — 完成 ({mb:.1f} MB)")
            ok += 1
        except Exception as e:
            log("error", f"{prefix} 第 {ep_num} 集 — 下载失败: {e}")
            failed_eps.append(ep_num)

        ep_cb(ok, total, len(failed_eps), failed_eps)
        # 兜底：基于循环进度更新，确保进度条与集数进展一致
        progress(0.03 + ((idx + 1) / total) * 0.95)

    progress(1.0 if not failed_eps else 0.98)
    result_msg = f"===== 完成: 成功 {ok}/{total} =====" if ok == total else f"===== 完成: 成功 {ok}, 失败 {len(failed_eps)} ====="
    log("info", result_msg)

    return ok, failed_eps, total


async def _drama_retry_failed(
    url: str,
    platform: str,
    out_dir: str,
    failed_eps: list[int],
    signal: TaskSignal,
) -> list[int]:
    """重试短剧平台失败的剧集。

    Returns:
        仍然失败的剧集列表
    """
    log = signal.log_callback
    pause = signal.pause_event

    AdapterClass = _import_adapter(platform)
    adapter = AdapterClass()

    await pause.wait()

    try:
        first_ep = await adapter.parse_url(url)
        all_episodes = await adapter.get_episode_list(first_ep.movie_id)
    except Exception as e:
        log("error", f"重试准备失败: {e}")
        return list(failed_eps)

    movie_title = all_episodes[0].movie_title or first_ep.movie_id
    safe_title = sanitize_filename(movie_title, max_len=50)
    out_path = Path(out_dir)

    hls_proxy = getattr(adapter, '_proxy_url', None) or None

    still_failed: list[int] = []

    for ep_num in failed_eps:
        await pause.wait()
        # ── 取消检查 ──
        if _is_cancelled(signal.task_id):
            log("warn", "任务已取消，停止重试")
            break

        target = next((e for e in all_episodes if e.episode_number == ep_num), None)
        if not target:
            log("warn", f"重试: 第 {ep_num} 集不存在")
            still_failed.append(ep_num)
            continue

        log("info", f"重试: 第 {ep_num} 集...")

        try:
            playback = await adapter.get_playback(target)
        except Exception as e:
            log("warn", f"重试: 第 {ep_num} 集 — 获取播放信息失败: {e}")
            still_failed.append(ep_num)
            continue

        if not playback.manifest_url:
            still_failed.append(ep_num)
            continue

        out_file = out_path / f"{safe_title}-{ep_num:02d}.mp4"

        async def _pause_check():
            await pause.wait()

        from zaizaimao.core.hls import HLSEngine
        engine = HLSEngine()
        try:
            await engine.download(
                playback.manifest_url, str(out_file),
                headers=playback.headers,
                proxy=hls_proxy,
                pause_check=_pause_check,
            )
            mb = Path(out_file).stat().st_size / 1024 / 1024
            await _normalize_audio_if_enabled(out_file, log)
            log("success", f"重试成功: 第 {ep_num} 集 ({mb:.1f} MB)")
        except Exception as e:
            log("error", f"重试失败: 第 {ep_num} 集 — {e}")
            still_failed.append(ep_num)

    return still_failed


# ═══════════════════════════════════════════════════════════
#  TikTok 下载
# ═══════════════════════════════════════════════════════════

async def _tiktok_download(
    url: str,
    out_dir: str,
    episode_range: str,
    signal: TaskSignal,
    url_idx: int = 0,
    total_urls: int = 1,
    pre_discovered_urls: list[str] | None = None,
) -> tuple[int, list[int]]:
    """TikTok 视频下载。

    Args:
        pre_discovered_urls: 预发现的剧集 URL 列表。
            传入后跳过 auto-discover，直接使用此列表。
            用于多 URL +「全部」模式的去重。

    Returns:
        (completed_count, failed_episode_numbers)
    """
    log = signal.log_callback
    progress = signal.progress_callback
    ep_cb = signal.episode_callback
    pause = signal.pause_event

    from zaizaimao.core.tiktok_dl import TikTokDownloader, detect_proxy, extract_tiktok_series

    # 自动发现剧集
    ep_range_str = episode_range.strip().lower() if episode_range else ""
    is_auto_discover = ep_range_str in ("全部", "all", "")

    await pause.wait()

    proxy = await detect_proxy()
    if proxy:
        log("info", f"代理: {proxy}")
    else:
        log("warn", "未检测到代理，可能需要科学上网")

    downloader = TikTokDownloader(proxy=proxy, auto_cdp=True)
    if not downloader.is_ready:
        log("error", "yt-dlp 未找到，请下载 yt-dlp.exe 放到项目根目录")
        return 0, []

    # 获取 Cookie
    cookie_ok = downloader.has_cookies
    if not cookie_ok:
        log("info", "正在通过 Chrome 获取 TikTok Cookie...")
        cookie_ok = await downloader.ensure_cookies()
        if cookie_ok:
            log("success", "已从 Chrome 获取 Cookie")
        else:
            log("warn", "未获取到 Cookie，下载可能失败")

    await pause.wait()

    # 剧集发现
    if pre_discovered_urls is not None:
        all_urls = pre_discovered_urls
        log("info", f"使用预发现的 {len(all_urls)} 集（已跳过重复发现）")
    elif is_auto_discover:
        log("info", "检测到单链接 + 全部模式，正在自动发现剧集列表...")
        try:
            cookies_path = downloader.cookies_file if downloader.has_cookies else None
            discovered = await extract_tiktok_series(url, cookies_file=cookies_path, proxy=proxy)
            if discovered and len(discovered) > 1:
                all_urls = discovered
                log("success", f"自动发现 {len(discovered)} 集短剧视频")
            else:
                all_urls = [url]
        except Exception as e:
            log("warn", f"剧集发现失败 ({e})，将仅下载当前视频")
            all_urls = [url]
    else:
        all_urls = [url]

    # 筛选集数
    total_available = len(all_urls)
    selected_indices = parse_episode_range(ep_range_str, total_available, default_ep=1)
    url_list = [all_urls[i - 1] for i in selected_indices]

    if ep_range_str and ep_range_str not in ("全部", "all"):
        log("info", f"共 {total_available} 个视频，筛选后: {len(url_list)} 个")
    else:
        log("info", f"共 {len(url_list)} 个 TikTok 视频")

    # 提取名称
    tiktok_name = "tiktok"
    m = re.search(r'@([^/?]+)', url_list[0])
    if m:
        tiktok_name = sanitize_filename(m.group(1), max_len=30)

    out_path = Path(out_dir)

    total = len(url_list)
    progress(0.03)
    ep_cb(0, total, 0, [])

    ok = 0
    failed_eps: list[int] = []

    for idx, tiktok_url in enumerate(url_list):
        await pause.wait()
        # ── 取消检查 ──
        if _is_cancelled(signal.task_id):
            log("warn", "任务已取消，停止下载")
            break

        ep_num = selected_indices[idx]
        prefix = f"[{idx+1}/{total}]"
        log("info", f"{prefix} 第 {ep_num} 个 — 开始下载...")

        out_file = out_path / f"{tiktok_name}-{ep_num:02d}.mp4"
        try:
            result = await downloader.download(
                tiktok_url,
                str(out_file),
                episode_num=ep_num,
            )
            mb = Path(result).stat().st_size / 1024 / 1024
            await _normalize_audio_if_enabled(Path(result), log)
            log("success", f"{prefix} 第 {ep_num} 个 — 完成 ({mb:.1f} MB)")
            ok += 1
        except Exception as e:
            log("error", f"{prefix} 第 {ep_num} 个 — {e}")
            failed_eps.append(ep_num)

        ep_cb(ok, total, len(failed_eps), failed_eps)
        # 兜底：基于循环进度更新，确保进度条与集数进展一致
        progress(0.03 + ((idx + 1) / total) * 0.95)

    progress(1.0 if not failed_eps else 0.98)
    return ok, failed_eps


async def _tiktok_single_download(
    url: str,
    out_dir: str,
    ep_num: int,
    signal: TaskSignal,
) -> str:
    """TikTok 单集下载（用于重试）。"""
    from zaizaimao.core.tiktok_dl import TikTokDownloader, detect_proxy

    proxy = await detect_proxy()
    downloader = TikTokDownloader(proxy=proxy, auto_cdp=True)
    if not downloader.has_cookies:
        await downloader.ensure_cookies()

    m = re.search(r'@([^/?]+)', url)
    tiktok_name = sanitize_filename(m.group(1), max_len=30) if m else "tiktok"
    out_path = Path(out_dir)
    out_file = out_path / f"{tiktok_name}-{ep_num:02d}.mp4"

    return await downloader.download(url, str(out_file), episode_num=ep_num)


# ═══════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════

def _import_adapter(platform: str):
    """动态导入平台适配器"""
    import importlib

    registry = {
        "dramashorts": "zaizaimao.platforms.dramashorts:DramaShortsAdapter",
        "shortmax": "zaizaimao.platforms.shortmax:ShortMaxAdapter",
        "tiktok": "zaizaimao.platforms.tiktok:TikTokAdapter",
    }
    entry = registry.get(platform)
    if not entry:
        raise ValueError(f"未知平台: {platform}")
    module_path, class_name = entry.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _flatten_failed(all_failed: dict[int, list[int]]) -> list[int]:
    """将按 URL 索引分组的失败列表展平"""
    result: list[int] = []
    for eps in all_failed.values():
        result.extend(eps)
    return sorted(set(result))


def _extract_movie_id(url: str, platform: str) -> str | None:
    """从短剧平台 URL 中提取 movie_id（用于同剧去重）。

    DramaShorts: /shorts/{uuid}
    ShortMax:    /episode/{slug}-{numeric_id}-{ep}
    """
    import re as _re
    if platform == "dramashorts":
        m = _re.search(r'dramashorts\.io/shorts/([a-f0-9-]+)', url)
        return m.group(1) if m else None
    elif platform == "shortmax":
        for pat in (
            r'shorttv\.live/episode/.+-(\d+)-\d+$',
            r'shortmax\.com/episode/.+-(\d+)-\d+$',
        ):
            m = _re.search(pat, url)
            if m:
                return m.group(1)
    return None


async def _normalize_audio_if_enabled(video_path: Path, log) -> None:
    """如果配置启用了响度归一化，对视频执行 loudnorm 两遍法处理。

    处理成功后根据 keep_original 配置决定是否替换原文件。
    处理失败时仅 warn 日志，保留原文件不阻塞下载管线。
    """
    from zaizaimao.models.config import load_config
    from zaizaimao.core.loudnorm import LoudnormProcessor, LoudnormError

    cfg = load_config()
    if not cfg.normalize_audio:
        return

    processor = LoudnormProcessor(
        target_lufs=cfg.target_lufs,
        max_true_peak=cfg.max_true_peak,
        ffmpeg_path=cfg.ffmpeg_path or None,
    )

    try:
        result = await processor.process(video_path)
        if not cfg.keep_original:
            normalized = Path(result.output_path)
            # Windows 上原视频文件可能被 FFmpeg/杀软短暂锁定，重试替换
            for i in range(5):
                try:
                    normalized.replace(video_path)
                    break
                except PermissionError:
                    if i == 4:
                        raise
                    await asyncio.sleep(0.3 * (2 ** i))
            log("info",
                f"响度归一化: {video_path.name} (输入 {result.input_i:.1f} LUFS, 增益 {result.target_offset:+.1f} dB)")
        else:
            log("info",
                f"响度归一化: -> {result.output_path} (增益 {result.target_offset:+.1f} dB)")
    except (LoudnormError, PermissionError, OSError) as e:
        log("warn", f"响度归一化失败，保留原文件: {e}")
