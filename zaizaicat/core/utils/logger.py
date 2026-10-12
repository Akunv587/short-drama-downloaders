"""Centralized logging with daily rotation (7-day retention)."""
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from config import LOGS_DIR

LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"

_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str = "zaizaicat") -> logging.Logger:
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = LOGS_DIR / f"zaizaicat_{today}.log"
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FMT))
        logger.addHandler(fh)

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FMT))
        logger.addHandler(ch)

    _loggers[name] = logger
    _cleanup_old_logs()
    return logger


def get_task_logger(task_id: str) -> logging.Logger:
    logger = logging.getLogger(f"task.{task_id}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


class TaskLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[tuple[str, str]] = []

    def emit(self, record):
        self.records.append((record.levelname.lower(), self.format(record)))

    def get_logs(self) -> list[tuple[str, str]]:
        return list(self.records)

    def clear(self):
        self.records.clear()


_task_log_handlers: dict[str, TaskLogHandler] = {}


def attach_task_log_handler(task_id: str, logger: logging.Logger):
    if task_id in _task_log_handlers:
        return _task_log_handlers[task_id]
    handler = TaskLogHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", DATE_FMT))
    logger.addHandler(handler)
    _task_log_handlers[task_id] = handler
    return handler


def get_task_logs(task_id: str) -> list[tuple[str, str]]:
    handler = _task_log_handlers.get(task_id)
    return handler.get_logs() if handler else []


def _cleanup_old_logs():
    cutoff = datetime.now() - timedelta(days=7)
    for f in LOGS_DIR.glob("zaizaicat_*.log"):
        try:
            date_str = f.stem.replace("zaizaicat_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                f.unlink()
        except (ValueError, OSError):
            pass
