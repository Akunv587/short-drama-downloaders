"""
ShortMax 平台适配器 (shorttv.live / shortmax.com)

技术栈:
- 前端:    Nuxt (Vue.js, SSR + CSR)
- 播放器:  xgplayer
- 视频格式: HLS (.m3u8 via Akamai CDN)
- 内容类型: 前6集免费 / 后续 VIP
- CDN:     akamai-static.shorttv.live/hls-encrypted/...

Nuxt 数据序列化格式:
- __NUXT_DATA__ 是一个 JSON 数组
- 字典中的整数类型值代表指向数组索引的引用
- 需要逐层 resolve 引用才能获取实际值

下载策略:
- 免费内容: 解析 __NUXT_DATA__ → resolve 索引 → 提取 m3u8
- VIP 内容: 需要登录 → API 获取播放凭证 (TODO)
"""

import json
import logging
import re
from typing import Any

from zaizaimao.platforms.base import PlatformAdapter, EpisodeInfo, PlaybackInfo

logger = logging.getLogger("zaizaimao.shortmax")

# ── 常量 ──────────────────────────────────────────────────

PLATFORM_NAME = "shortmax"
WEB_BASE = "https://www.shorttv.live"

# URL 解析正则: /episode/{slug}-{shortPlayId}-{episodeNum}
# slug 可能包含多个连字符，如 "wolfless-bow-to-the-queen"
URL_PATTERN = re.compile(
    r"shorttv\.live/episode/(?P<slug>.+)-(?P<movie_id>\d+)-(?P<episode>\d+)$"
)
URL_PATTERN_ALT = re.compile(
    r"shortmax\.com/episode/(?P<slug>.+)-(?P<movie_id>\d+)-(?P<episode>\d+)$"
)

