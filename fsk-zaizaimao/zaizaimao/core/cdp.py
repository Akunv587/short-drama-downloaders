"""
CDP (Chrome DevTools Protocol) 模块

通过 Chrome 远程调试端口实现:
- TikTok 登录 Cookie 提取 (Netscape 格式)
- TikTok 创作者主页短剧列表提取

核心流程:
1. 探测 Chrome 调试端口 (9222-9225)
2. HTTP GET /json 获取可调试的标签页
3. WebSocket 连接 → CDP 命令交互
4. Cookie: Network.getCookies → Netscape cookies.txt
5. 短剧: performance entries + Runtime.evaluate → fetch drama_list API

参考: fsk-tool/tiktok-video-downloader.js (Node.js 已验证方案)
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp

logger = logging.getLogger("zaizaimao.cdp")

# Cookie 文件有效期 (24 小时)
COOKIE_TTL_SECONDS = 86400

# Chrome 可执行文件搜索路径
CHROME_EXE_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

# macOS
if sys.platform == "darwin":
    CHROME_EXE_PATHS = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]

# Linux
if sys.platform == "linux":
    CHROME_EXE_PATHS = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ]


async def _http_get_json(session: aiohttp.ClientSession, url: str, timeout: float = 5.0) -> dict | None:
    """HTTP GET 并解析 JSON，失败时返回 None"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            return await resp.json()
    except Exception:
        return None


# ── Chrome 调试端口探测 ────────────────────────────────────


async def find_chrome_debug_port() -> int | None:
    """
    探测 Chrome 远程调试端口 (9222-9225)。

    请求 /json/version 端点，如果返回包含 Browser 字段则确认可用。
    """
    async with aiohttp.ClientSession() as session:
        for port in range(9222, 9226):
            try:
                info = await _http_get_json(
                    session,
                    f"http://127.0.0.1:{port}/json/version",
                    timeout=3.0,
                )
                if info and info.get("Browser"):
                    logger.info("检测到 Chrome 调试端口: %s (%s)", port, info.get("Browser"))
                    return port
            except Exception:
                continue
    return None


# ── CDP WebSocket Cookie 获取 ──────────────────────────────


async def cdp_get_cookies(port: int, domains: list[str]) -> list[dict]:
    """
    通过 CDP Network.getCookies 获取指定域名的 Cookie。

    Args:
        port: Chrome 调试端口
        domains: 要获取 Cookie 的域名列表

    Returns:
        CDP Cookie 对象列表
    """
    async with aiohttp.ClientSession() as session:
        # 1. 获取可用的调试目标
        targets = await _http_get_json(
            session,
            f"http://127.0.0.1:{port}/json",
            timeout=5.0,
        )

        # 优先选 TikTok 页面，否则用任意 page 类型
        page_target = (
            next((t for t in targets if t.get("type") == "page" and "tiktok.com" in t.get("url", "")), None)
            or next((t for t in targets if t.get("type") == "page"), None)
            or next((t for t in targets if t.get("webSocketDebuggerUrl")), None)
        )

        if not page_target or not page_target.get("webSocketDebuggerUrl"):
            raise RuntimeError("无法找到可用的 Chrome 调试目标，请确保 Chrome 中有打开的标签页")

        ws_url = page_target["webSocketDebuggerUrl"]

    # 2. WebSocket 连接
    msg_id = 42  # 随机消息 ID
    cookies: list[dict] = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                ws_url,
                timeout=aiohttp.ClientTimeout(total=10.0),
                max_msg_size=4 * 1024 * 1024,
            ) as ws:
                # 发送 Network.getCookies 命令
                await ws.send_json({
                    "id": msg_id,
                    "method": "Network.getCookies",
                    "params": {"urls": domains},
                })

                # 接收响应
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = msg.json()
                        if data.get("id") == msg_id:
                            if data.get("error"):
                                raise RuntimeError(
                                    f"CDP 命令失败: {data['error'].get('message', 'unknown')}"
                                )
                            cookies = data.get("result", {}).get("cookies", [])
                            break
                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break

    except asyncio.TimeoutError:
        raise RuntimeError("CDP WebSocket 连接超时 (10s)")

    return cookies


