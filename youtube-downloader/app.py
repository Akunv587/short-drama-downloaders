import os
import json
import queue
import threading
import uuid
import time
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, jsonify, Response

import yt_dlp

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = "yt-downloader-secret-key-change-me"

BASE_DIR = Path(__file__).parent.resolve()
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)
COOKIE_DIR = BASE_DIR / "cookies"
COOKIE_DIR.mkdir(exist_ok=True)

# Locate deno for yt-dlp JS runtime
_DENO_PATHS = [
    Path(os.path.expandvars("%USERPROFILE%")) / ".deno" / "bin" / "deno.exe",
    Path("C:/Program Files/deno/bin/deno.exe"),
]
_DENO_EXE = None
for _p in _DENO_PATHS:
    if _p.exists():
        _DENO_EXE = str(_p)
        break

# ---------------------------------------------------------------------------
# In-memory task store
# ---------------------------------------------------------------------------
tasks: dict[str, dict] = {}           # task_id → metadata
progress_queues: dict[str, queue.Queue] = {}  # task_id → Queue for SSE

TASK_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Subtitle language options
# ---------------------------------------------------------------------------
SUBTITLE_LANGUAGES = {
    "en":    "English",
    "zh-Hans": "中文 (简体)",
    "zh-Hant": "中文 (繁體)",
    "ja":    "日本語",
    "ko":    "한국어",
    "fr":    "Français",
    "de":    "Deutsch",
    "es":    "Español",
    "pt":    "Português",
    "ru":    "Русский",
    "ar":    "العربية",
    "hi":    "हिन्दी",
    "th":    "ไทย",
    "vi":    "Tiếng Việt",
    "id":    "Bahasa Indonesia",
    "it":    "Italiano",
    "nl":    "Nederlands",
    "tr":    "Türkçe",
    "pl":    "Polski",
}

# ---------------------------------------------------------------------------
# Routes – pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        languages=SUBTITLE_LANGUAGES,
        download_dir=str(DOWNLOAD_DIR),
    )


# ---------------------------------------------------------------------------
# Routes – API: get video info (preview)
# ---------------------------------------------------------------------------
@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL is required"}), 400

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
    }

    cookie_path = _get_active_cookie()
    if cookie_path:
        ydl_opts["cookiefile"] = cookie_path

    # JS runtime for better YouTube extraction
    if _DENO_EXE:
        ydl_opts["js_runtimes"] = {"deno": {"path": _DENO_EXE, "version": "auto"}}
        ydl_opts["remote_components"] = ["ejs:github"]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if info is None:
            return jsonify({"ok": False, "error": "YouTube returned no data. Try uploading a fresh cookies.txt."}), 400

        result = {
            "ok": True,
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
            "thumbnail": info.get("thumbnail"),
            "is_playlist": info.get("_type") == "playlist" or "entries" in info,
            "playlist_count": len(info.get("entries", [])) if "entries" in info else None,
            "subtitles": list(info.get("subtitles", {}).keys()),
            "automatic_captions": list(info.get("automatic_captions", {}).keys()),
        }
        return jsonify(result)

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---------------------------------------------------------------------------
# Routes – API: start download
# ---------------------------------------------------------------------------
@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL is required"}), 400

    task_id = str(uuid.uuid4())[:8]
    save_path = data.get("save_path", str(DOWNLOAD_DIR)).strip() or str(DOWNLOAD_DIR)

    options = {
        "download_video": data.get("download_video", True),
        "download_audio": data.get("download_audio", False),
        "download_thumbnail": data.get("download_thumbnail", False),
        "download_subtitles": data.get("download_subtitles", False),
        "subtitle_langs": data.get("subtitle_langs", ["en"]),
        "subtitle_format": data.get("subtitle_format", "vtt"),
        "video_quality": data.get("video_quality", "1080p"),
    }

    cookie_path = _get_active_cookie()

    q: queue.Queue = queue.Queue()
    progress_queues[task_id] = q

    task = {
        "id": task_id,
        "url": url,
        "save_path": save_path,
        "options": options,
        "status": "queued",
        "created_at": datetime.now().isoformat(),
        "title": "",
        "error": None,
    }
    with TASK_LOCK:
        tasks[task_id] = task

    thread = threading.Thread(
        target=_do_download,
        args=(task_id, url, save_path, options, cookie_path, q),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "task_id": task_id})


