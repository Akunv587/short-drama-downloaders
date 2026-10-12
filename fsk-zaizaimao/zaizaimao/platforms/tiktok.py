"""
TikTok 平台适配器 (tiktok.com)

TikTok 与短剧平台根本不同:
- 每个 URL 是独立视频，非剧集系列
- 使用 yt-dlp 子进程下载（非 HLS 引擎）
- 需要 Cookie (Netscape 格式) 才能下载
- 需要代理访问（中国大陆用户）

适配器仅用于 URL 解析和元数据提取，
实际下载由 zaizaimao.core.tiktok_dl.TikTokDownloader 处理。
"""

import logging
import re

from zaizaimao.platforms.base import PlatformAdapter, EpisodeInfo, PlaybackInfo

logger = logging.getLogger("zaizaimao.tiktok")

PLATFORM_NAME = "tiktok"
WEB_BASE = "https://www.tiktok.com"

# TikTok URL 正则
# 格式: tiktok.com/@username/video/1234567890
#       vm.tiktok.com/XXXXX/  (短链)
#       m.tiktok.com/v/1234567890
URL_PATTERN = re.compile(
    r"(?:www\.|vm\.|m\.)?tiktok\.com/"
    r"(?:(?:@[\w.-]+/video/(?P<video_id>\d+))"
    r"|(?:v/(?P<video_id2>\d+))"
    r"|(?:(?P<short_id>[\w]+)/?$))"
)

# 提取视频 ID
VIDEO_ID_PATTERN = re.compile(r"/video/(\d+)")


class TikTokAdapter(PlatformAdapter):
    """
    TikTok 平台适配器。

    注意: 此适配器仅用于 URL 解析和平台标识。
    实际下载不经过 get_playback() → HLSEngine 流程，
    而是通过 zaizaimao.core.tiktok_dl.TikTokDownloader 直接调用 yt-dlp。
    """

    platform_name = PLATFORM_NAME
    api_base_url = WEB_BASE

    def _setup(self) -> None:
        """TikTok 不需要额外的 HTTP 配置"""
        self.http.set_header("Referer", "https://www.tiktok.com/")

    # ── 认证 ──────────────────────────────────────────────

    async def login(self, **credentials) -> bool:
        """
        TikTok 不使用传统 token 登录。
        认证通过 yt-dlp 的 --cookies 参数传入 Cookie 文件。
        """
        logger.warning("TikTok 不需要传统登录，请使用 Cookie 文件")
        return True

    # ── URL 解析 ──────────────────────────────────────────

    async def parse_url(self, url: str) -> EpisodeInfo:
        """
        从 TikTok URL 提取视频信息。

        Args:
            url: TikTok 视频链接

        Returns:
            EpisodeInfo (movie_id = video_id, episode_number = 1)
        """
        # 提取视频 ID
        match = VIDEO_ID_PATTERN.search(url)
        if match:
            video_id = match.group(1)
        else:
            # 短链或无法解析的 URL，用 hash 做 ID
            video_id = str(abs(hash(url)))[:16]

        return EpisodeInfo(
            movie_id=video_id,
            movie_title=f"TikTok {video_id[:8]}",
            episode_number=1,
            episode_title=url,
        )

    # ── 剧集列表 ──────────────────────────────────────────

    async def get_episode_list(self, movie_id: str) -> list[EpisodeInfo]:
        """
        TikTok 没有剧集概念，返回单条记录。

        实际批量下载时，多个 URL 会在外层循环处理。
        """
        return [
            EpisodeInfo(
                movie_id=movie_id,
                movie_title=f"TikTok {movie_id[:8]}",
                episode_number=1,
            )
        ]

    # ── 播放凭证 ──────────────────────────────────────────

    async def get_playback(self, episode: EpisodeInfo) -> PlaybackInfo:
        """
        TikTok 不使用 m3u8 播放。

        返回空 PlaybackInfo，实际下载由 TikTokDownloader 处理。
        """
        return PlaybackInfo(
            manifest_url="",
            headers={"Referer": "https://www.tiktok.com/"},
        )

    # ── 静态方法 ──────────────────────────────────────────

    @staticmethod
    def extract_video_id(url: str) -> str | None:
        """从 TikTok URL 提取视频 ID"""
        match = VIDEO_ID_PATTERN.search(url)
        return match.group(1) if match else None

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """检查是否为有效的 TikTok URL"""
        return bool(URL_PATTERN.search(url))
