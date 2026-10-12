"""
仔仔猫 Web UI — 下载历史持久化层

基于 SQLite + Peewee ORM，提供任务记录的 CRUD 操作。
数据库文件: <项目根>/zaizaimao.db
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from peewee import (
    CharField,
    DateTimeField,
    FloatField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

# ── 数据库初始化 ──

DB_PATH = Path(__file__).resolve().parent.parent.parent / "zaizaimao.db"
_db = SqliteDatabase(
    str(DB_PATH),
    pragmas={
        "journal_mode": "wal",          # Write-Ahead Logging: 支持并发读写
        "foreign_keys": 1,
        "busy_timeout": 5000,           # 5s 超时，避免锁冲突
    },
)


# ── 模型定义 ──

class TaskRecord(Model):
    """下载任务持久化记录"""

    id = CharField(primary_key=True)                # UUID
    platform = CharField()                           # dramashorts / shortmax / tiktok
    task_name = CharField()                          # 去重后的显示名称
    episode_range = CharField(default="")            # "1-55" / "全部" / ""
    urls_json = TextField(default="[]")              # JSON: ["url1","url2"]
    out_dir = CharField(default="")
    status = CharField(default="queued")             # queued/running/paused/completed/partial/failed
    progress = FloatField(default=0.0)               # 0.0 ~ 1.0
    total_episodes = IntegerField(default=0)
    completed_episodes = IntegerField(default=0)
    failed_episodes_json = TextField(default="[]")   # JSON: [1, 3, 5]
    retry_count = IntegerField(default=0)
    max_retries = IntegerField(default=3)
    logs_json = TextField(default="[]")              # JSON: [["info","msg"], ...]
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        database = _db
        table_name = "download_history"


# ── 表创建 ──

def init_db() -> None:
    """初始化数据库（创建表），幂等操作。"""
    _db.connect(reuse_if_open=True)
    _db.create_tables([TaskRecord], safe=True)


# ── 工具函数 ──

def _now() -> datetime:
    return datetime.now()


def _safe_json_loads(raw: str, default: Any = None) -> Any:
    """安全解析 JSON 字符串"""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


def _safe_json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ── CRUD 操作 ──

def create_task(
    platform: str,
    task_name: str,
    urls: list[str],
    out_dir: str,
    episode_range: str = "",
    max_retries: int = 3,
) -> str:
    """创建新任务记录，自动处理重名。

    Returns:
        新创建的任务 ID (UUID)
    """
    init_db()

    # ── 去重: 同名任务追加序号 ──
    display_name = _deduplicate_name(task_name)

    task_id = uuid.uuid4().hex[:12]  # 短 UUID

    record = TaskRecord.create(
        id=task_id,
        platform=platform,
        task_name=display_name,
        episode_range=episode_range,
        urls_json=_safe_json_dumps(urls),
        out_dir=out_dir,
        status="queued",
        progress=0.0,
        total_episodes=0,
        completed_episodes=0,
        failed_episodes_json="[]",
        retry_count=0,
        max_retries=max_retries,
        logs_json="[]",
        created_at=_now(),
        updated_at=_now(),
    )
    return record.id


def _deduplicate_name(base_name: str) -> str:
    """为重复剧名追加序号。

    Examples:
        "剧名A" 已存在 → "剧名A-1"
        "剧名A-1" 已存在 → "剧名A-2"
    """
    existing = (
        TaskRecord.select(TaskRecord.task_name)
        .where(TaskRecord.task_name == base_name)
        .first()
    )
    if not existing:
        return base_name

    # 基础名 + 序号冲突检测
    counter = 1
    while True:
        candidate = f"{base_name}-{counter}"
        dup = (
            TaskRecord.select(TaskRecord.id)
            .where(TaskRecord.task_name == candidate)
            .first()
        )
        if not dup:
            return candidate
        counter += 1


def update_task(task_id: str, **fields) -> int:
    """更新任务字段，自动更新 updated_at。

    Returns:
        受影响的行数
    """
    init_db()
    fields["updated_at"] = _now()
    return (
        TaskRecord.update(**fields)
        .where(TaskRecord.id == task_id)
        .execute()
    )


def get_task(task_id: str) -> dict | None:
    """获取单个任务记录（返回字典）"""
    init_db()
    try:
        record = TaskRecord.get_by_id(task_id)
        return _record_to_dict(record)
    except TaskRecord.DoesNotExist:
        return None


def list_tasks(
    platform: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """列出任务记录，支持按平台和状态筛选。"""
    init_db()
    query = TaskRecord.select()
    if platform:
        query = query.where(TaskRecord.platform == platform)
    if status:
        query = query.where(TaskRecord.status == status)
    query = query.order_by(TaskRecord.created_at.desc()).limit(limit).offset(offset)
    return [_record_to_dict(r) for r in query]


def search_tasks(keyword: str, limit: int = 50) -> list[dict]:
    """按剧名搜索任务记录（模糊匹配）。"""
    init_db()
    query = (
        TaskRecord.select()
        .where(TaskRecord.task_name.contains(keyword))
        .order_by(TaskRecord.created_at.desc())
        .limit(limit)
    )
    return [_record_to_dict(r) for r in query]


def count_all_tasks() -> int:
    """获取任务总数（用于分页）"""
    init_db()
    return TaskRecord.select().count()


def count_search_tasks(keyword: str) -> int:
    """获取搜索结果总数（用于分页）"""
    init_db()
    return (
        TaskRecord.select()
        .where(TaskRecord.task_name.contains(keyword))
        .count()
    )


def delete_task(task_id: str) -> bool:
    """删除任务记录。

    Returns:
        是否成功删除
    """
    init_db()
    rows = TaskRecord.delete().where(TaskRecord.id == task_id).execute()
    return rows > 0


def append_log(task_id: str, level: str, message: str) -> None:
    """向任务日志追加一条记录（原子更新）。"""
    init_db()
    try:
        record = TaskRecord.get_by_id(task_id)
        logs = _safe_json_loads(record.logs_json, [])
        logs.append([level, message])
        # 限制日志条数
        if len(logs) > 500:
            logs = logs[-500:]
        record.logs_json = _safe_json_dumps(logs)
        record.updated_at = _now()
        record.save()
    except TaskRecord.DoesNotExist:
        pass


def get_task_logs(task_id: str) -> list[tuple[str, str]]:
    """获取任务的日志列表"""
    init_db()
    try:
        record = TaskRecord.get_by_id(task_id)
        raw = _safe_json_loads(record.logs_json, [])
        return [(entry[0], entry[1]) for entry in raw]
    except TaskRecord.DoesNotExist:
        return []


def update_episode_progress(
    task_id: str,
    completed: int,
    total: int,
    failed_episodes: list[int] | None = None,
) -> None:
    """更新剧集完成进度"""
    init_db()
    try:
        record = TaskRecord.get_by_id(task_id)
        record.completed_episodes = completed
        record.total_episodes = total
        record.progress = (completed / total) if total > 0 else 0.0
        if failed_episodes is not None:
            record.failed_episodes_json = _safe_json_dumps(failed_episodes)
        record.updated_at = _now()
        record.save()
    except TaskRecord.DoesNotExist:
        pass


# ── 内部工具 ──

def _record_to_dict(record: TaskRecord) -> dict:
    """将 ORM 实例转为字典"""
    return {
        "id": record.id,
        "platform": record.platform,
        "task_name": record.task_name,
        "episode_range": record.episode_range,
        "urls": _safe_json_loads(record.urls_json, []),
        "out_dir": record.out_dir,
        "status": record.status,
        "progress": record.progress,
        "total_episodes": record.total_episodes,
        "completed_episodes": record.completed_episodes,
        "failed_episodes": _safe_json_loads(record.failed_episodes_json, []),
        "retry_count": record.retry_count,
        "max_retries": record.max_retries,
        "logs": _safe_json_loads(record.logs_json, []),
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }
