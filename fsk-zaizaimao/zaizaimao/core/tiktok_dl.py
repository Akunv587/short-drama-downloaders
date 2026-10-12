"""
TikTok 视频下载器 — 基于 yt-dlp 子进程封装

核心教训 (来自 fsk-tool 实战经验 + 2026.07 实测):
1. 【已变更】默认模式（无 --extractor-args）为当前唯一可用策略
   - api=mobile / api=web 均返回 HTTP 403 Forbidden
   - 默认模式会走 JS challenge 解决流程，配合 CDP Cookie 可成功
2. Cookie 用 CDP (Chrome DevTools Protocol) 提取，不用 --cookies-from-browser
3. TikTok 反爬极其激进：短时间内多次请求会触发 IP 级 403
   - 增加 --sleep-requests / --retries / --fragment-retries 缓解
   - 建议每次下载前通过 CDP 刷新 Cookie
4. 串行优于并发 —— TikTok 对单 IP 并发极其敏感
5. 下载后必须验证文件是否真实落盘
6. 203009 错误通过 app_info 轮换恢复
"""

import asyncio
import json
import logging
import os
import re
import shutil
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Callable, Optional

import httpx

logger = logging.getLogger("zaizaimao.tiktok")

# ── yt-dlp 查找 ───────────────────────────────────────────

def find_ytdlp() -> str | None:
    """查找 yt-dlp 可执行文件，返回绝对路径或 None"""
    # 1. 先检查项目本地的 yt-dlp.exe
    local = Path(__file__).resolve().parent.parent.parent / "yt-dlp.exe"
    if local.exists():
        return str(local)

    # 2. 检查 PATH 中的 yt-dlp
    found = shutil.which("yt-dlp")
    if found:
        return found

    # 3. 检查 PATH 中的 yt-dlp.exe
    found = shutil.which("yt-dlp.exe")
    if found:
        return found

    # 4. pip 默认安装路径 (Windows)
    import sys
    scripts_dir = Path(sys.executable).parent / "Scripts"
    for name in ("yt-dlp.exe", "yt-dlp"):
        p = scripts_dir / name
        if p.exists():
            return str(p)

    # 5. 用户级 pip 安装路径
    import sysconfig
    user_scripts = Path(sysconfig.get_path("scripts"))
    for name in ("yt-dlp.exe", "yt-dlp"):
        p = user_scripts / name
        if p.exists():
            return str(p)

    # 6. Windows APP_DATA Roaming pip 安装路径
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        for name in ("yt-dlp.exe", "yt-dlp"):
            p = Path(appdata) / "Python" / "Python314" / "Scripts" / name
            if p.exists():
                return str(p)

    return None


# ── 代理探测 ──────────────────────────────────────────────


async def _check_port(host: str, port: int, timeout: float = 0.8) -> bool:
    """异步 TCP 端口探测"""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def detect_proxy() -> str:
    """
    自动探测本地代理。

    按优先级探测常见代理端口（Clash / V2Ray / SS）。
    Returns:
        代理 URL (如 http://127.0.0.1:10808) 或空字符串
    """
    # 优先环境变量
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        val = os.environ.get(var, "")
        if val:
            logger.info("检测到环境变量代理: %s", val)
            return val

    candidates = [
        ("127.0.0.1", 7890, "Clash"),
        ("127.0.0.1", 10808, "V2Ray 混合"),
        ("127.0.0.1", 10809, "V2Ray HTTP"),
        ("127.0.0.1", 1080, "SOCKS5"),
        ("127.0.0.1", 7891, "Clash 备用"),
        ("127.0.0.1", 8118, "Privoxy"),
        ("127.0.0.1", 9090, "系统代理"),
    ]

    for host, port, label in candidates:
        if await _check_port(host, port):
            proxy = f"http://{host}:{port}"
            logger.info("检测到 %s 代理: %s", label, proxy)
            return proxy

    return ""


# ── Cookie 管理 ───────────────────────────────────────────


def find_cookies_file() -> str | None:
    """
    查找 cookies.txt 文件。

    检查顺序:
    1. 项目根目录 cookies.txt
    2. 当前工作目录 cookies.txt
    """
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "cookies.txt",
        Path.cwd() / "cookies.txt",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 100:
            return str(p)
    return None


