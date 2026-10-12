"""Proxy detection and management."""
from __future__ import annotations
import asyncio
import socket


PROXY_PORTS = [
    (7890, "Clash"),
    (10808, "V2Ray"),
    (10809, "V2Ray HTTP"),
]


async def check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def detect_proxy() -> str | None:
    for port, _ in PROXY_PORTS:
        if await check_port("127.0.0.1", port):
            return f"http://127.0.0.1:{port}"
    return None


async def get_proxy_status() -> dict:
    results = {}
    for port, label in PROXY_PORTS:
        ok = await check_port("127.0.0.1", port)
        results[label] = {"port": port, "available": ok}
    proxy_url = await detect_proxy()
    return {
        "proxy_url": proxy_url,
        "ports": results,
    }
