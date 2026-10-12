"""Text split API routes."""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class TextSplitRequest(BaseModel):
    text: str
    lines_per_segment: int = 30


@router.post("/text/split")
async def split_text(req: TextSplitRequest):
    lines = req.text.strip().split("\n")
    total_lines = len(lines)
    segments = []
    for i in range(0, total_lines, req.lines_per_segment):
        chunk = lines[i:i + req.lines_per_segment]
        segments.append({
            "index": len(segments) + 1,
            "lines": len(chunk),
            "content": "\n".join(chunk),
        })
    return {
        "total_lines": total_lines,
        "segment_count": len(segments),
        "segments": segments,
    }
