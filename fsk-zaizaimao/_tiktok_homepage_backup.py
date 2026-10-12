"""
TikTok homepage drama extractor.

Extracts drama info from TikTok user homepages using multiple strategies:
1. Mobile UA page parsing (fast)
2. CDP Chrome browser extraction (reliable)
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

        result = await self._extract_via_page(url, username)
        if result is not None:
            return result

        result = await self._extract_via_cdp(url, username)
        if result is not None:
            return result

        result = await self._extract_via_ytdlp(url, username)
        if result is not None:
            return result

        return []

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
                    resp = await client.get(url, headers=headers, follow_redirects=True)
                    html = resp.text

                if self._is_waf_page(html):
                    logger.warning(f"UA={ua_label}: WAF blocked (HTML={len(html)}B)")
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
            if "sigi_state" not in html_lower and "__universal_data" not in html_lower:
                return True
        return False

    def _parse_page_html(self, html: str) -> list[dict]:
        data = None
        for pattern in [_RE_UNIVERSAL_DATA_SCRIPT, _RE_UNIVERSAL_DATA_JS, _RE_SIGI_STATE]:
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
                if author_name and video_id else ""
            ),
            "tags": item.get("challenges", []) or [],
            "publish_date": str(item.get("createTime", "")),
        }

    async def _extract_via_cdp(self, url: str, username: str) -> list[dict] | None:
        try:
            from websocket import create_connection
            cdp_ports = [9222, 9223, 9229]
            ws = None
            for port in cdp_ports:
                try:
                    ws_url = f"ws://127.0.0.1:{port}/devtools/browser"
                    ws = create_connection(ws_url, timeout=3)
                    logger.info(f"CDP connected: port {port}")
                    break
                except Exception:
                    continue

            if ws is None:
                return None

            html = await self._cdp_navigate_and_extract(ws, url)
            ws.close()

            if html and not self._is_waf_page(html):
                dramas = self._parse_page_html(html)
                if dramas:
                    return dramas

            return None
        except ImportError:
            return None
        except Exception as e:
            logger.warning(f"CDP extraction failed: {e}")
            return None

    async def _cdp_navigate_and_extract(self, ws, url: str) -> str | None:
        import time
        try:
            ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
            time.sleep(0.5)
            resp_str = ws.recv()
            targets = json.loads(resp_str).get("result", {}).get("targetInfos", [])

            page_target = None
            for t in targets:
                if t.get("type") == "page":
                    page_target = t
                    break

            if page_target:
                target_id = page_target["targetId"]
                ws.send(json.dumps({
                    "id": 2, "method": "Target.attachToTarget",
                    "params": {"targetId": target_id, "flatten": True},
                }))
                time.sleep(0.5)
                attach_resp = json.loads(ws.recv())
                session_id = attach_resp.get("result", {}).get("sessionId", "")

                ws.send(json.dumps({
                    "id": 3, "method": "Page.enable", "sessionId": session_id,
                }))
                time.sleep(0.3)

                ws.send(json.dumps({
                    "id": 4, "method": "Page.navigate",
                    "params": {"url": url}, "sessionId": session_id,
                }))
                time.sleep(0.3)

                await asyncio.sleep(5)

                ws.settimeout(1)
                try:
                    while True:
                        ws.recv()
                except Exception:
                    pass
                ws.settimeout(10)

                ws.send(json.dumps({
                    "id": 5, "method": "Runtime.evaluate",
                    "params": {"expression": "document.documentElement.outerHTML"},
                    "sessionId": session_id,
                }))
                time.sleep(1)

                result_str = ws.recv()
                result = json.loads(result_str)
                html = result.get("result", {}).get("result", {}).get("value", "")
                if html:
                    logger.info(f"CDP extracted HTML: {len(html)} bytes")
                    return html
        except Exception as e:
            logger.warning(f"CDP navigate/extract failed: {e}")
        return None

    async def _extract_via_ytdlp(self, url: str, username: str) -> list[dict] | None:
        try:
            from core.utils.file_utils import run_subprocess
            from config import COOKIES_FILE

            cmd = [
                "python", "-m", "yt_dlp",
                "--flat-playlist", "--dump-json",
                "--no-check-certificates", "--no-warnings",
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
                        "name": video.get("title", video.get("description", ""))[:100],
                        "play_count": str(video.get("view_count", "")),
                        "episode_count": 0,
                        "first_episode_url": video.get("webpage_url", video.get("url", "")),
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
        name = drama_info.get("title") or drama_info.get("name") or obj.get("desc", "")
        if not name:
            return None
        play_count = drama_info.get("playCount") or drama_info.get("play_count", "")
        episode_count = drama_info.get("episodeTotal") or drama_info.get("episode_count", 0)
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
        match = re.search(r'/@([^/?]+)', url)
        return match.group(1) if match else None
