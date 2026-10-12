"""DramaShorts platform adapter — Next.js SSR parsing + HLS download."""
from __future__ import annotations
import asyncio
import json
import re
from pathlib import Path
import httpx
from .base import BasePlatformAdapter, EpisodeInfo, PlatformMeta, ProgressInfo, ProgressCallback
from .hls_engine import hls_engine
from core.utils.logger import get_logger

logger = get_logger("dramashorts")

WEB_BASE = "https://dramashorts.io"
CDN_VIDEO_BASE = "https://cdn.dramashorts.io/video"

URL_PATTERN = re.compile(
    r"dramashorts\.io/shorts/(?P<movie_id>[a-f0-9-]+)"
    r"(?:\?episode=(?P<episode>\d+))?"
)

NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>'
)

COVER_HASH_PATTERN = re.compile(
    r'/episodes-previews/(?P<hash1>[^/]+)/(?P<hash2>[^/]+)/cover\.jpeg'
)


class DramaShortsAdapter(BasePlatformAdapter):
    platform_meta = PlatformMeta(
        name="DramaShorts",
        key="dramashorts",
        domain="dramashorts.io",
        accent="#4ade80",
        supports_hls=True,
        requires_proxy=False,
        status="Free",
    )

    # ── Episode extraction ──────────────────────────────

    async def extract_episodes(self, url: str) -> list[EpisodeInfo]:
        match = URL_PATTERN.search(url)
        if not match:
            return [EpisodeInfo(url=url, number=1)]
        movie_id = match.group("movie_id")

        try:
            page_url = f"{WEB_BASE}/shorts/{movie_id}?episode=1"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(page_url)
                resp.raise_for_status()
                html = resp.text

            next_match = NEXT_DATA_PATTERN.search(html)
            if not next_match:
                logger.warning("__NEXT_DATA__ not found")
                return [EpisodeInfo(url=url, number=1)]

            next_data = json.loads(next_match.group(1))
            page_props = next_data.get("props", {}).get("pageProps", {})
            episodes_raw = page_props.get("episodes", [])
            movie_title = (
                page_props.get("movieDetails", {})
                .get("movie", {})
                .get("title", "")
            )

            result = []
            for ep in episodes_raw:
                ep_data = ep.get("episode", {})
                ep_num = ep_data.get("index", 0)
                info = EpisodeInfo(
                    url=f"{WEB_BASE}/shorts/{movie_id}?episode={ep_num}",
                    number=ep_num,
                    title=f"第{ep_num}集" if not movie_title else f"{movie_title} E{ep_num}",
                )
                info.cover_url = ep_data.get("coverUrl", "")
                result.append(info)

            logger.info(f"DramaShorts: {len(result)} episodes found")
            return result if result else [EpisodeInfo(url=url, number=1)]

        except Exception as e:
            logger.error(f"DramaShorts extract_episodes failed: {e}")
            return [EpisodeInfo(url=url, number=1)]

    # ── Download ────────────────────────────────────────

    async def download_episode(
        self,
        url: str,
        output_dir: str | Path,
        episode_number: int | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Path | None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        match = URL_PATTERN.search(url)
        if not match:
            logger.error(f"Cannot parse DramaShorts URL: {url}")
            return None
        movie_id = match.group("movie_id")
        ep_num = int(match.group("episode") or episode_number or 1)

        try:
            # Fetch page data
            page_url = f"{WEB_BASE}/shorts/{movie_id}?episode={ep_num}"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(page_url)
                resp.raise_for_status()
                html = resp.text

            next_match = NEXT_DATA_PATTERN.search(html)
            if not next_match:
                raise RuntimeError("__NEXT_DATA__ not found in page")

            next_data = json.loads(next_match.group(1))
            page_props = next_data.get("props", {}).get("pageProps", {})
            episodes_raw = page_props.get("episodes", [])

            # Find the specific episode's cover URL
            cover_url = ""
            movie_title = ""
            movie_details = page_props.get("movieDetails", {})
            movie_title = movie_details.get("movie", {}).get("title", "")

            for ep in episodes_raw:
                ep_data = ep.get("episode", {})
                if ep_data.get("index") == ep_num:
                    cover_url = ep_data.get("coverUrl", "")
                    break

            if not cover_url:
                # Try first episode as fallback
                if episodes_raw:
                    cover_url = episodes_raw[0].get("episode", {}).get("coverUrl", "")

            if not cover_url:
                raise RuntimeError(f"Cannot find cover URL for episode {ep_num}")

            # Construct m3u8 from coverUrl hash
            hash_match = COVER_HASH_PATTERN.search(cover_url)
            if not hash_match:
                raise RuntimeError(f"Cannot extract hash from coverUrl: {cover_url}")

            m3u8_url = (
                f"{CDN_VIDEO_BASE}/{hash_match.group('hash1')}/"
                f"{hash_match.group('hash2')}/manifest.m3u8"
            )

            # Determine output filename
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', movie_title or "drama")[:50]
            ep_str = f"{ep_num:02d}"
            output_path = output_dir / f"{safe_title}_E{ep_str}.mp4"

            if progress_callback:
                await progress_callback(ProgressInfo(
                    task_id="", status="downloading", progress=0.1,
                    drama_name=movie_title or "DramaShorts",
                    episode_number=ep_num,
                    message="HLS downloading..."
                ))

            # Download via HLS engine
            result = await hls_engine.download(
                m3u8_url,
                str(output_path),
                headers={
                    "Origin": WEB_BASE,
                    "Referer": f"{WEB_BASE}/shorts/{movie_id}",
                },
            )

            if result.success and output_path.exists():
                if progress_callback:
                    await progress_callback(ProgressInfo(
                        task_id="", status="completed", progress=1.0,
                        drama_name=movie_title or "DramaShorts",
                        episode_number=ep_num,
                        message=f"Done ({result.file_size / 1024 / 1024:.1f} MB)"
                    ))
                return output_path
            else:
                raise RuntimeError(result.error or "HLS download failed")

        except Exception as e:
            logger.error(f"DramaShorts download failed: {e}")
            if progress_callback:
                await progress_callback(ProgressInfo(
                    task_id="", status="failed", progress=0,
                    message=str(e)
                ))
            return None
