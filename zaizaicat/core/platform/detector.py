"""URL-based platform detection."""
from __future__ import annotations

PLATFORM_PATTERNS = {
    "tiktok": ["tiktok.com"],
    "shortmax": ["shorttv.live", "shortmax.com"],
    "dramashorts": ["dramashorts.io"],
}


def detect_platform(url: str) -> str | None:
    """Detect platform from URL. Returns platform key or None."""
    url_lower = url.lower().strip()
    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if pattern in url_lower:
                return platform
    return None


def get_adapter(platform: str):
    """Get adapter instance by platform key."""
    if platform == "tiktok":
        from .tiktok import TikTokAdapter
        return TikTokAdapter()
    elif platform == "shortmax":
        from .shortmax import ShortMaxAdapter
        return ShortMaxAdapter()
    elif platform == "dramashorts":
        from .dramashorts import DramaShortsAdapter
        return DramaShortsAdapter()
    return None
