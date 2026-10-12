"""Simple test: check if secUid is in the page HTML right after navigation."""
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

async def evaluate_async(ws, expr, msg_id, timeout=15):
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
            ws_url, timeout=aiohttp.ClientTimeout(total=60), max_msg_size=50*1024*1024
        ) as ws:
            await ws.send_json({"id": 1, "method": "Page.enable"})
            
            # Create a new tab for a clean test
            await ws.send_json({
                "id": 2, "method": "Page.navigate",
                "params": {"url": URL},
            })

            print("Waiting for page load...")
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=3)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("method") == "Page.loadEventFired":
                            print("Load event!")
                            break
                except asyncio.TimeoutError:
                    pass

            # Wait different durations and check
            for wait_time in [2, 5, 10, 15]:
                await asyncio.sleep(wait_time)
                
                # Check URL
                url_val = await evaluate_async(ws, "window.location.href", 100 + wait_time)
                
                # Search for secUid
                secuid = await evaluate_async(ws, """
                    (function(){
                        var html = document.documentElement.outerHTML;
                        var idx = html.indexOf('secUid');
                        if (idx < 0) return 'NOT_FOUND_IN_HTML';
                        var start = Math.max(0, idx - 20);
                        var snippet = html.substring(start, idx + 120);
                        snippet = snippet.replace(/\\s+/g, ' ');
                        var match = html.match(/"secUid":"([^"]+)"/);
                        return JSON.stringify({
                            found: true,
                            value: match ? match[1].substring(0,40)+'...' : 'regex_no_match',
                            snippet: snippet.substring(0, 150)
                        });
                    })()
                """, 110 + wait_time, timeout=10)
                
                print(f"  After {wait_time:2d}s: URL={url_val}, secUid={secuid}")

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