# ---------------------------------------------------------------------------
# Routes – API: task status
# ---------------------------------------------------------------------------
@app.route("/api/task/<task_id>", methods=["GET"])
def api_task(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"ok": False, "error": "Task not found"}), 404
    return jsonify({"ok": True, "task": task})


# ---------------------------------------------------------------------------
# Routes – API: list all tasks
# ---------------------------------------------------------------------------
@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    with TASK_LOCK:
        return jsonify({"ok": True, "tasks": list(tasks.values())})


# ---------------------------------------------------------------------------
# Routes – API: cancel task
# ---------------------------------------------------------------------------
@app.route("/api/task/<task_id>/cancel", methods=["POST"])
def api_cancel(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"ok": False, "error": "Task not found"}), 404
    if task["status"] in ("completed", "cancelled"):
        return jsonify({"ok": False, "error": "Cannot cancel"}), 400

    task["status"] = "cancelled"
    # Push cancel event to SSE
    q = progress_queues.get(task_id)
    if q:
        q.put({"event": "cancelled"})
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes – API: save cookie text (pasted)
# ---------------------------------------------------------------------------
@app.route("/api/cookie/save", methods=["POST"])
def api_cookie_save():
    data = request.get_json(force=True)
    cookie_text = data.get("cookie_text", "").strip()
    if not cookie_text:
        return jsonify({"ok": False, "error": "Cookie text is empty"}), 400

    # Basic validation: should contain Netscape-format cookie lines
    if not any("youtube.com" in line or ".youtube.com" in line for line in cookie_text.split("\n")):
        return jsonify({"ok": False, "error": "Invalid cookie format. Make sure the content contains YouTube cookies."}), 400

    save_to = COOKIE_DIR / "cookies.txt"
    save_to.write_text(cookie_text, encoding="utf-8")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes – API: check if cookie exists
# ---------------------------------------------------------------------------
@app.route("/api/cookie/status", methods=["GET"])
def api_cookie_status():
    cookie_file = COOKIE_DIR / "cookies.txt"
    exists = cookie_file.exists()
    return jsonify({
        "ok": True,
        "exists": exists,
        "mtime": datetime.fromtimestamp(cookie_file.stat().st_mtime).isoformat() if exists else None,
    })


# ---------------------------------------------------------------------------
# Routes – API: delete cookie
# ---------------------------------------------------------------------------
@app.route("/api/cookie/delete", methods=["POST"])
def api_cookie_delete():
    cookie_file = COOKIE_DIR / "cookies.txt"
    if cookie_file.exists():
        cookie_file.unlink()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes – SSE: progress stream
# ---------------------------------------------------------------------------
@app.route("/api/progress/<task_id>")
def api_progress(task_id):
    q = progress_queues.get(task_id)
    if q is None:
        return Response("data: {}\n\n", mimetype="text/event-stream")

    def generate():
        while True:
            try:
                msg = q.get(timeout=30)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("event") in ("completed", "error", "cancelled"):
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
                # Check if task is still alive
                task = tasks.get(task_id)
                if task and task["status"] in ("completed", "error", "cancelled"):
                    break

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Download logic
# ---------------------------------------------------------------------------
def _get_active_cookie() -> str | None:
    """Return path to cookie file if it exists."""
    cookie_file = COOKIE_DIR / "cookies.txt"
    return str(cookie_file) if cookie_file.exists() else None


def _progress_hook(task_id: str, q: queue.Queue):
    """yt-dlp progress hook — pushes status to the SSE queue."""
    def hook(d: dict):
        try:
            if not isinstance(d, dict):
                return
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                percent = (downloaded / total * 100) if total > 0 else 0
                q.put({
                    "event": "progress",
                    "percent": round(percent, 1),
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                    "speed": d.get("speed"),
                    "speed_str": d.get("_speed_str", ""),
                    "eta": d.get("eta"),
                    "eta_str": d.get("_eta_str", ""),
                    "filename": os.path.basename(d.get("filename", "") or "unknown"),
                    "info_dict": {},
                })
            elif status == "finished":
                q.put({
                    "event": "postprocessing",
                    "message": "Processing / merging...",
                    "filename": os.path.basename(d.get("filename", "") or "unknown"),
                })
        except Exception:
            pass  # Never let a progress hook crash the download
    return hook


