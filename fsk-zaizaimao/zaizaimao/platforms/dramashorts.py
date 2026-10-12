"""
DramaShorts 平台适配器 (dramashorts.io)

技术栈:
- 前端:    Next.js (SSR + CSR)
- 播放器:  Mux Player (env-key: vctn0qeffvtl72iep576g5b5t)
- 视频格式: fMP4/HLS (.m4s segments via .m3u8)
- 内容类型: regular (免费) / plus (VIP)
- 认证:    Firebase Auth (仅 VIP 需要)

下载策略:
- 免费内容: 从 __NEXT_DATA__ 的 episode.coverUrl 提取 hash,
           拼出 m3u8: cdn.dramashorts.io/video/{hash1}/{hash2}/manifest.m3u8
- VIP 内容: 需要 Firebase 登录 → API 获取播放凭证 (TODO)
"""

import json
import logging
import re
from typing import TYPE_CHECKING

from zaizaimao.platforms.base import PlatformAdapter, EpisodeInfo, PlaybackInfo

if TYPE_CHECKING:
    from zaizaimao.core.client import HTTPClient
    from zaizaimao.core.auth import AuthManager

logger = logging.getLogger("zaizaimao.dramashorts")

# ── 常量 ──────────────────────────────────────────────────

PLATFORM_NAME = "dramashorts"
WEB_BASE = "https://dramashorts.io"
CDN_VIDEO_BASE = "https://cdn.dramashorts.io/video"

# URL 解析正则: /shorts/{movieId} 或 /shorts/{movieId}?episode={n}
URL_PATTERN = re.compile(
    r"dramashorts\.io/shorts/(?P<movie_id>[a-f0-9-]+)"
    r"(?:\?episode=(?P<episode>\d+))?"
)

# 从 __NEXT_DATA__ 提取页面数据
NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>'
)

# 从 coverUrl 提取双 hash: .../episodes-previews/{hash1}/{hash2}/cover.jpeg
COVER_HASH_PATTERN = re.compile(
    r'/episodes-previews/(?P<hash1>[^/]+)/(?P<hash2>[^/]+)/cover\.jpeg'
)


# ── 适配器 ────────────────────────────────────────────────

