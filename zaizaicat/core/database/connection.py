"""SQLite connection manager (WAL mode, singleton)."""
import sqlite3
import threading
from pathlib import Path
from config import DB_PATH, DATA_DIR

_conn_local = threading.local()


def get_db_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DB_PATH


def get_connection() -> sqlite3.Connection:
    if not hasattr(_conn_local, "conn") or _conn_local.conn is None:
        db_path = get_db_path()
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _conn_local.conn = conn
    return _conn_local.conn


def init_db():
    conn = get_connection()
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    if schema_path.exists():
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def close_db():
    if hasattr(_conn_local, "conn") and _conn_local.conn is not None:
        _conn_local.conn.close()
        _conn_local.conn = None
