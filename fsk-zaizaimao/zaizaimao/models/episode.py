"""剧集 & 影片数据模型"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Episode:
    """单集数据"""
    episode_id: str
    number: int
    title: str = ""
    duration: int = 0   # 秒
    poster_url: str = ""


@dataclass
class Movie:
    """影片/剧集元信息"""
    movie_id: str
    title: str
    description: str = ""
    platform: str = ""               # dramashorts / shortmax / tiktok / ...
    total_episodes: int = 0
    genre: str = ""
    release_date: datetime | None = None
    episodes: list[Episode] = field(default_factory=list)
