"""Состояние доски и файлы тикетов.

По умолчанию хранятся на сетевом диске Q:, чтобы одну доску могли открыть
несколько коллег. Путь можно переопределить переменной KANBAN_DATA_DIR.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL_DATA_PATH = ROOT / "data" / "board.json"
LOCAL_UPLOAD_DIR = ROOT / "uploads"

DEFAULT_DATA_DIR = Path(
    r"Q:\ПОДРАЗДЕЛЕНИЯ\Коммерческая дирекция\Управление закупок"
    r"\Business Analyst\Деев\Документы канбан доски"
)

DATA_DIR = Path(os.environ.get("KANBAN_DATA_DIR", DEFAULT_DATA_DIR))
DATA_PATH = DATA_DIR / "board.json"
UPLOAD_DIR = DATA_DIR / "uploads"

_LOCK = threading.Lock()


def _empty() -> dict:
    return {"columns": [], "tickets": []}


def _migrate_from_local() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DATA_PATH.exists():
        return
    if LOCAL_DATA_PATH.is_file():
        shutil.copy2(LOCAL_DATA_PATH, DATA_PATH)
    if LOCAL_UPLOAD_DIR.is_dir():
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for item in LOCAL_UPLOAD_DIR.iterdir():
            if not item.is_file():
                continue
            target = UPLOAD_DIR / item.name
            if not target.exists():
                shutil.copy2(item, target)


def load() -> dict:
    with _LOCK:
        if not DATA_PATH.exists():
            return _empty()
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def save(board: dict) -> None:
    with _LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_text(
            json.dumps(board, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def ensure_dirs() -> None:
    _migrate_from_local()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
