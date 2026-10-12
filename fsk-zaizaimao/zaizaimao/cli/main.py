"""
仔仔猫 CLI — Typer 命令行入口

用法:
    zaizaimao dl <url>                   # 下载单集
    zaizaimao dl <url> --episodes 1-10   # 下载多集
    zaizaimao login --platform dramashorts  # 登录
    zaizaimao platforms                  # 查看支持的平台
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskID
from rich.table import Table

from zaizaimao.models.config import load_config, resolve_download_dir
from zaizaimao.utils import detect_platform, URLParseError, sanitize_filename, setup_logger

app = typer.Typer(
    name="zaizaimao",
    help="仔仔猫 — 多平台短剧视频下载工具",
    add_completion=False,
)

console = Console()
logger = setup_logger()


# ── 平台注册表 ────────────────────────────────────────────

# 延迟导入以避免启动时加载所有模块
_PLATFORM_REGISTRY = {
    "dramashorts": "zaizaimao.platforms.dramashorts:DramaShortsAdapter",
    "shortmax": "zaizaimao.platforms.shortmax:ShortMaxAdapter",
    "tiktok": "zaizaimao.platforms.tiktok:TikTokAdapter",
}

SUPPORTED_PLATFORMS = list(_PLATFORM_REGISTRY.keys())


def _import_adapter(platform: str):
    """动态导入平台适配器"""
    import importlib

    entry = _PLATFORM_REGISTRY.get(platform)
    if not entry:
        raise ValueError(f"未知平台: {platform}，支持: {SUPPORTED_PLATFORMS}")

    module_path, class_name = entry.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


# ── 命令 ──────────────────────────────────────────────────


@app.command()
def dl(
    url: str = typer.Argument(..., help="短剧剧集 URL"),
    output: Optional[str] = typer.Option(
        None, "-o", "--output", help="输出目录（默认: ./downloads）"
    ),
    episodes: Optional[str] = typer.Option(
        None, "-e", "--episodes", help="集数范围，如 1-64 或 1,3,5"
    ),
    quality: str = typer.Option(
        "best", "-q", "--quality", help="视频质量: best / 720p / 1080p"
    ),
    name: Optional[str] = typer.Option(
        None, "-n", "--name", help="剧名（用于文件命名: 剧名-集数）"
    ),
):
    """
    下载短剧视频

    示例:
        zaizaimao dl "https://dramashorts.io/shorts/9d12e305-xxx?episode=1"
        zaizaimao dl "https://dramashorts.io/shorts/9d12e305-xxx" -e 1-64
    """
    # 1. 检测平台
    try:
        platform_name = detect_platform(url)
    except URLParseError as e:
        console.print(f"[red]错误:[/red] {e}")
        raise typer.Exit(code=1)

    console.print(f"[bold cyan]仔仔猫[/bold cyan] — 检测到平台: [green]{platform_name}[/green]")

    # 2. 初始化适配器
    AdapterClass = _import_adapter(platform_name)
    adapter = AdapterClass()

    # 3. 先尝试恢复缓存的 token（如果有的话，VIP 内容用到）
    cached = adapter.load_cached_token()
    if cached:
        adapter.http.set_auth_token(cached.get("access_token", ""))
        console.print("[dim]已加载缓存登录状态[/dim]")

    # 4. 解析 URL → 获取播放凭证 → 下载
    async def _download():
        # ── TikTok 特殊处理 ──
        if platform_name == "tiktok":
            from zaizaimao.core.tiktok_dl import TikTokDownloader, detect_proxy

            downloader = TikTokDownloader()
            if not downloader.is_ready:
                console.print("[red]错误:[/red] yt-dlp 未找到")
                console.print("请下载 yt-dlp.exe 放到项目根目录，或: pip install yt-dlp")
                raise typer.Exit(code=1)

            if not downloader.has_cookies:
                console.print("[yellow][!] 未检测到 Cookie，可能无法下载[/yellow]")

            if not downloader._proxy:
                proxy = await detect_proxy()
                if proxy:
                    downloader.set_proxy(proxy)
                    console.print(f"[+] 代理: {proxy}")

            cfg = load_config()
            base_dir = resolve_download_dir(output or cfg.download_dir)
            out_dir = base_dir

            console.print(f"[*] 下载中 (yt-dlp)...")

            def on_progress(pct: float, speed: str):
                bar = "#" * int(pct / 5) + "-" * (20 - int(pct / 5))
                speed_str = f" {speed}" if speed else ""
                console.print(f"\r  [{bar}] {pct:.0f}%{speed_str}", end="")

            try:
                result = await downloader.download(
                    url,
                    str(out_dir / f"{name or 'tiktok'}-01.mp4"),
                    episode_num=1,
                    progress_callback=on_progress,
                )
                console.print()  # newline after progress bar
                mb = Path(result).stat().st_size / 1024 / 1024
                console.print(f"[green][OK] 下载完成:[/green] {result} ({mb:.1f} MB)")
            except RuntimeError as e:
                console.print()
                console.print(f"[red]下载失败:[/red] {e}")
                raise typer.Exit(code=1)
            return

        # ── 短剧平台（DramaShorts / ShortMax）──
        # 解析 URL
        episode_info = await adapter.parse_url(url)

        console.print(f"[bold]{episode_info.movie_title or episode_info.movie_id}[/bold] "
                      f"— 第 {episode_info.episode_number} 集")

        # 获取播放凭证（免费内容直接提取，VIP 走 API）
        try:
            playback = await adapter.get_playback(episode_info)
        except RuntimeError as e:
            console.print(f"[red]错误:[/red] {e}")
            console.print(
                f"\n[yellow]可能需要登录。[/yellow]\n"
                f"请在浏览器中登录 {platform_name}，然后运行:\n"
                f"  [bold]zaizaimao login -p {platform_name} -t <Firebase_idToken>[/bold]\n"
                f"(Token 获取: 浏览器 F12 → Network → 任意 API 请求 → Authorization header)"
            )
            raise typer.Exit(code=1)

        if not playback.manifest_url:
            console.print("[red]错误:[/red] 无法获取播放地址")
            raise typer.Exit(code=1)

        console.print(f"[*] 播放地址: [dim]{playback.manifest_url[:80]}...[/dim]")

        # HLS 下载（ffmpeg 自动处理）
        from zaizaimao.core.hls import HLSEngine

        cfg = load_config()
        base_dir = resolve_download_dir(output or cfg.download_dir)
        out_dir = base_dir
        safe_name = sanitize_filename(
            episode_info.movie_title or episode_info.movie_id, max_len=50
        )
        out_path = out_dir / f"{safe_name}-{episode_info.episode_number:02d}.mp4"

        console.print(f"[*] 下载中 (ffmpeg 自动选择最高画质 + 合并音视频)...")

        def on_progress(current: int, total: int):
            pass  # ffmpeg 内置进度显示

        engine = HLSEngine(progress_callback=on_progress)
        result = await engine.download(
            playback.manifest_url,
            str(out_path),
            headers=playback.headers,
        )

        console.print(f"[green][OK] 下载完成:[/green] {result}")

    asyncio.run(_download())


@app.command()
def login(
    platform: str = typer.Option(
        ..., "-p", "--platform", help="平台名称 (dramashorts / shortmax / tiktok)"
    ),
    token: str = typer.Option(
        "", "-t", "--token", help="认证 token（从浏览器 DevTools 复制）"
    ),
):
    """
    登录指定平台

    获取 token 的方法:
    1. 在浏览器中打开平台网站并登录
    2. 打开 DevTools (F12) → Application → Local Storage
    3. 查找 Firebase idToken 或类似字段
    4. 复制 token 值，使用 --token 参数传入
    """
    if platform not in SUPPORTED_PLATFORMS:
        console.print(f"[red]未知平台:[/red] {platform}")
        console.print(f"支持: {', '.join(SUPPORTED_PLATFORMS)}")
        raise typer.Exit(code=1)

    if not token:
        token = typer.prompt("请粘贴认证 token", hide_text=True)

    AdapterClass = _import_adapter(platform)
    adapter = AdapterClass()

    success = asyncio.run(adapter.login(id_token=token))
    if success:
        console.print(f"[green][OK] {platform} 登录成功[/green]")
    else:
        console.print(f"[red][X] {platform} 登录失败[/red]")
        raise typer.Exit(code=1)


@app.command()
def platforms():
    """查看支持的平台"""
    table = Table(title="仔仔猫 支持的平台")
    table.add_column("平台", style="cyan")
    table.add_column("域名", style="green")
    table.add_column("状态", style="yellow")

    platform_info = [
        ("DramaShorts", "dramashorts.io", "[OK] Free"),
        ("ShortMax", "shorttv.live", "[OK] Free"),
        ("TikTok", "tiktok.com", "[yt-dlp] Cookie"),
    ]

    for name, domain, status in platform_info:
        table.add_row(name, domain, status)

    console.print(table)


@app.command()
def version():
    """显示版本信息"""
    from zaizaimao import __version__
    console.print(f"[bold cyan]仔仔猫[/bold cyan] v{__version__}")
    console.print("多平台短剧视频下载工具")


@app.command()
def webui(
    host: str = typer.Option("127.0.0.1", "-h", "--host", help="监听地址"),
    port: int = typer.Option(8080, "-p", "--port", help="监听端口"),
):
    """启动 Web 界面"""
    from nicegui import ui

    console.print(f"[bold cyan]仔仔猫 Web UI[/bold cyan] 启动中...")
    console.print(f"访问: [green]http://{host}:{port}[/green]")
    console.print("按 Ctrl+C 停止服务\n")

    # 导入 webui 模块以注册页面
    import zaizaimao.webui.app  # noqa: F401

    ui.run(
        title="仔仔猫 - 短剧下载",
        host=host,
        port=port,
        reload=False,
        show=False,
    )


@app.command()
def cookie(
    refresh: bool = typer.Option(
        False, "-r", "--refresh", help="强制从 Chrome 重新提取 Cookie"
    ),
):
    """
    管理 TikTok Cookie（通过 Chrome CDP 自动提取）

    无需手动登录——自动从 Chrome 浏览器中获取 TikTok 登录态。

    前提条件:
    1. 在 Chrome 浏览器中已登录 tiktok.com
    2. Chrome 以调试模式启动（工具会自动尝试启动）
    """
    async def _cookie_mgmt():
        from zaizaimao.core.cdp import find_chrome_debug_port, auto_extract_cookies
        from zaizaimao.core.tiktok_dl import find_cookies_file

        # 检查当前状态
        existing = find_cookies_file()
        if existing:
            import time
            age = time.time() - os.path.getmtime(existing)
            console.print(f"[*] Cookie 文件: [green]{existing}[/green]")
            console.print(f"    大小: {Path(existing).stat().st_size} bytes")
            console.print(f"    时间: {age / 3600:.1f} 小时前")

        # 探测 Chrome
        port = await find_chrome_debug_port()
        if port:
            console.print(f"[+] Chrome 调试端口: [green]{port}[/green]")
        else:
            console.print("[yellow][!] 未检测到 Chrome 调试端口[/yellow]")
            console.print("    请以调试模式启动 Chrome:")
            console.print("    [bold]chrome.exe --remote-debugging-port=9222[/bold]")

        # 刷新
        if refresh or not existing:
            console.print("\n==> 正在通过 CDP 提取 Cookie...")
            success, msg = await auto_extract_cookies(force_refresh=True)
            if success:
                console.print(f"[green][OK] {msg}[/green]")
                new_path = find_cookies_file()
                if new_path:
                    console.print(f"[*] 已保存到: [green]{new_path}[/green]")
            else:
                console.print(f"[red][X] {msg}[/red]")

    asyncio.run(_cookie_mgmt())


@app.command()
def tiktok_drama(
    url: str = typer.Argument(
        None, help="TikTok 创作者主页 URL（如 https://www.tiktok.com/@username）"
    ),
    output: Optional[str] = typer.Option(
        None, "-o", "--output", help="输出 CSV 文件路径"
    ),
):
    """
    从 TikTok 创作者主页提取短剧列表

    通过 Chrome CDP 自动获取创作者的所有短剧信息（剧名、集数、播放量）。

    前提条件:
    1. Chrome 以调试模式启动: chrome.exe --remote-debugging-port=9222
    2. 在 Chrome 中已登录 tiktok.com
    3. 打开目标创作者主页（或通过 URL 参数自动导航）

    示例:
        zaizaimao tiktok-drama
        zaizaimao tiktok-drama "https://www.tiktok.com/@polestoryflix"
        zaizaimao tiktok-drama "@polestoryflix" -o dramas.csv
    """
    from zaizaimao.core.cdp import cdp_extract_dramas, DramaInfo, find_chrome_debug_port, launch_chrome_with_debug
    from rich.table import Table

    # 规范化 URL
    creator_url = None
    if url:
        url = url.strip()
        if url.startswith("@"):
            creator_url = f"https://www.tiktok.com/{url}"
        elif "tiktok.com" in url:
            creator_url = url if url.startswith("http") else f"https://{url}"
        else:
            console.print("[red]无效的 URL，请提供 TikTok 创作者主页链接或 @用户名[/red]")
            raise typer.Exit(code=1)

    async def _extract():
        try:
            console.print("[bold cyan]仔仔猫 TikTok 短剧提取[/bold cyan]")
            if creator_url:
                console.print(f"目标: [green]{creator_url}[/green]")
            else:
                console.print("使用 Chrome 当前打开的 TikTok 页面")

            # 自动探测或启动 Chrome 调试端口
            port = await find_chrome_debug_port()
            if not port:
                console.print("[yellow]未检测到 Chrome 调试端口，尝试自动启动...[/yellow]")
                launched = await launch_chrome_with_debug()
                if launched:
                    port = await find_chrome_debug_port()
            if not port:
                console.print("[red]无法连接 Chrome 调试端口。[/red]")
                console.print("请手动以调试模式启动 Chrome:")
                console.print("  [bold]chrome.exe --remote-debugging-port=9222[/bold]")
                console.print("并在 Chrome 中登录 tiktok.com")
                raise typer.Exit(code=1)

            console.print(f"[*] Chrome CDP 端口: [green]{port}[/green]")
            console.print("[*] 正在提取短剧列表...")
            dramas = await cdp_extract_dramas(creator_url=creator_url, port=port)

            if not dramas:
                console.print("[yellow]未找到短剧数据[/yellow]")
                return

            # 显示表格
            table = Table(title=f"TikTok 短剧列表 ({len(dramas)} 部)")
            table.add_column("#", style="dim", width=4)
            table.add_column("剧名", style="cyan", max_width=50)
            table.add_column("集数", justify="right")
            table.add_column("播放量", justify="right")
            table.add_column("标签")

            for i, d in enumerate(dramas):
                table.add_row(
                    str(i + 1),
                    d.title[:50],
                    str(d.episodes),
                    d.plays_display,
                    ", ".join(d.themes[:2]),
                )

            console.print(table)

            # 保存 CSV
            csv_path = output or f"tiktok_dramas.csv"
            import csv as csv_module
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv_module.writer(f)
                writer.writerow(["剧名", "播放量", "集数", "标签", "ID"])
                for d in dramas:
                    writer.writerow([
                        d.title, d.plays, d.episodes,
                        "; ".join(d.themes), d.drama_id,
                    ])
            console.print(f"\n[green][OK] CSV 已保存: {csv_path}[/green]")

        except RuntimeError as e:
            console.print(f"[red]错误:[/red] {e}")
            raise typer.Exit(code=1)

    asyncio.run(_extract())


@app.command()
def proxy():
    """检测本地代理状态（Clash / V2Ray / SS）"""
    async def _check():
        from zaizaimao.core.tiktok_dl import detect_proxy, _check_port

        console.print("[bold]== Proxy Check ==[/bold]\n")

        # 检测环境变量
        for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
            val = os.environ.get(var, "")
            if val:
                console.print(f"  [*] {var}: [green]{val}[/green]")

        # 检测端口
        candidates = [
            (7890, "Clash"),
            (10808, "V2Ray 混合"),
            (10809, "V2Ray HTTP"),
            (1080, "SOCKS5"),
            (7891, "Clash 备用"),
            (8118, "Privoxy"),
            (9090, "系统代理"),
        ]

        for port, label in candidates:
            ok = await _check_port("127.0.0.1", port)
            status = "[green][ON] 在线[/green]" if ok else "[dim][OFF] 离线[/dim]"
            console.print(f"  [{label}] 127.0.0.1:{port} -- {status}")

        detected = await detect_proxy()
        if detected:
            console.print(f"\n[green][OK] 可用代理: {detected}[/green]")
        else:
            console.print("\n[yellow][!] 未检测到可用代理[/yellow]")

    asyncio.run(_check())


@app.command()
def tiktok(
    urls: str = typer.Argument(..., help="TikTok 视频 URL（多个用逗号分隔）或包含 URL 的文件路径"),
    output: Optional[str] = typer.Option(
        None, "-o", "--output", help="输出目录（默认: ./downloads/tiktok）"
    ),
    cookies: Optional[str] = typer.Option(
        None, "-c", "--cookies", help="Cookie 文件路径（Netscape 格式）"
    ),
    proxy: Optional[str] = typer.Option(
        None, "-p", "--proxy", help="代理地址，如 http://127.0.0.1:10808"
    ),
    name: Optional[str] = typer.Option(
        None, "-n", "--name", help="剧名（用于文件命名: 剧名-集数）"
    ),
):
    """
    批量下载 TikTok 视频

    示例:
        zaizaimao tiktok "https://www.tiktok.com/@user/video/123"
        zaizaimao tiktok "url1,url2,url3" -o ./my_videos
        zaizaimao tiktok urls.txt -c cookies.txt
    """
    # 解析输入: 可能是逗号分隔的 URL 列表或文件路径
    url_list: list[str] = []

    # 检查是否为文件
    if "\n" not in urls and "," not in urls:
        p = Path(urls)
        if p.exists() and p.is_file():
            url_list = [
                line.strip()
                for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip() and "tiktok.com" in line
            ]

    if not url_list:
        # 逗号分隔或单个 URL
        url_list = [u.strip() for u in urls.replace("\n", ",").split(",") if u.strip()]

    url_list = [u for u in url_list if "tiktok.com" in u]

    if not url_list:
        console.print("[red]未找到有效的 TikTok 链接[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold cyan]仔仔猫 TikTok 下载[/bold cyan] — {len(url_list)} 个视频")

    async def _download_batch():
        from zaizaimao.core.tiktok_dl import TikTokDownloader, detect_proxy

        # 代理
        actual_proxy = proxy or ""
        if not actual_proxy:
            actual_proxy = await detect_proxy()
            if actual_proxy:
                console.print(f"[+] 自动检测代理: {actual_proxy}")

        downloader = TikTokDownloader(cookies_file=cookies, proxy=actual_proxy)

        if not downloader.is_ready:
            console.print("[red]yt-dlp 未找到[/red]")
            console.print("请: pip install yt-dlp  或下载 yt-dlp.exe 到项目根目录")
            raise typer.Exit(code=1)

        if not downloader.has_cookies:
            console.print("[yellow][!] 未检测到 Cookie[/yellow]")
            console.print("请从 Chrome 登录 TikTok 后，将 Cookie 保存为 cookies.txt")
            console.print("或使用 --cookies 参数指定路径")

        cfg = load_config()
        base_dir = resolve_download_dir(output or cfg.download_dir)
        out_dir = base_dir

        ok = 0
        fail = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("下载中...", total=len(url_list))

            for idx, url in enumerate(url_list):
                ep_num = idx + 1
                progress.update(task, description=f"[{idx+1}/{len(url_list)}] 第 {ep_num} 个...")

                try:
                    result = await downloader.download(
                        url,
                        str(out_dir / f"{name or 'tiktok'}-{ep_num:02d}.mp4"),
                        episode_num=ep_num,
                    )
                    ok += 1
                except Exception as e:
                    console.print(f"[red]  第 {ep_num} 个失败:[/red] {e}")
                    fail += 1

                progress.update(task, advance=1)

        console.print(f"\n[bold]===== 下载完成: 成功 {ok}, 失败 {fail} =====[/bold]")

    asyncio.run(_download_batch())


@app.command()
def normalize(
    directory: str = typer.Argument(..., help="包含视频文件的目录"),
    target_lufs: float = typer.Option(-16.0, "-l", "--target-lufs", help="目标响度 LUFS（默认 -16）"),
    replace: bool = typer.Option(False, "-r", "--replace", help="替换原文件（默认生成 *_normalized.mp4）"),
    keep_original: bool = typer.Option(False, "-k", "--keep-original", help="与 --replace 配合: 保留原文件 .orig 后缀"),
    extensions: str = typer.Option(".mp4,.mkv", "-e", "--extensions", help="处理的视频扩展名（逗号分隔）"),
):
    """
    对目录中的视频文件批量执行响度归一化（EBU R128 loudnorm）

    使用 FFmpeg 两遍法，视频流直拷零画质损失。

    示例:
        zaizaimao normalize ./downloads/dramashorts
        zaizaimao normalize ./downloads -l -14 -r
        zaizaimao normalize ./videos -e .mp4,.mov,.avi
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        console.print(f"[red]错误:[/red] 目录不存在 — {directory}")
        raise typer.Exit(code=1)

    exts = [e.strip() for e in extensions.split(",") if e.strip()]
    if not exts:
        exts = [".mp4", ".mkv"]

    videos: list[Path] = []
    for ext in exts:
        if not ext.startswith("."):
            ext = f".{ext}"
        videos.extend(sorted(dir_path.rglob(f"*{ext}")))
        videos.extend(sorted(dir_path.rglob(f"*{ext.upper()}")))

    videos = sorted(set(videos))  # 去重

    if not videos:
        console.print(f"[yellow]未找到视频文件 ({', '.join(exts)})[/yellow]")
        raise typer.Exit(0)

    console.print(f"[bold cyan]仔仔猫 响度归一化[/bold cyan] — {len(videos)} 个视频")
    console.print(f"目标响度: [green]{target_lufs} LUFS[/green]")
    if replace:
        mode_desc = "替换原文件" if not keep_original else "替换原文件 (.orig 保留)"
    else:
        mode_desc = "输出 *_normalized.mp4"
    console.print(f"模式: [dim]{mode_desc}[/dim]\n")

    from zaizaimao.core.loudnorm import LoudnormProcessor, LoudnormError

    processor = LoudnormProcessor(target_lufs=target_lufs)
    ok = 0
    fail = 0

    async def _run():
        nonlocal ok, fail
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("处理中...", total=len(videos))

            for v in videos:
                rel = v.relative_to(dir_path) if v.is_relative_to(dir_path) else v.name
                progress.update(task, description=f"{rel}")

                try:
                    result = await processor.process(v)
                    if replace:
                        normalized = Path(result.output_path)
                        if keep_original:
                            bak = v.with_suffix(v.suffix + ".orig")
                            v.rename(bak)
                        normalized.rename(v)
                        console.print(
                            f"  [green]OK[/green] {v.name}  "
                            f"(增益 [bold]{result.target_offset:+.1f} dB[/bold])"
                        )
                    else:
                        console.print(
                            f"  [green]OK[/green] {v.name} → "
                            f"{Path(result.output_path).name}  "
                            f"(增益 [bold]{result.target_offset:+.1f} dB[/bold])"
                        )
                    ok += 1
                except LoudnormError as e:
                    console.print(f"  [red]FAIL[/red] {v.name}: {e}")
                    fail += 1

                progress.update(task, advance=1)

    asyncio.run(_run())

    summary_color = "green" if fail == 0 else ("yellow" if ok > 0 else "red")
    console.print(f"\n[bold {summary_color}]===== 完成: 成功 {ok}, 失败 {fail} =====[/bold {summary_color}]")


# ── 入口 ──────────────────────────────────────────────────

def main():
    app()


if __name__ == "__main__":
    main()
