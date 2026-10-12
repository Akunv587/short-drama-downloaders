"""Debug: find drama tab element on TikTok page."""
import asyncio
import json
import time
import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        # Find CDP port
        for p in range(9222, 9226):
            try:
                async with session.get(f"http://127.0.0.1:{p}/json/version", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    info = await resp.json()
                    if info.get("Browser"):
                        port = p
                        break
            except Exception:
                continue
        else:
            print("No CDP port!")
            return

        # Get TikTok page WS
        async with session.get(f"http://127.0.0.1:{port}/json", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            targets = await resp.json()
        
        tiktok = next((t for t in targets if t.get("type") == "page" and "tiktok.com" in t.get("url", "")), None)
        if not tiktok:
            print("No TikTok page!")
            return
        print(f"Page: {tiktok.get('title','?')[:60]}")
        print(f"URL: {tiktok.get('url','')[:120]}")
        
        async with session.ws_connect(tiktok["webSocketDebuggerUrl"], timeout=aiohttp.ClientTimeout(total=30), max_msg_size=10*1024*1024) as ws:
            msg_id = 1
            
            async def ev(expr, await_p=False):
                nonlocal msg_id
                msg_id += 1
                mid = msg_id
                params = {"expression": expr, "returnByValue": True}
                if await_p:
                    params["awaitPromise"] = True
                await ws.send_json({"id": mid, "method": "Runtime.evaluate", "params": params})
                
                deadline = time.time() + 15
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=min(3, max(0.5, deadline - time.time())))
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("id") == mid:
                                err = data.get("error")
                                if err: return f"ERR:{err}"
                                res = data.get("result", {})
                                exc = res.get("exceptionDetails")
                                if exc: return f"JS_ERR:{exc.get('exception',{}).get('description','?')}"
                                return res.get("result", {}).get("value", "")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            return None
                    except asyncio.TimeoutError:
                        pass
                return "TIMEOUT"
            
            # 1. Check current URL
            r = await ev("(function(){ return window.location.href; })()")
            print(f"\n1. Current URL: {str(r)[:120]}")
            
            # 2. Search for elements with "短剧" text - various approaches
            # Approach A: Search for text content containing "短剧"
            r = await ev("""
            (function(){
                var results = [];
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    var t = (el.textContent || '').trim();
                    if (t === '\u77ed\u5267' || t === 'Short Drama' || t === 'Shorts') {
                        results.push({
                            tag: el.tagName,
                            id: el.id,
                            className: el.className,
                            role: el.getAttribute('role'),
                            href: el.getAttribute('href'),
                            text: t.substring(0, 50),
                            visible: el.offsetParent !== null
                        });
                    }
                }
                return JSON.stringify(results.slice(0, 10));
            })()
            """)
            print(f"2. Elements with 'short drama' text: {str(r)[:500]}")
            
            # 3. Search for elements with role=tab
            r = await ev("""
            (function(){
                var results = [];
                var all = document.querySelectorAll('[role="tab"]');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    results.push({
                        tag: el.tagName,
                        text: (el.textContent || '').trim().substring(0, 30),
                        ariaLabel: el.getAttribute('aria-label'),
                        ariaSelected: el.getAttribute('aria-selected')
                    });
                }
                return JSON.stringify(results);
            })()
            """)
            print(f"3. Elements with role=tab: {str(r)[:500]}")
            
            # 4. Get all links/buttons near the profile header area
            r = await ev("""
            (function(){
                var results = [];
                // Look for navigation elements
                var navAreas = document.querySelectorAll('nav, [role="tablist"], .css-1g9w6w2-DivNavContainer');
                for (var i = 0; i < navAreas.length; i++) {
                    var nav = navAreas[i];
                    var links = nav.querySelectorAll('a, button, [role="tab"]');
                    var items = [];
                    for (var j = 0; j < links.length; j++) {
                        items.push({
                            tag: links[j].tagName,
                            text: (links[j].textContent || '').trim().substring(0, 30),
                            href: (links[j].getAttribute('href') || '').substring(0, 60)
                        });
                    }
                    results.push({navClass: nav.className, items: items});
                }
                return JSON.stringify(results.slice(0, 5));
            })()
            """)
            print(f"4. Nav/tab areas: {str(r)[:1000]}")
            
            # 5. Directly search for elements with Chinese text matching
            r = await ev("""
            (function(){
                var results = [];
                var all = document.querySelectorAll('a, button, span, p, div');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    var childText = '';
                    for (var j = 0; j < el.childNodes.length; j++) {
                        if (el.childNodes[j].nodeType === 3) {  // TEXT_NODE
                            childText += el.childNodes[j].textContent;
                        }
                    }
                    childText = childText.trim();
                    if (childText.length >= 2 && childText.length <= 10) {
                        results.push({
                            tag: el.tagName,
                            className: (el.className || '').toString().substring(0, 50),
                            text: childText,
                            visible: el.offsetParent !== null,
                            clickable: el.tagName === 'A' || el.tagName === 'BUTTON' || el.onclick !== null
                        });
                    }
                    if (results.length >= 30) break;
                }
                return JSON.stringify(results);
            })()
            """)
            print(f"5. Short text elements (2-10 chars): {str(r)[:2000]}")
            
            # 6. Performance entries check
            r = await ev("""
            (function(){
                var entries = performance.getEntriesByType('resource');
                var apis = [];
                for (var i = 0; i < entries.length; i++) {
                    var u = entries[i].name;
                    if (u.indexOf('/api/') !== -1 && u.indexOf('tiktok.com') !== -1) {
                        var m = u.match(/tiktok\\.com(\\/[^?]+)/);
                        apis.push(m ? m[1] : u.substring(0, 100));
                    }
                }
                var unique = [];
                var seen = {};
                for (var j = 0; j < apis.length; j++) {
                    if (!seen[apis[j]]) {
                        seen[apis[j]] = true;
                        unique.push(apis[j]);
                    }
                }
                return JSON.stringify(unique.slice(0, 15));
            })()
            """)
            print(f"6. API endpoints from performance: {str(r)[:1500]}")

asyncio.run(main())
