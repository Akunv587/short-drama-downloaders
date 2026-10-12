"""Download history API routes."""
from fastapi import APIRouter, HTTPException
from core.database.history_repo import get_history, delete_history

router = APIRouter()


@router.get("/history")
async def list_history(page: int = 1, per_page: int = 20, search: str = None):
    return get_history(page=page, per_page=per_page, search=search)


@router.delete("/history/{history_id}")
async def remove_history(history_id: int):
    delete_history(history_id)
    return {"success": True}
