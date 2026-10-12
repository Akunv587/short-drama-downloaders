"""
TikTok series discovery extractor.
"""
import json
import re
import httpx
from urllib.parse import urlparse, parse_qs, unquote
from core.platform.base import EpisodeInfo
from core.utils.logger import get_logger
from core.utils.proxy import detect_proxy

logger = get_logger()


class TikTokSeriesExtractor:
    """
    TikTok series discovery.
    - Extract dramaID from __UNIVERSAL_DATA_FOR_REHYDRATION__
    - Call internal API for episode list
    - Fallback: collect /video/{id} links from HTML
    """

    async def extract(self, url: str) -> list[EpisodeInfo]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        }

        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        url_drama_name = None
        if "q" in query_params:
            url_drama_name = unquote(query_params["q"][0])

        proxy = await detect_proxy()
        client_kwargs = {"timeout": 30}
        if proxy:
            client_kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            html = resp.text

        # Strategy 1: dramaID
        drama_id = self._extract_drama_id(html)
        if drama_id:
            episodes = await self._fetch_drama_episodes(drama_id, url_drama_name, proxy)
            if episodes:
                return episodes

        # Strategy 2: video links from HTML
        return self._extract_video_links(html, url, url_drama_name)

    def _extract_drama_id(self, html: str) -> str | None:
        match = re.search(
            r'__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{[\s\S]*?\})\s*;',
            html,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                drama_id = self._deep_search(data, "dramaID")
                if drama_id:
                    return str(drama_id)
            except json.JSONDecodeError:
                pass

        match = re.search(r'"dramaID"\s*:\s*"(\d+)"', html)
        if match:
            return match.group(1)
        match = re.search(r'dramaID[=:]"?(\d+)"?', html)
        if match:
            return match.group(1)
        return None

    async def _fetch_drama_episodes(self, drama_id: str, url_drama_name: str | None = None,
                                    proxy: str | None = None) -> list[EpisodeInfo]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Referer": "https://www.tiktok.com/",
        }

        all_episodes = []
        cursor = 0
        count = 200
        fallback_name = url_drama_name or "TikTok"

        client_kwargs = {"timeout": 30}
        if proxy:
            client_kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**client_kwargs) as client:
            while True:
                api_url = (
                    f"https://www.tiktok.com/api/drama/episode/item_list/"
                    f"?aid=1988&dramaID={drama_id}&count={count}&cursor={cursor}"
                )
                try:
                    resp = await client.get(api_url, headers=headers)
                    data = resp.json()
                    items = data.get("itemList", []) or data.get("items", [])

                    for item in items:
                        video_id = item.get("id", "")
                        desc = item.get("desc", "")
                        if desc and desc != str(len(all_episodes) + 1):
                            name = desc
                        else:
                            name = f"{fallback_name}-第{len(all_episodes) + 1}集"
                        all_episodes.append(EpisodeInfo(
                            url=f"https://www.tiktok.com/@/video/{video_id}",
                            number=len(all_episodes) + 1,
                            title=name,
                        ))

                    if not data.get("hasMore", False) or not items:
                        break
                    cursor = data.get("cursor", cursor + count)
                except Exception as e:
                    logger.warning(f"TikTok API failed (cursor={cursor}): {e}")
                    break

        logger.info(f"TikTok series (API): {len(all_episodes)} episodes")
        return all_episodes

    def _extract_video_links(self, html: str, source_url: str,
                             url_drama_name: str | None = None) -> list[EpisodeInfo]:
        matches = re.findall(r'/(@[\w.]+/)?video/(\d+)', html)
        seen = set()
        episodes = []
        fallback_name = url_drama_name or "TikTok"

        for _, video_id in matches:
            if video_id in seen:
                continue
            seen.add(video_id)
            episodes.append(EpisodeInfo(
                url=f"https://www.tiktok.com/@/video/{video_id}",
                number=len(episodes) + 1,
                title=f"{fallback_name}-{video_id}",
            ))

        logger.info(f"TikTok series (page links): {len(episodes)} episodes")
        return episodes

    def _deep_search(self, obj, key: str, depth: int = 0):
        if depth > 20:
            return None
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                result = self._deep_search(v, key, depth + 1)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._deep_search(item, key, depth + 1)
                if result is not None:
                    return result
        return None
