"""Optimized: capture secUid from network, then call API via fetch after page loads."""
import asyncio
import json
import time
import aiohttp
import urllib.parse

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
    async with session.put(
        f"http://127.0.0.1:{port}/json/new",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        new_target = await resp.json()
        return new_target.get("webSocketDebuggerUrl")


async def evaluate_async(ws, expr, msg_id, timeout=15, await_promise=False):
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
        ws_url = await create_new_page(session, port)
        if not ws_url:
            print("Failed to create new tab!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=90),
            max_msg_size=50 * 1024 * 1024,
        ) as ws:
            # Enable Page + Network (for secUid capture)
            await ws.send_json({"id": 1, "method": "Page.enable"})
            await ws.send_json({"id": 2, "method": "Network.enable"})

            # Navigate
            print("[..] Navigating...")
            await ws.send_json({
                "id": 3, "method": "Page.navigate",
                "params": {"url": URL},
            })

            # Capture secUid from API URL + wait for page load
            secuid = None
            load_done = False
            deadline = time.time() + 30

            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(
                        ws.receive(), timeout=min(3, deadline - time.time())
                    )
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        method = data.get("method", "")

                        if method == "Page.loadEventFired":
                            load_done = True
                            print("[OK] Page loaded")

                        elif method == "Network.responseReceived":
                            resp = data.get("params", {}).get("response", {})
                            resp_url = resp.get("url", "")

                            if not secuid and "/api/post/item_list/" in resp_url:
                                parsed = urllib.parse.urlparse(resp_url)
                                qs = urllib.parse.parse_qs(parsed.query)
                                s = qs.get("secUid", [None])[0]
                                if s:
                                    secuid = s
                                    print(f"[OK] secUid captured from API URL: {s[:40]}...")

                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break

                    if load_done and secuid:
                        break
                except asyncio.TimeoutError:
                    break

            if not secuid:
                print("[!!] Could not capture secUid!")
                return

            # DISABLE Network monitoring to stop event flood
            await ws.send_json({"id": 99, "method": "Network.disable"})
            print("[OK] Network monitoring disabled")

            # Wait extra for page to stabilize
            print("[..] Waiting 5s for page to settle...")
            await asyncio.sleep(5)

            # Now call API from within page (browser handles auth)
            print("[..] Calling TikTok API via page fetch()...")
            all_items = []
            cursor = 0

            for page_num in range(3):
                api_result = await evaluate_async(ws, f"""
                    (async function(){{
                        var u='/api/post/item_list/?'
                          +'aid=1988&count=35&cursor={cursor}&secUid='
                          +encodeURIComponent('{secuid}');
                        try{{
                            var r=await fetch(u,{{credentials:'include'}});
                            if(!r.ok) return JSON.stringify({{_error:'HTTP '+r.status}});
                            return await r.text();
                        }}catch(e){{
                            return JSON.stringify({{_error:e.message||String(e)}});
                        }}
                    }})()
                """, 50 + page_num, await_promise=True, timeout=20)

                if not api_result:
                    print(f"[!!] Page {page_num+1}: no response")
                    break

                try:
                    api_data = json.loads(api_result)
                except json.JSONDecodeError:
                    print(f"[!!] Page {page_num+1}: invalid JSON: {api_result[:200]}")
                    break

                if "_error" in api_data:
                    print(f"[!!] Page {page_num+1}: API error: {api_data['_error']}")
                    break

                items = api_data.get("itemList") or []
                has_more = api_data.get("hasMore", False)
                new_cursor = api_data.get("cursor", 0)

                all_items.extend(items)
                print(f"[OK] Page {page_num+1}: {len(items)} items "
                      f"(total {len(all_items)}, hasMore={has_more})")

                if not has_more:
                    break
                cursor = new_cursor
                await asyncio.sleep(1)

            # Results
            print(f"\n{'='*60}")
            print(f"Total items: {len(all_items)}")

            for i, item in enumerate(all_items[:15]):
                desc = item.get("desc", "")[:70]
                plays = item.get("stats", {}).get("playCount", 0)
                vid = item.get("id", "")[:20]
                print(f"  [{i+1:2d}] plays={str(plays):>10s}  id={vid}  {desc}")

            if len(all_items) > 15:
                print(f"  ... and {len(all_items)-15} more items")

    print(f"\n{'='*60}")
    print(f"SUCCESS: {len(all_items)} videos extracted!")


if __name__ == "__main__":
    asyncio.run(main())
