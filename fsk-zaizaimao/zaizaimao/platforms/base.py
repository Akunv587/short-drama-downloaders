"""
平台适配器抽象基类

所有平台模块必须实现此接口，确保统一的调用方式。
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zaizaimao.core.client import HTTPClient
    from zaizaimao.core.auth import AuthManager

logger = logging.getLogger("zaizaimao.platform")


@dataclass
class EpisodeInfo:
    """剧集信息"""
    movie_id: str
    movie_title: str = ""
    episode_number: int = 0
    episode_title: str = ""
    duration: int = 0       # 秒
    cover_url: str = ""     # 封面图 URL (dramashorts 用于提取 m3u8 hash)

    def __str__(self) -> str:
        return f"[E{self.episode_number:02d}] {self.episode_title or self.movie_title}"


@dataclass
class PlaybackInfo:
    """播放凭证"""
    manifest_url: str                       # m3u8 地址
    headers: dict[str, str] = field(default_factory=dict)  # 下载时需要的请求头
    drm_token: str | None = None            # DRM 解密密钥（如有）
    subtitle_url: str | None = None         # 字幕地址（如有）


class PlatformAdapter(ABC):
    """
    平台适配器抽象基类

    每个平台必须实现以下方法:
    - login:           登录认证
    - parse_url:       从 URL 解析剧集信息
    - get_episode_list: 获取剧集列表
    - get_playback:    获取播放凭证
    - is_authenticated: 检查登录状态
    """

    # 子类必须设置
    platform_name: str      # "dramashorts" / "shortmax" / "tiktok" / ...
    api_base_url: str       # API 基础地址

    def __init__(
        self,
        http: "HTTPClient | None" = None,
        auth: "AuthManager | None" = None,
    ):
        from zaizaimao.core.client import HTTPClient
        from zaizaimao.core.auth import AuthManager

        self.http = http or HTTPClient()
        self.auth = auth or AuthManager()
        self._setup()

    def _setup(self) -> None:
        """初始化后的钩子，子类可覆写"""

    # ── 抽象方法 ──────────────────────────────────────────

    @abstractmethod
    async def login(self, **credentials) -> bool:
        """
        登录认证

        Returns:
            是否登录成功
        """

    @abstractmethod
    async def parse_url(self, url: str) -> EpisodeInfo:
        """
        从平台 URL 解析剧集信息

        Args:
            url: 如 "https://dramashorts.io/shorts/{movieId}?episode=1"

        Returns:
            EpisodeInfo 包含 movieId 和 episode number
        """

    @abstractmethod
    async def get_episode_list(self, movie_id: str) -> list[EpisodeInfo]:
        """
        获取某部剧的所有剧集列表

        Args:
            movie_id: 影片 ID

        Returns:
            剧集列表
        """

    @abstractmethod
    async def get_playback(self, episode: EpisodeInfo) -> PlaybackInfo:
        """
        获取剧集的播放凭证

        Args:
            episode: 剧集信息

        Returns:
            PlaybackInfo 包含 m3u8 地址和认证头
        """

    # ── 公共方法 ──────────────────────────────────────────

    def load_cached_token(self) -> dict | None:
        """加载缓存的认证 token"""
        return self.auth.load_token(self.platform_name)

    async def is_authenticated(self) -> bool:
        """检查认证状态是否有效"""
        return self.auth.is_token_valid(self.platform_name)

    async def ensure_auth(self) -> None:
        """确保已认证，否则尝试从缓存恢复或提示登录"""
        if await self.is_authenticated():
            token = self.load_cached_token()
            if token:
                self.http.set_auth_token(token["access_token"])
                return
        raise RuntimeError(
            f"未登录 {self.platform_name}。请先运行: zaizaimao login --platform {self.platform_name}"
        )
