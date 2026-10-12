"""Dedicated WebSocket approach: capture secUid, then new WS for API call."""
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


async def get_page_ws_url(session, port):
    """Get WebSocket URL for an existing page target."""
    async with session.get(
        f"http://127.0.0.1:{port}/json",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        targets = await resp.json()
    # Find a TikTok page or any page
    for t in targets:
        if t.get("type") == "page" and "tiktok.com" in t.get("url", ""):
            return t.get("webSocketDebuggerUrl")
    for t in targets:
        if t.get("type") == "page":
            return t.get("webSocketDebuggerUrl")
    return None


async def create_new_page(session, port):
    async with session.put(
        f"http://127.0.0.1:{port}/json/new",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        new_target = await resp.json()
        return new_target.get("webSocketDebuggerUrl")


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    async with aiohttp.ClientSession() as session:
        # ── Phase 1: Navigate + Capture secUid ──
        print("=== Phase 1: Navigate & Capture secUid ===")
        ws_url = await create_new_page(session, port)
        if not ws_url:
            print("Failed to create new tab!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=60),
            max_msg_size=10 * 1024 * 1024,
        ) as ws:
            await ws.send_json({"id": 1, "method": "Page.enable"})
            await ws.send_json({"id": 2, "method": "Network.enable"})

            print("[..] Navigating...")
            await ws.send_json({
                "id": 3, "method": "Page.navigate",
                "params": {"url": URL},
            })

            # Capture secUid from API URL
            secuid = None
            deadline = time.time() + 30

            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(
                        ws.receive(),
                        timeout=min(3, max(0.5, deadline - time.time())),
                    )
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        method = data.get("method", "")

                        if not secuid and method == "Network.responseReceived":
                            resp = data.get("params", {}).get("response", {})
                            resp_url = resp.get("url", "")
                            if "/api/post/item_list/" in resp_url:
                                parsed = urllib.parse.urlparse(resp_url)
                                qs = urllib.parse.parse_qs(parsed.query)
                                s = qs.get("secUid", [None])[0]
                                if s:
                                    secuid = s
                                    print(f"[OK] secUid: {s[:40]}...")

                        if method == "Page.loadEventFired":
                            print("[OK] Page loaded")

                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break

                    if secuid:
                        # Got secUid, we can exit early
                        # Wait a bit more for page to stabilize
                        start_wait = time.time()
                        while time.time() - start_wait < 5:
                            try:
                                msg = await asyncio.wait_for(ws.receive(), timeout=1)
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    if data.get("method") == "Page.loadEventFired":
                                        print("[OK] Page loaded (late)")
                            except asyncio.TimeoutError:
                                pass
                        break

                except asyncio.TimeoutError:
                    if secuid:
                        break

        if not secuid:
            print("[!!] Could not capture secUid!")
            return

        print("[OK] Phase 1 complete, WebSocket closed")

        # ── Phase 2: Call API via dedicated WebSocket ──
        print("\n=== Phase 2: Call TikTok API ===")
        # Wait a moment for page to settle
        await asyncio.sleep(3)

        # Get fresh WebSocket URL (page is now on TikTok)
        ws_url2 = await get_page_ws_url(session, port)
        if not ws_url2:
            print("Failed to get page WebSocket URL!")
            return

        async with session.ws_connect(
            ws_url2, timeout=aiohttp.ClientTimeout(total=60),
            max_msg_size=10 * 1024 * 1024,
        ) as ws:
            all_items = []
            cursor = 0

            for page_num in range(3):
                msg_id = 100 + page_num
                js_expr = (
                    "(async function(){"
                    "  try{"
                    "    var u='/api/post/item_list/?"
                    "      +'aid=1988&count=35&cursor=" + str(cursor)
                    + "&secUid='+encodeURIComponent('" + secuid + "');"
                    "    var r=await fetch(u,{credentials:'include'});"
                    "    if(!r.ok) return JSON.stringify({_error:'HTTP '+r.status});"
                    "    return await r.text();"
                    "  }catch(e){"
                    "    return JSON.stringify({_error:e.message||String(e)});"
                    "  }"
                    "})()"
                )

                await ws.send_json({
                    "id": msg_id,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": js_expr,
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                })

                print(f"[..] Sent evaluate msg_id={msg_id}, waiting for response...")

                # Wait for response
                result = None
                deadline = time.time() + 25
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(
                            ws.receive(),
                            timeout=min(5, max(0.5, deadline - time.time())),
                        )
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("id") == msg_id:
                                err = data.get("error")
                                if err:
                                    print(f"[!!] CDP error: {err}")
                                    break
                                result_obj = data.get("result", {})
                                # Check for exception details
                                exc = result_obj.get("exceptionDetails", {})
                                if exc:
                                    print(f"[!!] JS Exception:")
                                    print(f"    type: {exc.get('type','?')}")
                                    print(f"    className: {exc.get('className','?')}")
                                    print(f"    description: {exc.get('description','?')}")
                                    print(f"    text: {exc.get('text','?')}")
                                    # Get stack trace if available
                                    stack = exc.get("stackTrace", {})
                                    callframes = stack.get("callFrames", [])
                                    for cf in callframes[:3]:
                                        print(f"    at {cf.get('functionName','?')} "
                                              f"({cf.get('url','')}:{cf.get('lineNumber','?')})")
                                    result = ""
                                else:
                                    result = (
                                        result_obj.get("result", {})
                                        .get("value", "")
                                    )
                                print(f"[OK] Response: {len(result)} chars (has exception: {bool(exc)})")
                                # Print full result structure for debugging
                                if page_num == 0:
                                    print(f"    Full result keys: {list(result_obj.keys())}")
                                    sub = result_obj.get("result", {})
                                    print(f"    Sub-result keys: {list(sub.keys()) if isinstance(sub, dict) else type(sub).__name__}")
                                    print(f"    Value type: {type(result).__name__} = {repr(result)[:200]}")
                                break
                            else:
                                # Log unexpected messages
                                rid = data.get("id", "")
                                rmethod = data.get("method", "")
                                if rid or rmethod:
                                    print(f"    (skipping id={rid} method={rmethod})")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            print(f"[!!] WS {msg.type.name}")
                            break
                    except asyncio.TimeoutError:
                        pass

                if not result:
                    print(f"[!!] No response for msg_id={msg_id}")
                    break

                try:
                    api_data = json.loads(result)
                except json.JSONDecodeError:
                    print(f"[!!] Invalid JSON: {result[:300]}")
                    break

                if "_error" in api_data:
                    print(f"[!!] API error: {api_data['_error']}")
                    # Maybe rate limited - wait and retry
                    if "429" in str(api_data.get("_error", "")):
                        print("    Rate limited, waiting 10s...")
                        await asyncio.sleep(10)
                        continue
                    break

                items = api_data.get("itemList") or []
                has_more = api_data.get("hasMore", False)
                new_cursor = api_data.get("cursor", 0)

                all_items.extend(items)
                print(f"    {len(items)} items (total {len(all_items)}, hasMore={has_more})")

                if not has_more:
                    break
                cursor = new_cursor
                await asyncio.sleep(1)

        # ── Results ──
        print(f"\n{'='*60}")
        print(f"Total items: {len(all_items)}")

        for i, item in enumerate(all_items[:15]):
            desc = item.get("desc", "")[:70]
            plays = item.get("stats", {}).get("playCount", 0)
            vid = item.get("id", "")[:20]
            print(f"  [{i+1:2d}] plays={str(plays):>10s}  id={vid}  {desc}")

        if len(all_items) > 15:
            print(f"  ... and {len(all_items)-15} more items")

        print(f"\nSUCCESS: {len(all_items)} videos!")


if __name__ == "__main__":
    asyncio.run(main())
