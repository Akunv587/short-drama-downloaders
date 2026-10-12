"""Debug v2: check page HTML content and try longer waits."""
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
            await ws.send_json({
                "id": 2, "method": "Page.navigate",
                "params": {"url": URL},
            })

            # Wait for load event
            loaded = False
            deadline = time.time() + 20
            while time.time() < deadline and not loaded:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=3)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("method") == "Page.loadEventFired":
                            print("Load event received")
                            loaded = True
                except asyncio.TimeoutError:
                    pass

            print(f"Loaded: {loaded}")

            # Wait extra
            print("Waiting 10s for JS init...")
            await asyncio.sleep(10)

            # Check URL
            url_val = await evaluate(ws, "window.location.href", 10)
            title_val = await evaluate(ws, "document.title", 11)
            print(f"URL: {url_val}")
            print(f"Title: '{title_val}'")

            # Check HTML length
            html_len = await evaluate(ws, "document.documentElement.outerHTML.length", 12)
            print(f"HTML length: {html_len}")

            # Check for captcha / verification
            captcha = await evaluate(
                ws,
                "(function(){"
                "  var h=document.documentElement.outerHTML.toLowerCase();"
                "  return JSON.stringify({"
                "    captcha: h.includes('captcha'),"
                "    verify: h.includes('verify'),"
                "    sigi: h.includes('sigi_state'),"
                "    universal: h.includes('__universal_data'),"
                "    itemlist: h.includes('itemlist'),"
                "  });"
                "})()",
                13,
            )
            print(f"Page indicators: {captcha}")

            # Check cookies
            cookies_js = await evaluate(
                ws,
                "(function(){"
                "  var cs=document.cookie.split(';');"
                "  var out=[];"
                "  for(var i=0;i<cs.length;i++){"
                "    var c=cs[i].trim();"
                "    var eq=c.indexOf('=');"
                "    var name=eq>0?c.substring(0,eq):c;"
                "    out.push(name);"
                "  }"
                "  return JSON.stringify(out);"
                "})()",
                14,
            )
            print(f"Cookie names: {cookies_js}")

            # Get first 1000 chars of body
            body_start = await evaluate(
                ws,
                "document.body?document.body.innerText.substring(0,500):'no body'",
                15,
            )
            print(f"\nBody text start: {body_start}")


if __name__ == "__main__":
    asyncio.run(main())
