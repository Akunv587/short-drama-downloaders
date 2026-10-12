"""Log viewing API routes."""
from fastapi import APIRouter
from pathlib import Path
from config import LOGS_DIR

router = APIRouter()


@router.get("/logs")
async def list_logs():
    files = sorted(
        LOGS_DIR.glob("zaizaicat_*.log"),
        key=lambda f: f.name,
        reverse=True
    )
    return {
        "files": [{"name": f.name, "size": f.stat().st_size,
                    "date": f.stem.replace("zaizaicat_", "")}
                   for f in files[:30]]
    }


@router.get("/logs/{filename}")
async def get_log_content(filename: str, lines: int = 200):
    filepath = LOGS_DIR / filename
    if not filepath.exists() or ".." in filename:
        return {"content": "", "error": "File not found"}
    content = filepath.read_text(encoding="utf-8", errors="replace")
    all_lines = content.strip().split("\n")
    recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
    return {"content": "\n".join(recent), "total_lines": len(all_lines)}
