"""Test: create a NEW tab instead of reusing existing page."""
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


async def create_new_page(session, port):
    """Always create a new tab instead of reusing existing ones."""
    async with session.put(
        f"http://127.0.0.1:{port}/json/new",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        new_target = await resp.json()
        ws_url = new_target.get("webSocketDebuggerUrl")
        title = new_target.get("title", "")
        print(f"Created new tab: '{title}'")
        return ws_url


async def cdp_evaluate_raw(ws, expr, msg_id, timeout=10):
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
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if data.get("id") == msg_id:
                err = data.get("error")
                if err:
                    return f"CDP_ERROR: {err}"
                result = data.get("result", {})
                sub_result = result.get("result", {})
                value = sub_result.get("value", "")
                return str(value)
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            return f"WS_{msg.type.name}"
    return "TIMEOUT"


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    async with aiohttp.ClientSession() as session:
        # Create NEW tab
        ws_url = await create_new_page(session, port)
        if not ws_url:
            print("Failed to create new tab!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=90),
            max_msg_size=50 * 1024 * 1024,
        ) as ws:
            await ws.send_json({"id": 1, "method": "Page.enable"})

            print("[..] Navigating...")
            await ws.send_json({
                "id": 2, "method": "Page.navigate",
                "params": {"url": URL},
            })

            # Wait for load
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=3)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("method") == "Page.loadEventFired":
                            print("[OK] Load event")
                            break
                except asyncio.TimeoutError:
                    pass

            print("[..] Waiting 3s...")
            await asyncio.sleep(3)

            # Check page state
            url_val = await cdp_evaluate_raw(ws, "window.location.href", 50)
            title_val = await cdp_evaluate_raw(ws, "document.title", 51)
            html_len = await cdp_evaluate_raw(ws, "document.documentElement.outerHTML.length", 52)
            has_secuid = await cdp_evaluate_raw(ws, "document.documentElement.outerHTML.includes('secUid')", 53)

            print(f"URL: {url_val}")
            print(f"Title: '{title_val}'")
            print(f"HTML: {html_len} bytes")
            print(f"Has secUid: {has_secuid}")

            if has_secuid == "True":
                secuid = await cdp_evaluate_raw(ws, """
                    (function(){
                        var m=document.documentElement.outerHTML.match(
                            /"secUid"\\s*:\\s*"([^"]+)"/
                        );
                        return m?m[1]:'NOT_FOUND';
                    })()
                """, 60)
                print(f"secUid: {secuid[:60]}...")

                # Call API
                print("\n[..] Calling TikTok API...")
                result = await cdp_evaluate_raw(ws, f"""
                    (async function(){{
                        var u='/api/post/item_list/?'
                          +'aid=1988&count=35&cursor=0&secUid='
                          +encodeURIComponent('{secuid}');
                        try{{
                            var r=await fetch(u,{{credentials:'include'}});
                            if(!r.ok) return JSON.stringify({{_error:'HTTP '+r.status}});
                            return await r.text();
                        }}catch(e){{
                            return JSON.stringify({{_error:e.message||String(e)}});
                        }}
                    }})()
                """, 70, timeout=20)

                if result and not result.startswith("CDP_ERROR") and not result.startswith("TIMEOUT"):
                    try:
                        api_data = json.loads(result)
                        items = api_data.get("itemList") or []
                        print(f"[OK] Got {len(items)} items!")
                        for i, item in enumerate(items[:10]):
                            desc = item.get("desc", "")[:70]
                            print(f"  [{i+1}] {desc}")
                    except json.JSONDecodeError:
                        print(f"Invalid JSON: {result[:200]}")
                else:
                    print(f"API call failed: {result}")
            else:
                print("secUid not in HTML, trying longer wait...")
                for delay in [5, 10]:
                    await asyncio.sleep(delay)
                    has_secuid = await cdp_evaluate_raw(ws, "document.documentElement.outerHTML.includes('secUid')", 80+delay)
                    html_len2 = await cdp_evaluate_raw(ws, "document.documentElement.outerHTML.length", 81+delay)
                    print(f"  After +{delay}s: HTML={html_len2}, secUid={has_secuid}")

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
