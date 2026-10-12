"""Final test: extract secUid from scripts + call API via page fetch()."""
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

async def evaluate_async(ws, expr, msg_id, timeout=15, await_promise=False):
    """Send Runtime.evaluate and wait for result."""
    params = {"expression": expr, "returnByValue": True}
    if await_promise:
        params["awaitPromise"] = True

    await ws.send_json({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": params,
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
            ws_url, timeout=aiohttp.ClientTimeout(total=60), max_msg_size=32*1024*1024
        ) as ws:
            await ws.send_json({"id": 1, "method": "Page.enable"})
            await ws.send_json({
                "id": 2, "method": "Page.navigate",
                "params": {"url": URL},
            })

            # Wait for page to fully load
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=3)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("method") == "Page.loadEventFired":
                            print("[OK] Page loaded")
                            break
                except asyncio.TimeoutError:
                    pass

            print("[..] Waiting 8s for JS init...")
            await asyncio.sleep(8)

            # Step 1: Extract secUid from page (multiple strategies)
            print("[..] Extracting secUid...")
            secuid = await evaluate_async(ws, """
                (function(){
                    // Strategy 1: from outerHTML (works even if scripts not parsed)
                    var m = document.documentElement.outerHTML.match(
                        /"secUid":"([^"]+)"/
                    );
                    if (m) return m[1];

                    // Strategy 2: from script tags
                    var scripts = document.querySelectorAll('script');
                    for (var i = 0; i < scripts.length; i++) {
                        var m2 = scripts[i].textContent.match(
                            /"secUid":"([^"]+)"/
                        );
                        if (m2) return m2[1];
                    }
                    return '';
                })()
            """, 10)

            if secuid:
                print(f"[OK] secUid: {secuid[:40]}...")
            else:
                print("[!!] secUid NOT FOUND in scripts")
                return

            # Step 2: Call TikTok API from page context
            print("[..] Calling TikTok API via page fetch()...")
            api_result = await evaluate_async(ws, f"""
                (async function(){{
                    var secUid = '{secuid}';
                    try {{
                        var url = '/api/post/item_list/?'
                            + 'aid=1988&count=35&cursor=0&secUid='
                            + encodeURIComponent(secUid);
                        var resp = await fetch(url, {{credentials: 'include'}});
                        if (!resp.ok) return JSON.stringify({{_error: 'HTTP ' + resp.status}});
                        return await resp.text();
                    }} catch(e) {{
                        return JSON.stringify({{_error: e.message || String(e)}});
                    }}
                }})()
            """, 20, await_promise=True)

            if not api_result:
                print("[!!] API call returned nothing")
                return

            try:
                api_data = json.loads(api_result)
            except json.JSONDecodeError:
                print(f"[!!] API response not JSON: {api_result[:300]}")
                return

            if "_error" in api_data:
                print(f"[!!] API error: {api_data['_error']}")
                return

            items = api_data.get("itemList") or []
            has_more = api_data.get("hasMore", False)
            cursor = api_data.get("cursor", 0)
            print(f"[OK] Got {len(items)} items (hasMore={has_more}, cursor={cursor})")

            for i, item in enumerate(items[:15]):
                desc = item.get("desc", "")[:80]
                plays = item.get("stats", {}).get("playCount", 0)
                vid = item.get("id", "")[:20]
                print(f"  [{i+1:2d}] plays={str(plays):>10s}  id={vid}  {desc}")

            if len(items) > 15:
                print(f"  ... and {len(items) - 15} more items")

            # Step 3: Test pagination (next page)
            if has_more and cursor:
                print(f"\n[..] Fetching page 2 (cursor={cursor})...")
                await asyncio.sleep(0.5)
                api_result2 = await evaluate_async(ws, f"""
                    (async function(){{
                        var secUid = '{secuid}';
                        try {{
                            var url = '/api/post/item_list/?'
                                + 'aid=1988&count=35&cursor={cursor}&secUid='
                                + encodeURIComponent(secUid);
                            var resp = await fetch(url, {{credentials: 'include'}});
                            if (!resp.ok) return JSON.stringify({{_error: 'HTTP ' + resp.status}});
                            return await resp.text();
                        }} catch(e) {{
                            return JSON.stringify({{_error: e.message || String(e)}});
                        }}
                    }})()
                """, 21, await_promise=True)

                if api_result2:
                    try:
                        api_data2 = json.loads(api_result2)
                        items2 = api_data2.get("itemList") or []
                        print(f"[OK] Page 2: {len(items2)} items")
                        for item in items2[:5]:
                            desc = item.get("desc", "")[:60]
                            print(f"       {desc}")
                    except json.JSONDecodeError:
                        print("[!!] Page 2 response not JSON")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
