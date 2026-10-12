"""Settings API routes."""
from fastapi import APIRouter
from pydantic import BaseModel
from core.database.settings_repo import get_all_settings, set_setting

router = APIRouter()


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


@router.get("/settings")
async def get_settings():
    return {"settings": get_all_settings()}


@router.put("/settings")
async def update_settings(req: SettingsUpdate):
    for key, value in req.settings.items():
        set_setting(key, str(value))
    return {"settings": get_all_settings()}
