"""Minimal test: just evaluate simple expressions on the TikTok page."""
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


async def evaluate_and_print(ws, expr, label, msg_id, await_p=False):
    params = {"expression": expr, "returnByValue": True}
    if await_p:
        params["awaitPromise"] = True

    await ws.send_json({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": params,
    })
    print(f"[..] Sent {label} (id={msg_id}, await={await_p})")

    deadline = time.time() + 15
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
                    print(f"[!!] CDP error: {json.dumps(err, indent=2)[:500]}")
                    return

                result = data.get("result", {})
                exc = result.get("exceptionDetails", {})
                if exc:
                    print(f"[!!] Exception: type={exc.get('type')}, "
                          f"class={exc.get('className')}, "
                          f"desc={exc.get('description')}, "
                          f"text={exc.get('text')}")
                    print(f"    Full exceptionDetails: {json.dumps({k:v for k,v in exc.items() if k!='stackTrace'}, indent=2)[:500]}")
                    return

                value = result.get("result", {}).get("value", "")
                vtype = result.get("result", {}).get("type", "")
                print(f"[OK] {label}: type={vtype}, value={repr(value)[:200]}")
                return

        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            print(f"[!!] WS closed/error")
            return

    print(f"[!!] Timeout for {label}")


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    async with aiohttp.ClientSession() as session:
        ws_url = await get_page_ws_url(session, port)
        if not ws_url:
            print("No TikTok page found! Navigate to one first.")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=60),
            max_msg_size=10 * 1024 * 1024,
        ) as ws:
            # Test 1: Simple expression
            await evaluate_and_print(ws, "1+1", "1+1", 1)

            # Test 2: Access window
            await evaluate_and_print(ws, "window.location.href", "window.location", 2)

            # Test 3: Simple async
            await evaluate_and_print(ws, "(async ()=>{return 42;})()", "async 42", 3, await_p=True)

            # Test 4: Simple fetch
            await evaluate_and_print(ws,
                "(async ()=>{"
                "  var r=await fetch('/api/post/item_list/?"
                "    +'aid=1988&count=1&cursor=0&secUid=MS4wLjABAAAApK9iGa-YvbSrwWw9QZJvOqcpBpdYKaSLGl9Afrp8WnPdb3nH_yPoLWooxn4gBS5H');"
                "  return r.status;"
                "})()",
                "fetch status", 4, await_p=True)

            # Test 5: Full fetch with response text
            await evaluate_and_print(ws,
                "(async ()=>{"
                "  var r=await fetch('/api/post/item_list/?"
                "    +'aid=1988&count=1&cursor=0&secUid=MS4wLjABAAAApK9iGa-YvbSrwWw9QZJvOqcpBpdYKaSLGl9Afrp8WnPdb3nH_yPoLWooxn4gBS5H');"
                "  return await r.text();"
                "})()",
                "fetch full", 5, await_p=True)


if __name__ == "__main__":
    asyncio.run(main())
