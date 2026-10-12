"""
TikTok homepage drama extractor.

Extracts drama info from TikTok user homepages using multiple strategies:
1. Mobile UA page parsing (fast)
2. CDP Chrome browser extraction (reliable – calls API from page context)
3. yt-dlp extraction (fallback)
"""
import json
import re
import asyncio
import os
import httpx
from core.utils.logger import get_logger
from core.utils.proxy import detect_proxy

logger = get_logger()

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)

_RE_UNIVERSAL_DATA_SCRIPT = re.compile(
    r'<script[^>]*id\s*=\s*"__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>\s*'
    r'(\{[\s\S]*?\})\s*</script>'
)
_RE_UNIVERSAL_DATA_JS = re.compile(
    r'__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{[\s\S]*?\})\s*;'
)
_RE_SIGI_STATE = re.compile(
    r'<script[^>]*id\s*=\s*["\x27]SIGI_STATE["\x27][^>]*>\s*(\{[\s\S]*?\})\s*</script>'
)

_WAF_SIGNATURES = ["slardar", "_wafchallengeid", "Please wait..."]


class TikTokHomepageExtractor:
    """TikTok homepage extractor - extract all drama info from user page."""

    async def extract(self, url: str) -> list[dict]:
        username = self._extract_username(url)
        logger.info(f"TikTok homepage extraction: @{username}")

        result = await self._extract_via_cdp(url, username)
        if result is not None:
            return result

        result = await self._extract_via_page(url, username)
        if result is not None:
            return result

        result = await self._extract_via_ytdlp(url, username)
        if result is not None:
            return result

        return []

    # ── Strategy 1: CDP (Chrome DevTools Protocol) ──────────────────

    async def _extract_via_cdp(self, url: str, username: str) -> list[dict] | None:
        """Extract via Chrome CDP: navigate in real browser, call API from page context.

        The browser natively handles cookies, msToken, and X-Bogus signatures,
        so calling fetch() from within the TikTok page returns authenticated data.
        """
        try:
            import aiohttp
        except ImportError:
            logger.warning("aiohttp not installed, CDP unavailable")
            return None

        port = await self._find_cdp_port()
        if not port:
            logger.info(
                "No Chrome debug port found – "
                "start Chrome with: chrome.exe --remote-debugging-port=9222"
            )
            return None

        try:
            async with aiohttp.ClientSession() as session:
                ws_url = await self._cdp_get_page_ws_url(session, port, url)
                if not ws_url:
                    return None

                async with session.ws_connect(
                    ws_url,
                    timeout=aiohttp.ClientTimeout(total=45),
                    max_msg_size=32 * 1024 * 1024,
                ) as ws:
                    return await self._cdp_extract_dramas(ws, url, username)
        except Exception as e:
            logger.warning(f"CDP extraction failed: {e}")
            return None

    async def _find_cdp_port(self) -> int | None:
        """Probe Chrome remote debugging ports (9222-9225)."""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            for p in range(9222, 9226):
                try:
                    async with session.get(
                        f"http://127.0.0.1:{p}/json/version",
                        timeout=aiohttp.ClientTimeout(total=2),
                    ) as resp:
                        info = await resp.json()
                        if info.get("Browser"):
                            logger.info(f"CDP Chrome found on port {p}")
                            return p
                except Exception:
                    continue
        return None

    async def _cdp_get_page_ws_url(
        self, session, port: int, url: str
    ) -> str | None:
        """Get WebSocket URL for a TikTok page target. Creates a new tab if needed."""
        import aiohttp
        try:
            async with session.get(
                f"http://127.0.0.1:{port}/json",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                targets = await resp.json()

            # Prefer an existing TikTok page
            tiktok_target = next(
                (t for t in targets
                 if t.get("type") == "page" and "tiktok.com" in t.get("url", "")),
                None,
            )
            if tiktok_target:
                ws_url = tiktok_target.get("webSocketDebuggerUrl")
                if ws_url:
                    logger.info("CDP: reusing existing TikTok page")
                    return ws_url

            # Fallback: any page target
            page_target = next(
                (t for t in targets if t.get("type") == "page"),
                None,
            )
            if page_target:
                ws_url = page_target.get("webSocketDebuggerUrl")
                if ws_url:
                    return ws_url

            # Create a new tab
            async with session.put(
                f"http://127.0.0.1:{port}/json/new?{url}",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                new_target = await resp.json()
                return new_target.get("webSocketDebuggerUrl")

        except Exception as e:
            logger.warning(f"Failed to get CDP page target: {e}")
            return None

    async def _cdp_extract_dramas(
        self, ws, url: str, username: str
    ) -> list[dict] | None:
        """Extract DRAMA items via the TikTok drama API using page context.

        Uses performance.getEntriesByType('resource') to discover the
        /api/drama/user/drama_list/ endpoint, then calls it via Runtime.evaluate.
        The browser handles all auth (cookies + msToken + X-Bogus) natively.
        """
        import aiohttp

        # Step 1: Enable domains
        await ws.send_json({"id": 1, "method": "Page.enable"})
        await ws.send_json({"id": 2, "method": "Network.enable"})

        # Step 2: Check current URL - only navigate if not already on TikTok
        current_url = await self._cdp_get_current_url(ws)
        if not current_url or "tiktok.com" not in current_url:
            logger.info("CDP: navigating to %s", url)
            await ws.send_json({
                "id": 3,
                "method": "Page.navigate",
                "params": {"url": url},
            })
            loaded = await self._cdp_wait_for_load(ws)
            if not loaded:
                logger.warning("CDP: page load timeout")
            await asyncio.sleep(5)
        else:
            logger.info("CDP: already on TikTok page, skipping navigation")
            # Drain any pending messages
            await asyncio.sleep(1)

        # Step 3: Discover drama API URL from performance entries
        api_url = await self._cdp_find_drama_api(ws)
        if not api_url:
            # Try clicking the "短剧" tab
            logger.info("CDP: drama API not found, trying to click drama tab...")
            clicked = await self._cdp_click_drama_tab(ws)
            if clicked:
                await asyncio.sleep(4)
                api_url = await self._cdp_find_drama_api(ws)

        if not api_url:
            logger.warning(
                "CDP: drama_list API URL not found. "
                "Make sure the TikTok page is on the 'Short Drama' tab."
            )
            return None

        logger.info("CDP: found drama API URL")

        # Step 4: Clean up API URL and paginate
        import re as _re
        base_url = _re.sub(r'&cursor=\d+', '', api_url)
        base_url = _re.sub(r'&count=\d+', '', base_url)
        sep = '&' if '?' in base_url else '?'
        base_url += f'{sep}count=35'

        all_dramas = []
        cursor = 0
        max_pages = 10

        for page_num in range(max_pages):
            page_url = f"{base_url}&cursor={cursor}"
            dramas, has_more, new_cursor = await self._cdp_fetch_drama_list(
                ws, page_url
            )
            if dramas is None:
                if page_num == 0:
                    logger.warning("CDP: drama API fetch failed")
                    return None
                break

            all_dramas.extend(dramas)
            logger.info(
                f"CDP page {page_num + 1}: {len(dramas)} dramas "
                f"(total {len(all_dramas)})"
            )

            if not has_more:
                break
            cursor = new_cursor
            await asyncio.sleep(1.5)

        logger.info(f"CDP extraction complete: {len(all_dramas)} dramas")
        return all_dramas if all_dramas else None

    async def _cdp_get_current_url(self, ws) -> str | None:
        """Get the current page URL via Runtime.evaluate."""
        return await self._cdp_evaluate(
            ws, "(function(){ return window.location.href; })()", 5
        )

    async def _cdp_find_drama_api(self, ws) -> str | None:
        """Find the drama_list API URL from page performance entries."""
        js_expr = (
            "(function(){"
            "  var entries = performance.getEntriesByType('resource');"
            "  for (var i = 0; i < entries.length; i++) {"
            "    var u = entries[i].name;"
            "    if (u.indexOf('/api/drama/user/drama_list/') !== -1) {"
            "      return u;"
            "    }"
            "  }"
            "  return '';"
            "})()"
        )
        result = await self._cdp_evaluate(ws, js_expr, 10)
        return result if result else None

    async def _cdp_click_drama_tab(self, ws) -> bool:
        """Click the '短剧' tab on the TikTok profile page."""
        js_expr = (
            "(async function(){"
            "  var all = document.querySelectorAll('span, p, div');"
            "  for (var i = 0; i < all.length; i++) {"
            "    var el = all[i];"
            "    if (el.textContent.trim() === '\\u77ed\\u5267'"
            "        && el.children.length === 0) {"
            "      var p = el;"
            "      while (p && p.tagName !== 'A' && p.tagName !== 'BUTTON'"
            "             && p.getAttribute('role') !== 'tab') {"
            "        p = p.parentElement;"
            "      }"
            "      if (p) { p.click(); return 'clicked'; }"
            "    }"
            "  }"
            "  return 'not_found';"
            "})()"
        )
        result = await self._cdp_evaluate(ws, js_expr, 11, await_promise=True)
        return result == "clicked"

    async def _cdp_evaluate(
        self, ws, expression: str, msg_id: int,
        await_promise: bool = False, timeout: float = 20.0,
    ) -> str | None:
        """Send Runtime.evaluate and return the result value."""
        params = {"expression": expression, "returnByValue": True}
        if await_promise:
            params["awaitPromise"] = True

        await ws.send_json({
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": params,
        })

        import aiohttp
        deadline = asyncio.get_event_loop().time() + timeout
        try:
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                try:
                    msg = await asyncio.wait_for(
                        ws.receive(),
                        timeout=min(3, max(0.1, remaining)),
                    )
                except asyncio.TimeoutError:
                    continue

                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    if data.get("id") == msg_id:
                        err = data.get("error")
                        if err:
                            logger.warning(f"CDP eval error [{msg_id}]: {err}")
                            return None
                        res = data.get("result", {})
                        exc = res.get("exceptionDetails")
                        if exc:
                            desc = exc.get("exception", {}).get("description", "?")
                            logger.warning(f"CDP JS error [{msg_id}]: {desc}")
                            return None
                        return res.get("result", {}).get("value", "")
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except asyncio.TimeoutError:
            logger.warning(f"CDP evaluate timeout [{msg_id}]")
        return None

    _cdp_msg_counter: int = 0

    def _cdp_next_msg_id(self) -> int:
        """Generate a unique message ID for CDP requests."""
        self._cdp_msg_counter += 1
        return self._cdp_msg_counter + 100

    async def _cdp_fetch_drama_list(
        self, ws, page_url: str
    ) -> tuple[list | None, bool, int]:
        """Fetch one page of drama_list API from within the TikTok page.

        Returns:
            (dramas: list|None, has_more: bool, cursor: int)
            dramas is a list of drama dicts in the frontend-expected format.
        """
        js_expr = (
            "(async function(){"
            "  try {"
            "    var r = await fetch("
            + json.dumps(page_url)
            + ", {credentials: 'include'});"
            "    if (!r.ok) return JSON.stringify({_err: 'HTTP ' + r.status});"
            "    return await r.text();"
            "  } catch(e) {"
            "    return JSON.stringify({_err: e.message || String(e)});"
            "  }"
            "})()"
        )

        import aiohttp
        msg_id = self._cdp_next_msg_id()

        await ws.send_json({
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": js_expr,
                "awaitPromise": True,
                "returnByValue": True,
            },
        })

        deadline = asyncio.get_event_loop().time() + 25
        try:
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                try:
                    msg = await asyncio.wait_for(
                        ws.receive(),
                        timeout=min(5, max(0.1, remaining)),
                    )
                except asyncio.TimeoutError:
                    continue

                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    if data.get("id") == msg_id:
                        raw_value = (
                            data.get("result", {})
                            .get("result", {})
                            .get("value", "{}")
                        )
                        try:
                            api_data = json.loads(raw_value)
                        except json.JSONDecodeError:
                            logger.warning(
                                f"CDP drama API response not JSON: {raw_value[:200]}"
                            )
                            return None, False, 0

                        if "_err" in api_data:
                            err = api_data["_err"]
                            logger.warning(f"CDP drama API error: {err}")
                            if "429" in err:
                                logger.info("Rate limited, waiting...")
                                return [], True, 0  # signal retry
                            return None, False, 0

                        # Parse dramaList items into frontend format
                        drama_list = api_data.get("dramaList") or []
                        dramas = []
                        for d in drama_list:
                            dramas.append({
                                "name": d.get("dramaName", ""),
                                "play_count": d.get("numWatched", "0"),
                                "episode_count": d.get("numVideos", 0),
                                "first_episode_url": "",
                                "tags": [
                                    t.get("tagVal", "")
                                    for t in (d.get("themes") or [])
                                ],
                                "publish_date": "",
                            })

                        has_more = api_data.get("hasMore", False)
                        new_cursor = api_data.get("cursor", 0)
                        if isinstance(new_cursor, str):
                            try:
                                new_cursor = int(new_cursor)
                            except ValueError:
                                new_cursor = 0

                        return dramas, bool(has_more), new_cursor

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except asyncio.TimeoutError:
            logger.warning("CDP drama API fetch timeout")
        return None, False, 0

    async def _cdp_wait_for_load(self, ws, timeout: float = 20.0) -> bool:
        """Wait for Page.loadEventFired event."""
        import aiohttp
        deadline = asyncio.get_event_loop().time() + timeout
        try:
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                try:
                    msg = await asyncio.wait_for(
                        ws.receive(), timeout=min(3, max(0.1, remaining))
                    )
                except asyncio.TimeoutError:
                    continue

                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    if data.get("method") == "Page.loadEventFired":
                        logger.info("CDP: page load event received")
                        return True
                    if data.get("id") == 3 and data.get("error"):
                        logger.warning(f"CDP navigation error: {data['error']}")
                        return False
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    return False
        except Exception as e:
            logger.warning(f"CDP wait for load: {e}")

        logger.info("CDP: load event not received – proceeding anyway")
        return True

    async def _cdp_fetch_item_list(
        self, ws, secuid: str, cursor: int
    ) -> tuple[list | None, bool, int]:
        """Call TikTok's post/item_list API from within the page.

        Uses Runtime.evaluate with awaitPromise=True to call fetch() inside
        the TikTok page. The browser handles all auth automatically.

        Returns:
            (items: list|None, has_more: bool, cursor: int)
        """
        js_expr = (
            "(async function(){"
            "  try{"
            "    var u='/api/post/item_list/?"
            "      +'aid=1988&count=35&cursor=" + str(cursor)
            + "&secUid='+encodeURIComponent('" + secuid + "');"
            "    var r=await fetch(u,{credentials:'include'});"
            "    if(!r.ok) return JSON.stringify({_error:'HTTP '+r.status});"
            "    return await r.text();"
            "  }catch(e){"
            "    return JSON.stringify({_error:e.message||String(e)});"
            "  }"
            "})()"
        )

        msg_id = 20 + cursor
        await ws.send_json({
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": js_expr,
                "awaitPromise": True,
                "returnByValue": True,
            },
        })

        import aiohttp
        try:
            deadline = asyncio.get_event_loop().time() + 15
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                msg = await asyncio.wait_for(
                    ws.receive(), timeout=min(5, max(0.1, remaining))
                )
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    if data.get("id") == msg_id:
                        raw_value = (
                            data.get("result", {})
                            .get("result", {})
                            .get("value", "{}")
                        )
                        try:
                            api_data = json.loads(raw_value)
                        except json.JSONDecodeError:
                            logger.warning(
                                f"CDP API response not JSON: {raw_value[:200]}"
                            )
                            return None, False, 0

                        if "_error" in api_data:
                            logger.warning(
                                f"CDP API error: {api_data['_error']}"
                            )
                            return None, False, 0

                        items = api_data.get("itemList") or []
                        has_more = api_data.get("hasMore", False)
                        new_cursor = api_data.get("cursor", 0)
                        if isinstance(new_cursor, str):
                            try:
                                new_cursor = int(new_cursor)
                            except ValueError:
                                new_cursor = 0

                        return items, bool(has_more), new_cursor

                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except asyncio.TimeoutError:
            logger.warning("CDP API fetch timeout")
        return None, False, 0

    # ── Strategy 2: Page parsing (mobile UA) ────────────────────────

    async def _extract_via_page(self, url: str, username: str) -> list[dict] | None:
        proxy = await detect_proxy()
        client_kwargs = {"timeout": 30}
        if proxy:
            client_kwargs["proxy"] = proxy

        for ua, ua_label in [
            (_MOBILE_UA, "mobile"),
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "desktop",
            ),
        ]:
            try:
                headers = {"User-Agent": ua}
                async with httpx.AsyncClient(**client_kwargs) as client:
                    resp = await client.get(
                        url, headers=headers, follow_redirects=True
                    )
                    html = resp.text

                if self._is_waf_page(html):
                    logger.warning(
                        f"UA={ua_label}: WAF blocked (HTML={len(html)}B)"
                    )
                    continue

                dramas = self._parse_page_html(html)
                if dramas:
                    return dramas
            except Exception as e:
                logger.warning(f"UA={ua_label} request failed: {e}")

        return None

    def _is_waf_page(self, html: str) -> bool:
        if len(html) < 3000:
            html_lower = html.lower()
            if any(sig.lower() in html_lower for sig in _WAF_SIGNATURES):
                return True
            if (
                "sigi_state" not in html_lower
                and "__universal_data" not in html_lower
            ):
                return True
        return False

    def _parse_page_html(self, html: str) -> list[dict]:
        data = None
        for pattern in [
            _RE_UNIVERSAL_DATA_SCRIPT,
            _RE_UNIVERSAL_DATA_JS,
            _RE_SIGI_STATE,
        ]:
            match = pattern.search(html)
            if match:
                try:
                    data = json.loads(match.group(1))
                    break
                except json.JSONDecodeError:
                    continue
        if data is None:
            return []
        return self._extract_dramas_from_data(data)

    def _extract_dramas_from_data(self, data: dict) -> list[dict]:
        dramas = []
        try:
            default_scope = data.get("__DEFAULT_SCOPE__", data)
            user_detail = default_scope.get("webapp.user-detail", {})
            user_info = user_detail.get("userInfo", {})
            item_list = user_info.get("itemList", [])

            for item in item_list:
                drama = self._parse_video_as_drama(item)
                if drama:
                    dramas.append(drama)

            if not dramas:
                dramas = self._search_drama_items(data)
        except Exception as e:
            logger.warning(f"Error extracting drama data: {e}")

        return dramas

    def _parse_video_as_drama(self, item: dict) -> dict | None:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                return None
        if not isinstance(item, dict):
            return None

        desc = item.get("desc", "")
        if not desc:
            return None

        video_id = item.get("id", "")
        stats = item.get("stats", {})
        play_count = stats.get("playCount", 0)
        author = item.get("author", {})
        author_name = author.get("uniqueId", "")

        return {
            "name": desc[:100],
            "play_count": str(play_count),
            "episode_count": 0,
            "first_episode_url": (
                f"https://www.tiktok.com/@{author_name}/video/{video_id}"
                if author_name and video_id
                else ""
            ),
            "tags": item.get("challenges", []) or [],
            "publish_date": str(item.get("createTime", "")),
        }

    # ── Strategy 3: yt-dlp fallback ─────────────────────────────────

    async def _extract_via_ytdlp(
        self, url: str, username: str
    ) -> list[dict] | None:
        try:
            from core.utils.file_utils import run_subprocess
            from config import COOKIES_FILE

            cmd = [
                "python",
                "-m",
                "yt_dlp",
                "--flat-playlist",
                "--dump-json",
                "--no-check-certificates",
                "--no-warnings",
            ]

            if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 100:
                cmd.extend(["--cookies", str(COOKIES_FILE)])

            proxy = await detect_proxy()
            if proxy:
                cmd.extend(["--proxy", proxy])

            cmd.append(url)
            result = await run_subprocess(cmd, timeout=60)

            if not result["success"]:
                return None

            lines = result.get("stdout", "").strip().split("\n")
            dramas = []
            for line in lines:
                try:
                    video = json.loads(line)
                    drama = {
                        "name": video.get(
                            "title", video.get("description", "")
                        )[:100],
                        "play_count": str(video.get("view_count", "")),
                        "episode_count": 0,
                        "first_episode_url": video.get(
                            "webpage_url", video.get("url", "")
                        ),
                        "tags": video.get("tags", []) or [],
                        "publish_date": str(video.get("upload_date", "")),
                    }
                    if drama["name"]:
                        dramas.append(drama)
                except json.JSONDecodeError:
                    pass
            return dramas if dramas else None

        except Exception as e:
            logger.warning(f"yt-dlp strategy failed: {e}")
            return None

    # ── Shared helpers ─────────────────────────────────────────────

    def _search_drama_items(self, obj, depth: int = 0) -> list[dict]:
        if depth > 15:
            return []
        results = []
        if isinstance(obj, dict):
            if "dramaInfo" in obj or "dramaID" in obj:
                drama = self._parse_drama_item(obj)
                if drama:
                    results.append(drama)
            for v in obj.values():
                results.extend(self._search_drama_items(v, depth + 1))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(self._search_drama_items(item, depth + 1))
        return results

    def _parse_drama_item(self, obj: dict) -> dict | None:
        drama_info = obj.get("dramaInfo") or obj
        name = (
            drama_info.get("title")
            or drama_info.get("name")
            or obj.get("desc", "")
        )
        if not name:
            return None
        play_count = drama_info.get("playCount") or drama_info.get(
            "play_count", ""
        )
        episode_count = drama_info.get("episodeTotal") or drama_info.get(
            "episode_count", 0
        )
        first_ep_url = drama_info.get("firstEpisodeUrl") or ""
        tags = drama_info.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        return {
            "name": str(name),
            "play_count": str(play_count),
            "episode_count": int(episode_count) if episode_count else 0,
            "first_episode_url": str(first_ep_url) if first_ep_url else "",
            "tags": tags,
            "publish_date": str(drama_info.get("createTime") or ""),
        }

    def _extract_username(self, url: str) -> str | None:
        match = re.search(r"/@([^/?]+)", url)
        return match.group(1) if match else None
