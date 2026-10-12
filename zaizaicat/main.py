"""zaizaicat FastAPI application entry point."""
from __future__ import annotations
import sys
import os
import webbrowser
import uvicorn
from pathlib import Path

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from fastapi.responses import RedirectResponse, HTMLResponse

from api.router import api_router, register_routes
from api.websocket_manager import get_ws_manager
from core.database.connection import init_db
from core.utils.logger import get_logger

logger = get_logger("main")

app = FastAPI(
    title="zaizaicat",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

static_dir = PROJECT_ROOT / "web" / "static"
templates_dir = PROJECT_ROOT / "web" / "templates"

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))

register_routes()
app.include_router(api_router)

# Navigation pages
PAGES = [
    "batch-download", "range-download", "download-center",
    "audio-tool", "homepage-extract", "episode-extract",
    "drama-db", "text-split", "history", "settings", "logs"
]

NAV_ITEMS = [
    ("batch-download", "batch_download", "📥", "批量下载"),
    ("range-download", "range_download", "📋", "范围下载"),
    ("download-center", "download_center", "⬇️", "下载中心"),
    ("audio-tool", "audio_tool", "🔊", "音频工具"),
    ("homepage-extract", "homepage_extract", "📊", "主页提取"),
    ("episode-extract", "episode_extract", "🔗", "剧集提取"),
    ("drama-db", "drama_db", "📚", "短剧库"),
    ("text-split", "text_split", "✂️", "文本分段"),
    ("history", "history", "📁", "下载历史"),
    ("settings", "settings", "⚙️", "设置"),
    ("logs", "logs", "📜", "日志"),
]

TEMPLATE_MAP = {slug: template for slug, template, _, _ in NAV_ITEMS}
NAV_ITEMS_FOR_TEMPLATE = [
    {"slug": slug, "label": label, "icon": icon}
    for slug, _, icon, label in NAV_ITEMS
]

PAGES_WITH_SIDEBAR = ["batch-download", "range-download"]


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("zaizaicat started")


@app.get("/")
async def root():
    return RedirectResponse(url="/batch-download")


@app.get("/{page}")
async def page(request: Request, page: str):
    if page not in PAGES:
        return RedirectResponse(url="/batch-download")
    template_name = TEMPLATE_MAP.get(page, "batch_download")
    template = jinja_env.get_template(f"{template_name}.html")
    return HTMLResponse(template.render(
        request=request,
        current_page=page,
        nav_items=NAV_ITEMS_FOR_TEMPLATE,
        show_sidebar_panels=page in PAGES_WITH_SIDEBAR,
    ))


@app.websocket("/ws/progress")
async def ws_progress(ws):
    mgr = get_ws_manager()
    await mgr.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except Exception:
        pass
    finally:
        mgr.disconnect(ws)


def main():
    host = os.environ.get("ZAICAT_HOST", "127.0.0.1")
    port = int(os.environ.get("ZAICAT_PORT", "8088"))
    logger.info(f"Starting zaizaicat on http://{host}:{port}")
    webbrowser.open(f"http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
