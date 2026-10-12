"""Drama database API routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.database.drama_repo import (
    get_all_dramas, add_drama, update_drama, delete_drama,
    upsert_drama, compare_dramas, export_csv
)
from fastapi.responses import PlainTextResponse

router = APIRouter()


class DramaCreate(BaseModel):
    name: str
    source_platform: str = None
    data_source: str = "manual"
    play_count: int = None
    episode_count: int = None
    first_episode_url: str = None
    tags: str = None
    publish_date: str = None
    status: str = "unwatched"
    notes: str = None


class DramaUpdate(BaseModel):
    play_count: int = None
    episode_count: int = None
    first_episode_url: str = None
    tags: str = None
    publish_date: str = None
    source_platform: str = None
    status: str = None
    notes: str = None
    data_source: str = None


class CompareRequest(BaseModel):
    names: list[str]


@router.get("/drama")
async def list_dramas(page: int = 1, per_page: int = 50,
                      search: str = None, status: str = None,
                      platform: str = None, sort_by: str = "created_at"):
    return get_all_dramas(page=page, per_page=per_page, search=search,
                          status=status, platform=platform, sort_by=sort_by)


@router.post("/drama")
async def create_drama(req: DramaCreate):
    drama = add_drama(
        name=req.name,
        source_platform=req.source_platform,
        data_source=req.data_source,
        play_count=req.play_count,
        episode_count=req.episode_count,
        first_episode_url=req.first_episode_url,
        tags=req.tags,
        publish_date=req.publish_date,
        status=req.status,
        notes=req.notes,
    )
    return {"drama": drama}


@router.put("/drama/{name}")
async def edit_drama(name: str, req: DramaUpdate):
    drama = update_drama(name, **req.model_dump(exclude_none=True))
    if not drama:
        raise HTTPException(status_code=404, detail="Drama not found")
    return {"drama": drama}


@router.delete("/drama/{name}")
async def remove_drama(name: str):
    delete_drama(name)
    return {"success": True}


@router.post("/drama/compare")
async def compare(req: CompareRequest):
    results = compare_dramas(req.names)
    return {"results": results}


@router.get("/drama/export", response_class=PlainTextResponse)
async def export_dramas(status: str = None, platform: str = None):
    csv_content = export_csv(status=status, platform=platform)
    return csv_content
