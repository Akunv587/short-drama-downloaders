"""Extraction API routes (batch, episodes, homepage)."""
from fastapi import APIRouter
from pydantic import BaseModel
from core.platform.detector import detect_platform, get_adapter
from core.extractors.tiktok_series import TikTokSeriesExtractor
from core.extractors.tiktok_homepage import TikTokHomepageExtractor
from core.utils.logger import get_logger

router = APIRouter()
logger = get_logger("api.extract")


class BatchExtractRequest(BaseModel):
    urls: list[str]


class EpisodeExtractRequest(BaseModel):
    url: str


class HomepageExtractRequest(BaseModel):
    url: str


@router.post("/extract/batch")
async def extract_batch(req: BatchExtractRequest):
    results = []
    for url in req.urls:
        platform_key = detect_platform(url)
        if not platform_key:
            results.append({
                "url": url, "platform": "unknown",
                "drama_name": "", "episode_number": None,
                "error": "Unknown platform"
            })
            continue

        adapter = get_adapter(platform_key)
        if not adapter:
            results.append({
                "url": url, "platform": platform_key,
                "drama_name": "", "episode_number": None,
                "error": f"No adapter for {platform_key}"
            })
            continue

        try:
            episodes = await adapter.extract_episodes(url)
            results.append({
                "url": url,
                "platform": platform_key,
                "drama_name": episodes[0].title if episodes else "",
                "episode_count": len(episodes),
                "episodes": [
                    {"url": ep.url, "number": ep.number, "title": ep.title}
                    for ep in episodes
                ],
            })
        except Exception as e:
            logger.error(f"Batch extract failed for {url}: {e}")
            results.append({
                "url": url, "platform": platform_key,
                "drama_name": "", "episode_number": None,
                "error": str(e)
            })

    return {"results": results}


@router.post("/extract/episodes")
async def extract_episodes(req: EpisodeExtractRequest):
    platform_key = detect_platform(req.url)
    if not platform_key:
        return {
            "url": req.url, "drama_name": "", "total_episodes": 0,
            "episodes": [], "error": "Unknown platform"
        }

    adapter = get_adapter(platform_key)
    if not adapter:
        return {
            "url": req.url, "drama_name": "", "total_episodes": 0,
            "episodes": [], "error": f"No adapter for {platform_key}"
        }

    try:
        episodes = await adapter.extract_episodes(req.url)
        return {
            "url": req.url,
            "platform": platform_key,
            "drama_name": episodes[0].title if episodes else "",
            "total_episodes": len(episodes),
            "episodes": [
                {"url": ep.url, "number": ep.number, "title": ep.title}
                for ep in episodes
            ],
        }
    except Exception as e:
        logger.error(f"Episode extraction failed: {e}")
        return {
            "url": req.url, "drama_name": "", "total_episodes": 0,
            "episodes": [], "error": str(e)
        }


@router.post("/extract/homepage")
async def extract_homepage(req: HomepageExtractRequest):
    try:
        extractor = TikTokHomepageExtractor()
        dramas = await extractor.extract(req.url)
        return {
            "url": req.url,
            "dramas": dramas,
        }
    except Exception as e:
        logger.error(f"Homepage extraction failed: {e}")
        return {
            "url": req.url,
            "dramas": [],
            "error": str(e)
        }
