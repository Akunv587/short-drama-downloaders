"""ShortMax platform adapter — Nuxt SSR parsing + HLS download."""
from __future__ import annotations
import asyncio
import json
import re
import socket
from pathlib import Path
import httpx
from .base import BasePlatformAdapter, EpisodeInfo, PlatformMeta, ProgressInfo, ProgressCallback
from .hls_engine import hls_engine
from core.utils.logger import get_logger

logger = get_logger("shortmax")

WEB_BASE = "https://www.shorttv.live"

URL_PATTERN = re.compile(
    r"shorttv\.live/episode/(?P<slug>.+)-(?P<movie_id>\d+)-(?P<episode>\d+)$"
)
URL_PATTERN_ALT = re.compile(
    r"shortmax\.com/episode/(?P<slug>.+)-(?P<movie_id>\d+)-(?P<episode>\d+)$"
)

NUXT_DATA_PATTERN = re.compile(
    r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


class NuxtDataResolver:
    """Resolve Nuxt __NUXT_DATA__ index references."""

    def __init__(self, data: list):
        self._data = data
        self._cache: dict[int, object] = {}
        self._resolving: set[int] = set()

    def resolve(self, idx: int, max_depth: int = 20) -> object:
        if idx in self._cache:
            return self._cache[idx]
        if idx in self._resolving:
            return None
        self._resolving.add(idx)
        try:
            value = self._data[idx] if idx < len(self._data) else None
            result = self._resolve_value(value, max_depth - 1)
            self._cache[idx] = result
            return result
        finally:
            self._resolving.discard(idx)

    def _resolve_value(self, value, depth: int) -> object:
        if depth <= 0:
            return value
        if isinstance(value, dict):
            return {k: self._resolve_entry(v, depth) for k, v in value.items()}
        if isinstance(value, list):
            if (len(value) == 2 and isinstance(value[0], str)
                    and value[0] in ("ShallowReactive", "Reactive", "Set")):
                return value
            return [self._resolve_entry(v, depth) for v in value]
        return value

    def _resolve_entry(self, value, depth: int) -> object:
        if isinstance(value, int) and 0 <= value < len(self._data):
            return self.resolve(value, depth)
        return self._resolve_value(value, depth)

    def find_shortplay_data(self) -> dict | None:
        for item in self._data:
            if isinstance(item, dict) and "shortPlayId" in item:
                return self._resolve_value(item, 20)
        return None


class ShortMaxAdapter(BasePlatformAdapter):
    platform_meta = PlatformMeta(
        name="ShortMax",
        key="shortmax",
        domain="shorttv.live",
        accent="#f59e0b",
        supports_hls=True,
        requires_proxy=True,
        status="Free",
    )

    def __init__(self):
        super().__init__()
        self._proxy_url: str | None = self._detect_proxy_sync()

    @staticmethod
    def _detect_proxy_sync() -> str | None:
        candidates = [
            ("127.0.0.1", 10808, "V2Ray"),
            ("127.0.0.1", 10809, "V2Ray HTTP"),
            ("127.0.0.1", 7890, "Clash"),
        ]
        for host, port, label in candidates:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                result = s.connect_ex((host, port))
                s.close()
                if result == 0:
                    logger.info(f"Detected {label} proxy: {host}:{port}")
                    return f"http://{host}:{port}"
            except Exception:
                continue
        return None

    # ── Episode extraction ──────────────────────────────

    async def extract_episodes(self, url: str) -> list[EpisodeInfo]:
        match = None
        for pattern in [URL_PATTERN, URL_PATTERN_ALT]:
            match = pattern.search(url)
            if match:
                break
        if not match:
            return [EpisodeInfo(url=url, number=1)]

        movie_id = match.group("movie_id")
        try:
            page_url = f"{WEB_BASE}/episode/short-{movie_id}-1"
            client_kwargs = {"timeout": 30}
            if self._proxy_url:
                client_kwargs["proxy"] = self._proxy_url
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.get(page_url)
                resp.raise_for_status()
                html = resp.text

            nuxt_match = NUXT_DATA_PATTERN.search(html)
            if not nuxt_match:
                logger.warning("__NUXT_DATA__ not found")
                return [EpisodeInfo(url=url, number=1)]

            data = json.loads(nuxt_match.group(1))
            resolver = NuxtDataResolver(data)
            sp_data = resolver.find_shortplay_data()

            if not sp_data:
                logger.warning("shortPlay data not found in Nuxt data")
                return [EpisodeInfo(url=url, number=1)]

            movie_title = sp_data.get("shortPlayName", "")
            episode_list = sp_data.get("episodeList", [])

            result = []
            for ep_obj in episode_list:
                if not isinstance(ep_obj, dict):
                    continue
                ep_num = ep_obj.get("episodeNum", 0)
                enc_url = ep_obj.get("encryptedVideoUrl", "")
                info = EpisodeInfo(
                    url=f"{WEB_BASE}/episode/short-{movie_id}-{ep_num}",
                    number=int(ep_num) if ep_num else 0,
                    title=f"第{ep_num}集" if not movie_title else f"{movie_title} E{ep_num}",
                )
                info.cover_url = enc_url if enc_url else ""  # reuse field for enc_url
                result.append(info)

            logger.info(f"ShortMax: {len(result)} episodes found")
            return result if result else [EpisodeInfo(url=url, number=1)]

        except Exception as e:
            logger.error(f"ShortMax extract_episodes failed: {e}")
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

        match = None
        for pattern in [URL_PATTERN, URL_PATTERN_ALT]:
            match = pattern.search(url)
            if match:
                break
        if not match:
            logger.error(f"Cannot parse ShortMax URL: {url}")
            return None

        movie_id = match.group("movie_id")
        ep_num = int(match.group("episode") or episode_number or 1)

        try:
            page_url = f"{WEB_BASE}/episode/short-{movie_id}-{ep_num}"
            client_kwargs = {"timeout": 30}
            if self._proxy_url:
                client_kwargs["proxy"] = self._proxy_url
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.get(page_url)
                resp.raise_for_status()
                html = resp.text

            nuxt_match = NUXT_DATA_PATTERN.search(html)
            if not nuxt_match:
                raise RuntimeError("__NUXT_DATA__ not found in page")

            data = json.loads(nuxt_match.group(1))
            resolver = NuxtDataResolver(data)
            sp_data = resolver.find_shortplay_data()

            movie_title = ""
            m3u8_url = ""

            if sp_data:
                movie_title = sp_data.get("shortPlayName", "")
                episode_list = sp_data.get("episodeList", [])
                for ep_obj in episode_list:
                    if isinstance(ep_obj, dict) and ep_obj.get("episodeNum") == ep_num:
                        enc_url = ep_obj.get("encryptedVideoUrl", "")
                        m3u8_url = self._resolve_manifest(enc_url)
                        break

            if not m3u8_url:
                # Fallback: search HTML for m3u8 URL
                m3u8_match = re.search(
                    r'https://akamai-static\.shorttv\.live/hls-encrypted/[^"\\]+\.m3u8',
                    html
                )
                if m3u8_match:
                    m3u8_url = m3u8_match.group(0)

            if not m3u8_url:
                raise RuntimeError(
                    f"Cannot find m3u8 URL. Episode {ep_num} may require VIP login. "
                    "First 6 episodes are usually free."
                )

            safe_title = re.sub(r'[<>:"/\\|?*]', '_', movie_title or "shortmax")[:50]
            ep_str = f"{ep_num:02d}"
            output_path = output_dir / f"{safe_title}_E{ep_str}.mp4"

            if progress_callback:
                await progress_callback(ProgressInfo(
                    task_id="", status="downloading", progress=0.1,
                    drama_name=movie_title or "ShortMax",
                    episode_number=ep_num,
                    message="HLS downloading..."
                ))

            result = await hls_engine.download(
                m3u8_url,
                str(output_path),
                headers={
                    "Origin": WEB_BASE,
                    "Referer": WEB_BASE,
                },
                proxy=self._proxy_url,
            )

            if result.success and output_path.exists():
                if progress_callback:
                    await progress_callback(ProgressInfo(
                        task_id="", status="completed", progress=1.0,
                        drama_name=movie_title or "ShortMax",
                        episode_number=ep_num,
                        message=f"Done ({result.file_size / 1024 / 1024:.1f} MB)"
                    ))
                return output_path
            else:
                raise RuntimeError(result.error or "HLS download failed")

        except Exception as e:
            logger.error(f"ShortMax download failed: {e}")
            if progress_callback:
                await progress_callback(ProgressInfo(
                    task_id="", status="failed", progress=0,
                    message=str(e)
                ))
            return None

    @staticmethod
    def _resolve_manifest(enc_url: str) -> str | None:
        if not enc_url or not isinstance(enc_url, str):
            return None
        if enc_url in ('""', '', '""'):
            return None

        if enc_url.startswith('{'):
            try:
                data = json.loads(enc_url)
            except json.JSONDecodeError:
                return None
            for quality in ["video_1080", "video_720", "video_480"]:
                if quality in data and data[quality]:
                    return data[quality]
            return None

        if enc_url.startswith("http") and ".m3u8" in enc_url:
            return enc_url

        return None