class DramaShortsAdapter(PlatformAdapter):
    """DramaShorts 平台适配器"""

    platform_name = PLATFORM_NAME
    api_base_url = WEB_BASE

    def _setup(self) -> None:
        """初始化钩子"""
        # 不设置 Origin/Referer 到默认 headers，
        # 因为页面请求不需要这些（会导致 Cloudflare 返回缩水版 HTML）
        # 只在 API/CDN 请求时按需添加

    # ── 认证 ──────────────────────────────────────────────

    async def login(self, **credentials) -> bool:
        """Firebase 登录（仅 VIP 内容需要）"""
        id_token = credentials.get("id_token")
        if not id_token:
            logger.error("需要提供 id_token（浏览器 F12 → Network → API 请求 → Authorization header）")
            return False
        self.http.set_auth_token(id_token)
        self.auth.save_token(PLATFORM_NAME, {
            "access_token": id_token,
            "token_type": "firebase_id_token",
            "expires_at": float("inf"),
        })
        logger.info("Token 已保存")
        return True

    # ── URL 解析 ──────────────────────────────────────────

    async def parse_url(self, url: str) -> EpisodeInfo:
        """从 URL 解析 movieId 和 episode"""
        match = URL_PATTERN.search(url)
        if not match:
            raise ValueError(f"无法解析 DramaShorts URL: {url}")
        return EpisodeInfo(
            movie_id=match.group("movie_id"),
            episode_number=int(match.group("episode") or 1),
        )

    # ── 内部: 提取 __NEXT_DATA__ ──────────────────────────

    @staticmethod
    def _extract_next_data(html: str) -> dict:
        """从 HTML 中提取 __NEXT_DATA__ JSON"""
        match = NEXT_DATA_PATTERN.search(html)
        if not match:
            raise RuntimeError("页面中未找到 __NEXT_DATA__")
        return json.loads(match.group(1))

    @staticmethod
    def _extract_page_props(next_data: dict) -> dict:
        """从 __NEXT_DATA__ 提取 pageProps"""
        return next_data.get("props", {}).get("pageProps", {})

    # ── 从 coverUrl 构造 m3u8 URL ─────────────────────────

    @staticmethod
    def _cover_to_manifest(cover_url: str) -> str:
        """
        从封面图 URL 提取 hash 并构造 m3u8 地址

        coverUrl: .../episodes-previews/{hash1}/{hash2}/cover.jpeg
        m3u8:     https://cdn.dramashorts.io/video/{hash1}/{hash2}/manifest.m3u8
        """
        match = COVER_HASH_PATTERN.search(cover_url)
        if not match:
            raise RuntimeError(f"无法从 coverUrl 提取 hash: {cover_url}")
        return f"{CDN_VIDEO_BASE}/{match.group('hash1')}/{match.group('hash2')}/manifest.m3u8"

    # ── 获取页面数据 ──────────────────────────────────────

    async def _fetch_page_data(self, movie_id: str, episode: int = 1) -> dict:
        """获取页面 HTML 并提取 pageProps"""
        url = f"{WEB_BASE}/shorts/{movie_id}?episode={episode}"
        resp = await self.http.get(url)
        resp.raise_for_status()
        next_data = self._extract_next_data(resp.text)
        return self._extract_page_props(next_data)

    # ── 剧集列表 ──────────────────────────────────────────

    async def get_episode_list(self, movie_id: str) -> list[EpisodeInfo]:
        """
        获取剧集列表

        从页面 __NEXT_DATA__ 解析 episodes 数组，
        同时提取 coverUrl 用于后续构造 m3u8 地址。
        """
        try:
            page_props = await self._fetch_page_data(movie_id)
        except Exception as e:
            logger.error("获取页面数据失败: %s", e)
            return []

        episodes_raw = page_props.get("episodes", [])
        movie_title = (
            page_props.get("movieDetails", {})
            .get("movie", {})
            .get("title", "")
        )

        result = []
        for ep in episodes_raw:
            ep_data = ep.get("episode", {})
            info = EpisodeInfo(
                movie_id=movie_id,
                movie_title=movie_title,
                episode_number=ep_data.get("index", 0),
                duration=int(ep_data.get("duration", 0)),
            )
            # 存储 coverUrl 到 extra 字段，供 get_playback 使用
            info.cover_url = ep_data.get("coverUrl", "")
            result.append(info)

        logger.info("获取到 %d 集: %s", len(result), movie_title)
        return result

    # ── 播放凭证 ──────────────────────────────────────────

    async def get_playback(self, episode: EpisodeInfo) -> PlaybackInfo:
        """
        获取播放凭证

        免费内容: 从 __NEXT_DATA__ 的 episode.coverUrl 提取 hash，构造 m3u8 URL
        VIP 内容: 需要先登录，调用 web-episode-access API (TODO)
        """
        # ── 策略 1: 从 coverUrl 构造 m3u8（免费内容）──
        cover_url = getattr(episode, "cover_url", "")

        if not cover_url:
            # 如果 EpisodeInfo 没有 cover_url（比如直接 parse_url 来的），
            # 先获取页面数据找到对应 episode
            page_props = await self._fetch_page_data(
                episode.movie_id, episode.episode_number
            )
            episodes_raw = page_props.get("episodes", [])
            for ep in episodes_raw:
                ep_data = ep.get("episode", {})
                if ep_data.get("index") == episode.episode_number:
                    cover_url = ep_data.get("coverUrl", "")
                    break

        if cover_url:
            manifest_url = self._cover_to_manifest(cover_url)
            logger.info("m3u8: %s", manifest_url[:80])
            return PlaybackInfo(
                manifest_url=manifest_url,
                headers={
                    "Origin": WEB_BASE,
                    "Referer": f"{WEB_BASE}/shorts/{episode.movie_id}",
                },
            )

        # ── 策略 2: API 获取（VIP 内容）──
        raise RuntimeError(
            "无法获取播放地址。该内容可能需要 VIP 登录。\n"
            "请运行: zaizaimao login -p dramashorts -t <Firebase_token>"
        )
