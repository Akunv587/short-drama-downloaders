"""Extract short drama list from TikTok creator page using CDP + drama_list API."""
import asyncio
import json
import re
import time
import aiohttp


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


async def get_tiktok_page_ws(session, port):
    async with session.get(
        f"http://127.0.0.1:{port}/json",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        targets = await resp.json()
    for t in targets:
        if t.get("type") == "page" and "tiktok.com" in t.get("url", ""):
            print(f"Page: {t.get('title','?')[:60]}")
            print(f"URL: {t.get('url','')[:100]}")
            return t.get("webSocketDebuggerUrl")
    return None


async def evaluate(ws, expr, msg_id, await_p=False, timeout=25):
    """Send Runtime.evaluate and get result value."""
    params = {"expression": expr, "returnByValue": True}
    if await_p:
        params["awaitPromise"] = True
    await ws.send_json({"id": msg_id, "method": "Runtime.evaluate", "params": params})

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(
                ws.receive(), timeout=min(3, max(0.5, deadline - time.time())),
            )
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("id") == msg_id:
                    err = data.get("error")
                    if err:
                        print(f"  CDP err [{msg_id}]: {err}")
                        return None
                    res = data.get("result", {})
                    exc = res.get("exceptionDetails", {})
                    if exc:
                        print(f"  JS err [{msg_id}]: {exc.get('exception',{}).get('description','?')}")
                        return None
                    return res.get("result", {}).get("value", "")
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                return None
        except asyncio.TimeoutError:
            pass
    print(f"  Timeout [{msg_id}]")
    return None


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port! Chrome debug port not running.")
        return

    async with aiohttp.ClientSession() as session:
        ws_url = await get_tiktok_page_ws(session, port)
        if not ws_url:
            print("No TikTok page!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=180),
            max_msg_size=50 * 1024 * 1024,
        ) as ws:
            # Step 1: Find drama_list API URL from performance entries
            print("\n[1] Finding drama_list API URL...")
            js_find = """
            (function(){
                var entries = performance.getEntriesByType('resource');
                for (var i = 0; i < entries.length; i++) {
                    var u = entries[i].name;
                    if (u.indexOf('/api/drama/user/drama_list/') !== -1) {
                        return u;
                    }
                }
                return '';
            })()
            """
            api_url = await evaluate(ws, js_find, 1)
            if not api_url:
                print("  No drama_list API URL found in performance entries!")
                print("  (Make sure you're on the 'Short Drama' tab of the TikTok creator page)")
                return

            print(f"  Found: {api_url[:150]}...")

            # Step 2: Extract creator name from URL
            js_creator = """
            (function(){
                var m = window.location.href.match(/tiktok\\.com\\/@([^\\/?]+)/);
                return m ? m[1] : '';
            })()
            """
            creator = await evaluate(ws, js_creator, 2)
            print(f"  Creator: @{creator}")

            # Step 3: Clean up the API URL - reset cursor, increase count
            # Remove cursor and count params, then add our own
            base_url = re.sub(r'&cursor=\d+', '', api_url)
            base_url = re.sub(r'&count=\d+', '', base_url)
            # Add count param
            if '?' in base_url:
                base_url += '&count=35'
            else:
                base_url += '?count=35'
            print(f"  Base URL: {base_url[:150]}...")

            # Step 4: Paginate through all drama pages
            all_dramas = []
            cursor = 0
            max_pages = 10

            for page in range(max_pages):
                page_url = f"{base_url}&cursor={cursor}"
                print(f"\n[2.{page+1}] Fetching page cursor={cursor}...")

                fetch_js = f"""
                (async function(){{
                    try {{
                        var r = await fetch({json.dumps(page_url)}, {{credentials: 'include'}});
                        if (!r.ok) return JSON.stringify({{_err: 'HTTP ' + r.status}});
                        return await r.text();
                    }} catch(e) {{
                        return JSON.stringify({{_err: e.message || String(e)}});
                    }}
                }})()
                """
                result = await evaluate(ws, fetch_js, 100 + page, await_p=True, timeout=30)

                if not result:
                    print(f"  No result")
                    break

                try:
                    data = json.loads(result)
                except json.JSONDecodeError:
                    print(f"  Invalid JSON: {result[:300]}")
                    break

                if "_err" in data:
                    err = data["_err"]
                    print(f"  Error: {err}")
                    if "429" in err:
                        print("  Rate limited, waiting 10s...")
                        await asyncio.sleep(10)
                        continue
                    break

                drama_list = data.get("dramaList") or []
                count = len(drama_list)
                print(f"  Got {count} dramas")

                for d in drama_list:
                    title = (d.get("title") or d.get("dramaName") or
                             (d.get("dramaInfo") or {}).get("title") or "?")
                    eps = (d.get("totalEpisode") or d.get("episodeCount") or
                           d.get("totalEpisodes") or
                           (d.get("dramaInfo") or {}).get("totalEpisode") or 0)
                    plays = (d.get("playCount") or d.get("viewCount") or
                             (d.get("dramaInfo") or {}).get("playCount") or
                             (d.get("stats") or {}).get("playCount") or 0)
                    drama_id = d.get("id") or d.get("dramaId") or ""
                    all_dramas.append({
                        "title": str(title),
                        "episodes": int(eps) if eps else 0,
                        "plays": int(plays) if plays else 0,
                        "id": str(drama_id),
                    })
                    print(f"    [{len(all_dramas):2d}] {str(title)[:50]} | {eps} eps | plays={plays}")

                if count == 0:
                    print("  Empty page, done")
                    break

                # Check hasMore
                has_more = data.get("hasMore", False)
                new_cursor = data.get("cursor", 0)
                if isinstance(new_cursor, str):
                    try:
                        new_cursor = int(new_cursor)
                    except ValueError:
                        new_cursor = 0

                if not has_more:
                    print("  hasMore=false, done")
                    break

                cursor = new_cursor
                await asyncio.sleep(1.5)  # Rate limit between pages

            # Step 5: Summary
            print(f"\n{'='*60}")
            print(f"TOTAL: {len(all_dramas)} short dramas for @{creator}")
            print(f"{'='*60}")
            for i, d in enumerate(all_dramas):
                print(f"  [{i+1:2d}] {d['title'][:60]} | {d['episodes']} eps | plays={d['plays']}")

            # CSV output
            csv = "\uFEFF剧名,播放量,剧集数\n"
            for d in all_dramas:
                csv += f'"{d["title"].replace(chr(34), chr(34)+chr(34))}",{d["plays"]},{d["episodes"]}\n'
            print(f"\nCSV ({len(all_dramas)} rows):")
            print(csv[:2000])

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
