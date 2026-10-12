"""TikTok platform adapter — wraps yt-dlp subprocess."""
from __future__ import annotations
import asyncio
import os
import re
import shutil
from pathlib import Path
from .base import BasePlatformAdapter, EpisodeInfo, PlatformMeta, ProgressInfo, ProgressCallback
from core.utils.logger import get_logger
from core.utils.proxy import detect_proxy

logger = get_logger("tiktok")


def _find_ytdlp() -> str | None:
    """Find yt-dlp executable."""
    local = Path(__file__).resolve().parent.parent.parent / "yt-dlp.exe"
    if local.exists():
        return str(local)
    found = shutil.which("yt-dlp")
    if found:
        return found
    found = shutil.which("yt-dlp.exe")
    if found:
        return found
    import sys
    scripts_dir = Path(sys.executable).parent / "Scripts"
    for name in ("yt-dlp.exe", "yt-dlp"):
        p = scripts_dir / name
        if p.exists():
            return str(p)
    return None


class TikTokAdapter(BasePlatformAdapter):
    platform_meta = PlatformMeta(
        name="TikTok",
        key="tiktok",
        domain="tiktok.com",
        accent="#ec4899",
        requires_proxy=True,
        status="Cookie Required",
    )

    def __init__(self):
        super().__init__()
        self._ytdlp = _find_ytdlp()
        if self._ytdlp:
            logger.info(f"yt-dlp found: {self._ytdlp}")
        else:
            logger.warning("yt-dlp not found in PATH")

    # ── Episode extraction ──────────────────────────────

    async def extract_episodes(self, url: str) -> list[EpisodeInfo]:
        """For TikTok, each URL is a single video. Return one episode."""
        match = re.search(r'/video/(\d+)', url)
        video_id = match.group(1) if match else str(abs(hash(url)))[:16]
        return [EpisodeInfo(url=url, number=1, title=f"TikTok {video_id[:8]}")]

    # ── Download ────────────────────────────────────────

    async def download_episode(
        self,
        url: str,
        output_dir: str | Path,
        episode_number: int | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Path | None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not self._ytdlp:
            err = "yt-dlp not found. Please install: pip install yt-dlp"
            logger.error(err)
            if progress_callback:
                await progress_callback(ProgressInfo(
                    task_id="", status="failed", progress=0, message=err
                ))
            return None

        ep_num = episode_number or 1
        ep_str = f"{ep_num:02d}"
        output_template = str(output_dir / f"{ep_str}.%(ext)s")

        # Detect proxy
        proxy = await detect_proxy()

        # Find cookies file
        cookies_file = None
        from config import COOKIES_FILE
        if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 100:
            cookies_file = str(COOKIES_FILE)

        args = [
            self._ytdlp, url,
            "--output", output_template,
            "--no-playlist",
            "--force-ipv4",
            "--restrict-filenames",
            "--windows-filenames",
            "--newline",
            "--extractor-retries", "3",
            "--retries", "5",
            "--fragment-retries", "5",
            "--sleep-requests", "3",
            "--sleep-interval", "5",
            "--max-sleep-interval", "15",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36",
            "--add-header", "Referer:https://www.tiktok.com/",
        ]

        if cookies_file:
            args += ["--cookies", cookies_file]
        if proxy:
            args += ["--proxy", proxy]

        if progress_callback:
            await progress_callback(ProgressInfo(
                task_id="", status="downloading", progress=0.05,
                drama_name="TikTok", episode_number=ep_num,
                message="Starting yt-dlp..."
            ))

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            downloaded_file = ""
            last_percent = 0.0
            error_lines: list[str] = []

            async for line in process.stdout:
                text = line.decode("utf-8", errors="replace")

                dest_match = re.search(r"\[download\] Destination: (.+)", text)
                if dest_match:
                    downloaded_file = dest_match.group(1).strip()

                pct_match = re.search(r"\[download\]\s+([\d.]+)%\s+of\s+", text)
                if pct_match:
                    percent = float(pct_match.group(1))
                    if percent > last_percent and progress_callback:
                        last_percent = percent
                        await progress_callback(ProgressInfo(
                            task_id="", status="downloading",
                            progress=0.05 + percent * 0.009,
                            drama_name="TikTok", episode_number=ep_num,
                            message=f"{percent:.0f}%"
                        ))

                if "ERROR:" in text:
                    error_lines.append(text.strip())

            await process.wait()

            if process.returncode == 0:
                # Find output file
                output_path = None
                if downloaded_file and os.path.exists(downloaded_file):
                    output_path = downloaded_file
                else:
                    for ext in (".mp4", ".mkv", ".webm", ".mov"):
                        p = output_dir / f"{ep_str}{ext}"
                        if p.exists():
                            output_path = str(p)
                            break

                if output_path:
                    if progress_callback:
                        await progress_callback(ProgressInfo(
                            task_id="", status="completed", progress=1.0,
                            drama_name="TikTok", episode_number=ep_num,
                            message="Done"
                        ))
                    return Path(output_path)

                err = "yt-dlp succeeded but no output file found"
                logger.error(err)
                if progress_callback:
                    await progress_callback(ProgressInfo(
                        task_id="", status="failed", progress=0, message=err
                    ))
                return None
            else:
                error_msg = "\n".join(error_lines[-5:]) if error_lines else f"Exit code {process.returncode}"
                logger.error(f"yt-dlp failed: {error_msg}")
                if progress_callback:
                    await progress_callback(ProgressInfo(
                        task_id="", status="failed", progress=0,
                        message=error_msg[:200]
                    ))
                return None

        except Exception as e:
            logger.error(f"TikTok download exception: {e}")
            if progress_callback:
                await progress_callback(ProgressInfo(
                    task_id="", status="failed", progress=0, message=str(e)
                ))
            return None
