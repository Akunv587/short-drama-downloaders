"""
DramaShorts 剧集发现 - delegates to adapter.
"""
from core.platform.dramashorts import DramaShortsAdapter
from core.platform.base import EpisodeInfo
from core.utils.logger import get_logger

logger = get_logger()


class DramaShortsEpisodesExtractor:
    """DramaShorts episode discovery."""

    def __init__(self):
        self.adapter = DramaShortsAdapter()

    async def extract(self, url: str) -> list[EpisodeInfo]:
        return await self.adapter.extract_episodes(url)
