"""Platform adapter base class."""
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Awaitable


@dataclass
class EpisodeInfo:
    url: str
    number: int
    title: str = ""
    # Extra fields used by platform adapters
    cover_url: str = ""  # DramaShorts: cover URL for m3u8 hash
    # ShortMax: encryptedVideoUrl stored here


@dataclass
class ProgressInfo:
    task_id: str
    status: str
    progress: float
    message: str = ""
    drama_name: str = ""
    episode_number: int | None = None


@dataclass
class PlatformMeta:
    name: str
    key: str
    domain: str
    accent: str = "#888"
    supports_hls: bool = False
    requires_proxy: bool = False
    status: str = "Free"


ProgressCallback = Callable[[ProgressInfo], Awaitable[None]]


class BasePlatformAdapter(ABC):
    platform_meta: PlatformMeta

    @abstractmethod
    async def extract_episodes(self, url: str) -> list[EpisodeInfo]:
        """Discover all episodes from a single episode URL."""

    @abstractmethod
    async def download_episode(
        self,
        url: str,
        output_dir: str | Path,
        episode_number: int | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Path | None:
        """Download a single episode. Returns output path or None on failure."""

    async def discover_series(self, url: str) -> list[str]:
        episodes = await self.extract_episodes(url)
        return [ep.url for ep in episodes]
