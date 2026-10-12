"""Test fetching short drama data using actual TikTok API URLs from performance entries."""
import asyncio
import json
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
            print(f"  Page: {t.get('title','?')[:60]}")
            return t.get("webSocketDebuggerUrl")
    return None


async def evaluate(ws, expr, msg_id, await_p=False, timeout=25):
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
                        return f"CDP_ERR:{err}"
                    res = data.get("result", {})
                    exc = res.get("exceptionDetails", {})
                    if exc:
                        return f"JS_ERR:{exc.get('exception',{}).get('description','?')}"
                    val = res.get("result", {}).get("value", "")
                    return val
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                return None
        except asyncio.TimeoutError:
            pass
    return "TIMEOUT"


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    async with aiohttp.ClientSession() as session:
        ws_url = await get_tiktok_page_ws(session, port)
        if not ws_url:
            print("No TikTok page!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=120),
            max_msg_size=20 * 1024 * 1024,
        ) as ws:
            # Step 1: Get ALL resource URLs with /api/ to find drama endpoints
            print("\n=== Step 1: Discover API URLs ===")
            js_find_apis = """
            (function(){
                var entries = performance.getEntriesByType('resource');
                var apis = [];
                for (var i = 0; i < entries.length; i++) {
                    var u = entries[i].name;
                    if (u.indexOf('/api/') !== -1 && u.indexOf('tiktok.com') !== -1) {
                        // Extract the path
                        var m = u.match(/tiktok\\.com(\\/[^?]+)/);
                        var path = m ? m[1] : u;
                        apis.push({url: u, path: path.split('?')[0]});
                    }
                }
                // Unique by path
                var seen = {};
                var unique = [];
                for (var j = 0; j < apis.length; j++) {
                    if (!seen[apis[j].path]) {
                        seen[apis[j].path] = true;
                        unique.push(apis[j]);
                    }
                }
                return JSON.stringify(unique.slice(0, 20));
            })()
            """
            result = await evaluate(ws, js_find_apis, 1)
            print(f"  API endpoints:\n{result[:2000] if result else 'None'}")

            if not result or result.startswith("CDP_ERR") or result.startswith("JS_ERR") or result == "TIMEOUT":
                print(f"  Failed: {result}")
                return

            try:
                apis = json.loads(result)
            except json.JSONDecodeError:
                print(f"  Parse error: {result[:300]}")
                return

            # Find the most promising API URLs
            drama_apis = []
            for api in apis:
                url = api.get("url", "")
                path = api.get("path", "")
                # Look for story, playlist, drama-related endpoints
                if any(kw in path.lower() for kw in ["story", "playlist", "drama", "series", "collection", "post"]):
                    drama_apis.append(url)

            print(f"\n  Drama-relevant APIs ({len(drama_apis)}):")
            for u in drama_apis[:8]:
                # Truncate for display
                display = u
                if len(display) > 150:
                    display = display[:150] + "..."
                print(f"    {display}")

            # Step 2: Try each drama API
            for idx, api_url in enumerate(drama_apis[:5]):
                print(f"\n=== Test {idx+1}: {api_url[:120]}... ===")

                fetch_js = f"""
                (async function(){{
                    try {{
                        var url = {json.dumps(api_url)};
                        // Clean up cursor and count
                        url = url.replace(/&cursor=\\d+/g, '');
                        url = url.replace(/&count=\\d+/g, '&count=5');
                        if (url.indexOf('count=') === -1) {{
                            url += (url.indexOf('?') !== -1 ? '&' : '?') + 'count=5';
                        }}
                        url += '&cursor=0';
                        var r = await fetch(url, {{credentials: 'include'}});
                        if (!r.ok) return JSON.stringify({{_err: 'HTTP ' + r.status}});
                        var t = await r.text();
                        // Return first 5000 chars
                        return t.substring(0, 5000);
                    }} catch(e) {{
                        return JSON.stringify({{_err: e.message || String(e)}});
                    }}
                }})()
                """
                result = await evaluate(ws, fetch_js, 10 + idx, await_p=True, timeout=20)

                if not result:
                    print(f"  NULL result")
                    continue
                if result.startswith("CDP_ERR") or result.startswith("JS_ERR") or result == "TIMEOUT":
                    print(f"  {result}")
                    continue

                try:
                    data = json.loads(result)
                    if "_err" in data:
                        print(f"  Error: {data['_err']}")
                        continue

                    # Success! Parse and explore
                    print(f"  SUCCESS! len={len(result)}")
                    keys = list(data.keys())
                    print(f"  Keys: {keys}")

                    # Find list fields
                    for k in keys:
                        v = data[k]
                        if isinstance(v, list) and len(v) > 0:
                            print(f"\n  [{k}]: {len(v)} items")
                            first = v[0]
                            if isinstance(first, dict):
                                fk = list(first.keys())
                                print(f"    Item keys: {fk}")
                                # Try to find title
                                for tk in ["title", "name", "dramaName", "desc", "dramaInfo"]:
                                    if tk in first:
                                        tv = first[tk]
                                        if isinstance(tv, dict):
                                            print(f"    {tk}: {json.dumps(tv)[:200]}")
                                        else:
                                            print(f"    {tk}: {str(tv)[:120]}")
                                # Try to find episode count
                                for ek in ["episodeCount", "totalEpisodes", "episode_count", "total_episodes", "count"]:
                                    if ek in first:
                                        print(f"    {ek}: {first[ek]}")
                                # Try to find play count
                                for pk in ["playCount", "viewCount", "views", "play_count", "view_count"]:
                                    if pk in first:
                                        print(f"    {pk}: {first[pk]}")
                                    elif "stats" in first and pk in first["stats"]:
                                        print(f"    stats.{pk}: {first['stats'][pk]}")

                            # Show first 3 titles
                            for item in v[:3]:
                                title = (item.get("title") or item.get("name") or
                                         item.get("dramaName") or item.get("desc") or "")
                                if isinstance(title, dict):
                                    title = title.get("title") or str(title)
                                title = str(title)[:80]
                                if title:
                                    print(f"    -> {title}")
                        elif isinstance(v, dict):
                            print(f"  [{k}]: dict, keys={list(v.keys())[:10]}")
                        elif not isinstance(v, (int, float, bool, type(None))):
                            print(f"  [{k}]: {str(v)[:100]}")

                except json.JSONDecodeError:
                    print(f"  Not JSON: {result[:300]}")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
