"""zaizaicat global default config."""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass

PROJECT_ROOT = Path(__file__).resolve().parent
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
DB_PATH = DATA_DIR / "zaizaicat.db"
COOKIES_FILE = PROJECT_ROOT / "cookies.txt"


@dataclass
class AppConfig:
    download_dir: str = str(DOWNLOADS_DIR)
    target_lufs: float = -14.0
    max_true_peak: float = -1.0
    auto_normalize: bool = False
    auto_add_drama: bool = True
    max_concurrent_shortmax: int = 5
    max_concurrent_dramashorts: int = 5
    proxy_url: str = ""
    theme: str = "light"
    chrome_debug_port: int = 9222


DEFAULT_CONFIG = AppConfig()