def _do_download(
    task_id: str,
    url: str,
    save_path: str,
    options: dict,
    cookie_path: str | None,
    q: queue.Queue,
):
    """Run yt-dlp download in a background thread."""
    task = tasks.get(task_id)
    if not task:
        return

    task["status"] = "running"

    # Ensure save path exists
    os.makedirs(save_path, exist_ok=True)

    # Build yt-dlp options
    ydl_opts: dict = {
        "outtmpl": os.path.join(save_path, "%(title)s.%(ext)s"),
        "progress_hooks": [_progress_hook(task_id, q)],
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,          # skip failed videos in playlists
        "nooverwrites": False,
        "continuedl": True,
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "fragment_retries": 5,
    }

    if cookie_path:
        ydl_opts["cookiefile"] = cookie_path

    # JS runtime for better YouTube extraction
    if _DENO_EXE:
        ydl_opts["js_runtimes"] = {"deno": {"path": _DENO_EXE, "version": "auto"}}
        ydl_opts["remote_components"] = ["ejs:github"]

    # --- Video format selection ---
    if options.get("download_video"):
        # Prefer 1080p MP4 video + M4A audio → merge
        ydl_opts["format"] = (
            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo[height<=1080]+bestaudio/"
            "best[height<=1080][ext=mp4]/"
            "best[height<=1080]/"
            "best"
        )
        ydl_opts["merge_output_format"] = "mp4"
    elif options.get("download_audio"):
        # Audio only
        ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio"
        ydl_opts["postprocessors"] = ydl_opts.get("postprocessors", [])
    else:
        # Nothing selected — default to video
        ydl_opts["format"] = (
            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=1080]"
        )
        ydl_opts["merge_output_format"] = "mp4"

    # --- Post-processors ---
    postprocessors = ydl_opts.get("postprocessors", [])

    # Thumbnail
    if options.get("download_thumbnail"):
        ydl_opts["writethumbnail"] = True
        postprocessors.append({
            "key": "EmbedThumbnail",
            "already_have_thumbnail": False,
        })
    else:
        ydl_opts["writethumbnail"] = False

    ydl_opts["postprocessors"] = postprocessors

    # --- Subtitles ---
    sub_langs = options.get("subtitle_langs", ["en"])
    if options.get("download_subtitles") and sub_langs:
        ydl_opts["writesubtitles"] = True
        ydl_opts["writeautomaticsub"] = True
        ydl_opts["subtitleslangs"] = sub_langs
    else:
        ydl_opts["writesubtitles"] = False
        ydl_opts["writeautomaticsub"] = False

    ydl_opts["postprocessors"] = postprocessors

    # --- Execute ---
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if info is None:
            raise RuntimeError(
                "Download failed: YouTube returned no data. "
                "Possible causes: bot-detection, age-restriction, or invalid URL. "
                "Try uploading a fresh cookies.txt from a logged-in browser."
            )

        task["title"] = info.get("title", "")

        # Count downloaded entries in playlist
        if info.get("_type") == "playlist" or "entries" in info:
            entries = info.get("entries", [])
            success_count = sum(1 for e in entries if e is not None)
            task["playlist_total"] = len(entries)
            task["playlist_success"] = success_count

        task["status"] = "completed"
        q.put({
            "event": "completed",
            "message": "Download finished!",
            "title": task["title"],
            "save_path": save_path,
            "playlist_total": task.get("playlist_total"),
            "playlist_success": task.get("playlist_success"),
        })

    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)
        q.put({"event": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════╗
║       YouTube 视频下载器 已启动               ║
║                                              ║
║   打开浏览器访问:  http://127.0.0.1:5000      ║
║                                              ║
║   按 Ctrl+C 停止服务                          ║
╚══════════════════════════════════════════════╝
    """)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
