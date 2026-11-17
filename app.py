"""Канбан проработки. Оболочка в духе Microsoft Planner и запись тикета в DGDWH."""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import uuid
import webbrowser
from email.parser import BytesParser
from email.policy import default as email_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import importlib.util

import storage

ROOT = Path(__file__).resolve().parent


def _load_db_module():
    """Всегда брать db.py из папки канбана, а не чужой модуль db из PYTHONPATH."""
    path = ROOT / "db.py"
    spec = importlib.util.spec_from_file_location("kanban_db", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не найден модуль записи в БД: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


db = _load_db_module()
STATIC = ROOT / "static"
HOST = "0.0.0.0"
PORT = 8765
API_BUILD = "2026-11-17-pause"
TICKET_ID_RE = re.compile(r"^[a-fA-F0-9]{32}$")
TICKET_ACTION_RE = re.compile(
    r"^/api/tickets/([a-fA-F0-9]{32})/(move|done|cancel|start-work|pause|resume|file)$",
    re.IGNORECASE,
)

STATUSES = ("Создано", "Назначен отв.", "Выполняется", "Пауза", "Выполнено", "Отменено")
COMPLEXITY = ("легкое", "среднее", "сложное")
TASK_TYPES = ("Предложение", "ТЭО", "ЗИП", "ЗПКД", "Точный")
DIRECTORATES = (
    "D1 CASUAL",
    "D10 HOME",
    "D11 UNDE",
    "D2 SPORT",
    "D3 FORMA",
    "D4 DENIM",
    "D5 OUTER",
    "D6 SHOES",
    "D7 ACC",
    "D8 KIDS",
    "D9 Q-LINE",
)
CLOSE_LABEL = {
    "Предложение": "Номер БП",
    "ТЭО": "Номер ТЭО",
    "ЗИП": "Номер ЗИП",
    "ЗПКД": "Номер заявки на производство",
    "Точный": "Номер точного",
}
NUMBER_FIELDS = {
    "Предложение": "bp_number",
    "ТЭО": "teo_number",
    "ЗИП": "zip_number",
    "ЗПКД": "zpkd_number",
    "Точный": "exact_number",
}
FROZEN = ("Выполнено", "Отменено")
FILE_EXT = {".xlsx", ".xls", ".xlsm", ".docx", ".doc"}
MAX_FILE = 25 * 1024 * 1024
MAX_TEXT = 500

_BOARD_LOCK = threading.RLock()


def _now() -> str:
    return db.now_msk()


def _reconcile_executing_status(board: dict) -> list[dict]:
    """Раньше статус «Выполняется» подставлялся только при отдаче API. Дожимаем JSON и DGDWH."""
    fixed: list[dict] = []
    for ticket in board.get("tickets", []):
        if ticket.get("work_started_at") and ticket.get("status") == "Назначен отв.":
            ticket["status"] = "Выполняется"
            ticket["updated_at"] = _now()
            fixed.append(ticket)
    return fixed


def _read_board() -> dict:
    with _BOARD_LOCK:
        board = storage.load()
        fixed = _reconcile_executing_status(board)
        if fixed:
            storage.save(board)
            for ticket in fixed:
                _persist(ticket, board, insert=False)
        return _prepare_board(board)


def _ticket_or_none(board: dict, ticket_id: str) -> dict | None:
    return next((item for item in board["tickets"] if item["id"] == ticket_id), None)


def _column_or_none(board: dict, column_id: str) -> dict | None:
    return next((item for item in board["columns"] if item["id"] == column_id), None)


def _assignee(board: dict, ticket: dict) -> str | None:
    column = _column_or_none(board, ticket.get("column_id") or "")
    return column["name"] if column else None


def _executing_in_column(board: dict, column_id: str, *, skip_ticket_id: str | None = None) -> dict | None:
    for item in board.get("tickets", []):
        if skip_ticket_id and item.get("id") == skip_ticket_id:
            continue
        if item.get("column_id") == column_id and item.get("status") == "Выполняется":
            return item
    return None


def _assert_single_executing(board: dict, ticket: dict) -> None:
    column_id = ticket.get("column_id")
    if not column_id:
        return
    other = _executing_in_column(board, column_id, skip_ticket_id=ticket.get("id"))
    if other is None:
        return
    label = other.get("task_type") or "задача"
    record_id = other.get("record_id")
    suffix = f" (№ {record_id})" if record_id else ""
    raise ValueError(f"Уже выполняется другой тикет: {label}{suffix}")


def _close_open_pause(ticket: dict) -> dict | None:
    pause_id = ticket.get("open_pause_id")
    if pause_id in (None, ""):
        return None
    if not db.writing_enabled():
        ticket["open_pause_id"] = None
        return {"saved": False, "skipped": True, "error": None}
    try:
        db.close_pause(int(pause_id), _now())
        return {"saved": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"saved": False, "error": str(exc)}
    finally:
        ticket["open_pause_id"] = None


def _persist(ticket: dict, board: dict, *, insert: bool) -> dict:
    payload = dict(ticket)
    payload["assignee"] = _assignee(board, ticket)
    if not db.writing_enabled():
        return {"saved": False, "skipped": True, "error": None}
    try:
        db.save_ticket(payload, insert=insert)
        return {"saved": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"saved": False, "error": str(exc)}


def _allocate_record_id(board: dict) -> int:
    current = board.get("next_record_id")
    if not isinstance(current, int) or current < 1:
        used = [int(item["record_id"]) for item in board.get("tickets", []) if item.get("record_id")]
        current = max(used, default=0) + 1
    board["next_record_id"] = current + 1
    return current


def _empty_numbers() -> dict:
    return {name: None for name in NUMBER_FIELDS.values()}


def _as_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _prepare_ticket(ticket: dict) -> None:
    for name in NUMBER_FIELDS.values():
        ticket[name] = _as_text(ticket.get(name))
    legacy = _as_text(ticket.get("result_number"))
    field = NUMBER_FIELDS.get(ticket.get("task_type") or "")
    if legacy and ticket.get("status") == "Выполнено" and field and not ticket.get(field):
        ticket[field] = legacy
    ticket["directorate"] = _as_text(ticket.get("directorate"))
    ticket["cancel_comment"] = _as_text(ticket.get("cancel_comment"))
    ticket["started_at"] = _as_text(ticket.get("started_at"))
    ticket["work_started_at"] = _as_text(ticket.get("work_started_at"))
    ticket["finished_at"] = _as_text(ticket.get("finished_at"))
    ticket["document_number"] = _as_text(ticket.get("document_number"))
    if ticket.get("open_pause_id") not in (None, ""):
        ticket["open_pause_id"] = int(ticket["open_pause_id"])
    else:
        ticket["open_pause_id"] = None
    if ticket.get("record_id") not in (None, ""):
        ticket["record_id"] = int(ticket["record_id"])
    ticket.setdefault("journal", [])


def _prepare_board(board: dict) -> dict:
    board.setdefault("columns", [])
    board.setdefault("tickets", [])
    for column in board["columns"]:
        column["hidden"] = bool(column.get("hidden"))
    for ticket in board["tickets"]:
        _prepare_ticket(ticket)
    return board


def _log(ticket: dict, status_from, status_to, assignee_from, assignee_to, cancel_comment=None) -> None:
    ticket.setdefault("journal", [])
    ticket["journal"].append({
        "at": _now(),
        "status_from": status_from,
        "status_to": status_to,
        "assignee_from": assignee_from,
        "assignee_to": assignee_to,
        "cancel_comment": cancel_comment if status_to == "Отменено" else None,
        "user_id": None,
        "user_name": None,
        "user_position": None,
    })


def _ensure_open(ticket: dict) -> None:
    if ticket.get("status") in FROZEN:
        raise ValueError("Закрытую задачу нельзя изменить. Для повторной работы создайте новую карточку.")


def _parse_directorate(raw: str) -> str:
    value = (raw or "").strip()
    if value not in DIRECTORATES:
        raise ValueError("Выберите дирекцию")
    return value


def _parse_task_type(raw: str) -> str:
    task_type = (raw or "").strip()
    if task_type not in TASK_TYPES:
        raise ValueError("Выберите тип задачи")
    return task_type


def _parse_rows(raw: str) -> int:
    text = str(raw or "").strip()
    if not re.fullmatch(r"\d+", text):
        raise ValueError("Количество строк — целое число")
    return int(text)


def _parse_text(raw: str | None, title: str) -> str:
    text = (raw or "").strip()
    if len(text) > MAX_TEXT:
        raise ValueError(f"{title}: не больше {MAX_TEXT} символов")
    return text


def _public(ticket: dict, board: dict) -> dict:
    item = dict(ticket)
    item["assignee"] = _assignee(board, ticket)
    item.pop("stored_file", None)
    item.pop("journal", None)
    item.pop("result_number", None)
    return item


def create_ticket(fields: dict, upload: tuple[str, bytes] | None) -> dict:
    row_count = _parse_rows(fields.get("row_count", ""))
    complexity = (fields.get("complexity") or "").strip()
    if complexity not in COMPLEXITY:
        raise ValueError("Выберите уровень сложности")
    task_type = _parse_task_type(fields.get("task_type", ""))
    directorate = _parse_directorate(fields.get("directorate", ""))
    comment = _parse_text(fields.get("comment"), "Комментарий")
    lead_comment = _parse_text(fields.get("lead_comment"), "Комментарий лида")

    ticket = {
        "id": uuid.uuid4().hex,
        **_empty_numbers(),
        "task_type": task_type,
        "directorate": directorate,
        "row_count": row_count,
        "complexity": complexity,
        "file_name": None,
        "stored_file": None,
        "comment": comment,
        "lead_comment": lead_comment,
        "cancel_comment": None,
        "document_number": None,
        "started_at": None,
        "work_started_at": None,
        "finished_at": None,
        "open_pause_id": None,
        "status": "Создано",
        "column_id": None,
        "journal": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    _log(ticket, None, "Создано", None, None)
    if upload:
        _attach(ticket, upload)

    with _BOARD_LOCK:
        board = _read_board()
        ticket["record_id"] = _allocate_record_id(board)
        board["tickets"].append(ticket)
        storage.save(board)
        db_result = _persist(ticket, board, insert=True)
        return {"ticket": _public(ticket, board), "db": db_result}


def update_ticket(ticket_id: str, fields: dict, upload: tuple[str, bytes] | None) -> dict:
    with _BOARD_LOCK:
        board = _read_board()
        ticket = _ticket_or_none(board, ticket_id)
        if ticket is None:
            raise KeyError("Задача не найдена")
        _ensure_open(ticket)
        if "task_type" in fields:
            ticket["task_type"] = _parse_task_type(fields.get("task_type", ""))
        if "directorate" in fields:
            ticket["directorate"] = _parse_directorate(fields.get("directorate", ""))
        if "row_count" in fields:
            ticket["row_count"] = _parse_rows(fields.get("row_count", ""))
        if "complexity" in fields:
            complexity = fields.get("complexity", "").strip()
            if complexity not in COMPLEXITY:
                raise ValueError("Выберите уровень сложности")
            ticket["complexity"] = complexity
        if "comment" in fields:
            ticket["comment"] = _parse_text(fields.get("comment"), "Комментарий")
        if "lead_comment" in fields:
            ticket["lead_comment"] = _parse_text(fields.get("lead_comment"), "Комментарий лида")
        if upload:
            _replace_file(ticket, upload)
        ticket["updated_at"] = _now()
        storage.save(board)
        return {"ticket": _public(ticket, board)}


def move_ticket(ticket_id: str, column_id: str) -> dict:
    with _BOARD_LOCK:
        board = _read_board()
        ticket = _ticket_or_none(board, ticket_id)
        column = _column_or_none(board, column_id)
        if ticket is None:
            raise KeyError("Задача не найдена")
        if column is None:
            raise ValueError("Колонка сотрудника не найдена")
        _ensure_open(ticket)
        if column.get("hidden"):
            raise ValueError("Скрытому сотруднику задачу не назначают")
        if ticket.get("column_id"):
            raise ValueError("Тикет уже назначен сотруднику. Перенос другому запрещён, чтобы не менять начало проработки.")
        status_from = ticket.get("status")
        assignee_from = _assignee(board, ticket)
        ticket["column_id"] = column_id
        ticket["status"] = "Назначен отв."
        now = _now()
        ticket["started_at"] = ticket.get("started_at") or now
        ticket["updated_at"] = now
        _log(ticket, status_from, ticket["status"], assignee_from, column["name"])
        storage.save(board)
        db_result = _persist(ticket, board, insert=False)
        return {"ticket": _public(ticket, board), "db": db_result}


def cancel_ticket(ticket_id: str, comment_raw: str) -> dict:
    comment = _parse_text(comment_raw, "Комментарий отмены")
    with _BOARD_LOCK:
        board = _read_board()
        ticket = _ticket_or_none(board, ticket_id)
        if ticket is None:
            raise KeyError("Задача не найдена")
        _ensure_open(ticket)
        status_from = ticket.get("status")
        assignee_from = _assignee(board, ticket)
        pause_db = _close_open_pause(ticket)
        for name in NUMBER_FIELDS.values():
            ticket[name] = None
        ticket["cancel_comment"] = comment or None
        ticket["status"] = "Отменено"
        ticket["updated_at"] = _now()
        _log(ticket, status_from, "Отменено", assignee_from, assignee_from, comment or None)
        storage.save(board)
        db_result = _persist(ticket, board, insert=False)
        return {"ticket": _public(ticket, board), "db": db_result, "pause_db": pause_db}


def start_work_ticket(ticket_id: str) -> dict:
    with _BOARD_LOCK:
        board = _read_board()
        ticket = _ticket_or_none(board, ticket_id)
        if ticket is None:
            raise KeyError("Задача не найдена")
        if not ticket.get("column_id"):
            raise ValueError("Сначала перенесите задачу сотруднику")
        _ensure_open(ticket)
        if ticket.get("status") not in ("Назначен отв.",):
            if ticket.get("status") == "Выполняется":
                raise ValueError("Проработка уже начата")
            if ticket.get("status") == "Пауза":
                raise ValueError("Сначала нажмите «Возобновить»")
            raise ValueError("Нельзя начать выполнение для этой карточки")
        if ticket.get("work_started_at"):
            raise ValueError("Проработка уже начата")
        _assert_single_executing(board, ticket)
        now = _now()
        status_from = ticket.get("status")
        assignee = _assignee(board, ticket)
        ticket["work_started_at"] = now
        ticket["status"] = "Выполняется"
        ticket["updated_at"] = now
        _log(ticket, status_from, "Выполняется", assignee, assignee)
        storage.save(board)
        db_result = _persist(ticket, board, insert=False)
        return {"ticket": _public(ticket, board), "db": db_result}


def pause_ticket(ticket_id: str) -> dict:
    with _BOARD_LOCK:
        board = _read_board()
        ticket = _ticket_or_none(board, ticket_id)
        if ticket is None:
            raise KeyError("Задача не найдена")
        if ticket.get("status") != "Выполняется":
            raise ValueError("Пауза доступна только для статуса «Выполняется»")
        _ensure_open(ticket)
        now = _now()
        status_from = ticket.get("status")
        assignee = _assignee(board, ticket)
        if not db.writing_enabled():
            raise ValueError("Пауза недоступна без записи в DGDWH")
        pause_id = db.open_pause(int(ticket["record_id"]), now)
        ticket["open_pause_id"] = pause_id
        pause_db = {"saved": True, "error": None, "pause_id": pause_id}
        ticket["status"] = "Пауза"
        ticket["updated_at"] = now
        _log(ticket, status_from, "Пауза", assignee, assignee)
        storage.save(board)
        db_result = _persist(ticket, board, insert=False)
        return {"ticket": _public(ticket, board), "db": db_result, "pause_db": pause_db}


def resume_ticket(ticket_id: str) -> dict:
    with _BOARD_LOCK:
        board = _read_board()
        ticket = _ticket_or_none(board, ticket_id)
        if ticket is None:
            raise KeyError("Задача не найдена")
        if ticket.get("status") != "Пауза":
            raise ValueError("Возобновить можно только тикет на паузе")
        if not ticket.get("open_pause_id"):
            raise ValueError("Нет открытой записи паузы для этого тикета")
        _ensure_open(ticket)
        _assert_single_executing(board, ticket)
        now = _now()
        status_from = ticket.get("status")
        assignee = _assignee(board, ticket)
        pause_db = _close_open_pause(ticket)
        ticket["status"] = "Выполняется"
        ticket["updated_at"] = now
        _log(ticket, status_from, "Выполняется", assignee, assignee)
        storage.save(board)
        db_result = _persist(ticket, board, insert=False)
        return {"ticket": _public(ticket, board), "db": db_result, "pause_db": pause_db}


def _parse_document_number(raw: str) -> str:
    # Потенциальный коннектор: номер позже выбирается из документов Postgres
    # Байер Про. Пока его вводит пользователь при закрытии.
    number = (raw or "").strip()
    if not number:
        raise ValueError("Укажите номер документа")
    if len(number) > 100:
        raise ValueError("Номер документа: не больше 100 символов")
    return number


def complete_ticket(ticket_id: str, document_number: str) -> dict:
    number = _parse_document_number(document_number)
    with _BOARD_LOCK:
        board = _read_board()
        ticket = _ticket_or_none(board, ticket_id)
        if ticket is None:
            raise KeyError("Задача не найдена")
        if not ticket.get("column_id"):
            raise ValueError("Сначала перенесите задачу сотруднику")
        _ensure_open(ticket)
        if not ticket.get("work_started_at"):
            raise ValueError("Сначала нажмите «Начать выполнение»")
        if ticket.get("status") not in ("Выполняется", "Пауза"):
            raise ValueError("Закрыть можно только выполняемую или приостановленную задачу")
        status_from = ticket.get("status")
        assignee_from = _assignee(board, ticket)
        pause_db = _close_open_pause(ticket) if ticket.get("status") == "Пауза" else None
        now = _now()
        field = NUMBER_FIELDS.get(ticket.get("task_type") or "")
        if field:
            ticket[field] = number
        ticket["document_number"] = number
        ticket["status"] = "Выполнено"
        ticket["finished_at"] = ticket.get("finished_at") or now
        ticket["updated_at"] = now
        _log(ticket, status_from, "Выполнено", assignee_from, assignee_from)
        storage.save(board)
        db_result = _persist(ticket, board, insert=False)
        return {"ticket": _public(ticket, board), "db": db_result, "pause_db": pause_db}


def add_column(name: str) -> dict:
    clean = " ".join((name or "").split())
    if len(clean) < 2:
        raise ValueError("Укажите ФИО сотрудника")
    if len(clean) > 120:
        raise ValueError("ФИО слишком длинное")
    with _BOARD_LOCK:
        board = _read_board()
        if any(item["name"].casefold() == clean.casefold() for item in board["columns"]):
            raise ValueError("Такой сотрудник уже есть на доске")
        column = {"id": uuid.uuid4().hex, "name": clean, "hidden": False}
        board["columns"].append(column)
        storage.save(board)
        return column


def delete_column(column_id: str) -> None:
    raise ValueError("Колонку нельзя удалить. Её можно скрыть.")


def set_column_hidden(column_id: str, hidden: bool) -> dict:
    with _BOARD_LOCK:
        board = _read_board()
        column = _column_or_none(board, column_id)
        if column is None:
            raise KeyError("Колонка не найдена")
        column["hidden"] = hidden
        storage.save(board)
        return column


def _attach(ticket: dict, upload: tuple[str, bytes]) -> None:
    original, content = upload
    suffix = Path(original).suffix.lower()
    if suffix not in FILE_EXT:
        raise ValueError("Можно прикрепить Excel или Word")
    if len(content) > MAX_FILE:
        raise ValueError("Файл больше 25 МБ")
    if not content:
        raise ValueError("Файл пустой")
    stored = f"{uuid.uuid4().hex}{suffix}"
    storage.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (storage.UPLOAD_DIR / stored).write_bytes(content)
    ticket["file_name"] = Path(original).name
    ticket["stored_file"] = stored


def _replace_file(ticket: dict, upload: tuple[str, bytes]) -> None:
    previous = ticket.get("stored_file")
    _attach(ticket, upload)
    if previous:
        path = storage.UPLOAD_DIR / previous
        if path.exists():
            path.unlink()


def _stored_path(file_id: str) -> Path | None:
    if not re.fullmatch(r"[a-f0-9]{32}\.(xlsx|xls|xlsm|docx|doc)", file_id):
        return None
    path = storage.UPLOAD_DIR / file_id
    return path if path.exists() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "KanbanBoard/1.0"

    def _api_path(self) -> str:
        return urlparse(self.path).path.rstrip("/")

    def log_message(self, fmt: str, *args) -> None:
        print("[kanban]", fmt % args)

    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Ожидался объект JSON")
        return data

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        return self.rfile.read(length) if length else b""

    def _read_form(self) -> tuple[dict, tuple[str, bytes] | None]:
        content_type = self.headers.get("Content-Type", "")
        body = self._read_body()
        message = BytesParser(policy=email_default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
        fields: dict[str, str] = {}
        upload = None
        if not message.is_multipart():
            return fields, upload
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                upload = (filename, payload)
            elif name:
                fields[name] = payload.decode("utf-8", "replace")
        return fields, upload

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            page = (STATIC / "index.html").read_bytes()
            self._send(200, page, "text/html; charset=utf-8")
            return
        if path.rstrip("/") == "/Data_Processing_Department":
            self._redirect("/")
            return
        if path.startswith("/static/"):
            name = unquote(path[len("/static/"):])
            file_path = (STATIC / name).resolve()
            if not str(file_path).startswith(str(STATIC.resolve())) or not file_path.is_file():
                self._json(404, {"error": "Не найдено"})
                return
            kind = "text/css; charset=utf-8" if file_path.suffix == ".css" else "text/javascript; charset=utf-8"
            self._send(200, file_path.read_bytes(), kind)
            return
        if path.startswith("/files/"):
            self._download(unquote(path[len("/files/"):]).split("/")[0])
            return
        if path == "/api/board":
            board = _read_board()
            self._json(200, {
                "columns": board["columns"],
                "tickets": [_public(item, board) for item in board["tickets"]],
            })
            return
        if path == "/api/health":
            ok, error = db.check_connection()
            info = db.schema_info()
            self._json(
                200,
                {
                    "db": ok,
                    "error": error,
                    "enabled": db.writing_enabled(),
                    "schema": info,
                    "app_dir": str(ROOT),
                    "api_build": API_BUILD,
                    "ticket_actions": [
                        "move",
                        "done",
                        "cancel",
                        "start-work",
                        "pause",
                        "resume",
                        "file",
                    ],
                },
            )
            return
        if path == "/api/share":
            self._json(200, {"urls": share_urls()})
            return
        self._json(404, {"error": "Не найдено"})

    def _download(self, ticket_id: str) -> None:
        board = _read_board()
        ticket = _ticket_or_none(board, ticket_id)
        file_id = ticket.get("stored_file") if ticket else None
        path = _stored_path(file_id) if file_id else None
        if path is None or ticket is None:
            self._json(404, {"error": "Файл не найден"})
            return
        name = ticket.get("file_name") or path.name
        encoded = name.encode("utf-8").decode("latin-1", "replace")
        self._send(
            200,
            path.read_bytes(),
            "application/octet-stream",
            {"Content-Disposition": f"attachment; filename*=UTF-8''{quote_name(name)}; filename=\"{encoded}\""},
        )

    def do_POST(self) -> None:  # noqa: N802
        path = self._api_path()
        try:
            if path == "/api/tickets":
                fields, upload = self._read_form()
                self._json(201, create_ticket(fields, upload))
                return
            if path == "/api/columns":
                data = self._read_json()
                self._json(201, add_column(data.get("name", "")))
                return
            column_match = re.fullmatch(r"/api/columns/([a-f0-9]{32})/(hide|show)", path)
            if column_match:
                self._json(200, set_column_hidden(column_match.group(1), column_match.group(2) == "hide"))
                return
            match = TICKET_ACTION_RE.match(path)
            if match:
                ticket_id, action = match.group(1).lower(), match.group(2).lower()
                if action == "move":
                    data = self._read_json()
                    self._json(200, move_ticket(ticket_id, data.get("column_id", "")))
                    return
                if action == "done":
                    data = self._read_json()
                    self._json(200, complete_ticket(ticket_id, data.get("document_number", "")))
                    return
                if action == "cancel":
                    data = self._read_json()
                    self._json(200, cancel_ticket(ticket_id, data.get("cancel_comment", "")))
                    return
                if action == "start-work":
                    self._json(200, start_work_ticket(ticket_id))
                    return
                if action == "pause":
                    self._json(200, pause_ticket(ticket_id))
                    return
                if action == "resume":
                    self._json(200, resume_ticket(ticket_id))
                    return
                fields, upload = self._read_form()
                if upload is None:
                    raise ValueError("Файл не выбран")
                self._json(200, update_ticket(ticket_id, {}, upload))
                return
            print(f"[kanban] POST 404: {path}", flush=True)
            self._json(404, {"error": "Не найдено", "path": path, "api_build": API_BUILD})
        except KeyError as exc:
            self._json(404, {"error": str(exc)})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        match = re.fullmatch(r"/api/tickets/([a-f0-9]{32})", path)
        if not match:
            self._json(404, {"error": "Не найдено"})
            return
        try:
            content_type = self.headers.get("Content-Type", "")
            if content_type.startswith("multipart/form-data"):
                fields, upload = self._read_form()
            else:
                fields, upload = self._read_json(), None
            self._json(200, update_ticket(match.group(1), fields, upload))
        except KeyError as exc:
            self._json(404, {"error": str(exc)})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        match = re.fullmatch(r"/api/columns/([a-f0-9]{32})", path)
        if not match:
            self._json(404, {"error": "Не найдено"})
            return
        try:
            delete_column(match.group(1))
            self._json(200, {"ok": True})
        except KeyError as exc:
            self._json(404, {"error": str(exc)})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})


def quote_name(name: str) -> str:
    from urllib.parse import quote

    return quote(name)


def _ipv4_candidates() -> list[str]:
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("1.1.1.1", 80))
        found.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    return list(dict.fromkeys(found))