async def auto_get_cookies() -> str | None:
    """
    尝试通过 CDP 自动从 Chrome 提取 TikTok Cookie。

    这是 find_cookies_file() 的增强替代方案——
    当本地没有 cookies.txt 时，自动连接 Chrome 获取。
    """
    try:
        from zaizaimao.core.cdp import ensure_cookies_cdp
        return await ensure_cookies_cdp()
    except ImportError:
        logger.warning("CDP 模块不可用 (缺少 aiohttp?)")
        return None
    except Exception as e:
        logger.warning("CDP Cookie 提取失败: %s", e)
        return None


# ── 下载引擎 ──────────────────────────────────────────────


class TikTokDownloader:
    """
    TikTok 视频下载器。

    通过 yt-dlp 子进程下载单个视频，提供进度回调。
    严格串行，不并发。

    特性:
    - CDP 自动提取 Chrome Cookie
    - 203009 错误自动轮换 app_info 重试
    - 文件落盘验证
    """

    # 203009 错误时轮换的 app_info 值
    _APP_INFO_FALLBACKS = ["trill", "musical_ly"]

    # API 策略回退链: 默认(无 extractor-args) → web → mobile
    # 实测: 默认模式可行; api=mobile / api=web 均返回 HTTP 403
    _API_STRATEGIES = ["", "web", "mobile"]

    def __init__(
        self,
        cookies_file: str | None = None,
        proxy: str = "",
        ytdlp_path: str | None = None,
        auto_cdp: bool = True,
    ):
        self._ytdlp = ytdlp_path or find_ytdlp()
        self._cookies = cookies_file or find_cookies_file()
        self._proxy = proxy
        self._auto_cdp = auto_cdp

        if self._proxy:
            logger.info("TikTok 下载器代理: %s", self._proxy)
        if self._cookies:
            logger.info("TikTok 下载器 Cookie: %s", self._cookies)

    @property
    def is_ready(self) -> bool:
        """检查 yt-dlp 是否可用"""
        return self._ytdlp is not None and os.path.exists(self._ytdlp)

    @property
    def has_cookies(self) -> bool:
        """检查是否有 Cookie 文件"""
        return self._cookies is not None and (
            os.path.exists(self._cookies) and os.path.getsize(self._cookies) > 100
        )

    @property
    def ytdlp_path(self) -> str | None:
        return self._ytdlp

    @property
    def cookies_file(self) -> str | None:
        return self._cookies

    def set_cookies(self, path: str) -> None:
        self._cookies = path

    def set_proxy(self, proxy: str) -> None:
        self._proxy = proxy

    async def refresh_cookies(self) -> bool:
        """
        通过 CDP 刷新 Cookie (从 Chrome 重新提取)。

        Returns:
            是否成功刷新
        """
        try:
            from zaizaimao.core.cdp import auto_extract_cookies
            success, msg = await auto_extract_cookies(force_refresh=True)
            if success:
                self._cookies = find_cookies_file()
                logger.info("Cookie 已刷新: %s", msg)
            else:
                logger.warning("Cookie 刷新失败: %s", msg)
            return success
        except Exception as e:
            logger.error("Cookie 刷新异常: %s", e)
            return False

    async def ensure_cookies(self) -> bool:
        """
        确保 Cookie 可用。

        检查顺序: 已有 Cookie → 本地文件 → CDP 自动提取
        """
        if self.has_cookies:
            return True

        # 重新检查本地文件
        self._cookies = find_cookies_file()
        if self._cookies:
            return True

        # 尝试 CDP 自动提取
        if self._auto_cdp:
            self._cookies = await auto_get_cookies()
            if self._cookies:
                logger.info("已通过 CDP 获取 Cookie: %s", self._cookies)
                return True

        return False

    def _build_args(
        self,
        url: str,
        output_template: str,
        app_info: str = "",
        api: str = "",
    ) -> list[str]:
        """
        构建 yt-dlp 命令行参数。

        Args:
            url: TikTok 视频 URL
            output_template: 输出路径模板
            app_info: 自定义 app_info (用于 203009 错误恢复)
            api: API 策略 — "" (默认) / "mobile" / "web"
        """
        # 基础 extractor args
        parts = []
        if api:
            parts.append(f"tiktok:api={api}")
            if api == "mobile" and app_info:
                parts.append(f"app_info={app_info}")
        extractor_args = ";".join(parts) if parts else None

        args = [
            self._ytdlp,
            url,
            "--output", output_template,
            "--no-playlist",
            "--force-ipv4",
            "--restrict-filenames",
            "--windows-filenames",
            "--newline",
        ]

        if extractor_args:
            args += ["--extractor-args", extractor_args]

        args += [
            "--extractor-retries", "3",
            "--retries", "5",
            "--fragment-retries", "5",
            "--sleep-requests", "3",
            "--sleep-interval", "5",
            "--max-sleep-interval", "15",
            "--impersonate", "chrome",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36",
            "--add-header", "Referer:https://www.tiktok.com/",
        ]

        if self.has_cookies:
            args += ["--cookies", self._cookies]

        if self._proxy:
            args += ["--proxy", self._proxy]

        return args

    async def download(
        self,
        url: str,
        output_path: str,
        episode_num: int = 1,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> str:
        """
        下载单个 TikTok 视频。

        支持多级回退策略:
        1. API 策略回退: 默认 → web → mobile
        2. 203009 错误: 轮换 app_info (trill / musical_ly)
        3. 非 203009 错误: 尝试刷新 Cookie 后重试

        Args:
            url: TikTok 视频 URL
            output_path: 输出文件路径 (不含扩展名，yt-dlp 自动追加)
            episode_num: 集号（用于纯数字文件名）
            progress_callback: 进度回调 (percent: float, speed: str)

        Returns:
            实际输出文件路径

        Raises:
            RuntimeError: yt-dlp 未找到或所有策略均失败
        """
        if not self.is_ready:
            raise RuntimeError(
                "yt-dlp 未找到。请下载 yt-dlp.exe 放到项目根目录，"
                "或安装到系统 PATH: pip install yt-dlp"
            )

        # 输出目录
        out_dir = Path(output_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        # 使用纯数字集号命名 (01.mp4, 02.mp4...)
        ep_str = f"{episode_num:02d}"
        output_template = str(out_dir / f"{ep_str}.%(ext)s")

        # ── 多级回退下载 ──
        app_info_list = [""] + self._APP_INFO_FALLBACKS
        last_error_msg = ""
        cookie_refreshed = False

        for api_idx, api_strategy in enumerate(self._API_STRATEGIES):
            api_label = api_strategy or "默认"
            if api_idx > 0:
                logger.info("API 策略回退: %s", api_label)

            for attempt, app_info in enumerate(app_info_list):
                if attempt > 0:
                    logger.info(
                        "203009 错误，尝试 app_info=%s (第 %s 次重试)",
                        app_info, attempt,
                    )

                args = self._build_args(url, output_template, app_info, api=api_strategy)
                logger.debug("yt-dlp args: %s", " ".join(args))

                downloaded_file, error_msg, is_203009 = await self._run_ytdlp(
                    args, output_template, progress_callback,
                )

                if downloaded_file:
                    logger.info("下载成功 (API=%s)", api_label)
                    return downloaded_file

                last_error_msg = error_msg

                # 只有 203009 才值得轮换 app_info 重试
                if not is_203009:
                    break

            # ── 非 203009 错误: 尝试刷新 Cookie 后重试当前策略（仅一次）──
            if not cookie_refreshed and "Unexpected response" in last_error_msg:
                logger.info("检测到 'Unexpected response'，尝试刷新 Cookie...")
                try:
                    refreshed = await self.refresh_cookies()
                    cookie_refreshed = True
                    if refreshed:
                        logger.info("Cookie 已刷新，用相同 API 策略重试...")
                        # 重新用当前 api 策略重试 app_info 循环
                        for attempt, app_info in enumerate(app_info_list):
                            if attempt > 0:
                                logger.info(
                                    "203009 错误，尝试 app_info=%s (第 %s 次重试)",
                                    app_info, attempt,
                                )
                            args = self._build_args(url, output_template, app_info, api=api_strategy)
                            downloaded_file, error_msg, is_203009 = await self._run_ytdlp(
                                args, output_template, progress_callback,
                            )
                            if downloaded_file:
                                logger.info("下载成功 (API=%s, Cookie 刷新后)", api_label)
                                return downloaded_file
                            last_error_msg = error_msg
                            if not is_203009:
                                break
                    else:
                        logger.warning("Cookie 刷新未成功")
                except Exception as e:
                    logger.warning("Cookie 刷新异常: %s", e)

        # ── 所有策略都失败 ──
        if "Unexpected response" in last_error_msg:
            last_error_msg += (
                "\n提示: TikTok 可能更新了 API，请尝试:"
                "\n  1. 更新 yt-dlp: pip install --upgrade yt-dlp"
                "\n  2. 刷新浏览器 Cookie 后重试"
            )
        raise RuntimeError(last_error_msg or "下载失败: 未知错误")

    async def _run_ytdlp(
        self,
        args: list[str],
        output_template: str,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> tuple[str, str, bool]:
        """
        执行 yt-dlp 子进程并解析输出。

        Returns:
            (downloaded_file_path, error_message, is_203009_error)
        """
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        downloaded_file = ""
        last_percent = 0.0
        error_lines: list[str] = []

        async for line in process.stdout:
            text = line.decode("utf-8", errors="replace")

            # 解析目标文件名
            dest_match = re.search(r"\[download\] Destination: (.+)", text)
            if dest_match:
                downloaded_file = dest_match.group(1).strip()

            # 解析进度百分比
            pct_match = re.search(r"\[download\]\s+([\d.]+)%\s+of\s+", text)
            if pct_match:
                percent = float(pct_match.group(1))
                if percent > last_percent:
                    last_percent = percent
                    speed = ""
                    spd_match = re.search(r"at\s+([\d.]+[KMG]?i?B/s)", text)
                    if spd_match:
                        speed = spd_match.group(1)
                    if progress_callback:
                        progress_callback(percent, speed)

            # 收集错误
            if "ERROR:" in text:
                error_lines.append(text.strip())

        await process.wait()

        # ── 成功 ──
        if process.returncode == 0:
            file_path = self._find_output_file(downloaded_file, output_template)
            if file_path:
                return file_path, "", False
            return "", "yt-dlp 返回成功但未生成文件（可能是文件名冲突或 Cookie 不足）", False

        # ── 失败分类 ──
        error_msg = (
            "\n".join(error_lines[-5:])
            if error_lines
            else f"退出码 {process.returncode}"
        )
        is_203009 = "203009" in error_msg or (
            "not available" in error_msg.lower()
            and "video" in error_msg.lower()
        )

        if "No video formats" in error_msg:
            return "", "TikTok 要求登录，请提供 Cookie 后重试", False
        if "403" in error_msg or "Forbidden" in error_msg:
            return "", "TikTok 拒绝访问 (HTTP 403)，Cookie 可能已过期，正在尝试刷新...", False
        if (
            "blocked" in error_msg.lower()
            or "Your IP" in error_msg
            or "IP address is blocked" in error_msg
        ):
            return "", "IP 被 TikTok 限制，请切换代理节点", False
        if "Private video" in error_msg:
            return "", "该视频为私密视频，无法下载", False
        if is_203009:
            return "", "该视频在你所在地区不可用 (203009 地区限制)", True
        if "429" in error_msg:
            return "", "TikTok 请求过于频繁 (429)，请稍后重试", False

        return "", f"下载失败: {error_msg[:200]}", False

    @staticmethod
    def _find_output_file(downloaded_file: str, output_template: str) -> str:
        """查找 yt-dlp 实际输出的文件"""
        # 直接匹配
        if downloaded_file and os.path.exists(downloaded_file):
            return downloaded_file

        if not output_template:
            return ""

        # 从 output template 推断
        tmpl_path = Path(output_template)
        out_dir = tmpl_path.parent
        stem = tmpl_path.stem  # e.g. "01"

        # 尝试常见扩展名
        for ext in (".mp4", ".mkv", ".webm", ".mov"):
            p = out_dir / f"{stem}{ext}"
            if p.exists():
                return str(p)

        # 扫描目录
        if out_dir.exists():
            for f in out_dir.iterdir():
                if f.stem == stem:
                    return str(f)

        return ""


# ── 便捷函数 ──────────────────────────────────────────────


async def download_tiktok_videos(
    urls: list[str],
    output_dir: str,
    cookies_file: str | None = None,
    proxy: str = "",
    progress_callback: Callable[[int, int, float, str], None] | None = None,
    log_callback: Callable[[str, str], None] | None = None,
) -> tuple[int, int]:
    """
    批量下载 TikTok 视频（串行）。

    Args:
        urls: TikTok 视频 URL 列表
        output_dir: 输出目录
        cookies_file: Cookie 文件路径 (Netscape 格式)
        proxy: 代理地址
        progress_callback: (idx, total, percent, speed) 进度回调
        log_callback: (level, msg) 日志回调

    Returns:
        (成功数, 失败数)
    """
    downloader = TikTokDownloader(cookies_file=cookies_file, proxy=proxy)

    if not downloader.is_ready:
        if log_callback:
            log_callback("error", "yt-dlp 未找到，无法下载 TikTok 视频")
        return 0, len(urls)

    ok = 0
    fail = 0
    total = len(urls)

    for idx, url in enumerate(urls):
        ep_num = idx + 1
        prefix = f"[{idx+1}/{total}]"

        if log_callback:
            log_callback("info", f"{prefix} 第 {ep_num} 个 — 开始下载...")

        try:
            result = await downloader.download(
                url,
                str(Path(output_dir) / f"{ep_num:02d}.mp4"),
                episode_num=ep_num,
                progress_callback=(
                    lambda pct, spd, i=idx, t=total: progress_callback(i, t, pct, spd)
                    if progress_callback
                    else None
                ),
            )
            mb = os.path.getsize(result) / 1024 / 1024
            if log_callback:
                log_callback("success", f"{prefix} 第 {ep_num} 个 — 完成 ({mb:.1f} MB)")
            ok += 1
        except Exception as e:
            if log_callback:
                log_callback("error", f"{prefix} 第 {ep_num} 个 — {e}")
            fail += 1

    return ok, fail


# ── Cookie 辅助 ────────────────────────────────────────────


def _load_netscape_cookies(cookies_file: str) -> dict[str, str]:
    """将 Netscape 格式 cookies.txt 转为 {name: value} 字典"""
    jar = MozillaCookieJar(cookies_file)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (FileNotFoundError, OSError):
        return {}
    return {c.name: c.value for c in jar}


def _cookies_to_httpx(cookies_dict: dict[str, str], domain: str) -> httpx.Cookies:
    """将 {name: value} 字典转为 httpx.Cookies 对象"""
    cookies = httpx.Cookies()
    for name, value in cookies_dict.items():
        cookies.set(name, value, domain=domain)
    return cookies


def _extract_csrf_token(cookies_dict: dict[str, str]) -> str:
    """从 Cookie 字典中提取 TikTok CSRF token"""
    # TikTok 的 x-tt-csrf-token 头需要用 tt_csrf_token cookie 的值
    # 优先级: tt_csrf_token → ct0 → ttwid
    tt_csrf = cookies_dict.get("tt_csrf_token", "")
    if tt_csrf:
        return tt_csrf
    ct0 = cookies_dict.get("ct0", "")
    if ct0:
        return ct0
    ttwid = cookies_dict.get("ttwid", "")
    if ttwid:
        return ttwid
    return ""


# ── TikTok 剧集提取器 ─────────────────────────────────────


class TikTokSeriesExtractor:
    """
    从单个 TikTok 视频链接自动发现该短剧的全部剧集链接。

    通过 TikTok Web API 获取 drama episode list，
    适用于 TikTok 官方短剧 (Short Drama) 格式。

    参考: tiktok-extract-bookmarklet-minified.js
    """

    # TikTok web API 基础 URL
    _API_BASE = "https://www.tiktok.com"
    _DRAMA_API = "/api/drama/episode/item_list/"

    def __init__(
        self,
        cookies_file: str | None = None,
        proxy: str = "",
        timeout: float = 30.0,
    ):
        self._cookies_file = cookies_file or find_cookies_file()
        self._proxy = proxy
        self._timeout = timeout

        # 加载 cookies
        self._cookies_dict: dict[str, str] = {}
        if self._cookies_file and os.path.exists(self._cookies_file):
            self._cookies_dict = _load_netscape_cookies(self._cookies_file)

    # ── 公共接口 ───────────────────────────────────────────

    async def extract(self, url: str) -> list[dict]:
        """
        从单个 TikTok 视频 URL 提取该剧集的所有视频链接。

        Args:
            url: TikTok 视频 URL

        Returns:
            [{url: str, episode: int}, ...] 列表，按剧集号升序排列
            如果提取失败，返回空列表
        """
        creator, video_id = self._parse_url(url)
        if not creator or not video_id:
            logger.warning("无法解析 TikTok URL: %s", url)
            return []

        # 诊断: Cookie 状态
        if self._cookies_dict:
            key_cookies = [k for k in self._cookies_dict if k in ("sessionid", "tt_webid", "tt_webid_v2")]
            logger.info(
                "TikTok 剧集提取: creator=%s, videoId=%s | Cookie 数=%d, 关键=%s",
                creator, video_id, len(self._cookies_dict), key_cookies or "无",
            )
        else:
            logger.warning(
                "TikTok 剧集提取: creator=%s, videoId=%s | 无 Cookie（提取可能失败）",
                creator, video_id,
            )

        # 创建 HTTP 客户端
        client = self._build_client()

        try:
            # 方法1: 从页面 HTML 提取 drama ID → 调用 API
            drama_id = await self._find_drama_id(client, url)
            if drama_id:
                logger.info("找到 drama ID: %s", drama_id)
                episodes = await self._fetch_drama_episodes(client, drama_id, creator, video_id)
                if episodes:
                    logger.info("通过 API 获取 %d 集", len(episodes))
                    return episodes

            # 方法2: 若方法1未找到 drama ID，尝试从页面内嵌 JSON 中提取
            logger.info("方法1未找到 drama，尝试从页面 JSON 中提取...")
            episodes = await self._extract_from_page_json(client, url, creator)
            if episodes:
                logger.info("从页面 JSON 提取 %d 集", len(episodes))
                return episodes

            logger.info("未能提取剧集列表（该视频可能不属于短剧系列）")
            return []

        finally:
            await client.aclose()

    # ── URL 解析 ───────────────────────────────────────────

    @staticmethod
    def _parse_url(url: str) -> tuple[str, str]:
        """提取 (creator_username, video_id)"""
        m = re.search(r'tiktok\.com/@([^/?]+)', url)
        creator = m.group(1) if m else ""
        m = re.search(r'/video/(\d+)', url)
        video_id = m.group(1) if m else ""
        return creator, video_id

    # ── HTTP 客户端 ─────────────────────────────────────────

    def _build_client(self) -> httpx.AsyncClient:
        """构建带 Cookie/Proxy 的 httpx 客户端"""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.tiktok.com/",
        }
        # 使用 .tiktok.com (带前导点) 以确保 Cookie 匹配所有子域名
        cookies = _cookies_to_httpx(self._cookies_dict, ".tiktok.com")
        client_kwargs: dict = {
            "headers": headers,
            "cookies": cookies,
            "follow_redirects": True,
            "timeout": httpx.Timeout(self._timeout),
        }
        if self._proxy:
            client_kwargs["proxy"] = self._proxy
        return httpx.AsyncClient(**client_kwargs)

    # ── 方法1: 查找 drama ID ─────────────────────────────────

    async def _find_drama_id(
        self, client: httpx.AsyncClient, url: str
    ) -> str | None:
        """从 TikTok 页面中提取 drama ID"""
        try:
            # 使用正确的 Referer（页面自身 URL），避免被 TikTok 降级返回 SPA 壳
            resp = await client.get(url, headers={"Referer": url})
            html = resp.text
            logger.info(
                "TikTok 页面 HTTP %d | 长度=%d | 重定向=%d",
                resp.status_code, len(html), len(resp.history),
            )
            if resp.status_code != 200:
                logger.warning("非 200 响应，可能被反爬拦截")
            if len(html) < 500:
                logger.warning("页面内容极短 (%d 字节)，可能返回了验证页面", len(html))
        except Exception as e:
            logger.warning("获取 TikTok 页面失败: %s", e)
            return None

        # 诊断: 检查页面特征（只在未找到有用的数据容器时才警告）
        captcha_patterns = ["captcha-delivery", "tiktok-captcha", "verify-center-container"]
        if any(p in html for p in captcha_patterns):
            logger.warning("页面包含验证码组件，Cookie 可能已过期")
        if "__UNIVERSAL_DATA_FOR_REHYDRATION__" in html:
            logger.info("找到 __UNIVERSAL_DATA_FOR_REHYDRATION__ 内嵌数据")
        else:
            logger.warning("未找到 __UNIVERSAL_DATA_FOR_REHYDRATION__，页面可能是 SPA 壳")
            # 诊断: 检查是否有其他可能的 JSON 容器
            for key in ["SIGI_STATE", "__NEXT_DATA__"]:
                if key in html:
                    logger.info("找到备选 JSON 容器: %s", key)

        # 1) 查找 __UNIVERSAL_DATA_FOR_REHYDRATION__
        drama_id = self._extract_drama_from_universal_data(html)
        if drama_id:
            logger.info("从 __UNIVERSAL_DATA_FOR_REHYDRATION__ 提取到 drama ID: %s", drama_id)
            return drama_id

        # 2) 在 HTML 中直接搜索 dramaID 模式
        for pattern in [
            r'"dramaID"\s*:\s*"(\d+)"',
            r'"dramaId"\s*:\s*"(\d+)"',
            r'"drama_id"\s*:\s*"(\d+)"',
            r'"dramaInfo".*?"id"\s*:\s*"(\d+)"',
            r'dramaID=([\d]+)',
        ]:
            m = re.search(pattern, html)
            if m:
                logger.info("通过正则在 HTML 中找到 drama ID: %s", m.group(1))
                return m.group(1)

        logger.warning("未在页面中找到 drama ID: 该视频可能不属于短剧系列，或页面格式已变更")
        return None

    @staticmethod
    def _extract_drama_from_universal_data(html: str) -> str | None:
        """从 __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON 中提取 drama ID"""
        match = re.search(
            r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>'
            r'(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            return None

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        # 深度搜索 JSON 中的 drama ID
        return TikTokSeriesExtractor._find_drama_id_in_json(data)

    @staticmethod
    def _find_drama_id_in_json(node, depth: int = 0) -> str | None:
        """递归搜索 JSON 树中的 drama ID"""
        if depth > 15 or node is None:
            return None

        if isinstance(node, dict):
            # 检查是否是 dramaInfo 对象
            if "dramaInfo" in node:
                drama_info = node["dramaInfo"]
                if isinstance(drama_info, dict):
                    drama_id = drama_info.get("id") or drama_info.get("dramaId")
                    if drama_id:
                        return str(drama_id)
            # 直接查找 dramaID / dramaId 字段
            for key in ("dramaID", "dramaId", "drama_id"):
                if key in node and node[key]:
                    return str(node[key])
            # 递归搜索
            for value in node.values():
                result = TikTokSeriesExtractor._find_drama_id_in_json(value, depth + 1)
                if result:
                    return result

        elif isinstance(node, list):
            for item in node:
                result = TikTokSeriesExtractor._find_drama_id_in_json(item, depth + 1)
                if result:
                    return result

        return None

    # ── 方法1b: 调用 drama API 获取剧集 ────────────────────

    async def _fetch_drama_episodes(
        self,
        client: httpx.AsyncClient,
        drama_id: str,
        creator: str,
        video_id: str = "",
    ) -> list[dict]:
        """分页调用 TikTok drama API 获取全部剧集"""
        episodes: list[dict] = []
        seen: set[str] = set()
        cursor = 0
        has_more = True
        max_pages = 50  # 安全上限
        page = 0

        api_url = f"{self._API_BASE}{self._DRAMA_API}"
        # aid=1988 是 TikTok Web 端的 App ID，缺少此参数会返回 400 (10201)
        params = f"aid=1988&dramaID={drama_id}&count=200"

        # 构建正确的 Referer（使用实际 video_id 而非 "placeholder"）
        ref_video_id = video_id or drama_id
        referer = f"https://www.tiktok.com/@{creator}/video/{ref_video_id}"

        while has_more and page < max_pages:
            page += 1
            full_url = f"{api_url}?{params}&cursor={cursor}"
            logger.debug("Drama API page %d: %s", page, full_url)

            try:
                # TikTok API 需要的完整 headers
                api_headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Referer": referer,
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                    "x-tt-csrf-token": _extract_csrf_token(self._cookies_dict),
                }
                resp = await client.get(full_url, headers=api_headers)
                if resp.status_code != 200:
                    logger.warning("Drama API 返回 %d (page %d)", resp.status_code, page)
                    break

                data = resp.json()
            except Exception as e:
                logger.warning("Drama API 请求失败 (page %d): %s", page, e)
                break

            items = data.get("itemList") or []
            for item in items:
                vid = item.get("id") or (item.get("itemStruct") or {}).get("id")
                if vid and vid not in seen:
                    seen.add(vid)
                    ep_num = 0
                    drama_info = item.get("dramaInfo") or {}
                    drama_video = drama_info.get("DramaVideoData") or {}
                    raw_ep = drama_video.get("EpisodeNumber")
                    if raw_ep is not None:
                        ep_num = int(raw_ep) if isinstance(raw_ep, (int, str)) else 0
                    episodes.append({
                        "url": f"https://www.tiktok.com/@{creator}/video/{vid}",
                        "episode": ep_num,
                    })

            has_more = bool(data.get("hasMore"))
            raw_cursor = data.get("cursor")
            if isinstance(raw_cursor, (int, float)):
                cursor = int(raw_cursor)
            elif isinstance(raw_cursor, str) and raw_cursor.isdigit():
                cursor = int(raw_cursor)

            if has_more:
                await asyncio.sleep(0.5)  # 礼貌延迟

        # 排序: 按 episode 升序
        episodes.sort(key=lambda e: (e["episode"], e["url"]))
        return episodes

    # ── 方法2: 从页面嵌入 JSON 中提取剧集 ──────────────────

    async def _extract_from_page_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        creator: str,
    ) -> list[dict]:
        """备选方案：从页面 SIGI_STATE 或其他 JSON 中提取链接"""
        try:
            resp = await client.get(url)
            html = resp.text
        except Exception:
            return []

        # 尝试从 SIGI_STATE 提取
        match = re.search(
            r'<script[^>]*id="SIGI_STATE"[^>]*[^>]*>'
            r'(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            # 尝试其他常见的 JSON 容器
            match = re.search(
                r'<script[^>]*id="__NEXT_DATA__"[^>]*>'
                r'(.*?)</script>',
                html,
                re.DOTALL,
            )

        if not match:
            return []

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

        # 收集 JSON 中所有 /video/ 链接
        episodes: list[dict] = []
        seen: set[str] = set()
        self._collect_video_urls(data, creator, episodes, seen)

        episodes.sort(key=lambda e: (e["episode"], e["url"]))
        return episodes

    @staticmethod
    def _collect_video_urls(
        node,
        creator: str,
        episodes: list[dict],
        seen: set[str],
        depth: int = 0,
    ):
        """递归收集 JSON 中的 video URL"""
        if depth > 12 or node is None:
            return

        if isinstance(node, dict):
            # 检查是否有 video id
            vid = node.get("id") or node.get("videoId") or node.get("video_id")
            if vid and isinstance(vid, (str, int)) and str(vid) not in seen:
                seen.add(str(vid))
                ep = 0
                # 尝试提取剧集号
                drama_info = node.get("dramaInfo") or {}
                if isinstance(drama_info, dict):
                    drama_video = drama_info.get("DramaVideoData") or {}
                    raw_ep = drama_video.get("EpisodeNumber")
                    if raw_ep is not None:
                        ep = int(raw_ep) if isinstance(raw_ep, (int, str)) else 0
                episodes.append({
                    "url": f"https://www.tiktok.com/@{creator}/video/{vid}",
                    "episode": ep,
                })
            for value in node.values():
                TikTokSeriesExtractor._collect_video_urls(
                    value, creator, episodes, seen, depth + 1
                )

        elif isinstance(node, list):
            for item in node:
                TikTokSeriesExtractor._collect_video_urls(
                    item, creator, episodes, seen, depth + 1
                )


# ── 便捷函数 ──────────────────────────────────────────────


async def extract_tiktok_series(
    url: str,
    cookies_file: str | None = None,
    proxy: str = "",
) -> list[str]:
    """
    便捷函数: 从单个 TikTok URL 提取剧集链接列表。

    Returns:
        排序后的视频 URL 列表，提取失败返回空列表
    """
    extractor = TikTokSeriesExtractor(cookies_file=cookies_file, proxy=proxy)
    episodes = await extractor.extract(url)
    return [e["url"] for e in episodes]
