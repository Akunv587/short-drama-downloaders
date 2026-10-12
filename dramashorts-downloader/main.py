"""
DramaShorts Downloader-fsk
Lightweight batch video downloader for dramashorts.io
"""
import asyncio
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse


# ============================================================
# Constants
# ============================================================

WEB_BASE = "https://dramashorts.io"
CDN_VIDEO_BASE = "https://cdn.dramashorts.io/video"
DEFAULT_PORT = 18888
DEFAULT_OUTPUT_DIR = "./downloads"
MAX_CONCURRENT = 3
MAX_RETRIES = 3
LOUDNORM_TARGET = -16.0  # Streaming standard (louder than broadcast -23)

URL_PATTERN = re.compile(
    r"dramashorts\.io/shorts/(?P<movie_id>[a-f0-9-]+)"
    r"(?:\?episode=(?P<episode>\d+))?"
)

NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>'
)

COVER_HASH_PATTERN = re.compile(
    r'/episodes-previews/(?P<h1>[^/]+)/(?P<h2>[^/]+)/cover\.jpeg'
)

EXTINF_PATTERN = re.compile(r"#EXTINF:([\d.]+),")

# ============================================================
# FastAPI App
# ============================================================

app = FastAPI(title="DramaShorts Downloader-fsk")

BASE_DIR = Path(__file__).resolve().parent
INDEX_HTML = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")

# ============================================================
# Global State
# ============================================================

progress_queues: list[asyncio.Queue] = []
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# task_id -> {ep_num, title, status, progress, error}
tasks_state: dict[str, dict] = {}


# ============================================================
# Helper: DramaShorts Page Parsing
# ============================================================

def parse_dramashorts_url(url: str) -> tuple[Optional[str], Optional[int]]:
    """Parse a DramaShorts URL. Returns (movie_id, episode_number)."""
    m = URL_PATTERN.search(url)
    if not m:
        return None, None
    return m.group("movie_id"), (
        int(m.group("episode")) if m.group("episode") else None
    )


