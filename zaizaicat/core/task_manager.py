"""Task lifecycle manager."""
from __future__ import annotations
import asyncio
import uuid
from core.database.task_repo import create_task, update_task_status, get_task
from core.download_engine import execute_download
from core.scheduler import get_scheduler
from core.utils.logger import get_logger

logger = get_logger("task_mgr")


class TaskManager:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    async def start(self):
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self):
        if self._worker_task:
            self._worker_task.cancel()
            self._worker_task = None

    async def submit(self, url: str, platform: str = None,
                     drama_name: str = "", episode_number: int = None,
                     episode_range: str = "", output_dir: str = "") -> str:
        task_id = uuid.uuid4().hex[:8]
        create_task(task_id=task_id, url=url, platform=platform or "unknown",
                    drama_name=drama_name, episode_number=episode_number,
                    episode_range=episode_range, total_episodes=1)
        await self._queue.put(task_id)
        await self.start()
        return task_id

    async def _worker(self):
        scheduler = get_scheduler()
        while True:
            try:
                task_id = await self._queue.get()
                task = get_task(task_id)
                if not task:
                    continue
                sem = scheduler.get_semaphore(task.get("platform", "unknown"))
                async with sem:
                    if scheduler.is_cancelled(task_id):
                        continue
                    await execute_download(task)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")


_task_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
