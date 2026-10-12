"""Main router aggregating all API routes."""
from fastapi import APIRouter

api_router = APIRouter(prefix="/api")

# Lazy imports to avoid circular deps; routes register themselves
def register_routes():
    from api.routes import download, history, audio, extract, drama, text, settings, logs, platform
    api_router.include_router(download.router, tags=["download"])
    api_router.include_router(history.router, tags=["history"])
    api_router.include_router(audio.router, tags=["audio"])
    api_router.include_router(extract.router, tags=["extract"])
    api_router.include_router(drama.router, tags=["drama"])
    api_router.include_router(text.router, tags=["text"])
    api_router.include_router(settings.router, tags=["settings"])
    api_router.include_router(logs.router, tags=["logs"])
    api_router.include_router(platform.router, tags=["platform"])
