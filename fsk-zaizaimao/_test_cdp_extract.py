"""
Test the new CDP extraction pipeline directly.

Usage:
    python _test_cdp_extract.py <tiktok_profile_url>
Example:
    python _test_cdp_extract.py https://www.tiktok.com/@polestoryflix
"""
import asyncio
import json
import sys
import aiohttp
import time

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
                        print(f"[OK] Chrome CDP on port {p} ({info['Browser']})")
                        return p
            except Exception:
                continue
    return None


async def get_page_ws(session, port, url):
    async with session.get(
        f"http://127.0.0.1:{port}/json",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        targets = await resp.json()

    page_target = next((t for t in targets if t.get("type") == "page"), None)
    if page_target:
        ws_url = page_target.get("webSocketDebuggerUrl")
        if ws_url:
            print(f"[OK] Reusing existing page: {page_target.get('title', '')[:50]}")
            return ws_url

    async with session.put(
        f"http://127.0.0.1:{port}/json/new?{url}",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        new_target = await resp.json()
        ws_url = new_target.get("webSocketDebuggerUrl")
        if ws_url:
            print(f"[OK] Created new page tab")
        return ws_url


async def wait_for_load(ws, timeout=20):
    """Wait for Page.loadEventFired."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        try:
            msg = await asyncio.wait_for(
                ws.receive(), timeout=min(3, max(0.1, remaining))
            )
        except asyncio.TimeoutError:
            continue

        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if data.get("method") == "Page.loadEventFired":
                print("[OK] Page loaded!")
                return True
            if data.get("id") == 3 and data.get("error"):
                print(f"[!!] Navigation error: {data['error']}")
                return False
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            return False

    print("[OK] Load event timeout – continuing anyway")
    return True


async def extract_secuid(ws):
    """Extract secUid from page JavaScript state."""
    await ws.send_json({
        "id": 10,
        "method": "Runtime.evaluate",
        "params": {
            "expression": (
                "(function(){"
                "  var d=window.__UNIVERSAL_DATA_FOR_REHYDRATION__;"
                "  if(!d) return '';"
                "  try{"
                "    return d.__DEFAULT_SCOPE__"
                "      ['webapp.user-detail'].userInfo.user.secUid||'';"
                "  }catch(e){return ''}"
                "})()"
            ),
            "returnByValue": True,
        },
    })

    deadline = time.time() + 10
    while time.time() < deadline:
        remaining = deadline - time.time()
        msg = await asyncio.wait_for(
            ws.receive(), timeout=min(5, max(0.1, remaining))
        )
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("id") == 10:
                value = (
                    data.get("result", {})
                    .get("result", {})
                    .get("value", "")
                )
                return value if value else None
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            break
    return None


async def fetch_item_list(ws, secuid, cursor=0):
    """Call TikTok API via Runtime.evaluate (in-page fetch)."""
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

    msg_id = 20 + cursor
    await ws.send_json({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": js_expr,
            "awaitPromise": True,
            "returnByValue": True,
        },
    })

    deadline = time.time() + 15
    while time.time() < deadline:
        remaining = deadline - time.time()
        msg = await asyncio.wait_for(
            ws.receive(), timeout=min(5, max(0.1, remaining))
        )
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("id") == msg_id:
                raw_value = (
                    data.get("result", {})
                    .get("result", {})
                    .get("value", "{}")
                )
                try:
                    api_data = json.loads(raw_value)
                except json.JSONDecodeError:
                    print(f"[!!] API response not JSON: {raw_value[:300]}")
                    return None, False, 0

                if "_error" in api_data:
                    print(f"[!!] API error: {api_data['_error']}")
                    return None, False, 0

                items = api_data.get("itemList") or []
                has_more = api_data.get("hasMore", False)
                new_cursor = api_data.get("cursor", 0)
                return items, bool(has_more), new_cursor
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            break
    return None, False, 0


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.tiktok.com/@polestoryflix"
    print(f"Target: {url}")
    print("=" * 60)

    port = await find_cdp_port()
    if not port:
        print("[!!] No CDP port found!")
        return

    async with aiohttp.ClientSession() as session:
        ws_url = await get_page_ws(session, port, url)
        if not ws_url:
            print("[!!] Can't get page target!")
            return

        async with session.ws_connect(
            ws_url,
            timeout=aiohttp.ClientTimeout(total=45),
            max_msg_size=32 * 1024 * 1024,
        ) as ws:
            # Enable domains
            await ws.send_json({"id": 1, "method": "Page.enable"})
            await ws.send_json({"id": 2, "method": "Network.enable"})

            # Navigate
            print("[..] Navigating...")
            await ws.send_json({
                "id": 3,
                "method": "Page.navigate",
                "params": {"url": url},
            })

            # Wait for page load
            await wait_for_load(ws)

            # Extra wait for JS
            print("[..] Waiting 5s for JS init...")
            await asyncio.sleep(5)

            # Extract secUid
            secuid = await extract_secuid(ws)
            if not secuid:
                print("[!!] Could not extract secUid (page might have WAF/not logged in)")
                return

            print(f"[OK] secUid: {secuid[:40]}...")

            # Fetch videos
            print("[..] Fetching video list...")
            items, has_more, cursor = await fetch_item_list(ws, secuid)
            if items is None:
                print("[!!] API fetch failed!")
                return

            print(f"[OK] Got {len(items)} items (has_more={has_more}, cursor={cursor})")

            for i, item in enumerate(items[:10]):
                desc = item.get("desc", "")[:80]
                plays = item.get("stats", {}).get("playCount", 0)
                print(f"  [{i+1}] {desc}")
                print(f"       plays={plays}, id={item.get('id', '')[:20]}")

            if len(items) > 10:
                print(f"  ... and {len(items) - 10} more")

    print("=" * 60)
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
