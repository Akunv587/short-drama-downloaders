"""Download history CRUD operations."""
from __future__ import annotations
from .connection import get_connection


def add_history(drama_name: str, platform: str, episode_count: int = 1,
                download_path: str = None, total_size_bytes: int = None) -> dict:
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO download_history (drama_name, platform, episode_count,
           download_path, total_size_bytes) VALUES (?, ?, ?, ?, ?)""",
        (drama_name, platform, episode_count, download_path, total_size_bytes)
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM download_history WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return dict(row)


def get_history(page: int = 1, per_page: int = 20, search: str = None) -> dict:
    conn = get_connection()
    offset = (page - 1) * per_page
    if search:
        count = conn.execute(
            "SELECT COUNT(*) FROM download_history WHERE drama_name LIKE ?",
            (f"%{search}%",)
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT * FROM download_history WHERE drama_name LIKE ?
               ORDER BY completed_at DESC LIMIT ? OFFSET ?""",
            (f"%{search}%", per_page, offset)
        ).fetchall()
    else:
        count = conn.execute(
            "SELECT COUNT(*) FROM download_history"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM download_history ORDER BY completed_at DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "total": count,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (count + per_page - 1) // per_page)
    }


def delete_history(history_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM download_history WHERE id = ?", (history_id,))
    conn.commit()
