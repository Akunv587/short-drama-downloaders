"""Fixed: use encodeURIComponent for secUid in fetch URL."""
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


async def evaluate(ws, expr, label, msg_id, await_p=False, timeout=20):
    params = {"expression": expr, "returnByValue": True}
    if await_p:
        params["awaitPromise"] = True

    await ws.send_json({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": params,
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = await asyncio.wait_for(
            ws.receive(),
            timeout=min(3, max(0.5, deadline - time.time())),
        )
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("id") == msg_id:
                err = data.get("error")
                if err:
                    print(f"[!!] {label}: CDP error: {err}")
                    return None

                result = data.get("result", {})
                exc = result.get("exceptionDetails", {})
                if exc:
                    exc_obj = exc.get("exception", {})
                    print(f"[!!] {label}: {exc_obj.get('className','?')}: "
                          f"{exc_obj.get('description','?')}")
                    return None

                return result.get("result", {}).get("value", "")
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            print(f"[!!] {label}: WS closed/error")
            return None

    print(f"[!!] {label}: Timeout")
    return None


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    async with aiohttp.ClientSession() as session:
        ws_url = await get_page_ws_url(session, port)
        if not ws_url:
            print("No TikTok page found!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=90),
            max_msg_size=10 * 1024 * 1024,
        ) as ws:
            # Test with encodeURIComponent
            secuid = "MS4wLjABAAAApK9iGa-YvbSrwWw9QZJvOqcpBpdYKaSLGl9Afrp8WnPdb3nH_yPoLWooxn4gBS5H"

            js = (
                "var u='/api/post/item_list/?"
                "+'aid=1988&count=1&cursor=0&secUid='"
                "+encodeURIComponent('" + secuid + "');"
                "(async ()=>{"
                "  var r=await fetch(u,{credentials:'include'});"
                "  return r.status;"
                "})()"
            )
            print(f"JS snippet: {js[:150]}...")
            r1 = await evaluate(ws, js, "fetch with encodeURI", 1, await_p=True)
            print(f"Result: {r1}")

            # Test: full fetch
            js2 = (
                "var u='/api/post/item_list/?"
                "+'aid=1988&count=1&cursor=0&secUid='"
                "+encodeURIComponent('" + secuid + "');"
                "(async ()=>{"
                "  var r=await fetch(u,{credentials:'include'});"
                "  if(!r.ok) return 'HTTP '+r.status;"
                "  return await r.text();"
                "})()"
            )
            r2 = await evaluate(ws, js2, "full fetch result", 2, await_p=True)
            if r2:
                print(f"Full result ({len(r2)} chars): {r2[:500]}")

            # Test: count=35 
            js3 = (
                "var u='/api/post/item_list/?"
                "+'aid=1988&count=35&cursor=0&secUid='"
                "+encodeURIComponent('" + secuid + "');"
                "(async ()=>{"
                "  var r=await fetch(u,{credentials:'include'});"
                "  if(!r.ok) return JSON.stringify({_error:'HTTP '+r.status});"
                "  return await r.text();"
                "})()"
            )
            r3 = await evaluate(ws, js3, "35 items fetch", 3, await_p=True)
            if r3:
                try:
                    data = json.loads(r3)
                    items = data.get("itemList") or []
                    print(f"Items: {len(items)}, hasMore: {data.get('hasMore')}")
                    for item in items[:10]:
                        desc = item.get("desc", "")[:60]
                        print(f"  {desc}")
                except json.JSONDecodeError:
                    print(f"Not JSON: {r3[:300]}")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
