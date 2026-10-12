"""Final drama extraction using CDP + drama_list API."""
import asyncio
import json
import re
import sys
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
            print(f"Page: {t.get('title','?')[:60]}")
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
                        desc = exc.get("exception", {}).get("description", "?")
                        print(f"  JS err: {desc}")
                        return None
                    return res.get("result", {}).get("value", "")
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                return None
        except asyncio.TimeoutError:
            pass
    print(f"  Timeout")
    return None


async def main():
    port = await find_cdp_port()
    if not port:
        print("[ERROR] Chrome debug port not found. Start Chrome with --remote-debugging-port=9222")
        sys.exit(1)

    async with aiohttp.ClientSession() as session:
        ws_url = await get_tiktok_page_ws(session, port)
        if not ws_url:
            print("[ERROR] No TikTok page open in Chrome!")
            sys.exit(1)

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=180),
            max_msg_size=50 * 1024 * 1024,
        ) as ws:
            # 1. Find the drama_list API URL from performance entries
            print("\n[1] Discovering drama API URL...")
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
                # Try to navigate to the drama tab first if not found
                print("  Drama API URL not found in performance entries.")
                print("  Checking if we need to navigate to drama tab...")
                js_check_tab = """
                (function(){
                    var url = window.location.href;
                    return url;
                })()
                """
                current_url = await evaluate(ws, js_check_tab, 2)
                print(f"  Current URL: {current_url}")

                # Try clicking the drama tab
                js_click_drama = """
                (async function(){
                    // Look for drama tab
                    var all = document.querySelectorAll('span, p, div');
                    for (var i = 0; i < all.length; i++) {
                        var el = all[i];
                        if (el.textContent.trim() === '\u77ed\u5267' && el.children.length === 0) {
                            var p = el;
                            while (p && p.tagName !== 'A' && p.tagName !== 'BUTTON' && p.getAttribute('role') !== 'tab') {
                                p = p.parentElement;
                            }
                            if (p) {
                                p.click();
                                return 'clicked';
                            }
                        }
                    }
                    return 'not found';
                })()
                """
                click_result = await evaluate(ws, js_click_drama, 3, await_p=True, timeout=10)
                print(f"  Click result: {click_result}")
                if click_result == "clicked":
                    print("  Waiting for drama tab to load...")
                    await asyncio.sleep(4)
                    # Try again
                    api_url = await evaluate(ws, js_find, 4)
                    if not api_url:
                        print("  Still no drama API URL found!")
                        sys.exit(1)

            print(f"  API URL found!")

            # 2. Extract creator name
            js_creator = """
            (function(){
                var m = window.location.href.match(/tiktok\\.com\\/@([^\\/?]+)/);
                return m ? m[1] : '';
            })()
            """
            creator = await evaluate(ws, js_creator, 5)
            print(f"  Creator: @{creator}")

            # 3. Clean base URL
            base_url = re.sub(r'&cursor=\d+', '', api_url)
            base_url = re.sub(r'&count=\d+', '', base_url)
            sep = '&' if '?' in base_url else '?'
            base_url += f'{sep}count=35'

            # 4. Paginate
            all_dramas = []
            cursor = 0
            max_pages = 15

            print(f"\n[2] Fetching drama list...")
            for page in range(max_pages):
                page_url = f"{base_url}&cursor={cursor}"
                print(f"  Page {page+1} (cursor={cursor})...", end=" ")

                fetch_js = f"""
                (async function(){{
                    try {{
                        var r = await fetch({json.dumps(page_url)},
                            {{credentials: 'include'}});
                        if (!r.ok) return JSON.stringify({{_err: 'HTTP ' + r.status}});
                        return await r.text();
                    }} catch(e) {{
                        return JSON.stringify({{_err: e.message || String(e)}});
                    }}
                }})()
                """
                result = await evaluate(ws, fetch_js, 100 + page, await_p=True, timeout=30)

                if not result:
                    print("no response")
                    break

                try:
                    data = json.loads(result)
                except json.JSONDecodeError:
                    print(f"invalid JSON: {result[:100]}")
                    break

                if "_err" in data:
                    err = data["_err"]
                    print(f"error: {err}")
                    if "429" in err:
                        print("    rate limited, waiting 15s...")
                        await asyncio.sleep(15)
                        continue
                    break

                drama_list = data.get("dramaList") or []
                count = len(drama_list)
                print(f"{count} dramas")

                for d in drama_list:
                    all_dramas.append({
                        "title": d.get("dramaName", ""),
                        "episodes": d.get("numVideos", 0),
                        "plays": d.get("numWatched", "0"),
                        "id": d.get("dramaID", ""),
                        "description": d.get("description", ""),
                        "themes": [t.get("tagVal", "") for t in (d.get("themes") or [])],
                    })

                if count == 0:
                    break

                has_more = data.get("hasMore", False)
                new_cursor = data.get("cursor", 0)
                if isinstance(new_cursor, str):
                    try:
                        new_cursor = int(new_cursor)
                    except ValueError:
                        new_cursor = cursor + count

                if not has_more:
                    print("  (hasMore=false, done)")
                    break

                cursor = new_cursor
                await asyncio.sleep(1.5)

            # 5. Results
            print(f"\n{'='*60}")
            print(f"TOTAL: {len(all_dramas)} short dramas for @{creator}")
            print(f"{'='*60}")

            for i, d in enumerate(all_dramas):
                # Format play count
                plays = d["plays"]
                try:
                    plays_int = int(plays)
                    if plays_int >= 1_000_000:
                        plays_str = f"{plays_int/1_000_000:.1f}M"
                    elif plays_int >= 1_000:
                        plays_str = f"{plays_int/1_000:.1f}K"
                    else:
                        plays_str = str(plays_int)
                except (ValueError, TypeError):
                    plays_str = str(plays)

                eps = d["episodes"]
                title = d["title"][:55]
                print(f"  [{i+1:2d}] {title:<55s} | {eps:>3d} eps | views={plays_str:>8s}")

            # Generate CSV
            csv_lines = ["剧名,播放量,剧集数,标签"]
            for d in all_dramas:
                title = d["title"].replace('"', '""')
                themes = "; ".join(d["themes"]).replace('"', '""')
                csv_lines.append(f'"{title}",{d["plays"]},{d["episodes"]},"{themes}"')
            csv_content = "\n".join(csv_lines)

            # Write to file to avoid encoding issues
            output_file = f"dramas_{creator}.csv"
            with open(output_file, "w", encoding="utf-8-sig") as f:
                f.write(csv_content)
            print(f"\nCSV saved to: {output_file}")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
