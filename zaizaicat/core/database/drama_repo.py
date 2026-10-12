"""Drama database CRUD operations."""
from __future__ import annotations
import json
from .connection import get_connection


def add_drama(name: str, source_platform: str = None, data_source: str = "manual",
              **kwargs) -> dict:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO dramas (name, source_platform, data_source)
               VALUES (?, ?, ?)""",
            (name, source_platform, data_source)
        )
        conn.commit()
    except Exception:
        pass  # Already exists
    return get_drama_by_name(name)


def get_drama_by_name(name: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM dramas WHERE name = ?", (name,)
    ).fetchone()
    return dict(row) if row else None


def get_all_dramas(page: int = 1, per_page: int = 50,
                   search: str = None, status: str = None,
                   platform: str = None, sort_by: str = "created_at") -> dict:
    conn = get_connection()
    conditions = []
    params = []
    if search:
        conditions.append("name LIKE ?")
        params.append(f"%{search}%")
    if status:
        conditions.append("status = ?")
        params.append(status)
    if platform:
        conditions.append("source_platform = ?")
        params.append(platform)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    valid_sorts = {"created_at": "created_at DESC", "name": "name ASC",
                   "play_count": "play_count DESC", "updated_at": "updated_at DESC"}
    order = valid_sorts.get(sort_by, "created_at DESC")

    count = conn.execute(
        f"SELECT COUNT(*) FROM dramas {where}", params
    ).fetchone()[0]
    offset = (page - 1) * per_page
    rows = conn.execute(
        f"SELECT * FROM dramas {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [per_page, offset]
    ).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "total": count,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (count + per_page - 1) // per_page)
    }


def update_drama(name: str, **kwargs) -> dict | None:
    conn = get_connection()
    if not kwargs:
        return get_drama_by_name(name)
    allowed = ["play_count", "episode_count", "first_episode_url", "tags",
               "publish_date", "source_platform", "status", "notes", "data_source"]
    sets = []
    params = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        return get_drama_by_name(name)
    sets.append("updated_at = datetime('now')")
    params.append(name)
    conn.execute(
        f"UPDATE dramas SET {', '.join(sets)} WHERE name = ?", params
    )
    conn.commit()
    return get_drama_by_name(name)


def upsert_drama(name: str, source_platform: str = None,
                 data_source: str = "csv_import", **kwargs) -> dict:
    existing = get_drama_by_name(name)
    if existing:
        update_kwargs = {}
        for k, v in kwargs.items():
            if v is not None and (existing.get(k) is None or k in ("play_count", "episode_count")):
                update_kwargs[k] = v
        if update_kwargs:
            return update_drama(name, **update_kwargs)
        return existing
    else:
        return add_drama(name, source_platform=source_platform,
                        data_source=data_source, **kwargs)


def delete_drama(name: str):
    conn = get_connection()
    conn.execute("DELETE FROM dramas WHERE name = ?", (name,))
    conn.commit()


def compare_dramas(names: list[str]) -> list[dict]:
    results = []
    conn = get_connection()
    for name in names:
        row = conn.execute(
            "SELECT * FROM dramas WHERE name = ?", (name,)
        ).fetchone()
        if row:
            d = dict(row)
            d["_exists"] = True
        else:
            d = {"name": name, "_exists": False}
        results.append(d)
    return results


def export_csv(status: str = None, platform: str = None) -> str:
    import csv, io
    conn = get_connection()
    conditions = []
    params = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if platform:
        conditions.append("source_platform = ?")
        params.append(platform)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM dramas {where} ORDER BY name ASC", params
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "play_count", "episode_count", "first_episode_url",
                     "tags", "publish_date", "source_platform", "status", "notes",
                     "data_source", "created_at", "updated_at"])
    for r in rows:
        writer.writerow([r["name"], r["play_count"], r["episode_count"],
                        r["first_episode_url"], r["tags"], r["publish_date"],
                        r["source_platform"], r["status"], r["notes"],
                        r["data_source"], r["created_at"], r["updated_at"]])
    return output.getvalue()
