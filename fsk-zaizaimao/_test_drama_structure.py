"""Check raw drama API response structure."""
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
                        return None
                    res = data.get("result", {})
                    exc = res.get("exceptionDetails", {})
                    if exc:
                        return None
                    return res.get("result", {}).get("value", "")
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                return None
        except asyncio.TimeoutError:
            pass
    return None


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
            ws_url, timeout=aiohttp.ClientTimeout(total=60),
            max_msg_size=50 * 1024 * 1024,
        ) as ws:
            # Find drama API URL
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
                print("No drama_list URL found!")
                return

            # Clean and fetch with count=3 to see structure
            base_url = re.sub(r'&cursor=\d+', '', api_url)
            base_url = re.sub(r'&count=\d+', '', base_url)
            if '?' in base_url:
                base_url += '&count=3'
            else:
                base_url += '?count=3'

            fetch_js = f"""
            (async function(){{
                try {{
                    var r = await fetch({json.dumps(base_url + '&cursor=0')},
                        {{credentials: 'include'}});
                    if (!r.ok) return JSON.stringify({{_err: 'HTTP ' + r.status}});
                    return await r.text();
                }} catch(e) {{
                    return JSON.stringify({{_err: e.message || String(e)}});
                }}
            }})()
            """
            result = await evaluate(ws, fetch_js, 2, await_p=True, timeout=20)

            if not result:
                print("No result!")
                return

            try:
                data = json.loads(result)
            except json.JSONDecodeError:
                print(f"Not JSON: {result[:500]}")
                return

            # Print top-level keys
            print("Top-level keys:", list(data.keys()))
            for k, v in data.items():
                if k == "dramaList":
                    continue
                if isinstance(v, (int, float, str, bool)) or v is None:
                    print(f"  {k}: {v}")
                elif isinstance(v, dict):
                    print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:200]}")
                elif isinstance(v, list):
                    print(f"  {k}: list[{len(v)}]")

            # Print first drama item in detail
            drama_list = data.get("dramaList") or []
            print(f"\ndramaList count: {len(drama_list)}")

            for i, drama in enumerate(drama_list[:2]):
                print(f"\n--- Drama [{i+1}] raw JSON ---")
                print(json.dumps(drama, indent=2, ensure_ascii=False)[:3000])

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
