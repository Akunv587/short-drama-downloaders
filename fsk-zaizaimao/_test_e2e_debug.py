"""Debug E2E: log all CDP messages to find the issue."""
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


async def main():
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
            await ws.send_json({"id": 1, "method": "Page.enable"})
            
            print("[..] Navigating...")
            await ws.send_json({
                "id": 2, "method": "Page.navigate",
                "params": {"url": URL},
            })

            # Drain ALL messages until load event, logging as we go
            msg_count = 0
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=3)
                    msg_count += 1
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                        except json.JSONDecodeError:
                            print(f"  [{msg_count}] NON-JSON: {str(msg.data)[:100]}")
                            continue

                        mid = data.get("id", "")
                        method = data.get("method", "")
                        if method == "Page.loadEventFired":
                            print(f"  [{msg_count}] >>> LOAD EVENT <<<")
                            break
                        elif mid:
                            print(f"  [{msg_count}] id={mid} result={'error' if data.get('error') else 'ok'}")
                        elif method:
                            print(f"  [{msg_count}] event: {method}")
                        else:
                            print(f"  [{msg_count}] unknown: {str(data)[:100]}")
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        print(f"  [{msg_count}] WS CLOSED")
                        break
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        print(f"  [{msg_count}] WS ERROR")
                        break
                except asyncio.TimeoutError:
                    print("  (timeout waiting for messages)")
                    break

            print(f"Total messages drained: {msg_count}")
            print("[..] Waiting 3s...")
            await asyncio.sleep(3)

            # Check what the page looks like now
            title = await cdp_evaluate_raw(ws, "document.title", 98)
            url_current = await cdp_evaluate_raw(ws, "window.location.href", 99)
            html_len = await cdp_evaluate_raw(ws, "document.documentElement.outerHTML.length", 100)
            has_secuid = await cdp_evaluate_raw(ws, """
                document.documentElement.outerHTML.indexOf('secUid') >= 0
            """, 101)
            
            print(f"  Title: '{title}'")
            print(f"  URL: {url_current}")
            print(f"  HTML length: {html_len}")
            print(f"  Has secUid: {has_secuid}")

            # Now try the actual extraction
            secuid = await cdp_evaluate_raw(ws, """
                (function(){
                    var m=document.documentElement.outerHTML.match(
                        /"secUid"\\s*:\\s*"([^"]+)"/
                    );
                    if(m) return 'FOUND:'+m[1].substring(0,40);
                    return 'NOT_FOUND';
                })()
            """, 102)
            print(f"  secUid result: {secuid}")

            # Try alternative: just get a snippet around secUid
            snippet = await cdp_evaluate_raw(ws, """
                (function(){
                    var h=document.documentElement.outerHTML;
                    var i=h.indexOf('secUid');
                    if(i<0) return 'secUid NOT in HTML at all';
                    return h.substring(Math.max(0,i-30), i+100);
                })()
            """, 103)
            print(f"  Snippet: {snippet}")


async def cdp_evaluate_raw(ws, expr, msg_id, timeout=10):
    """Send evaluate and return raw value (no filtering)."""
    await ws.send_json({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True},
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        msg = await asyncio.wait_for(
            ws.receive(), timeout=min(3, max(0.1, remaining))
        )
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                print(f"    NON-JSON during evaluate {msg_id}: {str(msg.data)[:100]}")
                continue
            if data.get("id") == msg_id:
                # Full result for debugging
                err = data.get("error")
                if err:
                    return f"CDP_ERROR: {err}"
                result = data.get("result", {})
                sub_result = result.get("result", {})
                value = sub_result.get("value", "")
                exception = result.get("exceptionDetails", {})
                if exception:
                    return f"EXCEPTION: {exception.get('text', str(exception)[:200])}"
                return str(value)
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            return f"WS_{msg.type.name}"
    return "TIMEOUT"


if __name__ == "__main__":
    asyncio.run(main())
