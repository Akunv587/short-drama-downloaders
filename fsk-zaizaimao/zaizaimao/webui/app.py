"""
仔仔猫 Web UI — NiceGUI 驱动的下载界面

用法:
    python -m zaizaimao.webui.app
    zaizaimao webui
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from nicegui import ui, app

from zaizaimao.models.config import load_config, resolve_download_dir
from zaizaimao.utils import detect_platform, URLParseError
from zaizaimao.webui.download_engine import PLATFORM_INFO
from zaizaimao.webui.style import STYLE, CAT_SVG
from zaizaimao.webui.task_manager import TaskManager


# ═══════════════════════════════════════════════════════════
#  UI 构建
# ═══════════════════════════════════════════════════════════

def build_ui():
    ui.add_head_html(STYLE)

    # ── 背景层 ──
    ui.html(
        '<div class="bg-orb bg-orb-1"></div>'
        '<div class="bg-orb bg-orb-2"></div>'
        '<div class="bg-orb bg-orb-3"></div>'
        '<div class="bg-grid"></div>'
        '<div class="bg-noise"></div>'
    )

    # ═══ 顶部栏 ═══
    with ui.element("div").classes("max-w-6xl mx-auto w-full px-10 relative z-10"):
        with ui.row().classes("w-full items-center justify-between py-6"):
            with ui.row().classes("items-center gap-2 entrance-1"):
                ui.html(CAT_SVG)
                ui.label("仔仔猫").classes("logo-text")
                ui.html('<div class="divider-glow" style="width:36px;margin-top:2px"></div>')
                ui.label("多平台短剧下载工具").classes("text-sm text-gray-600 tracking-wide")
            ui.label("v0.2.0").classes(
                "entrance-1 text-xs text-gray-700 px-3 py-1 rounded-full"
                " border border-solid border-gray-800"
            )

    # ═══ 主布局 ═══
    with ui.element("div").classes("max-w-6xl mx-auto w-full px-10 relative z-10"):
        with ui.row().classes("w-full gap-6 items-start"):
            # ── 左栏: 下载面板 ──
            with ui.column().classes("flex-1 min-w-0 gap-5 entrance-2"):
                # ═══ 新建下载任务 ═══
                with ui.element("div").classes("card-panel animated-border w-full"):
                    ui.label("新建下载任务").classes("text-base font-semibold text-gray-200 mb-5")

                    url_input = ui.textarea(
                        label="视频链接",
                        placeholder="每行一个链接:\nhttps://dramashorts.io/shorts/xxx\nhttps://shorttv.live/xxx\nhttps://www.tiktok.com/@user/video/123",
                    ).classes("w-full url-textarea").props('outlined dark bg-color="#0f0f0f"')

                    episode_range_input = ui.input(
                        label="集数范围",
                        placeholder="留空=单集 / 全部=整部剧 / 1-10 / 1,3,5",
                    ).classes("w-full mt-3").props('outlined dark bg-color="#0f0f0f"')

                    cfg = load_config()
                    default_out_dir = str(resolve_download_dir(cfg.download_dir, auto_create=False))
                    with ui.row().classes("w-full items-center gap-2 mt-3"):
                        out_dir_input = ui.input(
                            label="下载目录",
                            value=default_out_dir,
                        ).classes("flex-1").props('outlined dark bg-color="#0f0f0f"')
                        ui.button("更改", on_click=lambda: _change_dir_dialog()).classes(
                            "text-xs px-3 py-2"
                        ).props('outline dark')
                        ui.button("打开", on_click=lambda: _open_download_dir()).classes(
                            "text-xs px-3 py-2"
                        ).props('outline dark')

                    # ── 后处理设置（可折叠）──
                    with ui.expansion("⚙ 后处理设置", value=False).classes("w-full mt-3") as postproc_expansion:
                        postproc_expansion.props('dark')
                        postproc_expansion.classes('text-xs text-gray-500')
                        with ui.row().classes("w-full items-center gap-4"):
                            normalize_switch = ui.switch(
                                "响度归一化 (EBU R128)",
                                value=cfg.normalize_audio,
                                on_change=lambda e: _on_normalize_toggle(e.value),
                            ).props('dark color="primary"')
                            ui.label(
                                "将视频音量统一到目标响度，改善播放体验"
                            ).classes("text-xs text-gray-600")
                        with ui.row().classes("w-full items-center gap-4 mt-2") as norm_settings_row:
                            target_lufs_input = ui.number(
                                "目标响度 (LUFS)",
                                value=cfg.target_lufs,
                                min=-33,
                                max=-10,
                                step=0.5,
                                on_change=lambda e: _on_lufs_change(e.value),
                            ).props('outlined dark bg-color="#0f0f0f"').classes("w-40")
                            max_tp_input = ui.number(
                                "最大真峰值 (dBTP)",
                                value=cfg.max_true_peak,
                                min=-5,
                                max=0,
                                step=0.1,
                                on_change=lambda e: _on_tp_change(e.value),
                            ).props('outlined dark bg-color="#0f0f0f"').classes("w-40")
                        if not cfg.normalize_audio:
                            norm_settings_row.set_visibility(False)

                    # 按钮行: 开始下载
                    with ui.row().classes("items-center gap-4 mt-3"):
                        dl_btn = ui.button(
                            "开始下载任务", on_click=lambda: start_download()
                        ).classes("btn-primary")

                    ui.html('<div class="divider-glow mt-5 mb-4"></div>')

                    # 日志标题
                    ui.label("控制台").classes(
                        "text-xs font-medium text-gray-600 uppercase tracking-widest mb-2"
                    )

                    # 日志区
                    log_container = ui.element("div").classes("log-area w-full")
                    with log_container:
                        ui.html('<span class="log-cursor"></span>')

            # ── 右栏 ──
            with ui.column().classes("w-72 shrink-0 gap-5"):
                # 平台状态
                with ui.element("div").classes("card-panel w-full entrance-3"):
                    ui.label("支持平台").classes("text-base font-semibold text-gray-200 mb-4")
                    for key, info in PLATFORM_INFO.items():
                        with ui.row().classes("items-center gap-3 py-2.5"):
                            ui.html(
                                f'<div class="status-dot-wrap">'
                                f'<span class="status-dot" style="background:{info["accent"]}"></span>'
                                f'<span class="status-ring" style="border-color:{info["accent"]}"></span>'
                                f'<span class="status-ring" style="border-color:{info["accent"]}"></span>'
                                f'<span class="status-ring" style="border-color:{info["accent"]}"></span>'
                                f'</div>'
                            )
                            with ui.column().classes("gap-0.5"):
                                ui.label(info["name"]).classes("text-sm font-medium text-gray-300")
                                ui.label(info["domain"]).classes("text-xs text-gray-600")
                            ui.label(info.get("status", "免费可用")).classes("status-badge").style(
                                f"background: {info['accent']}14; color: {info['accent']};"
                                f"border: 0.5px solid {info['accent']}22;"
                            )

                # TikTok 工具
                with ui.element("div").classes("card-panel w-full entrance-4"):
                    ui.label("TikTok 工具").classes("text-base font-semibold text-gray-200 mb-3")
                    tiktok_status = ui.label("").classes("text-xs text-gray-500 mb-3")
                    with ui.row().classes("gap-2"):
                        ui.button("刷新 Cookie", on_click=lambda: _refresh_cookies()).classes(
                            "text-xs px-3 py-1.5"
                        ).props('outline dark')
                        ui.button("检测代理", on_click=lambda: _check_proxy()).classes(
                            "text-xs px-3 py-1.5"
                        ).props('outline dark')
                    ui.html('<div class="divider-glow my-4"></div>')
                    ui.markdown("**TikTok** — 需 yt-dlp + Cookie").classes(
                        "text-xs text-gray-500 leading-relaxed"
                    )

                # 使用说明
                with ui.element("div").classes("card-panel w-full entrance-4"):
                    ui.label("使用说明").classes("text-base font-semibold text-gray-200 mb-4")
                    steps = [
                        ("1", "粘贴首集链接 + 集数填「全部」→ 下载整部剧"),
                        ("2", "多剧可每行一个链接粘贴到输入框"),
                        ("3", "支持 1-10 / 1,3,5 / 全部 / 留空(单集)"),
                        ("4", "不同平台可同时下载，同平台自动排队"),
                    ]
                    for num, desc in steps:
                        with ui.row().classes("items-start gap-3 py-1.5 guide-row"):
                            ui.label(num).classes("step-num")
                            ui.label(desc).classes("text-sm text-gray-400 leading-relaxed")
                    ui.html('<div class="divider-glow my-4"></div>')
                    ui.markdown(
                        "**DramaShorts** — 支持免费下载\n"
                        "**ShortMax** — 支持免费下载（需代理）"
                    ).classes("text-xs text-gray-500 leading-relaxed")

    # ═══ 页脚 ═══
    with ui.row().classes("w-full justify-center py-8 relative z-10 entrance-5"):
        ui.label("仔仔猫 | ffmpeg + httpx + nicegui + peewee").classes(
            "text-xs text-gray-700 tracking-wide footer-link"
        )

    # ═══════════════════════════════════════════════════════
    #  任务管理器初始化
    # ═══════════════════════════════════════════════════════

    manager = TaskManager.get()
    from zaizaimao.webui.download_engine import execute_download
    manager.set_executor(execute_download)

    # ═══════════════════════════════════════════════════════
    #  下载目录操作
    # ═══════════════════════════════════════════════════════

    async def _change_dir_dialog():
        """通过原生文件夹选择器更改下载目录（非阻塞）"""
        try:
            init_dir = out_dir_input.value or default_out_dir
            try:
                init_path = str(resolve_download_dir(init_dir, auto_create=False))
            except Exception:
                init_path = str(Path.cwd())
            if not Path(init_path).exists():
                init_path = str(Path.cwd())

            def _show_dialog():
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                folder = filedialog.askdirectory(
                    title="选择下载目录",
                    initialdir=init_path,
                )
                root.destroy()
                return folder

            folder = await asyncio.to_thread(_show_dialog)
            if folder:
                folder_str = str(Path(folder))
                out_dir_input.set_value(folder_str)
                ui.notify(f"下载目录已更改为: {folder_str}", type="positive", position="top")
        except Exception as e:
            ui.notify(f"打开文件夹选择器失败: {e}", type="negative", position="top")

    async def _open_explorer_centered(folder_str: str):
        """在资源管理器中打开文件夹并居中窗口（Windows，非阻塞）"""
        safe_path = folder_str.replace("'", "''")
        ps_script = f'''$ErrorActionPreference = 'SilentlyContinue'
$f = '{safe_path}'
explorer $f
Start-Sleep -Milliseconds 600
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class W32 {{
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindowW(string c, string w);
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr h, IntPtr a, int X, int Y, int cx, int cy, uint f);
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int i);
    public struct RECT {{ public int L, T, R, B; }}
}}
'@
$n = Split-Path $f -Leaf
$h = [W32]::FindWindowW("CabinetWClass", $n)
if ($h) {{
    $r = New-Object W32+RECT
    [W32]::GetWindowRect($h, [ref]$r)
    $w = $r.R - $r.L; $h2 = $r.B - $r.T
    $sw = [W32]::GetSystemMetrics(0); $sh = [W32]::GetSystemMetrics(1)
    $x = [Math]::Max(0, ($sw - $w) / 2); $y = [Math]::Max(0, ($sh - $h2) / 2)
    [W32]::SetWindowPos($h, 0, $x, $y, 0, 0, 0x0001)
}}
'''
        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-Command", ps_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
        except Exception:
            os.startfile(folder_str)  # 回退：仅打开不居中

    async def _open_download_dir():
        path_str = out_dir_input.value.strip()
        if not path_str:
            ui.notify("下载目录路径为空", type="warning", position="top")
            return
        try:
            folder = resolve_download_dir(path_str)
            folder_str = str(folder)
            if os.name == "nt":
                await _open_explorer_centered(folder_str)
            elif os.uname().sysname == "Darwin":
                proc = await asyncio.create_subprocess_exec("open", folder_str)
                await proc.wait()
            else:
                proc = await asyncio.create_subprocess_exec("xdg-open", folder_str)
                await proc.wait()
            ui.notify(f"已打开: {folder_str}", type="positive", position="top")
        except Exception as e:
            ui.notify(f"打开目录失败: {e}", type="negative", position="top")

    # ── 后处理设置回调 ──

    def _on_normalize_toggle(enabled: bool):
        """响度归一化开关"""
        cfg.normalize_audio = enabled
        norm_settings_row.set_visibility(enabled)
        if enabled:
            ui.notify("响度归一化已启用，下载完成后自动处理音频", type="info", position="top")
        else:
            ui.notify("响度归一化已关闭", type="info", position="top")

    def _on_lufs_change(value: float):
        """目标响度变更"""
        cfg.target_lufs = value

    def _on_tp_change(value: float):
        """最大真峰值变更"""
        cfg.max_true_peak = value

    # ═══════════════════════════════════════════════════════
    #  TikTok 工具
    # ═══════════════════════════════════════════════════════

    async def _refresh_cookies():
        try:
            from zaizaimao.core.cdp import auto_extract_cookies, find_chrome_debug_port
            tiktok_status.set_text("正在探测 Chrome 调试端口...")
            port = await find_chrome_debug_port()
            if not port:
                tiktok_status.set_text("未检测到 Chrome 调试端口\n请运行: chrome.exe --remote-debugging-port=9222")
                ui.notify("未检测到 Chrome，请先以调试模式启动", type="warning", position="top")
                return
            tiktok_status.set_text(f"Chrome 端口 {port} → 提取 Cookie...")
            success, msg = await auto_extract_cookies(force_refresh=True)
            if success:
                tiktok_status.set_text(f"Cookie 已刷新: {msg}")
                ui.notify("Cookie 已刷新", type="positive", position="top")
            else:
                tiktok_status.set_text(f"Cookie 刷新失败: {msg}")
                ui.notify("Cookie 刷新失败", type="negative", position="top")
        except Exception as e:
            tiktok_status.set_text(f"异常: {e}")
            ui.notify(f"Cookie 刷新失败: {e}", type="negative", position="top")

    async def _check_proxy():
        try:
            from zaizaimao.core.tiktok_dl import detect_proxy, _check_port
            tiktok_status.set_text("正在检测代理...")
            parts = []
            for port, label in [(7890, "Clash"), (10808, "V2Ray"), (10809, "V2Ray HTTP")]:
                ok = await _check_port("127.0.0.1", port)
                parts.append(f"{label}({port}): {'OK' if ok else 'FAIL'}")
            proxy = await detect_proxy()
            if proxy:
                tiktok_status.set_text(f"代理: {proxy}\n{' | '.join(parts)}")
                ui.notify(f"代理可用: {proxy}", type="positive", position="top")
            else:
                tiktok_status.set_text(f"无代理\n{' | '.join(parts)}")
                ui.notify("未检测到可用代理", type="warning", position="top")
        except Exception as e:
            tiktok_status.set_text(f"检测失败: {e}")

    # ═══════════════════════════════════════════════════════
    #  下载触发
    # ═══════════════════════════════════════════════════════

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

    async def _group_urls_by_drama(urls: list[str]) -> list[list[str]]:
        """将 URL 按短剧系列分组（所有平台）。

        DramaShorts / ShortMax: 从 URL 提取 movie_id，直接按 ID 分组。
        TikTok: 通过 extract_tiktok_series API 发现剧集后匹配。

        Returns:
            分组后的 URL 列表的列表，每组对应一部剧
        """
        tiktok_urls: list[str] = []
        drama_groups: dict[tuple[str, str], list[str]] = {}  # (platform, movie_id) -> urls

        for u in urls:
            try:
                p = detect_platform(u)
            except URLParseError:
                continue

            if p == "tiktok":
                tiktok_urls.append(u)
            else:
                mid = _extract_movie_id(u, p) or u  # 无法提取则用 URL 自身做 key
                key = (p, mid)
                if key not in drama_groups:
                    drama_groups[key] = []
                drama_groups[key].append(u)

        groups: list[list[str]] = list(drama_groups.values())

        if tiktok_urls:
            tiktok_groups = await _group_tiktok_by_drama(tiktok_urls)
            groups.extend(tiktok_groups)

        return groups

    async def _group_tiktok_by_drama(tiktok_urls: list[str]) -> list[list[str]]:
        """将 TikTok URL 按短剧系列分组。

        同一部剧的多个单集链接合并为一组；不同剧分到不同组。
        用第一条链接发现整部剧的全部集数，然后检查其余链接是否属于同一部剧。

        Returns:
            分组后的 URL 列表的列表，每组对应一部剧
        """
        import re as _re
        from zaizaimao.core.tiktok_dl import (
            TikTokDownloader,
            detect_proxy as _dp,
            extract_tiktok_series,
        )

        if len(tiktok_urls) <= 1:
            return [list(tiktok_urls)]

        proxy = await _dp()
        dl = TikTokDownloader(proxy=proxy, auto_cdp=True)
        await dl.ensure_cookies()
        cookies_path = dl.cookies_file if dl.has_cookies else None

        groups: list[list[str]] = []
        remaining = list(tiktok_urls)

        while remaining:
            first = remaining.pop(0)
            group = [first]

            # 用第一条链接发现整部剧的集数
            try:
                series_urls = await extract_tiktok_series(
                    first, cookies_file=cookies_path, proxy=proxy
                )
            except Exception:
                series_urls = None

            if series_urls and len(series_urls) > 1:
                # 收集已发现剧集的所有 video_id
                series_ids: set[str] = set()
                for s_url in series_urls:
                    m = _re.search(r'/video/(\d+)', s_url)
                    if m:
                        series_ids.add(m.group(1))

                # 检查剩余链接是否属于同一部剧
                still_remaining: list[str] = []
                for u in remaining:
                    m = _re.search(r'/video/(\d+)', u)
                    if m and m.group(1) in series_ids:
                        group.append(u)  # 同一部剧，合并
                    else:
                        still_remaining.append(u)  # 不同剧，留待下轮
                remaining = still_remaining

            groups.append(group)

        return groups

    async def start_download():
        raw = url_input.value.strip()
        if not raw:
            ui.notify("请输入视频链接", type="warning", position="top")
            return

        urls: list[str] = []
        for line in raw.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

        if not urls:
            ui.notify("未找到有效链接", type="warning", position="top")
            return

        out_dir = str(resolve_download_dir(out_dir_input.value.strip() or load_config().download_dir))
        ep_range = episode_range_input.value.strip()
        ep_range_lower = ep_range.lower()

        # ──「全部」模式: 按短剧系列分组，每组一个任务（所有平台）──
        if ep_range_lower in ("全部", "all", ""):
            groups = await _group_urls_by_drama(urls)
            task_count = 0

            for group_urls in groups:
                try:
                    await manager.submit(group_urls, out_dir, ep_range)
                    task_count += 1
                except Exception as e:
                    ui.notify(f"创建任务失败: {e}", type="negative", position="top")

            if task_count > 0:
                url_input.set_value("")
                episode_range_input.set_value("")
                ui.notify(
                    f"已创建 {task_count} 个任务",
                    type="positive", position="top"
                )
            return

        # ── 常规模式（非全部或单链接）──
        try:
            platform = detect_platform(urls[0])
        except URLParseError as e:
            ui.notify(str(e), type="warning", position="top")
            return

        try:
            task_id = await manager.submit(urls, out_dir, ep_range)
            # 清空输入
            url_input.set_value("")
            episode_range_input.set_value("")
            ui.notify(f"任务已创建: {task_id[:8]}...", type="positive", position="top")
        except Exception as e:
            ui.notify(f"创建任务失败: {e}", type="negative", position="top")

    # ═══════════════════════════════════════════════════════
    #  控制台日志同步
    # ═══════════════════════════════════════════════════════

    _synced_count = 0

    def sync_ui():
        nonlocal _synced_count

        mgr = TaskManager.get()

        # 查找活跃任务
        active_task_id = None
        for aid, info in mgr._task_cache.items():
            if info.get("status") in ("running", "paused"):
                active_task_id = aid
                break

        if active_task_id:
            logs = mgr.get_logs(active_task_id)
            new_logs = logs[_synced_count:]
            for level, msg in new_logs:
                dot_class = f"log-dot-{level}"
                msg_class = f"log-msg-{level}"
                with log_container:
                    with ui.row().classes("log-entry"):
                        ui.html(f'<span class="log-dot {dot_class}"></span>')
                        ui.label(msg).classes(f"log-msg {msg_class}")
            _synced_count = len(logs)

    ui.timer(0.5, sync_ui)


# ═══════════════════════════════════════════════════════════
#  路由
# ═══════════════════════════════════════════════════════════

@ui.page("/")
def index_page():
    build_ui()


def main():
    print("仔仔猫 Web UI 启动中...")
    print("打开: http://localhost:8080")
    ui.run(
        title="仔仔猫 | 短剧下载工具",
        host="127.0.0.1",
        port=8080,
        reload=False,
        show=False,
        storage_secret="zaizaimao-2026-session",
        reconnect_timeout=86400.0,
        binding_refresh_interval=0.5,
        message_history_length=2000,
    )


if __name__ in ("__main__", "__mp_main__"):
    main()
