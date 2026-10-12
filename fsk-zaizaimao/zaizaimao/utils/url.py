"""URL 解析工具"""

import re
from urllib.parse import urlparse, parse_qs


class URLParseError(ValueError):
    """URL 解析错误"""


def detect_platform(url: str) -> str:
    """
    根据 URL 自动检测平台

    Returns:
        平台名称: "dramashorts" / "shortmax" / "tiktok"
    """
    hostname = urlparse(url).hostname or ""

    platform_map = {
        "dramashorts.io": "dramashorts",
        "www.dramashorts.io": "dramashorts",
        "shorttv.live": "shortmax",
        "www.shorttv.live": "shortmax",
        "shortmax.com": "shortmax",
        "www.shortmax.com": "shortmax",
        "tiktok.com": "tiktok",
        "www.tiktok.com": "tiktok",
        "vm.tiktok.com": "tiktok",
        "m.tiktok.com": "tiktok",
    }

    for domain, platform in platform_map.items():
        if hostname == domain or hostname.endswith("." + domain):
            return platform

    raise URLParseError(
        f"未识别的平台 URL: {url}\n"
        f"支持的平台: dramashorts (dramashorts.io), shortmax (shorttv.live), tiktok (tiktok.com)"
    )


def extract_query_param(url: str, param: str) -> str | None:
    """提取 URL 查询参数"""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    values = params.get(param, [])
    return values[0] if values else None
