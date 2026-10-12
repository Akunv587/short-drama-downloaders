"""Download API routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.database.task_repo import create_task, get_task, get_all_tasks, delete_task, update_task_status
from core.task_manager import get_task_manager

router = APIRouter()


class DownloadRequest(BaseModel):
    url: str
    platform: str = ""
    drama_name: str = ""
    episode_range: str = ""
    episode_number: int = None
    output_dir: str = ""


@router.post("/download/start")
async def start_download(req: DownloadRequest):
    tm = get_task_manager()
    task_id = await tm.submit(
        url=req.url,
        platform=req.platform or None,
        drama_name=req.drama_name,
        episode_number=req.episode_number,
        episode_range=req.episode_range,
        output_dir=req.output_dir or "downloads",
    )
    task = get_task(task_id)
    return {"success": True, "task": task}


@router.get("/tasks")
async def list_tasks(status: str = None):
    tasks = get_all_tasks(status=status)
    return {"tasks": tasks}


@router.get("/tasks/{task_id}")
async def get_task_info(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task}


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: str):
    from core.utils.logger import get_task_logs
    logs = get_task_logs(task_id)
    return {"logs": logs}


@router.post("/download/cancel/{task_id}")
async def cancel_download(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    from core.scheduler import get_scheduler
    get_scheduler().cancel_task(task_id)
    update_task_status(task_id, "cancelled")
    return {"success": True}


@router.post("/download/pause/{task_id}")
async def pause_download(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    update_task_status(task_id, "paused")
    return {"success": True}


@router.post("/download/resume/{task_id}")
async def resume_download(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    update_task_status(task_id, "queued")
    tm = get_task_manager()
    await tm.submit(
        url=task["url"],
        platform=task.get("platform"),
        drama_name=task.get("drama_name", ""),
        episode_number=task.get("episode_number"),
        output_dir=task.get("output_path", "downloads"),
    )
    return {"success": True}


@router.post("/download/retry/{task_id}")
async def retry_download(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tm = get_task_manager()
    await tm.submit(
        url=task["url"],
        platform=task.get("platform"),
        drama_name=task.get("drama_name", ""),
        episode_number=task.get("episode_number"),
        output_dir=task.get("output_path", "downloads"),
    )
    return {"success": True}


@router.delete("/tasks/{task_id}")
async def remove_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    delete_task(task_id)
    return {"success": True}
