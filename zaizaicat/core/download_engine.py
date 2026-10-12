"""Unified download engine — platform detection + dispatch."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from core.platform.detector import detect_platform, get_adapter
from core.platform.base import ProgressInfo, EpisodeInfo
from core.database.task_repo import update_task_status, update_task_progress, set_task_output
from api.websocket_manager import get_ws_manager
from core.utils.logger import get_logger, get_task_logger, attach_task_log_handler

logger = get_logger("engine")


@dataclass
class DownloadResult:
    """Result of a download operation (used by HLS engine)."""
    success: bool = False
    file_path: str = ""
    file_size: int = 0
    duration: float = 0
    avg_speed: float = 0
    error: str = ""
    retry_count: int = 0


async def execute_download(task: dict) -> bool:
    """Execute a single download task. Returns True on success."""
    task_id = task["id"]
    url = task["url"]
    platform_key = task.get("platform") or detect_platform(url)
    if not platform_key:
        update_task_status(task_id, "failed", error_message="Unknown platform")
        return False

    adapter = get_adapter(platform_key)
    if not adapter:
        update_task_status(task_id, "failed", error_message=f"No adapter for {platform_key}")
        return False

    output_dir = Path(task.get("output_path") or "downloads")
    output_dir.mkdir(parents=True, exist_ok=True)

    update_task_status(task_id, "running")
    ws = get_ws_manager()
    task_logger = get_task_logger(task_id)
    attach_task_log_handler(task_id, task_logger)

    async def progress_callback(info: ProgressInfo):
        info.task_id = task_id
        info.drama_name = task.get("drama_name", "")
        info.episode_number = task.get("episode_number")
        if info.status == "completed":
            update_task_progress(task_id, info.progress)
        await ws.send_progress(task_id, info.status, info.progress,
                               info.drama_name, info.message)

    try:
        result = await adapter.download_episode(
            url=url,
            output_dir=output_dir,
            episode_number=task.get("episode_number"),
            progress_callback=progress_callback,
        )
        if result:
            set_task_output(task_id, str(result))
            update_task_status(task_id, "completed")
            return True
        else:
            update_task_status(task_id, "failed", error_message="Download returned no output")
            return False
    except asyncio.CancelledError:
        update_task_status(task_id, "cancelled")
        return False
    except Exception as e:
        update_task_status(task_id, "failed", error_message=str(e))
        task_logger.error(f"Download failed: {e}")
        return False