# ── Netscape 格式转换 ──────────────────────────────────────


def cookies_to_netscape(cookies: list[dict]) -> str:
    """
    将 CDP Cookie 对象转换为 Netscape cookies.txt 格式。

    **关键规则**（违反会触发 http.cookiejar 警告）:
    - domain 以 '.' 开头 → flag 必须为 TRUE  (domain cookie)
    - domain 不以 '.' 开头 → flag 必须为 FALSE (host-only cookie)

    Netscape 格式:
        domain  flag  path  secure  expiry  name  value
    """
    lines = [
        "# Netscape HTTP Cookie File",
        "# This file was generated by zaizaimao CDP",
        "# https://curl.haxx.se/rfc/cookie_spec.html",
        "",
    ]

    for c in cookies:
        domain = c.get("domain", "")
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = int(c["expires"]) if c.get("expires", 0) > 0 else 2147483647
        name = c.get("name", "")
        value = c.get("value", "")

        # 判断 domain cookie vs host-only cookie
        is_domain_cookie = domain.startswith(".")
        flag = "TRUE" if is_domain_cookie else "FALSE"

        lines.append("\t".join([
            domain,
            flag,
            path,
            secure,
            str(expires),
            name,
            value,
        ]))

    return "\n".join(lines) + "\n"


# ── Chrome 启动 ────────────────────────────────────────────


