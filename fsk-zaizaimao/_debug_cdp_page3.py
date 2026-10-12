"""Debug v3: find secUid from alternative sources + try direct API call."""
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

async def evaluate(ws, expr, msg_id, timeout=10):
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
            data = json.loads(msg.data)
            if data.get("id") == msg_id:
                value = data.get("result", {}).get("result", {}).get("value", "")
                return value
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            break
    return None

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
            ws_url, timeout=aiohttp.ClientTimeout(total=60), max_msg_size=32*1024*1024
        ) as ws:
            await ws.send_json({"id": 1, "method": "Page.enable"})

            # Navigate and wait
            await ws.send_json({
                "id": 2, "method": "Page.navigate",
                "params": {"url": URL},
            })

            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=3)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("method") == "Page.loadEventFired":
                            break
                except asyncio.TimeoutError:
                    pass

            await asyncio.sleep(8)

            # 1. Check various global variables
            checks = [
                ("SIGI_STATE", "window.SIGI_STATE ? JSON.stringify(Object.keys(window.SIGI_STATE)).substring(0,300) : 'null'"),
                ("__INITIAL_STATE__", "window.__INITIAL_STATE__ ? JSON.stringify(Object.keys(window.__INITIAL_STATE__)).substring(0,300) : 'null'"),
                ("self.__next_f", "JSON.stringify(Object.keys(self.__next_f || {}))"),
                # Try to find secUid from the page URL or rendered HTML
                ("secUid from links", """
                    (function(){
                        var links=document.querySelectorAll('a[href*="secUid"]');
                        var out=[];
                        links.forEach(function(l){out.push(l.href.substring(0,100));});
                        return JSON.stringify(out.slice(0,5));
                    })()
                """),
                # Try to find any script containing secUid
                ("secUid in scripts", """
                    (function(){
                        var scripts=document.querySelectorAll('script');
                        for(var i=0;i<scripts.length;i++){
                            var s=scripts[i].textContent||'';
                            var idx=s.indexOf('secUid');
                            if(idx>0){
                                return s.substring(Math.max(0,idx-50),idx+100);
                            }
                        }
                        return 'not found in scripts';
                    })()
                """),
                # Try to find user id from DOM
                ("user link", """
                    (function(){
                        var a=document.querySelector('a[href*="/@"]');
                        return a?a.href:'no user link';
                    })()
                """),
            ]

            for label, expr in checks:
                result = await evaluate(ws, expr, 100 + len(checks))
                print(f"{label}: {result}")

            # 2. Try calling API directly with fetch
            # First try with a guess of secUid format
            print("\n--- Trying API call with extracted user info ---")

            # Try to get uniqueId from DOM
            uid = await evaluate(
                ws,
                "(function(){"
                "  var m=document.querySelector('[data-e2e=\"user-title\"]');"
                "  return m?m.textContent.trim():'';"
                "})()",
                50,
            )
            print(f"User title from DOM: '{uid}'")

            # Extract unique_id from the page
            unique_id = await evaluate(
                ws,
                "(function(){"
                "  var h=document.location.href;"
                "  var m=h.match(/@([^/?]+)/);"
                "  return m?m[1]:'';"
                "})()",
                51,
            )
            print(f"Unique ID from URL: '{unique_id}'")

            # Extract user id from the page (digits only)
            user_id = await evaluate(
                ws,
                "(function(){"
                "  var scripts=document.querySelectorAll('script#__UNIVERSAL_DATA_FOR_REHYDRATION__');"
                "  if(scripts.length>0) return JSON.stringify(scripts[0].textContent.substring(0,500));"
                "  // Try other script data sources"
                "  var all=document.querySelectorAll('script[type=\"application/json\"],script[data-json]');"
                "  return 'found '+all.length+' json scripts';"
                "})()",
                52,
            )
            print(f"Script data: {user_id}")

            # 3. Try network interception approach
            # Enable Network and then reload to capture API calls
            print("\n--- Network interception approach ---")
            await ws.send_json({"id": 3, "method": "Network.enable"})

            # Reload the page
            await ws.send_json({
                "id": 4, "method": "Page.navigate",
                "params": {"url": URL},
            })

            api_responses = []
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(
                        ws.receive(),
                        timeout=min(5, deadline - time.time()),
                    )
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        method = data.get("method", "")
                        if method == "Network.responseReceived":
                            resp = data.get("params", {}).get("response", {})
                            url_r = resp.get("url", "")
                            if "item_list" in url_r or "post/item" in url_r:
                                api_responses.append({
                                    "url": url_r[:200],
                                    "status": resp.get("status"),
                                    "requestId": data["params"]["requestId"],
                                })
                                print(f"  API call: {resp.get('status')} {url_r[:120]}")
                        elif data.get("id") == 4:
                            if data.get("result"):
                                pass  # Navigation result
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    print(f"  Error: {e}")
                    break

            if not api_responses:
                print("  No item_list API calls captured")

            # Wait a bit more for delayed API calls
            await asyncio.sleep(5)
            # Check again
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=2)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        method = data.get("method", "")
                        if method == "Network.responseReceived":
                            resp = data.get("params", {}).get("response", {})
                            url_r = resp.get("url", "")
                            if "item_list" in url_r or "post/item" in url_r:
                                request_id = data["params"]["requestId"]
                                api_responses.append({
                                    "url": url_r[:200],
                                    "status": resp.get("status"),
                                    "requestId": request_id,
                                })
                                print(f"  Late API: {resp.get('status')} {url_r[:120]}")
                except asyncio.TimeoutError:
                    break

            # Try to get response body for captured API calls
            for ar in api_responses[:3]:
                try:
                    await ws.send_json({
                        "id": 200 + api_responses.index(ar),
                        "method": "Network.getResponseBody",
                        "params": {"requestId": ar["requestId"]},
                    })
                except Exception as e:
                    print(f"  getResponseBody error: {e}")

            # Wait for response bodies
            deadline = time.time() + 10
            bodies = {}
            while time.time() < deadline and len(bodies) < len(api_responses[:3]):
                try:
                    msg = await asyncio.wait_for(
                        ws.receive(),
                        timeout=min(3, deadline - time.time()),
                    )
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        rid = data.get("id", 0)
                        if rid >= 200 and rid < 300:
                            body = data.get("result", {}).get("body", "")
                            base64 = data.get("result", {}).get("base64Encoded", False)
                            bodies[rid] = body[:500] if not base64 else "(base64)"
                except asyncio.TimeoutError:
                    break

            for rid, body in bodies.items():
                print(f"\n  Body for request {rid}:")
                print(f"  {body[:500]}")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
