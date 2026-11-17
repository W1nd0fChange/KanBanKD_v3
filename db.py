"""Запись тикетов канбана в DGDWH, таблица tickets.commercial.

Доска живёт в локальном board.json. При статусе «Создано» строка вставляется.
Смена статуса и отдельные этапы проработки обновляют эту строку по id.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

import pyodbc

# Меняйте при смене имён колонок в SQL — по метке в /api/health видно, что сервер обновлён.
SCHEMA_TAG = "commercial-v2-2026-11-pauses"

CONN_STR = (
    r"DRIVER={ODBC Driver 17 for SQL Server};"
    r"SERVER=SRV-MSCS2-OLAP0\DWH;"
    r"DATABASE=DGDWH;"
    r"UID=deev.georgiy@famil.ru;"
    r"Trusted_Connection=yes;"
    r"TrustServerCertificate=yes;"
)

_INSERT_SQL = """
INSERT INTO tickets.commercial (
    [тип_задачи],
    [статус],
    [дирекция],
    [кол-во_строк],
    [сложность],
    [ссылка],
    [коммент_кд],
    [коммент_лида],
    [исполнитель],
    [Назначение],
    [Начало_проработки],
    [Конец_проработки],
    [номер_документа],
    [id]
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPDATE_SQL = """
UPDATE tickets.commercial SET
    [тип_задачи] = ?,
    [статус] = ?,
    [дирекция] = ?,
    [кол-во_строк] = ?,
    [сложность] = ?,
    [ссылка] = ?,
    [коммент_кд] = ?,
    [коммент_лида] = ?,
    [исполнитель] = ?,
    [Назначение] = ?,
    [Начало_проработки] = ?,
    [Конец_проработки] = ?,
    [номер_документа] = ?
WHERE [id] = ?
"""


def writing_enabled() -> bool:
    return os.environ.get("KANBAN_SKIP_DB") != "1"


def schema_info() -> dict:
    module_file = str(Path(__file__).resolve())
    sql = _INSERT_SQL
    legacy = "[начало]" in sql or "[конец]" in sql
    return {
        "tag": SCHEMA_TAG,
        "module_file": module_file,
        "legacy_column_names": legacy,
        "datetime_columns": ["Назначение", "Начало_проработки", "Конец_проработки"],
    }


def now_msk() -> str:
    """Текущий момент по Москве для JSON на доске и для записи в DGDWH."""
    return datetime.now(MSK).replace(microsecond=0).isoformat()


def connect():
    return pyodbc.connect(CONN_STR, timeout=5)


def check_connection() -> tuple[bool, str | None]:
    if not writing_enabled():
        return False, "запись в БД отключена"
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT TOP 0 [тип_задачи] FROM tickets.commercial")
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _as_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        # ISO без пояса: старые записи доски писались как UTC; смещаем в МСК.
        moment = moment.replace(tzinfo=timezone.utc).astimezone(MSK)
    else:
        moment = moment.astimezone(MSK)
    return moment.replace(tzinfo=None, microsecond=0)


def _clip(value, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _values(ticket: dict) -> tuple:
    row_count = ticket.get("row_count")
    record_id = ticket.get("record_id")
    if record_id in (None, ""):
        raise ValueError("У тикета нет id для записи в базу")
    return (
        _clip(ticket.get("task_type"), 100),
        _clip(ticket.get("status"), 100),
        _clip(ticket.get("directorate"), 100),
        None if row_count in (None, "") else int(row_count),
        _clip(ticket.get("complexity"), 100),
        _clip(ticket.get("file_name"), 300),
        _clip(ticket.get("comment"), 300),
        _clip(ticket.get("lead_comment"), 300),
        _clip(ticket.get("assignee"), 100),
        _as_datetime(ticket.get("started_at")),
        _as_datetime(ticket.get("work_started_at")),
        _as_datetime(ticket.get("finished_at")),
        _clip(ticket.get("document_number"), 100),
        int(record_id),
    )


def save_ticket(ticket: dict, *, insert: bool) -> None:
    if not writing_enabled():
        return

    params = _values(ticket)
    with connect() as conn:
        cur = conn.cursor()
        if insert:
            cur.execute(_INSERT_SQL, params)
        else:
            # UPDATE: все поля и id в конце для WHERE
            cur.execute(_UPDATE_SQL, (*params[:-1], params[-1]))
            # Тикет мог жить на доске без строки в commercial (раньше INSERT не прошёл).
            if cur.rowcount == 0:
                cur.execute(_INSERT_SQL, params)
        conn.commit()


_OPEN_PAUSE_SQL = """
INSERT INTO tickets.commercial_pauses ([id_ticket], [Начало])
OUTPUT INSERTED.id_Pause
VALUES (?, ?)
"""

_CLOSE_PAUSE_SQL = """
UPDATE tickets.commercial_pauses
SET [Конец] = ?
WHERE id_Pause = ? AND [Конец] IS NULL
"""


def open_pause(ticket_record_id: int, started_at) -> int:
    if not writing_enabled():
        raise RuntimeError("запись в БД отключена")
    moment = _as_datetime(started_at)
    if moment is None:
        raise ValueError("Некорректное время начала паузы")
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(_OPEN_PAUSE_SQL, (int(ticket_record_id), moment))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Не удалось создать запись паузы")
        pause_id = int(row[0])
        conn.commit()
        return pause_id


def close_pause(pause_id: int, ended_at) -> None:
    if not writing_enabled():
        raise RuntimeError("запись в БД отключена")
    moment = _as_datetime(ended_at)
    if moment is None:
        raise ValueError("Некорректное время конца паузы")
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(_CLOSE_PAUSE_SQL, (moment, int(pause_id)))
        if cur.rowcount == 0:
            raise ValueError(f"Открытая пауза id_Pause={pause_id} не найдена")
        conn.commit()