"""End-to-end test: CDP → extract secUid → call API → parse videos."""
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


async def cdp_evaluate(ws, expr, msg_id, timeout=15, await_promise=False):
    """Send Runtime.evaluate and wait for matching result."""
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


def parse_video_as_drama(item):
    """Same logic as TikTokHomepageExtractor._parse_video_as_drama."""
    desc = item.get("desc", "")
    if not desc:
        return None
    video_id = item.get("id", "")
    stats = item.get("stats", {})
    play_count = stats.get("playCount", 0)
    author = item.get("author", {})
    author_name = author.get("uniqueId", "")
    return {
        "name": desc[:100],
        "play_count": str(play_count),
        "episode_count": 0,
        "first_episode_url": (
            f"https://www.tiktok.com/@{author_name}/video/{video_id}"
            if author_name and video_id else ""
        ),
        "tags": item.get("challenges", []) or [],
        "publish_date": str(item.get("createTime", "")),
    }


async def main():
    print(f"E2E Test: {URL}")
    print("=" * 60)

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
            ws_url, timeout=aiohttp.ClientTimeout(total=90),
            max_msg_size=32 * 1024 * 1024,
        ) as ws:
            # Enable Page domain
            await ws.send_json({"id": 1, "method": "Page.enable"})

            # Navigate
            print("[..] Navigating...")
            await ws.send_json({
                "id": 2, "method": "Page.navigate",
                "params": {"url": URL},
            })

            # Wait for load event
            loaded = False
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=3)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("method") == "Page.loadEventFired":
                            print("[OK] Page loaded")
                            loaded = True
                            break
                except asyncio.TimeoutError:
                    pass

            if not loaded:
                print("[!] Load event timeout, continuing...")

            # Wait for JS init
            print("[..] Waiting 3s...")
            await asyncio.sleep(3)

            # Step 1: Extract secUid (same logic as updated _cdp_extract_secuid)
            print("[..] Extracting secUid...")
            secuid = await cdp_evaluate(ws, """
                (function(){
                    var m=document.documentElement.outerHTML.match(
                        /"secUid"\\s*:\\s*"([^"]+)"/
                    );
                    if(m) return m[1];
                    var d=window.__UNIVERSAL_DATA_FOR_REHYDRATION__;
                    if(d){
                        try{
                            return d.__DEFAULT_SCOPE__
                              ['webapp.user-detail'].userInfo.user.secUid||'';
                        }catch(e){}
                    }
                    return '';
                })()
            """, 10)

            if not secuid:
                print("[!!] secUid not found!")
                return

            print(f"[OK] secUid: {secuid[:40]}...{secuid[-10:]}")

            # Step 2: Call TikTok API
            all_items = []
            cursor = 0

            for page_num in range(3):
                print(f"[..] Fetching page {page_num + 1} (cursor={cursor})...")

                result = await cdp_evaluate(ws, f"""
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
                """, 20 + page_num, await_promise=True, timeout=20)

                if not result:
                    print(f"[!!] Page {page_num + 1} returned nothing")
                    if page_num == 0:
                        return
                    break

                try:
                    api_data = json.loads(result)
                except json.JSONDecodeError:
                    print(f"[!!] Invalid JSON: {result[:200]}")
                    break

                if "_error" in api_data:
                    print(f"[!!] API error: {api_data['_error']}")
                    break

                items = api_data.get("itemList") or []
                has_more = api_data.get("hasMore", False)
                new_cursor = api_data.get("cursor", 0)

                all_items.extend(items)
                print(f"[OK] Page {page_num + 1}: {len(items)} items "
                      f"(total {len(all_items)}, hasMore={has_more})")

                if not has_more:
                    break
                cursor = new_cursor
                await asyncio.sleep(0.5)

            # Step 3: Parse
            print(f"\n--- Results: {len(all_items)} total items ---")
            dramas = []
            for item in all_items:
                drama = parse_video_as_drama(item)
                if drama:
                    dramas.append(drama)

            for i, d in enumerate(dramas[:20]):
                print(f"  [{i+1:2d}] {d['name'][:70]}")
                print(f"       plays={d['play_count']}  url={d['first_episode_url'][:60]}")

            if len(dramas) > 20:
                print(f"  ... and {len(dramas) - 20} more")

            print(f"\n{'=' * 60}")
            print(f"SUCCESS: {len(dramas)} dramas extracted!")


if __name__ == "__main__":
    asyncio.run(main())
