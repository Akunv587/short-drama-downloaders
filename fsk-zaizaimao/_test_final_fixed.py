"""Final fixed: proper JS string construction with json.dumps for secUid."""
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


async def get_page_ws_url(session, port):
    async with session.get(
        f"http://127.0.0.1:{port}/json",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        targets = await resp.json()
    for t in targets:
        if t.get("type") == "page" and "tiktok.com" in t.get("url", ""):
            return t.get("webSocketDebuggerUrl")
    for t in targets:
        if t.get("type") == "page":
            return t.get("webSocketDebuggerUrl")
    return None


def js_string(s: str) -> str:
    """Safely embed a Python string as a JavaScript string literal."""
    return json.dumps(s)


async def evaluate_async(ws, expr, msg_id, timeout=20):
    """Send Runtime.evaluate with awaitPromise and wait for result."""
    await ws.send_json({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expr,
            "awaitPromise": True,
            "returnByValue": True,
        },
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        msg = await asyncio.wait_for(
            ws.receive(), timeout=min(3, max(0.5, remaining))
        )
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("id") == msg_id:
                err = data.get("error")
                if err:
                    print(f"  [!!] CDP error: {err}")
                    return None
                result = data.get("result", {})
                exc = result.get("exceptionDetails", {})
                if exc:
                    exc_obj = exc.get("exception", {})
                    print(f"  [!!] {exc_obj.get('className','?')}: "
                          f"{exc_obj.get('description','?')}")
                    return None
                return result.get("result", {}).get("value", "")
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            return None
    print("  [!!] Timeout")
    return None


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    async with aiohttp.ClientSession() as session:
        # ── Phase 1: Navigate + capture secUid ──
        print("=== Phase 1: Capture secUid ===")
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

            await ws.send_json({
                "id": 3, "method": "Page.navigate",
                "params": {"url": URL},
            })

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
                                    print(f"[OK] secUid captured")

                        if method == "Page.loadEventFired":
                            pass  # just drain

                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break

                    if secuid:
                        break
                except asyncio.TimeoutError:
                    if secuid:
                        break

        if not secuid:
            print("[!!] No secUid!")
            return

        # ── Phase 2: API call with proper JS ──
        print(f"\n=== Phase 2: Call API (secUid={secuid[:30]}...) ===")
        await asyncio.sleep(3)

        ws_url2 = await get_page_ws_url(session, port)
        if not ws_url2:
            print("No page target!")
            return

        async with session.ws_connect(
            ws_url2, timeout=aiohttp.ClientTimeout(total=90),
            max_msg_size=50 * 1024 * 1024,
        ) as ws:
            all_items = []
            cursor = 0

            for page_num in range(5):
                # Construct JavaScript safely
                js = (
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

                print(f"  Page {page_num+1} (cursor={cursor})...")
                result = await evaluate_async(ws, js, 100 + page_num, timeout=25)

                if not result:
                    print(f"    No result")
                    break

                try:
                    api_data = json.loads(result)
                except json.JSONDecodeError:
                    print(f"    Invalid JSON: {result[:200]}")
                    break

                if "_error" in api_data:
                    print(f"    Error: {api_data['_error']}")
                    if "429" in str(api_data.get("_error", "")):
                        print("    Rate limited, waiting...")
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
            print(f"  [{i+1:2d}] plays={str(plays):>10s}  {desc}")
        if len(all_items) > 15:
            print(f"  ... and {len(all_items)-15} more")
        print(f"\nDONE!")


if __name__ == "__main__":
    asyncio.run(main())
