"""
HTTP 客户端 — 带反检测的异步 HTTP/2 请求封装
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger("zaizaimao.client")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    # 注意: 不设置 Accept-Encoding，交给 httpx 自动处理
    # 手动设置会导致 Cloudflare 返回缩水版 HTML
    "Sec-Ch-Ua": '"Not/A)Brand";v="99", "Google Chrome";v="126", "Chromium";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


class HTTPClient:
    """异步 HTTP 客户端，自动管理 Cookie 和 Headers"""

    def __init__(
        self,
        base_headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        proxy: str | None = None,
        http2: bool = True,
    ):
        headers = {**DEFAULT_HEADERS, **(base_headers or {})}
        self._client = httpx.AsyncClient(
            http2=http2,
            timeout=httpx.Timeout(timeout),
            headers=headers,
            follow_redirects=True,
            cookies=httpx.Cookies(),
            proxy=proxy,
        )

    # ── 请求方法 ──────────────────────────────────────────

    async def get(self, url: str, **kwargs) -> httpx.Response:
        logger.debug("GET %s", url)
        return await self._client.get(url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        logger.debug("POST %s", url)
        return await self._client.post(url, **kwargs)

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        logger.debug("%s %s", method.upper(), url)
        return await self._client.request(method, url, **kwargs)

    # ── 便捷方法 ──────────────────────────────────────────

    async def get_json(self, url: str, **kwargs) -> dict[str, Any]:
        resp = await self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def post_json(
        self, url: str, json_data: dict[str, Any] | None = None, **kwargs
    ) -> dict[str, Any]:
        resp = await self.post(url, json=json_data, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # ── Cookie / Session ──────────────────────────────────

    def set_cookie(self, name: str, value: str, domain: str = "") -> None:
        self._client.cookies.set(name, value, domain=domain)

    def set_header(self, name: str, value: str) -> None:
        self._client.headers[name] = value

    def set_auth_token(self, token: str, scheme: str = "Bearer") -> None:
        self._client.headers["Authorization"] = f"{scheme} {token}"

    # ── 生命周期 ──────────────────────────────────────────

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "HTTPClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