def _share_rank(ip: str) -> tuple[int, str]:
    # Адреса виртуальных адаптеров не открываются у коллег в офисной сети.
    if ip.startswith("127.") or ip.startswith("169.254."):
        return (9, ip)
    if ip.startswith("192.168.56.") or ip.startswith("192.168.122."):
        return (5, ip)
    return (0, ip)


def share_urls() -> list[str]:
    ips = [ip for ip in _ipv4_candidates() if not ip.startswith("127.")]
    ips.sort(key=_share_rank)
    usable = [ip for ip in ips if _share_rank(ip)[0] == 0] or ips
    return [f"http://{ip}:{PORT}/" for ip in usable]


def main() -> None:
    storage.ensure_dirs()
    schema = db.schema_info()
    print(f"Данные доски: {storage.DATA_DIR}", flush=True)
    print(f"Модуль БД: {schema['module_file']}", flush=True)
    print(f"Схема SQL: {schema['tag']}", flush=True)
    print(f"API: {API_BUILD} (pause, resume)", flush=True)
    if schema.get("legacy_column_names"):
        print("ОШИБКА: в db.py остались старые имена [начало]/[конец]. Обновите файл.", flush=True)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    local = f"http://127.0.0.1:{PORT}/"
    print(f"Канбан у вас: {local}", flush=True)
    shared = share_urls()
    if shared:
        print("Ссылка для коллег:", flush=True)
        for url in shared:
            print(f"  {url}", flush=True)
    else:
        print("Адрес в сети не определился. Коллегам нужен IP этого компьютера и порт 8765.", flush=True)
    if os.environ.get("KANBAN_NO_BROWSER") != "1":
        threading.Timer(0.4, lambda: webbrowser.open(local)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
