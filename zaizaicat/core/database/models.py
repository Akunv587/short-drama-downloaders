"""
数据库表结构定义与初始化
"""

from core.database.connection import execute, fetchone
from core.utils.logger import get_logger

logger = get_logger()

# 建表 SQL
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS download_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL UNIQUE,
    batch_id        TEXT,
    drama_name      TEXT NOT NULL,
    episode_num     TEXT,
    platform        TEXT NOT NULL,
    download_url    TEXT NOT NULL,
    save_path       TEXT,
    status          TEXT NOT NULL DEFAULT 'waiting',
    progress        REAL DEFAULT 0,
    file_size       INTEGER DEFAULT 0,
    downloaded_size INTEGER DEFAULT 0,
    download_speed  REAL DEFAULT 0,
    eta             INTEGER DEFAULT 0,
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    last_error      TEXT,
    next_retry_at   TIMESTAMP,
    source          TEXT,
    loudnorm_done   INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON download_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_batch ON download_tasks(batch_id);
CREATE INDEX IF NOT EXISTS idx_tasks_platform ON download_tasks(platform);

CREATE TABLE IF NOT EXISTS download_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id           TEXT NOT NULL,
    drama_name        TEXT NOT NULL,
    episode_num       TEXT,
    platform          TEXT NOT NULL,
    download_url      TEXT NOT NULL,
    save_path         TEXT,
    file_size         INTEGER DEFAULT 0,
    status            TEXT NOT NULL,
    error_message     TEXT,
    download_duration REAL DEFAULT 0,
    avg_speed         REAL DEFAULT 0,
    retry_count       INTEGER DEFAULT 0,
    source            TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at      TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_history_status ON download_history(status);
CREATE INDEX IF NOT EXISTS idx_history_platform ON download_history(platform);
CREATE INDEX IF NOT EXISTS idx_history_created ON download_history(created_at);
CREATE INDEX IF NOT EXISTS idx_history_drama ON download_history(drama_name);

CREATE TABLE IF NOT EXISTS dramas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,
    play_count        TEXT,
    episode_count     INTEGER,
    first_episode_url TEXT,
    tags              TEXT,
    publish_date      TEXT,
    platform          TEXT,
    status            TEXT DEFAULT 'unwatched',
    remark            TEXT,
    data_source       TEXT DEFAULT 'manual',
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dramas_status ON dramas(status);
CREATE INDEX IF NOT EXISTS idx_dramas_platform ON dramas(platform);
CREATE INDEX IF NOT EXISTS idx_dramas_name ON dramas(name);

CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# 默认设置
DEFAULT_SETTINGS = [
    ("proxy_address", ""),
    ("proxy_auto_detect", "true"),
    ("cookie_file_path", ""),
    ("cdp_port", "9222"),
    ("loudnorm_enabled", "false"),
    ("loudnorm_target_lufs", "-23"),
    ("auto_import_drama", "true"),
    ("theme", "light"),
]


def init_database():
    """初始化数据库：建表 + 插入默认设置"""
    # 逐条执行建表
    for statement in CREATE_TABLES_SQL.split(";"):
        stmt = statement.strip()
        if stmt:
            execute(stmt)

    # 插入默认设置（如果不存在）
    for key, value in DEFAULT_SETTINGS:
        existing = fetchone("SELECT key FROM app_settings WHERE key = ?", (key,))
        if not existing:
            execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?)", (key, value)
            )

    logger.info("数据库初始化完成")
