"""Adaptive concurrency download scheduler."""
from __future__ import annotations
import asyncio
from core.utils.logger import get_logger

logger = get_logger("scheduler")

SERIAL_PLATFORMS = {"tiktok"}
MAX_CONCURRENT_HLS = 5


class DownloadScheduler:
    def __init__(self):
        self._sem_tiktok = asyncio.Semaphore(1)
        self._sem_hls = asyncio.Semaphore(MAX_CONCURRENT_HLS)
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    def get_semaphore(self, platform: str) -> asyncio.Semaphore:
        if platform in SERIAL_PLATFORMS:
            return self._sem_tiktok
        return self._sem_hls

    def create_cancel_event(self, task_id: str) -> asyncio.Event:
        event = asyncio.Event()
        self._cancel_events[task_id] = event
        return event

    def cancel_task(self, task_id: str):
        event = self._cancel_events.get(task_id)
        if event:
            event.set()

    def cleanup_task(self, task_id: str):
        self._cancel_events.pop(task_id, None)
        self._active_tasks.pop(task_id, None)

    def is_cancelled(self, task_id: str) -> bool:
        event = self._cancel_events.get(task_id)
        return event is not None and event.is_set()

    @staticmethod
    def retry_delay(attempt: int) -> float:
        """Exponential backoff: 5s -> 15s -> 30s."""
        delays = [5, 15, 30]
        return delays[min(attempt, len(delays) - 1)]


_scheduler: DownloadScheduler | None = None


def get_scheduler() -> DownloadScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = DownloadScheduler()
    return _scheduler