def extract_hashes_from_cover(cover_url: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (movie_hash, episode_hash) from a cover URL."""
    m = COVER_HASH_PATTERN.search(cover_url)
    if not m:
        return None, None
    return m.group("h1"), m.group("h2")


def build_m3u8_url(h1: str, h2: str) -> str:
    """Build CDN m3u8 URL."""
    return f"{CDN_VIDEO_BASE}/{h1}/{h2}/manifest.m3u8"


async def fetch_html(url: str) -> str:
    """Fetch HTML page content."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        return resp.text


async def fetch_text(url: str) -> str:
    """Fetch text content (for m3u8)."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        return resp.text


def parse_next_data(html: str) -> Optional[dict]:
    """Extract __NEXT_DATA__ JSON from page HTML."""
    m = NEXT_DATA_PATTERN.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def get_m3u8_duration_from_text(text: str) -> float:
    """Sum #EXTINF durations in an m3u8 playlist."""
    total = 0.0
    for m in EXTINF_PATTERN.finditer(text):
        total += float(m.group(1))
    return total


# ============================================================
# SSE Broadcasting
# ============================================================

async def broadcast(data: dict):
    """Push progress data to all connected SSE clients."""
    dead = []
    for q in progress_queues:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            progress_queues.remove(q)
        except ValueError:
            pass


# ============================================================
# ffmpeg Runner with Progress Parsing
# ============================================================

async def run_ffmpeg_with_progress(
    cmd: list[str],
    task_id: str,
    total_duration: float = 0.0,
    phase: str = "downloading",
    ep_num: int = 0,
    title: str = "",
    output_path: str = "",
) -> tuple[bool, str]:
    """Run ffmpeg, parse progress from stdout, broadcast via SSE.

    Returns (success: bool, stderr_output: str).
    Success is determined by output file existence, not ffmpeg return code
    (ffmpeg may return non-zero for harmless NAL warnings).
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    current_time = 0.0
    stderr_parts: list[str] = []

    async def _read_stdout():
        nonlocal current_time
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode(errors="replace").strip()
            if decoded.startswith("out_time_ms="):
                try:
                    ms = int(decoded.split("=", 1)[1])
                    current_time = ms / 1_000_000.0
                except ValueError:
                    pass
            elif decoded.startswith("out_time="):
                try:
                    ts = decoded.split("=", 1)[1]
                    h, m, s = ts.split(":")
                    current_time = int(h) * 3600 + int(m) * 60 + float(s)
                except (ValueError, IndexError):
                    pass

    async def _read_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_parts.append(line.decode(errors="replace"))

    stdout_task = asyncio.create_task(_read_stdout())
    stderr_task = asyncio.create_task(_read_stderr())

    last_pct = -1
    last_broadcast_time = time.time()

    while not stdout_task.done():
        await asyncio.sleep(0.3)
        pct = 0.0
        if total_duration > 0:
            pct = min(current_time / total_duration * 100, 99.9)

        now = time.time()
        if abs(pct - last_pct) >= 0.5 or (now - last_broadcast_time) > 1.0:
            await broadcast({
                "task_id": task_id,
                "type": "progress",
                "phase": phase,
                "ep_num": ep_num,
                "title": title,
                "time": round(current_time, 1),
                "total": round(total_duration, 1),
                "percent": round(pct, 1),
            })
            last_pct = pct
            last_broadcast_time = now

    await proc.wait()
    await stderr_task
    stderr_text = "".join(stderr_parts[-20:])  # Last 20 lines for error messages

    # Check output file rather than trusting ffmpeg return code
    # (ffmpeg often returns 1 for harmless NAL/codec warnings)
    success = bool(output_path and os.path.exists(output_path) and os.path.getsize(output_path) > 0)
    return success, stderr_text


# ============================================================
# HLS Download
# ============================================================

async def download_hls(
    m3u8_url: str,
    output_path: str,
    referer: str,
    task_id: str,
    ep_num: int,
    title: str,
    total_duration: float = 0.0,
) -> tuple[bool, str]:
    """Download HLS stream via ffmpeg. Returns (success, error_message)."""
    cmd = [
        "ffmpeg", "-y",
        "-progress", "pipe:1",
        "-loglevel", "error",
        "-headers",
        f"Origin: {WEB_BASE}\r\nReferer: {referer}\r\n",
        "-i", m3u8_url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        output_path,
    ]

    success, stderr = await run_ffmpeg_with_progress(
        cmd, task_id, total_duration,
        phase="downloading", ep_num=ep_num, title=title,
        output_path=output_path,
    )

    return success, stderr


# ============================================================
# LoudNorm (EBU R128 Audio Normalization)
# ============================================================

async def run_loudnorm(file_path: str, task_id: str, ep_num: int, title: str) -> bool:
    """Two-pass EBU R128 loudness normalization."""
    if not os.path.exists(file_path):
        return False

    # Pass 1: Analyze
    await broadcast({
        "task_id": task_id, "type": "progress",
        "phase": "loudnorm_analyze", "ep_num": ep_num,
        "title": title, "percent": 0, "message": "Analyzing loudness..."
    })

    cmd_analyze = [
        "ffmpeg", "-i", file_path,
        "-af", f"loudnorm=I={LOUDNORM_TARGET}:LRA=7:TP=-2:print_format=json",
        "-f", "null", "-",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd_analyze,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    stderr_text = stderr.decode(errors="replace")

    if proc.returncode != 0:
        return False

    # Parse loudnorm JSON from stderr
    analysis = None
    try:
        start = stderr_text.find("{")
        end = stderr_text.rfind("}") + 1
        if start >= 0 and end > start:
            analysis = json.loads(stderr_text[start:end])
    except json.JSONDecodeError:
        pass

    if not analysis:
        return False

    measured_i = float(analysis.get("input_i", -23.0))
    measured_tp = float(analysis.get("input_tp", -2.0))
    measured_lra = float(analysis.get("input_lra", 0.0))
    measured_thresh = float(analysis.get("input_thresh", -33.0))

    # Pass 2: Apply
    await broadcast({
        "task_id": task_id, "type": "progress",
        "phase": "loudnorm_apply", "ep_num": ep_num,
        "title": title, "percent": 50, "message": "Applying loudness normalization..."
    })

    filter_str = (
        f"loudnorm=I={LOUDNORM_TARGET}:LRA=7:TP=-2"
        f":measured_I={measured_i:.2f}"
        f":measured_TP={measured_tp:.2f}"
        f":measured_LRA={measured_lra:.2f}"
        f":measured_thresh={measured_thresh:.2f}"
        f":linear=true:print_format=summary"
    )

    temp_path = file_path + ".norm.tmp.mp4"

    # Try stream copy first
    cmd_apply = [
        "ffmpeg", "-y", "-progress", "pipe:1", "-loglevel", "error",
        "-i", file_path, "-af", filter_str,
        "-c:v", "copy", temp_path,
    ]
    ok, _ = await run_ffmpeg_with_progress(
        cmd_apply, task_id, 0, phase="loudnorm_apply",
        ep_num=ep_num, title=title, output_path=temp_path,
    )

    if not (ok and os.path.exists(temp_path)):
        # Fallback: re-encode
        cmd_fallback = [
            "ffmpeg", "-y", "-progress", "pipe:1", "-loglevel", "error",
            "-i", file_path, "-af", filter_str,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            temp_path,
        ]
        ok, _ = await run_ffmpeg_with_progress(
            cmd_fallback, task_id, 0, phase="loudnorm_apply",
            ep_num=ep_num, title=title, output_path=temp_path,
        )

    if ok and os.path.exists(temp_path):
        # Replace original
        try:
            os.remove(file_path)
        except OSError:
            pass
        try:
            os.rename(temp_path, file_path)
        except OSError:
            pass
        return True

    # Cleanup
    try:
        os.remove(temp_path)
    except OSError:
        pass
    return False


# ============================================================
# Single Episode Download Task
# ============================================================

async def download_single(
    ep_info: dict,
    output_dir: str,
    do_loudnorm: bool,
    movie_title: str,
):
    """Download a single episode with retries."""
    task_id = ep_info["task_id"]
    ep_num = ep_info["number"]
    cover_url = ep_info.get("cover_url", "")
    url = ep_info.get("url", "")
    title = ep_info.get("title", f"EP{ep_num:02d}")
    duration = ep_info.get("duration", 0.0)

    tasks_state[task_id] = {
        "ep_num": ep_num, "title": title,
        "status": "pending", "progress": 0,
    }

    # Parse URL for movie_id and referer
    movie_id, _ = parse_dramashorts_url(url)
    if not movie_id:
        tasks_state[task_id]["status"] = "failed"
        tasks_state[task_id]["error"] = "Cannot parse URL"
        await broadcast({"task_id": task_id, "type": "status", "status": "failed",
                         "ep_num": ep_num, "title": title, "error": "Cannot parse URL"})
        return

    # Build m3u8 URL from cover URL
    h1, h2 = extract_hashes_from_cover(cover_url)
    if not h1 or not h2:
        # Try fetching page to get cover_url
        try:
            page_url = f"{WEB_BASE}/shorts/{movie_id}?episode={ep_num}"
            html = await fetch_html(page_url)
            nd = parse_next_data(html)
            if nd:
                eps = nd.get("props", {}).get("pageProps", {}).get("episodes", [])
                for ep in eps:
                    ed = ep.get("episode", {})
                    if ed.get("index") == ep_num:
                        cover_url = ed.get("coverUrl", "")
                        h1, h2 = extract_hashes_from_cover(cover_url)
                        break
        except Exception:
            pass

    if not h1 or not h2:
        tasks_state[task_id]["status"] = "failed"
        tasks_state[task_id]["error"] = "Cannot extract video hash from cover URL"
        await broadcast({"task_id": task_id, "type": "status", "status": "failed",
                         "ep_num": ep_num, "title": title,
                         "error": "Cannot extract video hash"})
        return

    m3u8_url = build_m3u8_url(h1, h2)

    # Safe filename
    safe_title = re.sub(r'[<>:"/\\|?*]', '_', movie_title or "drama")[:50]
    fname = f"{safe_title}_E{ep_num:02d}.mp4"
    output_path = os.path.join(output_dir, fname)

    referer = f"{WEB_BASE}/shorts/{movie_id}"

    # Retry loop
    last_error = ""
    for attempt in range(MAX_RETRIES):
        tasks_state[task_id]["status"] = "downloading"
        tasks_state[task_id]["attempt"] = attempt + 1
        await broadcast({
            "task_id": task_id, "type": "status", "status": "downloading",
            "ep_num": ep_num, "title": title,
            "attempt": attempt + 1,
        })

        ok, err = await download_hls(
            m3u8_url, output_path, referer,
            task_id, ep_num, title, duration,
        )

        if ok:
            # Optional loudnorm
            if do_loudnorm:
                await broadcast({
                    "task_id": task_id, "type": "status",
                    "status": "loudnorm", "ep_num": ep_num, "title": title,
                })
                norm_ok = await run_loudnorm(output_path, task_id, ep_num, title)
                if not norm_ok:
                    # Loudnorm failed but download succeeded; still report success
                    pass

            tasks_state[task_id]["status"] = "completed"
            tasks_state[task_id]["progress"] = 100
            file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            await broadcast({
                "task_id": task_id, "type": "status", "status": "completed",
                "ep_num": ep_num, "title": title,
                "file_size": file_size,
            })
            return

        last_error = err
        if attempt < MAX_RETRIES - 1:
            delay = 2 ** attempt
            await broadcast({
                "task_id": task_id, "type": "status", "status": "retrying",
                "ep_num": ep_num, "title": title,
                "attempt": attempt + 1, "delay": delay,
            })
            await asyncio.sleep(delay)

    tasks_state[task_id]["status"] = "failed"
    tasks_state[task_id]["error"] = last_error[:200]
    await broadcast({
        "task_id": task_id, "type": "status", "status": "failed",
        "ep_num": ep_num, "title": title,
        "error": last_error[:200],
    })


# ============================================================
# Routes
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)


@app.post("/api/extract")
async def api_extract(request: Request):
    """Extract episodes from one or more DramaShorts URLs."""
    body = await request.json()
    urls: list[str] = body.get("urls", [])

    if not urls:
        return JSONResponse({"error": "No URLs provided"}, status_code=400)

    # Group by movie_id, deduplicate
    movie_map: dict[str, dict] = {}  # movie_id -> {title, cover_url, episodes}
    standalone_eps: list[dict] = []

    for url in urls:
        url = url.strip()
        if not url:
            continue
        mid, ep = parse_dramashorts_url(url)
        if not mid:
            continue
        if mid not in movie_map:
            movie_map[mid] = {"url": url, "ep_num": ep}

    if not movie_map:
        return JSONResponse({"error": "No valid DramaShorts URLs found"}, status_code=400)

    # For each unique movie, fetch page and extract ALL episodes
    result_dramas = []

    for mid, info in movie_map.items():
        try:
            page_url = f"{WEB_BASE}/shorts/{mid}"
            html = await fetch_html(page_url)
            nd = parse_next_data(html)

            if not nd:
                # Single episode fallback
                result_dramas.append({
                    "movie_id": mid,
                    "title": f"Drama {mid[:8]}",
                    "episodes": [{"number": info.get("ep_num") or 1,
                                  "url": info["url"],
                                  "cover_url": "",
                                  "title": f"第{info.get('ep_num') or 1}集",
                                  "duration": 0.0}],
                })
                continue

            page_props = nd.get("props", {}).get("pageProps", {})
            episodes_raw = page_props.get("episodes", [])
            movie_details = page_props.get("movieDetails", {})
            movie_title = movie_details.get("movie", {}).get("title", f"Drama {mid[:8]}")

            eps = []
            for ep in episodes_raw:
                ed = ep.get("episode", {})
                ep_num = ed.get("index", 0)
                cov = ed.get("coverUrl", "")
                dur = ed.get("duration", 0.0)
                eps.append({
                    "number": ep_num,
                    "url": f"{WEB_BASE}/shorts/{mid}?episode={ep_num}",
                    "cover_url": cov,
                    "title": f"第{ep_num}集",
                    "duration": dur,
                })

            if not eps:
                eps = [{"number": info.get("ep_num") or 1,
                        "url": info["url"],
                        "cover_url": "",
                        "title": f"第{info.get('ep_num') or 1}集",
                        "duration": 0.0}]

            result_dramas.append({
                "movie_id": mid,
                "title": movie_title,
                "episodes": eps,
            })

        except Exception as e:
            result_dramas.append({
                "movie_id": mid,
                "title": f"Drama {mid[:8]}",
                "error": str(e)[:200],
                "episodes": [{"number": info.get("ep_num") or 1,
                              "url": info["url"],
                              "cover_url": "",
                              "title": f"第{info.get('ep_num') or 1}集",
                              "duration": 0.0}],
            })

    total_eps = sum(len(d["episodes"]) for d in result_dramas)
    return JSONResponse({"dramas": result_dramas, "total_episodes": total_eps})


@app.post("/api/download")
async def api_download(request: Request):
    """Start batch download of selected episodes."""
    body = await request.json()
    episodes: list[dict] = body.get("episodes", [])
    output_dir: str = body.get("output_dir", DEFAULT_OUTPUT_DIR)
    do_loudnorm: bool = body.get("loudnorm", False)
    movie_title: str = body.get("movie_title", "drama")

    if not episodes:
        return JSONResponse({"error": "No episodes selected"}, status_code=400)

    # Resolve output directory
    out = Path(output_dir)
    if not out.is_absolute():
        out = BASE_DIR / output_dir
    out.mkdir(parents=True, exist_ok=True)

    task_ids = []
    for ep in episodes:
        tid = str(uuid.uuid4())[:8]
        ep["task_id"] = tid
        ep["_output_dir"] = str(out)
        ep["_loudnorm"] = do_loudnorm
        ep["_movie_title"] = movie_title
        task_ids.append(tid)
        tasks_state[tid] = {
            "ep_num": ep.get("number", 0),
            "title": ep.get("title", ""),
            "status": "queued",
            "progress": 0,
        }

    # Start downloads with concurrency control
    async def _run_all():
        try:
            sem = asyncio.Semaphore(MAX_CONCURRENT)

            async def _run_one(ep):
                async with sem:
                    await download_single(
                        ep, ep["_output_dir"], ep["_loudnorm"], ep["_movie_title"],
                    )

            await asyncio.gather(*[_run_one(ep) for ep in episodes])
        except Exception as e:
            print(f"[ERROR] Download task failed: {e}")
            import traceback
            traceback.print_exc()

    asyncio.create_task(_run_all())

    return JSONResponse({"task_ids": task_ids, "message": f"Started {len(task_ids)} downloads"})


@app.get("/api/progress")
async def api_progress(request: Request):
    """SSE endpoint for real-time progress."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    progress_queues.append(queue)

    async def generator():
        try:
            # Send current state on connect
            for tid, state in tasks_state.items():
                if state.get("status") not in ("completed", "failed"):
                    yield f"data: {json.dumps({'task_id': tid, 'type': 'status', **state}, ensure_ascii=False)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            try:
                progress_queues.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/retry")
async def api_retry(request: Request):
    """Retry failed downloads."""
    body = await request.json()
    episodes: list[dict] = body.get("episodes", [])
    output_dir: str = body.get("output_dir", DEFAULT_OUTPUT_DIR)
    do_loudnorm: bool = body.get("loudnorm", False)
    movie_title: str = body.get("movie_title", "drama")

    out = Path(output_dir)
    if not out.is_absolute():
        out = BASE_DIR / output_dir
    out.mkdir(parents=True, exist_ok=True)

    task_ids = []
    for ep in episodes:
        tid = str(uuid.uuid4())[:8]
        ep["task_id"] = tid
        ep["_output_dir"] = str(out)
        ep["_loudnorm"] = do_loudnorm
        ep["_movie_title"] = movie_title
        task_ids.append(tid)
        tasks_state[tid] = {
            "ep_num": ep.get("number", 0),
            "title": ep.get("title", ""),
            "status": "queued",
            "progress": 0,
        }

    async def _run_all():
        try:
            sem = asyncio.Semaphore(MAX_CONCURRENT)
            async def _run_one(ep):
                async with sem:
                    await download_single(
                        ep, ep["_output_dir"], ep["_loudnorm"], ep["_movie_title"],
                    )
            await asyncio.gather(*[_run_one(ep) for ep in episodes])
        except Exception as e:
            print(f"[ERROR] Retry task failed: {e}")
            import traceback
            traceback.print_exc()

    asyncio.create_task(_run_all())
    return JSONResponse({"task_ids": task_ids, "message": f"Retrying {len(task_ids)} episodes"})


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    import uvicorn
    print(f"\n{'='*60}")
    print(f"  DramaShorts Downloader-fsk")
    print(f"  http://127.0.0.1:{DEFAULT_PORT}")
    print(f"{'='*60}\n")
    uvicorn.run(app, host="127.0.0.1", port=DEFAULT_PORT, log_level="info")
