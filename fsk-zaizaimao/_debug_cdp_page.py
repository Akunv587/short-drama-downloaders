"""Debug: extract and inspect __UNIVERSAL_DATA_FOR_REHYDRATION__ from TikTok page."""
import asyncio
import json
import time
import aiohttp

URL = "https://www.tiktok.com/@polestoryflix"

async def find_cdp_port():
    async with aiohttp.ClientSession() as session:
        for p in range(9222, 9226):
            try:
                async with session.get(
                    f"http://127.0.0.1:{p}/json/version",
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as resp:
                    info = await resp.json()
                    if info.get("Browser"):
                        return p
            except Exception:
                continue
    return None

async def get_page_ws(session, port):
    async with session.get(
        f"http://127.0.0.1:{port}/json",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        targets = await resp.json()
    page = next((t for t in targets if t.get("type") == "page"), None)
    return page.get("webSocketDebuggerUrl") if page else None

async def evaluate(ws, expr, msg_id, timeout=10):
    """Send Runtime.evaluate and wait for result."""
    await ws.send_json({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True},
    })
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        msg = await asyncio.wait_for(
            ws.receive(), timeout=min(3, max(0.1, remaining))
        )
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("id") == msg_id:
                value = data.get("result", {}).get("result", {}).get("value", "")
                return value
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            break
    return None

async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    async with aiohttp.ClientSession() as session:
        ws_url = await get_page_ws(session, port)
        if not ws_url:
            print("No page target!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=45), max_msg_size=32*1024*1024
        ) as ws:
            # Navigate
            await ws.send_json({"id": 1, "method": "Page.enable"})
            await ws.send_json({
                "id": 2, "method": "Page.navigate",
                "params": {"url": URL},
            })
            await asyncio.sleep(5)

            # Get URL and title
            url_val = await evaluate(ws, "window.location.href", 10)
            title_val = await evaluate(ws, "document.title", 11)
            print(f"Current URL: {url_val}")
            print(f"Title: {title_val}")

            # Get full __UNIVERSAL_DATA_FOR_REHYDRATION__
            raw = await evaluate(
                ws,
                "JSON.stringify(window.__UNIVERSAL_DATA_FOR_REHYDRATION__ || {})",
                20, timeout=15,
            )

            if raw:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    print(f"JSON decode failed. Raw (first 500 chars):")
                    print(raw[:500])
                    return

                # Show top-level keys
                print("\n__UNIVERSAL_DATA_FOR_REHYDRATION__ keys:")
                if isinstance(data, dict):
                    for k in list(data.keys())[:30]:
                        v = data[k]
                        vtype = type(v).__name__
                        vsize = str(len(v)) if isinstance(v, (str, list, dict)) else ""
                        print(f"  {k}: {vtype} {vsize}")

                    # Try to navigate to user-detail
                    scope = data.get("__DEFAULT_SCOPE__", {})
                    print(f"\n__DEFAULT_SCOPE__ keys: {list(scope.keys())[:20]}")

                    ud = scope.get("webapp.user-detail", {})
                    print(f"\nwebapp.user-detail keys: {list(ud.keys())[:20]}")

                    ui = ud.get("userInfo", {})
                    print(f"\nuserInfo keys: {list(ui.keys())[:20]}")

                    user = ui.get("user", {})
                    print(f"\nuser keys: {list(user.keys())[:20]}")

                    secuid = user.get("secUid", "NOT FOUND")
                    uid = user.get("id", "NOT FOUND")
                    unique_id = user.get("uniqueId", "NOT FOUND")
                    print(f"\nsecUid: {secuid}")
                    print(f"id: {uid}")
                    print(f"uniqueId: {unique_id}")

                    # Show user object (limited)
                    user_safe = {k: v for k, v in user.items()
                                if not isinstance(v, (dict, list))}
                    print(f"\nUser info (scalars only):")
                    for k, v in list(user_safe.items())[:10]:
                        print(f"  {k}: {v}")
                else:
                    print(f"Not a dict: {type(data).__name__}")
                    print(str(data)[:500])
            else:
                print("Got no response for __UNIVERSAL_DATA_FOR_REHYDRATION__")

            # Try alternative: extract from HTML
            html_snippet = await evaluate(
                ws,
                "(function(){"
                " var m=document.documentElement.outerHTML.match("
                "   /id=\"__UNIVERSAL_DATA_FOR_REHYDRATION__\"[^>]*>([^<]+)</"
                " );"
                " return m?m[1]:'';"
                "})()",
                30,
            )
            if html_snippet:
                print(f"\nHTML snippet around universal data: {html_snippet[:200]}...")


if __name__ == "__main__":
    asyncio.run(main())