async def launch_chrome_with_debug() -> bool:
    """
    尝试以远程调试模式启动 Chrome。

    搜索已知的 Chrome 安装路径，以 detached 模式启动，
    等待最多 15 秒确认调试端口可用。
    """
    chrome_exe = None
    for p in CHROME_EXE_PATHS:
        if os.path.exists(p):
            chrome_exe = p
            break

    if not chrome_exe:
        logger.warning("未找到 Chrome 安装路径")
        return False

    logger.info("正在启动 Chrome 调试模式: %s", chrome_exe)

    temp_dir = os.path.join(os.environ.get("TEMP", "/tmp"), "chrome-debug-profile")

    try:
        if sys.platform == "win32":
            subprocess.Popen(
                [
                    chrome_exe,
                    "--remote-debugging-port=9222",
                    f"--user-data-dir={temp_dir}",
                    "https://www.tiktok.com/",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            subprocess.Popen(
                [
                    chrome_exe,
                    "--remote-debugging-port=9222",
                    f"--user-data-dir={temp_dir}",
                    "https://www.tiktok.com/",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception as e:
        logger.error("启动 Chrome 失败: %s", e)
        return False

    # 等待 Chrome 启动 (最多 15 秒)
    for _ in range(15):
        await asyncio.sleep(1)
        port = await find_chrome_debug_port()
        if port:
            logger.info("Chrome 调试模式已启动，端口: %s", port)
            return True

    return False


# ── Cookie 自动提取 (主入口) ────────────────────────────────


async def auto_extract_cookies(
    output_path: str | None = None,
    domains: list[str] | None = None,
    force_refresh: bool = False,
) -> tuple[bool, str]:
    """
    自动从 Chrome 提取 TikTok Cookie 并保存为 cookies.txt。

    这是 CDP 模块的主入口，编排完整的提取流程:
    1. 检查缓存 (非强制时)
    2. 探测 Chrome 调试端口
    3. 若未检测到 → 尝试自动启动 Chrome
    4. CDP 获取 Cookie → Netscape 转换 → 写入文件

    Args:
        output_path: cookies.txt 输出路径 (默认: 项目根目录)
        domains: 要获取 Cookie 的域名 (默认: TikTok 域名)
        force_refresh: 是否强制刷新（忽略缓存）

    Returns:
        (success: bool, message: str)
    """
    if output_path is None:
        output_path = str(Path(__file__).resolve().parent.parent.parent / "cookies.txt")

    if domains is None:
        domains = [
            "https://www.tiktok.com",
            "https://tiktok.com",
        ]

    # 1. 检查缓存 (24h 有效期)
    if not force_refresh and os.path.exists(output_path):
        stat = os.stat(output_path)
        age = (Path(output_path).stat().st_mtime if os.path.exists(output_path) else 0)
        import time
        age = time.time() - os.path.getmtime(output_path)
        if stat.st_size > 100 and age < COOKIE_TTL_SECONDS:
            return True, f"Cookie 缓存有效 ({(age / 3600):.1f} 小时前)"

    # 2. 探测 Chrome 调试端口
    port = await find_chrome_debug_port()

    if not port:
        logger.info("未检测到 Chrome 调试端口，尝试自动启动...")
        launched = await launch_chrome_with_debug()
        if not launched:
            return False, (
                "未检测到 Chrome 远程调试端口。\n"
                "请手动启用:\n"
                "① 完全关闭 Chrome\n"
                "② Win+R → chrome.exe --remote-debugging-port=9222\n"
                "③ 在 Chrome 中登录 tiktok.com\n"
                "④ 重新尝试"
            )
        port = await find_chrome_debug_port()
        if not port:
            return False, "Chrome 已启动但调试端口仍不可用"

    # 3. CDP 获取 Cookie
    try:
        cookies = await cdp_get_cookies(port, domains)
    except RuntimeError as e:
        return False, str(e)

    # 过滤 TikTok 相关 cookie
    tik_cookies = [
        c for c in cookies
        if (c.get("domain", "") or "").lower() in (
            "tiktok.com", ".tiktok.com",
            "www.tiktok.com",
        ) or (c.get("domain", "") or "").lower().endswith(".tiktok.com")
    ]

    if not tik_cookies:
        return False, (
            "Chrome 中未找到 TikTok 登录 Cookie。\n"
            "请先在 Chrome 中访问 tiktok.com 并登录，然后重试。"
        )

    # 4. 转换为 Netscape 并保存
    netscape = cookies_to_netscape(tik_cookies)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(netscape, encoding="utf-8")

    logger.info(
        "已通过 CDP 提取 %s 个 TikTok Cookie → %s (端口: %s)",
        len(tik_cookies), output_path, port,
    )

    return True, f"✅ 已从 Chrome 提取 {len(tik_cookies)} 个 TikTok Cookie"


# ── 便捷函数 ──────────────────────────────────────────────


async def ensure_cookies_cdp(
    cookies_path: str | None = None,
    force_refresh: bool = False,
) -> str | None:
    """
    确保 cookies.txt 可用，需要时自动通过 CDP 提取。

    Returns:
        cookies.txt 路径，或 None (提取失败)
    """
    if cookies_path is None:
        cookies_path = str(Path(__file__).resolve().parent.parent.parent / "cookies.txt")

    # 如果文件已存在且非强制刷新，直接返回
    if not force_refresh and os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 100:
        import time
        age = time.time() - os.path.getmtime(cookies_path)
        if age < COOKIE_TTL_SECONDS:
            return cookies_path

    # 尝试 CDP 提取
    success, msg = await auto_extract_cookies(cookies_path, force_refresh=force_refresh)
    logger.info("CDP Cookie 提取: %s — %s", "成功" if success else "失败", msg)

    if success and os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 100:
        return cookies_path

    return None


# ── TikTok 短剧列表提取 ─────────────────────────────────────


@dataclass
class DramaInfo:
    """TikTok 短剧信息"""
    drama_id: str
    title: str
    episodes: int          # 总集数 (numVideos)
    plays: str             # 播放量 (numWatched, 原始字符串)
    description: str = ""
    themes: list[str] = field(default_factory=list)

    @property
    def plays_int(self) -> int:
        """播放量（整数）"""
        try:
            return int(self.plays)
        except (ValueError, TypeError):
            return 0

    @property
    def plays_display(self) -> str:
        """播放量（格式化显示，如 1.2M / 345K）"""
        n = self.plays_int
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)


async def cdp_extract_dramas(
    creator_url: str | None = None,
    port: int | None = None,
    timeout: float = 120.0,
) -> list[DramaInfo]:
    """
    通过 CDP 从 TikTok 创作者主页提取短剧列表。

    核心策略（参考已验证的 JavaScript bookmarklet）:
    1. 从 performance.getEntriesByType('resource') 发现 drama_list API URL
    2. 通过 Runtime.evaluate 调用 fetch() 获取数据
    3. 自动翻页直到 hasMore=false

    Args:
        creator_url: TikTok 创作者主页 URL（如 https://www.tiktok.com/@username）
                     为 None 时使用 Chrome 当前打开的 TikTok 页面
        port: Chrome 调试端口（None = 自动探测）

    Returns:
        短剧信息列表

    Raises:
        RuntimeError: Chrome 调试端口不可用 / 未找到 TikTok 页面 / API 调用失败
    """
    import re

    # 1. 探测 Chrome 调试端口
    if port is None:
        port = await find_chrome_debug_port()
    if not port:
        raise RuntimeError(
            "未检测到 Chrome 远程调试端口。\n"
            "请以调试模式启动 Chrome:\n"
            "  chrome.exe --remote-debugging-port=9222\n"
            "并在 Chrome 中打开 TikTok 创作者主页。"
        )

    async with aiohttp.ClientSession() as session:
        # 2. 获取 TikTok 页面的 WebSocket URL
        #    策略: 优先复用已打开的 TikTok 页面 (WebSocket 更稳定)
        #          仅在无 TikTok 页面时才创建新标签页
        async with session.get(
            f"http://127.0.0.1:{port}/json",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            try:
                targets = await resp.json()
            except Exception:
                raise RuntimeError("CDP /json 返回非 JSON 响应，Chrome 调试端口可能不可用")

        tiktok_target = next(
            (t for t in targets
             if t.get("type") == "page" and "tiktok.com" in t.get("url", "")),
            None,
        )

        if tiktok_target:
            # 复用已有的 TikTok 页面
            ws_url = tiktok_target["webSocketDebuggerUrl"]
            current_url = tiktok_target.get("url", "")
            if creator_url and creator_url not in current_url:
                created_new = False
                need_nav = True
            else:
                created_new = False
                need_nav = False
        elif creator_url:
            # 无 TikTok 页面且指定了 URL → 创建新标签页
            async with session.put(
                f"http://127.0.0.1:{port}/json/new",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                try:
                    new_target = await resp.json()
                except Exception:
                    raise RuntimeError("CDP /json/new 返回非 JSON 响应，Chrome 调试端口可能不可用")
                ws_url = new_target.get("webSocketDebuggerUrl")
                if not ws_url:
                    raise RuntimeError("无法创建新的 Chrome 标签页")
                created_new = True
                need_nav = True
        else:
            raise RuntimeError(
                "Chrome 中未找到 TikTok 页面。\n"
                "请先在 Chrome 中打开 TikTok 创作者主页。"
            )

        # 3. WebSocket 连接 + 提取流程
        async with session.ws_connect(
            ws_url,
            timeout=aiohttp.ClientTimeout(total=timeout),
            max_msg_size=50 * 1024 * 1024,
        ) as ws:
            msg_id = 100

            # 辅助: 发送 evaluate 并等待结果
            async def _eval(expr: str, await_p: bool = False, t: float = 30.0) -> str | None:
                nonlocal msg_id
                msg_id += 1
                mid = msg_id
                params = {"expression": expr, "returnByValue": True}
                if await_p:
                    params["awaitPromise"] = True
                try:
                    await ws.send_json({
                        "id": mid, "method": "Runtime.evaluate", "params": params,
                    })
                except Exception as e:
                    logger.warning("CDP 发送命令失败: %s", e)
                    return None

                deadline = time.time() + t
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(
                            ws.receive(),
                            timeout=min(3, max(0.5, deadline - time.time())),
                        )
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = msg.json()
                            except (ValueError, TypeError) as e:
                                logger.warning("CDP 消息 JSON 解析失败: %s", str(e)[:100])
                                continue
                            if data.get("id") == mid:
                                err = data.get("error")
                                if err:
                                    logger.warning("CDP evaluate 错误: %s", err)
                                    return None
                                res = data.get("result", {})
                                exc = res.get("exceptionDetails")
                                if exc:
                                    desc = exc.get("exception", {}).get("description", "?")
                                    logger.warning("JS 异常: %s", desc)
                                    return None
                                return res.get("result", {}).get("value", "")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            return None
                    except asyncio.TimeoutError:
                        pass
                logger.warning("CDP evaluate 超时 (id=%s)", mid)
                return None

            # 如果需要导航到新 URL (新标签页 或 切换创作者)
            if need_nav:
                try:
                    await ws.send_json({"id": 1, "method": "Page.enable"})
                    await ws.send_json({
                        "id": 2, "method": "Page.navigate",
                        "params": {"url": creator_url},
                    })
                except Exception as e:
                    logger.warning("导航命令发送失败: %s", e)
                # 等待页面加载: 轮询 document.readyState 直到 complete
                logger.info("正在导航到 %s 并等待页面加载...", creator_url)
                for wait_i in range(20):
                    await asyncio.sleep(1)
                    state = await _eval("document.readyState")
                    if state == "complete":
                        logger.info("页面加载完成 (等待 %s 秒)", wait_i + 1)
                        break
                else:
                    logger.warning("页面加载等待超时 (20秒)")
                # 额外等待异步数据加载
                await asyncio.sleep(3)

            # 4. 从 performance entries 发现 drama_list API URL
            #    如果当前不在短剧 tab，尝试自动点击
            js_find_api = """
            (function(){
                var entries = performance.getEntriesByType('resource');
                for (var i = 0; i < entries.length; i++) {
                    var u = entries[i].name;
                    if (u.indexOf('/api/drama/user/drama_list/') !== -1) {
                        return u;
                    }
                }
                return '';
            })()
            """

            api_url = await _eval(js_find_api)
            if not api_url:
                # 尝试点击短剧 tab — 使用 CDP Input.dispatchMouseEvent
                # React 合成事件需要真实的浏览器鼠标事件而非 DOM dispatchEvent
                logger.info("未找到 drama API URL，尝试点击短剧 tab...")
                click_result = await _cdp_click_drama_tab(ws)
                if click_result:
                    await asyncio.sleep(4)
                    api_url = await _eval(js_find_api)

            if not api_url:
                raise RuntimeError(
                    "未找到 drama_list API URL。\n"
                    "请确保在 TikTok 创作者主页的「短剧」tab 页面。"
                )

            logger.info("发现 drama API URL")

            # 5. 清理 API URL（重置 cursor/count 参数）
            base_url = re.sub(r'&cursor=\d+', '', api_url)
            base_url = re.sub(r'&count=\d+', '', base_url)
            sep = '&' if '?' in base_url else '?'
            base_url += f'{sep}count=35'

            # 6. 翻页提取
            all_dramas: list[DramaInfo] = []
            cursor = 0
            max_pages = 15

            for page in range(max_pages):
                page_url = f"{base_url}&cursor={cursor}"
                logger.info("获取短剧列表 第 %s 页 (cursor=%s)", page + 1, cursor)

                fetch_js = f"""
                (async function(){{
                    try {{
                        var r = await fetch({json.dumps(page_url)},
                            {{credentials: 'include'}});
                        if (!r.ok) return JSON.stringify({{_err: 'HTTP ' + r.status}});
                        var ct = r.headers.get('content-type') || '';
                        var text = await r.text();
                        // 检测 HTML 错误响应 (TikTok 偶尔返回 Internal Server Error 页面)
                        if (ct.indexOf('text/html') !== -1 || text.trim().startsWith('<!DOCTYPE') || text.trim().startsWith('<html')) {{
                            return JSON.stringify({{_err: 'HTML response (likely 5xx error): ' + text.substring(0, 150)}});
                        }}
                        return text;
                    }} catch(e) {{
                        return JSON.stringify({{_err: e.message || String(e)}});
                    }}
                }})()
                """
                result = await _eval(fetch_js, await_p=True, t=30)

                if not result:
                    logger.warning("第 %s 页无响应，停止翻页", page + 1)
                    break

                try:
                    data = json.loads(result)
                except json.JSONDecodeError:
                    logger.warning("第 %s 页响应非 JSON: %s", page + 1, result[:200])
                    break

                if "_err" in data:
                    err = data["_err"]
                    logger.warning("API 错误: %s", err)
                    if "429" in err:
                        logger.info("触发限流，等待 15 秒...")
                        await asyncio.sleep(15)
                        continue
                    break

                drama_list = data.get("dramaList") or []
                for d in drama_list:
                    all_dramas.append(DramaInfo(
                        drama_id=d.get("dramaID", ""),
                        title=d.get("dramaName", ""),
                        episodes=d.get("numVideos", 0),
                        plays=d.get("numWatched", "0"),
                        description=d.get("description", ""),
                        themes=[t.get("tagVal", "") for t in (d.get("themes") or [])],
                    ))

                logger.info("  获取 %s 部短剧 (累计 %s)", len(drama_list), len(all_dramas))

                if len(drama_list) == 0:
                    break

                has_more = data.get("hasMore", False)
                new_cursor = data.get("cursor", 0)
                if isinstance(new_cursor, str):
                    try:
                        new_cursor = int(new_cursor)
                    except ValueError:
                        new_cursor = cursor + len(drama_list)

                if not has_more:
                    break

                cursor = new_cursor
                await asyncio.sleep(1.5)

            logger.info("短剧提取完成: 共 %s 部", len(all_dramas))
            return all_dramas


async def _cdp_click_drama_tab(ws) -> bool:
    """通过 CDP Input.dispatchMouseEvent 点击 TikTok 短剧 tab。

    React 合成事件系统需要真实的浏览器鼠标事件，DOM dispatchEvent
    或 element.click() 无法触发。此函数获取元素坐标后发送原生鼠标事件。
    """
    import aiohttp

    # 启用 Input 域
    await ws.send_json({"id": 390, "method": "Input.enable"})

    drama_selectors = [
        '[data-e2e="drama-tab"]',
        '[class*="PDrama"]',
        '[class*="drama-tab"]',
    ]

    for selector in drama_selectors:
        js_get_rect = (
            "(function(){"
            "  var el = document.querySelector(" + json.dumps(selector) + ");"
            "  if (!el || el.offsetParent === null) return JSON.stringify({found: false});"
            "  var r = el.getBoundingClientRect();"
            "  return JSON.stringify({"
            "    found: true,"
            "    x: Math.round(r.left + r.width / 2),"
            "    y: Math.round(r.top + r.height / 2)"
            "  });"
            "})()"
        )

        mid = int(time.time() * 1000) % 100000 + 400
        await ws.send_json({
            "id": mid, "method": "Runtime.evaluate",
            "params": {"expression": js_get_rect, "returnByValue": True},
        })

        deadline = time.time() + 8
        rect_data = None
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(
                    ws.receive(),
                    timeout=min(3, max(0.1, deadline - time.time())),
                )
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        logger.warning("CDP 非 JSON 消息: %s", msg.data[:120])
                        break
                    if data.get("id") == mid:
                        value = data.get("result", {}).get("result", {}).get("value", "")
                        if value:
                            try:
                                rect_data = json.loads(value)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        break
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
            except asyncio.TimeoutError:
                pass

        if not rect_data or not rect_data.get("found"):
            continue

        x, y = rect_data["x"], rect_data["y"]
        logger.info("CDP: Input.dispatchMouseEvent 点击 (%d, %d)", x, y)

        # 完整鼠标事件序列: mouseMoved → mousePressed → mouseReleased
        for event_type in ("mouseMoved", "mousePressed", "mouseReleased"):
            mid = int(time.time() * 1000) % 100000 + 500
            await ws.send_json({
                "id": mid,
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": event_type,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                },
            })

        logger.info("CDP: 短剧 tab 已点击 (selector=%s)", selector)
        return True

    return False
