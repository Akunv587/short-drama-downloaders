"""Test raw fetch behavior on TikTok page."""
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
            print(f"  Found page: {t.get('title','')} - {t.get('url','')[:80]}")
            return t.get("webSocketDebuggerUrl")
    return None


def js_string(s):
    return json.dumps(s)


async def evaluate(ws, expr, label, msg_id, await_p=False):
    params = {"expression": expr, "returnByValue": True}
    if await_p:
        params["awaitPromise"] = True

    await ws.send_json({"id": msg_id, "method": "Runtime.evaluate", "params": params})

    deadline = time.time() + 20
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
                    print(f"  [!] {label}: CDP err: {err}")
                    return None
                res = data.get("result", {})
                exc = res.get("exceptionDetails", {})
                if exc:
                    exc_obj = exc.get("exception", {})
                    print(f"  [!] {label}: {exc_obj.get('description','?')}")
                    return None
                inner = res.get("result", {})
                val = inner.get("value", "")
                print(f"  [OK] {label}: type={inner.get('type')}, "
                      f"value={repr(val)[:200]}")
                return val
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            print(f"  [!] {label}: WS closed/error")
            return None
    print(f"  [!] {label}: Timeout")
    return None


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    secuid = "MS4wLjABAAAApK9iGa-YvbSrwWw9QZJvOqcpBpdYKaSLGl9Afrp8WnPdb3nH_yPoLWooxn4gBS5H"

    async with aiohttp.ClientSession() as session:
        ws_url = await get_page_ws_url(session, port)
        if not ws_url:
            print("No TikTok page found!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=120),
            max_msg_size=10 * 1024 * 1024,
        ) as ws:
            # Test 1: Simple fetch status
            await evaluate(ws, """
                (async function(){
                    try {
                        var r = await fetch('/');
                        return 'status: ' + r.status;
                    } catch(e) {
                        return 'error: ' + (e.message || String(e));
                    }
                })()
            """, "fetch /", 1, await_p=True)

            # Test 2: Full URL fetch
            full_url = (
                "var u = '/api/post/item_list/' +"
                "  '?aid=1988&count=1&cursor=0&secUid=' +"
                "  encodeURIComponent(" + js_string(secuid) + ");"
            )
            await evaluate(ws, (
                full_url +
                "(async function(){"
                "  try {"
                "    var r = await fetch(u, {credentials: 'include'});"
                "    return 'status: ' + r.status + ' type: ' + r.headers.get('content-type');"
                "  } catch(e) {"
                "    return 'error: ' + (e.message || String(e));"
                "  }"
                "})()"
            ), "fetch API status", 2, await_p=True)

            # Test 3: fetch with headers
            await evaluate(ws, (
                full_url +
                "(async function(){"
                "  try {"
                "    var r = await fetch(u, {"
                "      credentials: 'include',"
                "      headers: {'Accept': 'application/json'}"
                "    });"
                "    return 'status: ' + r.status + ' len: ' + "
                "      (await r.clone().text()).length;"
                "  } catch(e) {"
                "    return 'error: ' + (e.message || String(e));"
                "  }"
                "})()"
            ), "fetch with headers", 3, await_p=True)

            # Test 4: fetch full text
            await evaluate(ws, (
                full_url +
                "(async function(){"
                "  try {"
                "    var r = await fetch(u, {credentials: 'include'});"
                "    var t = await r.text();"
                "    return 'len:' + t.length + ' first:[' + t.substring(0,200) + ']';"
                "  } catch(e) {"
                "    return 'error: ' + (e.message || String(e));"
                "  }"
                "})()"
            ), "fetch full text", 4, await_p=True)

            # Test 5: Check if fetch is monkey-patched
            await evaluate(ws, """
                (function(){
                    return 'fetch is: ' + (typeof fetch) + 
                           ' native: ' + (fetch.toString().includes('[native code]'));
                })()
            """, "check fetch", 5, await_p=False)

            # Test 6: XMLHttpRequest instead
            await evaluate(ws, (
                full_url +
                "(async function(){"
                "  return await new Promise(function(resolve, reject) {"
                "    var xhr = new XMLHttpRequest();"
                "    xhr.open('GET', u, true);"
                "    xhr.withCredentials = true;"
                "    xhr.onload = function() {"
                "      resolve('XHR status:' + xhr.status + ' len:' + xhr.responseText.length);"
                "    };"
                "    xhr.onerror = function() {"
                "      resolve('XHR error');"
                "    };"
                "    xhr.send();"
                "  });"
                "})()"
            ), "XHR test", 6, await_p=True)

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
