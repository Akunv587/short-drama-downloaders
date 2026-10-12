"""WebSocket connection manager for real-time progress broadcasting."""
from __future__ import annotations
import asyncio
import json
from fastapi import WebSocket
from core.utils.logger import get_logger

logger = get_logger("ws")


class WebSocketManager:
    def __init__(self):
        self.connections: list[WebSocket] = []
        self._task_subscribers: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)
        logger.info(f"WebSocket connected (total: {len(self.connections)})")

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)
        for subs in self._task_subscribers.values():
            if ws in subs:
                subs.remove(ws)
        logger.info(f"WebSocket disconnected (total: {len(self.connections)})")

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_progress(self, task_id: str, status: str, progress: float = 0,
                            drama_name: str = "", message: str = ""):
        await self.broadcast({
            "type": "progress",
            "task_id": task_id,
            "status": status,
            "progress": progress,
            "drama_name": drama_name,
            "message": message,
        })

    async def send_log(self, task_id: str, level: str, msg: str):
        await self.broadcast({
            "type": "log",
            "task_id": task_id,
            "level": level,
            "message": msg,
        })


_ws_manager: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager:
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager
