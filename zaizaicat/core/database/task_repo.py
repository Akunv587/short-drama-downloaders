"""Download task CRUD operations."""
from __future__ import annotations
import json
from .connection import get_connection


def create_task(task_id: str, url: str, platform: str, drama_name: str = None,
                episode_number: int = None, episode_range: str = None,
                total_episodes: int = 1) -> dict:
    conn = get_connection()
    conn.execute(
        """INSERT INTO download_tasks (id, url, platform, drama_name,
           episode_number, episode_range, total_episodes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (task_id, url, platform, drama_name, episode_number,
         episode_range, total_episodes)
    )
    conn.commit()
    return get_task(task_id)


def get_task(task_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM download_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return dict(row) if row else None


def get_all_tasks(status: str = None) -> list[dict]:
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM download_tasks WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM download_tasks ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_task_status(task_id: str, status: str, error_message: str = None):
    conn = get_connection()
    if error_message:
        conn.execute(
            """UPDATE download_tasks SET status = ?, error_message = ?,
               updated_at = datetime('now') WHERE id = ?""",
            (status, error_message, task_id)
        )
    else:
        conn.execute(
            """UPDATE download_tasks SET status = ?,
               updated_at = datetime('now') WHERE id = ?""",
            (status, task_id)
        )
    conn.commit()


def update_task_progress(task_id: str, progress: float,
                         completed_episodes: int = None):
    conn = get_connection()
    if completed_episodes is not None:
        conn.execute(
            """UPDATE download_tasks SET progress = ?, completed_episodes = ?,
               updated_at = datetime('now') WHERE id = ?""",
            (progress, completed_episodes, task_id)
        )
    else:
        conn.execute(
            """UPDATE download_tasks SET progress = ?,
               updated_at = datetime('now') WHERE id = ?""",
            (progress, task_id)
        )
    conn.commit()


def set_task_output(task_id: str, output_path: str):
    conn = get_connection()
    conn.execute(
        """UPDATE download_tasks SET output_path = ?,
           updated_at = datetime('now') WHERE id = ?""",
        (output_path, task_id)
    )
    conn.commit()


def delete_task(task_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM download_tasks WHERE id = ?", (task_id,))
    conn.commit()
