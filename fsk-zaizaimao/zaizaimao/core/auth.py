"""
认证管理器 — 支持 Firebase Auth / OAuth / 自定义 Token
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("zaizaimao.auth")


class AuthManager:
    """
    统一的认证管理器

    支持:
    - Firebase Auth (Google / Email)
    - 自定义 Token (平台自建认证)
    - Token 持久化到本地文件
    """

    def __init__(self, cache_dir: Path | None = None):
        self._tokens: dict[str, dict[str, Any]] = {}
        self._cache_dir = cache_dir or Path.home() / ".zaizaimao"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Token 存储 ────────────────────────────────────────

    def save_token(self, platform: str, token_data: dict[str, Any]) -> None:
        """保存 token 到内存和本地缓存"""
        token_data["_saved_at"] = time.time()
        self._tokens[platform] = token_data
        self._persist(platform, token_data)
        logger.info("Token saved for %s", platform)

    def load_token(self, platform: str) -> dict[str, Any] | None:
        """从内存或本地缓存加载 token"""
        if platform in self._tokens:
            return self._tokens[platform]
        return self._load_from_disk(platform)

    def clear_token(self, platform: str) -> None:
        """清除 token"""
        self._tokens.pop(platform, None)
        cache_file = self._cache_dir / f"{platform}_token.json"
        cache_file.unlink(missing_ok=True)

    def is_token_valid(self, platform: str) -> bool:
        """检查 token 是否仍然有效"""
        token = self.load_token(platform)
        if not token:
            return False
        expires_at = token.get("expires_at", 0)
        return time.time() < expires_at - 60  # 预留 60 秒缓冲

    # ── 内部方法 ──────────────────────────────────────────

    def _persist(self, platform: str, token_data: dict[str, Any]) -> None:
        cache_file = self._cache_dir / f"{platform}_token.json"
        cache_file.write_text(json.dumps(token_data, indent=2), encoding="utf-8")

    def _load_from_disk(self, platform: str) -> dict[str, Any] | None:
        cache_file = self._cache_dir / f"{platform}_token.json"
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            self._tokens[platform] = data
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load token cache: %s", e)
            return None
