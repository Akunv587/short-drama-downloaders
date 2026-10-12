"""平台适配层"""

from zaizaimao.platforms.base import PlatformAdapter, EpisodeInfo, PlaybackInfo
from zaizaimao.platforms.dramashorts import DramaShortsAdapter

__all__ = ["PlatformAdapter", "EpisodeInfo", "PlaybackInfo", "DramaShortsAdapter"]
