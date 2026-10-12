"""File utilities: path handling, retry-safe operations, subprocess runner."""
from __future__ import annotations
import asyncio
import os
import time
import shutil
from pathlib import Path
from core.utils.logger import get_logger

logger = get_logger("file_utils")


def safe_remove(path: str | Path, max_retries: int = 5, delay: float = 0.5):
    """Remove a file with retries for Windows file-lock issues (WinError 32)."""
    p = Path(path)
    if not p.exists():
        return
    for attempt in range(max_retries):
        try:
            p.unlink()
            return
        except OSError:
            if attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                try:
                    p.unlink()
                except OSError:
                    pass


def safe_rename(src: str | Path, dst: str | Path,
                max_retries: int = 5, delay: float = 0.5):
    """Rename with retries for Windows file-lock issues."""
    s, d = Path(src), Path(dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(max_retries):
        try:
            s.rename(d)
            return
        except OSError:
            if attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                shutil.copy2(s, d)
                safe_remove(s)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize_filename(name: str) -> str:
    """Remove characters unsafe for Windows filenames."""
    unsafe = '<>:"/\\|?*'
    for ch in unsafe:
        name = name.replace(ch, "_")
    return name.strip().strip(".")[:200]


async def run_subprocess(cmd: list[str], timeout: float = 300,
                         cwd: str | None = None) -> dict:
    """Run a subprocess asynchronously and return result dict.

    Returns:
        {"success": bool, "stdout": str, "stderr": str, "returncode": int}
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
        return {
            "success": process.returncode == 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": process.returncode,
        }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Timeout after {timeout}s",
            "returncode": -1,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command not found: {cmd[0] if cmd else 'unknown'}",
            "returncode": -1,
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
        }


async def safe_file_replace(src: str | Path, dst: str | Path,
                            max_retries: int = 10,
                            base_delay: float = 0.3) -> bool:
    """Replace dst with src, retrying on Windows file-lock errors.

    Uses exponential backoff: 0.3, 0.6, 1.2, 2.4, 4.8 seconds.
    Returns True on success.
    """
    s, d = Path(src), Path(dst)
    if not s.exists():
        return False

    for attempt in range(max_retries):
        try:
            if d.exists():
                d.unlink()
            s.rename(d)
            return True
        except (PermissionError, OSError):
            if attempt == max_retries - 1:
                try:
                    shutil.copy2(s, d)
                    safe_remove(s)
                    return True
                except Exception:
                    return False
            delay = base_delay * (2 ** attempt)
            logger.debug("文件被占用，%.1fs 后重试: %s", delay, d.name)
            await asyncio.sleep(delay)

    return False
