"""Single WebSocket: navigate → capture secUid → call API (all in one connection)."""
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


def js_string(s: str) -> str:
    return json.dumps(s)


def make_fetch_js(secuid: str, cursor: int) -> str:
    """Make JavaScript to call TikTok API via fetch()."""
    return (
        "(async function(){"
        "  var secUid = " + js_string(secuid) + ";"
        "  var u = '/api/post/item_list/' +"
        "    '?aid=1988&count=35&cursor=" + str(cursor) + "&secUid=' +"
        "    encodeURIComponent(secUid);"
        "  try {"
        "    var r = await fetch(u, {credentials: 'include'});"
        "    if (!r.ok) return JSON.stringify({_error: 'HTTP ' + r.status});"
        "    return await r.text();"
        "  } catch(e) {"
        "    return JSON.stringify({_error: e.message || String(e)});"
        "  }"
        "})()"
    )


async def drain_until(ws, predicate, timeout=30):
    """Drain messages until predicate returns non-None or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(
                ws.receive(),
                timeout=min(3, max(0.5, deadline - time.time())),
            )
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                result = predicate(data)
                if result is not None:
                    return result
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break
        except asyncio.TimeoutError:
            pass
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
            ws_url, timeout=aiohttp.ClientTimeout(total=120),
            max_msg_size=50 * 1024 * 1024,
        ) as ws:
            # ── Step 1: Navigate ──
            await ws.send_json({"id": 1, "method": "Page.enable"})
            await ws.send_json({"id": 2, "method": "Network.enable"})

            print("[..] Navigating...")
            await ws.send_json({
                "id": 3, "method": "Page.navigate",
                "params": {"url": URL},
            })

            # ── Step 2: Capture secUid and wait for page load ──
            secuid = None
            load_fired = False

            def pred(data):
                nonlocal secuid, load_fired
                method = data.get("method", "")
                if method == "Page.loadEventFired":
                    load_fired = True
                    print("  [LOAD] Page.loadEventFired")
                elif method == "Network.responseReceived":
                    resp = data.get("params", {}).get("response", {})
                    resp_url = resp.get("url", "")
                    if not secuid and "/api/post/item_list/" in resp_url:
                        parsed = urllib.parse.urlparse(resp_url)
                        qs = urllib.parse.parse_qs(parsed.query)
                        s = qs.get("secUid", [None])[0]
                        if s:
                            secuid = s
                            print(f"  [SECUID] Captured: {s[:40]}...")
                # Return secuid only after page loaded
                if secuid and load_fired:
                    return secuid
                return None

            result = await drain_until(ws, pred, timeout=45)
            if not result:
                print(f"[!] secUid={secuid}, load={load_fired}")
                if not secuid:
                    return
            secuid = result or secuid

            print(f"[OK] secUid captured, page loaded")

            # ── Step 3: Disable Network to stop event flood ──
            await ws.send_json({"id": 99, "method": "Network.disable"})
            # Drain disable response
            await asyncio.sleep(0.5)
            # Drain any pending messages
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=0.5)
                except asyncio.TimeoutError:
                    break

            # ── Step 4: Wait for page JS to fully initialize ──
            print("[..] Waiting 5s for JS init...")
            await asyncio.sleep(5)

            # ── Step 5: Call API ──
            print("[..] Calling TikTok API...")
            all_items = []
            cursor = 0

            for page_num in range(5):
                msg_id = 200 + page_num
                js = make_fetch_js(secuid, cursor)

                await ws.send_json({
                    "id": msg_id,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": js,
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                })

                print(f"  Page {page_num+1}: sent id={msg_id}, waiting...")

                # Wait for specific msg_id
                result_value = None
                deadline = time.time() + 30
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
                                    print(f"    CDP ERROR: {json.dumps(err)[:500]}")
                                    result_value = None
                                else:
                                    res = data.get("result", {})
                                    exc = res.get("exceptionDetails", {})
                                    if exc:
                                        exc_obj = exc.get("exception", {})
                                        print(f"    JS ERROR: {exc_obj.get('description','?')}")
                                        result_value = None
                                    else:
                                        inner = res.get("result", {})
                                        result_value = inner.get("value", "")
                                        res_type = inner.get("type", "?")
                                        res_desc = inner.get("description", "")
                                        print(f"    Response: type={res_type}, "
                                              f"len={len(str(result_value))}, "
                                              f"desc={str(res_desc)[:100]}")
                                        # Dump full keys for debugging
                                        if page_num == 0:
                                            print(f"    Full result keys: {list(res.keys())}")
                                            print(f"    Inner result keys: {list(inner.keys()) if isinstance(inner, dict) else type(inner).__name__}")
                                break
                            # else skip (could be lingering events)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            print(f"    WS {msg.type.name}")
                            break
                    except asyncio.TimeoutError:
                        pass

                if result_value is None:
                    print(f"    No valid response")
                    break

                try:
                    api_data = json.loads(result_value)
                except json.JSONDecodeError:
                    print(f"    INVALID JSON: {result_value[:200]}")
                    break

                if "_error" in api_data:
                    print(f"    API error: {api_data['_error']}")
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
            print(f"TOTAL: {len(all_items)} videos")

            for i, item in enumerate(all_items[:15]):
                desc = item.get("desc", "")[:70]
                plays = item.get("stats", {}).get("playCount", 0)
                vid = item.get("id", "")[:20]
                print(f"  [{i+1:2d}] plays={str(plays):>10s}  id={vid}  {desc}")

            if len(all_items) > 15:
                print(f"  ... and {len(all_items)-15} more")

            print(f"\nDONE: {len(all_items)} videos extracted!")


if __name__ == "__main__":
    asyncio.run(main())