# 从 __NUXT_DATA__ 提取数据
NUXT_DATA_PATTERN = re.compile(
    r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# 快速提取 m3u8 URL 的正则（备用方案）
M3U8_PATTERN = re.compile(
    r'https://akamai-static\.shorttv\.live/hls-encrypted/[^"\\]+\.m3u8'
)


# ── Nuxt 数据解析器 ─────────────────────────────────────

class NuxtDataResolver:
    """
    Nuxt __NUXT_DATA__ 解析器

    Nuxt 使用索引引用格式:
    - 字典中的整数值可能是指向数组索引的引用
    - 需要递归 resolve 才能获取真实值
    """

    def __init__(self, data: list):
        self._data = data
        self._cache: dict[int, Any] = {}
        self._resolving: set[int] = set()  # 防止循环引用

    def resolve(self, idx: int, max_depth: int = 20) -> Any:
        """解析索引 idx 处的值"""
        if idx in self._cache:
            return self._cache[idx]

        if idx in self._resolving:
            return None  # 循环引用
        self._resolving.add(idx)

        try:
            value = self._data[idx] if idx < len(self._data) else None
            result = self._resolve_value(value, max_depth - 1)
            self._cache[idx] = result
            return result
        finally:
            self._resolving.discard(idx)

    def _resolve_value(self, value: Any, depth: int) -> Any:
        """递归解析值"""
        if depth <= 0:
            return value

        if isinstance(value, dict):
            return {k: self._resolve_entry(v, depth) for k, v in value.items()}

        if isinstance(value, list):
            # Nuxt 特殊标记如 ["ShallowReactive", N]
            if (len(value) == 2 and isinstance(value[0], str)
                    and value[0] in ("ShallowReactive", "Reactive", "Set")):
                return value  # 保留标记不做解析
            return [self._resolve_entry(v, depth) for v in value]

        return value

    def _resolve_entry(self, value: Any, depth: int) -> Any:
        """解析单个条目：如果是整数则视为索引引用"""
        if isinstance(value, int) and 0 <= value < len(self._data):
            return self.resolve(value, depth)
        return self._resolve_value(value, depth)

    def find_shortplay_data(self) -> dict | None:
        """
        在 Nuxt 数据中定位 shortPlay 数据

        Nuxt 数据结构:
        [meta1, state1, meta2, state2, payload, response, code, shortplay_obj, ...]
        """
        for i, item in enumerate(self._data):
            if isinstance(item, dict) and "shortPlayId" in item:
                resolved = self._resolve_value(item, 20)
                return resolved
        return None


# ── 适配器 ────────────────────────────────────────────────

class ShortMaxAdapter(PlatformAdapter):
    """ShortMax 平台适配器"""

    platform_name = PLATFORM_NAME
    api_base_url = WEB_BASE

    def __init__(self, **kwargs):
        self._proxy_url: str | None = None
        super().__init__(**kwargs)

    def _setup(self) -> None:
        """初始化钩子: 尝试自动检测代理"""
        self._ensure_proxy()

    @staticmethod
    def _detect_proxy_sync() -> str | None:
        """同步检测本地代理端口"""
        import socket
        candidates = [
            ("127.0.0.1", 10808, "V2Ray"),
            ("127.0.0.1", 10809, "V2Ray HTTP"),
            ("127.0.0.1", 7890, "Clash"),
            ("127.0.0.1", 1080, "SOCKS5"),
            ("127.0.0.1", 7891, "Clash 备用"),
        ]
        for host, port, label in candidates:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                result = s.connect_ex((host, port))
                s.close()
                if result == 0:
                    logger.info("检测到 %s 代理: %s:%d", label, host, port)
                    return f"http://{host}:{port}"
            except Exception:
                continue
        return None

    def _ensure_proxy(self) -> None:
        """确保 HTTP 客户端配置了代理（ShortMax 需要代理访问）"""
        proxy_url = self._detect_proxy_sync()
        if not proxy_url:
            return

        # 重建 HTTPClient 并注入代理（禁用 HTTP/2，代理不支持）
        from zaizaimao.core.client import HTTPClient
        self.http = HTTPClient(proxy=proxy_url, http2=False)
        self._proxy_url = proxy_url
        logger.info("ShortMax 已启用代理: %s (HTTP/1.1)", proxy_url)

    # ── 认证 ──────────────────────────────────────────────

    async def login(self, **credentials) -> bool:
        """登录（VIP 内容需要）"""
        token = credentials.get("token") or credentials.get("id_token")
        if not token:
            logger.error("需要提供认证 token")
            return False
        self.http.set_auth_token(token)
        self.auth.save_token(PLATFORM_NAME, {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": float("inf"),
        })
        logger.info("Token 已保存")
        return True

    # ── URL 解析 ──────────────────────────────────────────

    async def parse_url(self, url: str) -> EpisodeInfo:
        """从 URL 解析 shortPlayId 和 episode"""
        for pattern in [URL_PATTERN, URL_PATTERN_ALT]:
            match = pattern.search(url)
            if match:
                return EpisodeInfo(
                    movie_id=match.group("movie_id"),
                    episode_number=int(match.group("episode") or 1),
                )
        raise ValueError(f"无法解析 ShortMax URL: {url}")

    # ── 内部: 获取和解析 Nuxt 数据 ─────────────────────────

    async def _get_nuxt_resolver(self, movie_id: str,
                                  episode: int = 1) -> NuxtDataResolver:
        """获取页面并返回 NuxtDataResolver"""
        url = f"{WEB_BASE}/episode/short-{movie_id}-{episode}"
        resp = await self.http.get(url)
        resp.raise_for_status()

        match = NUXT_DATA_PATTERN.search(resp.text)
        if not match:
            raise RuntimeError("页面中未找到 __NUXT_DATA__")

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"__NUXT_DATA__ JSON 解析失败: {e}")

        return NuxtDataResolver(data)

    # ── 剧集列表 ──────────────────────────────────────────

    async def get_episode_list(self, movie_id: str) -> list[EpisodeInfo]:
        """
        获取剧集列表

        从 __NUXT_DATA__ 解析 episodes，前6集免费。
        """
        try:
            resolver = await self._get_nuxt_resolver(movie_id)
        except Exception as e:
            logger.error("获取页面数据失败: %s", e)
            return []

        sp_data = resolver.find_shortplay_data()
        if not sp_data:
            logger.error("未找到 shortPlay 数据")
            return []

        movie_title = sp_data.get("shortPlayName", "")
        episode_list_refs = sp_data.get("episodeList", [])

        result = []
        for ep_obj in episode_list_refs:
            if not isinstance(ep_obj, dict):
                continue
            ep_num = ep_obj.get("episodeNum", 0)
            enc_url = ep_obj.get("encryptedVideoUrl", "")

            info = EpisodeInfo(
                movie_id=movie_id,
                movie_title=movie_title,
                episode_number=int(ep_num) if ep_num else 0,
                episode_title=f"第 {ep_num} 集",
            )
            # 存储 encryptedVideoUrl 到 cover_url（复用字段）
            info.cover_url = enc_url if enc_url else ""
            result.append(info)

        logger.info("解析到 %d 集", len(result))
        return result

    # ── 播放凭证 ──────────────────────────────────────────

    async def get_playback(self, episode: EpisodeInfo) -> PlaybackInfo:
        """
        获取播放凭证

        免费内容: 从 __NUXT_DATA__ 解析 m3u8
        VIP 内容: TODO
        """
        # ── 策略 1: 从 Nuxt 数据获取 ──
        enc_url = getattr(episode, "cover_url", "")

        if not enc_url:
            # 需要从页面获取数据
            try:
                resolver = await self._get_nuxt_resolver(
                    episode.movie_id, episode.episode_number
                )
                sp_data = resolver.find_shortplay_data()
                if sp_data:
                    ep_list = sp_data.get("episodeList", [])
                    for ep_obj in ep_list:
                        if isinstance(ep_obj, dict) and \
                           ep_obj.get("episodeNum") == episode.episode_number:
                            enc_url = ep_obj.get("encryptedVideoUrl", "")
                            break
            except Exception as e:
                logger.error("获取页面数据失败: %s", e)

        if enc_url:
            manifest_url = self._resolve_manifest(enc_url)
            if manifest_url:
                logger.info("m3u8: %s", manifest_url[:80])
                return PlaybackInfo(
                    manifest_url=manifest_url,
                    headers={
                        "Origin": WEB_BASE,
                        "Referer": WEB_BASE,
                    },
                )

        # ── 策略 2: 直接搜索 m3u8 URL ──
        raise RuntimeError(
            "无法获取播放地址。该集可能需要 VIP 登录。\n"
            "ShortMax 前 6 集通常免费，请尝试更小的集数。"
        )

    @staticmethod
    def _resolve_manifest(enc_url: str) -> str | None:
        """
        解析 encryptedVideoUrl 获取最佳 m3u8 地址

        enc_url 可能是:
        1. JSON 字符串: {"video_720": "...", "video_1080": "...", "video_480": "..."}
        2. 直接的 m3u8 URL
        3. 空字符串 / None
        """
        if not enc_url or not isinstance(enc_url, str):
            return None
        if enc_url in ('""', '""', ''):
            return None

        # 尝试 JSON 解析
        if enc_url.startswith('{'):
            try:
                data = json.loads(enc_url)
            except json.JSONDecodeError:
                logger.warning("无法解析 encryptedVideoUrl: %s", enc_url[:100])
                return None

            for quality in ["video_1080", "video_720", "video_480"]:
                if quality in data and data[quality]:
                    return data[quality]
            return None

        # 直接的 m3u8 URL
        if enc_url.startswith("http") and ".m3u8" in enc_url:
            return enc_url

        return None
