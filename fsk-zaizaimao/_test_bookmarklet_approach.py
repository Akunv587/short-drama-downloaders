"""Test bookmarklet approach via CDP: find API URLs from performance entries, then fetch."""
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
            print(f"  TikTok page: {t.get('title','?')[:60]}")
            print(f"  URL: {t.get('url','')[:100]}")
            return t.get("webSocketDebuggerUrl")
    return None


async def evaluate(ws, expr, msg_id, await_p=False, timeout=20):
    params = {"expression": expr, "returnByValue": True}
    if await_p:
        params["awaitPromise"] = True

    await ws.send_json({"id": msg_id, "method": "Runtime.evaluate", "params": params})

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(
                ws.receive(),
                timeout=min(3, max(0.5, deadline - time.time())),
            )
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("id") == msg_id:
                    err = data.get("error")
                    if err:
                        print(f"  CDP err: {err}")
                        return None
                    res = data.get("result", {})
                    exc = res.get("exceptionDetails", {})
                    if exc:
                        print(f"  JS err: {exc.get('exception',{}).get('description','?')}")
                        return None
                    val = res.get("result", {}).get("value", "")
                    return val
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                return None
        except asyncio.TimeoutError:
            pass
    print("  Timeout!")
    return None


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    async with aiohttp.ClientSession() as session:
        ws_url = await get_tiktok_page_ws(session, port)
        if not ws_url:
            print("No TikTok page found!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=60),
            max_msg_size=10 * 1024 * 1024,
        ) as ws:
            # Step 1: Get performance entries to find API URLs
            print("\n=== Step 1: Find API URLs from performance entries ===")
            js_get_entries = """
            (function(){
                var entries = performance.getEntriesByType('resource');
                var apiPatterns = [/drama/i, /series/i, /playlist/i, /collection/i, /secUid/i];
                var results = [];
                for (var i = 0; i < entries.length; i++) {
                    var url = entries[i].name;
                    for (var j = 0; j < apiPatterns.length; j++) {
                        if (apiPatterns[j].test(url) && url.indexOf('tiktok.com') !== -1) {
                            results.push(url);
                            break;
                        }
                    }
                }
                return JSON.stringify({count: results.length, urls: results.slice(0, 10)});
            })()
            """
            result = await evaluate(ws, js_get_entries, 1)
            print(f"  Performance entries result: {result[:500] if result else 'None'}")

            if not result:
                print("  Failed to get performance entries!")
                return

            try:
                entries_data = json.loads(result)
                api_urls = entries_data.get("urls", [])
                print(f"  Found {len(api_urls)} API URLs")
                for u in api_urls[:5]:
                    print(f"    {u[:120]}")
            except json.JSONDecodeError:
                print(f"  Invalid JSON: {result[:200]}")
                return

            if not api_urls:
                print("  No API URLs found! Trying broader search...")
                js_all_resources = """
                (function(){
                    var entries = performance.getEntriesByType('resource');
                    var results = [];
                    for (var i = 0; i < entries.length; i++) {
                        var url = entries[i].name;
                        if (url.indexOf('/api/') !== -1 || url.indexOf('tiktok.com') !== -1) {
                            results.push(url);
                        }
                    }
                    return JSON.stringify({count: results.length, urls: results.slice(0, 20)});
                })()
                """
                result = await evaluate(ws, js_all_resources, 2)
                print(f"  All resources with /api/: {result[:500] if result else 'None'}")
                if result:
                    try:
                        entries_data = json.loads(result)
                        api_urls = entries_data.get("urls", [])
                        print(f"  Found {len(api_urls)} URLs with /api/")
                        for u in api_urls[:10]:
                            print(f"    {u[:120]}")
                    except json.JSONDecodeError:
                        pass

                if not api_urls:
                    print("  Still no URLs found!")
                    return

            # Step 2: Try fetching the first API URL
            print("\n=== Step 2: Try fetching first API URL ===")
            first_url = api_urls[0]
            print(f"  URL: {first_url[:150]}")

            # Construct fetch JS like the bookmarklet does
            fetch_js = f"""
            (async function(){{
                try {{
                    var apiUrl = {json.dumps(first_url)};
                    // Replace cursor and count params
                    apiUrl = apiUrl.replace(/&cursor=\\d+/g, '');
                    if (apiUrl.indexOf('&count=') !== -1) {{
                        apiUrl = apiUrl.replace(/&count=\\d+/g, '&count=5');
                    }} else if (apiUrl.indexOf('?count=') !== -1) {{
                        apiUrl = apiUrl.replace(/\\?count=\\d+/g, '?count=5');
                    }} else {{
                        apiUrl += (apiUrl.indexOf('?') !== -1 ? '&' : '?') + 'count=5';
                    }}
                    var resp = await fetch(apiUrl + '&cursor=0', {{credentials: 'include'}});
                    if (!resp.ok) return JSON.stringify({{_error: 'HTTP ' + resp.status}});
                    var text = await resp.text();
                    return text.substring(0, 3000);
                }} catch(e) {{
                    return JSON.stringify({{_error: e.message || String(e)}});
                }}
            }})()
            """
            result = await evaluate(ws, fetch_js, 3, await_p=True, timeout=30)
            print(f"  Fetch result: {result[:500] if result else 'None'}")

            if result:
                try:
                    data = json.loads(result)
                    if "_error" in data:
                        print(f"  ERROR: {data['_error']}")
                    else:
                        print(f"  SUCCESS! Response length: {len(result)}")
                        # Try to parse
                        try:
                            parsed = json.loads(result)
                            keys = list(parsed.keys())
                            print(f"  Top-level keys: {keys}")
                            for k in keys:
                                v = parsed[k]
                                if isinstance(v, list):
                                    print(f"    {k}: list[{len(v)}]")
                                    if v and isinstance(v[0], dict):
                                        print(f"      First item keys: {list(v[0].keys())}")
                                        first = v[0]
                                        title = first.get('title') or first.get('name') or first.get('dramaName') or ''
                                        print(f"      Title: {str(title)[:80]}")
                                elif isinstance(v, dict):
                                    print(f"    {k}: dict keys={list(v.keys())[:10]}")
                                else:
                                    print(f"    {k}: {str(v)[:80]}")
                        except json.JSONDecodeError:
                            print(f"  Response is not JSON: {result[:200]}")
                except json.JSONDecodeError:
                    print(f"  Parse error: {result[:200]}")
            else:
                print("  Fetch returned None!")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
