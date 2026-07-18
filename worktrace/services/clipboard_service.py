from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta

from ..constants import CLIPBOARD_RETENTION_DAYS, STATUS_NORMAL, TIME_FORMAT
from ..data_generation_repository import DataGenerationNamespace
from ..db import now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..platforms.base import ActiveWindow
from . import project_inference_service
from .settings_service import get_bool_setting


def _report_uow() -> DomainUnitOfWork:
    return DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,))


def is_capture_enabled() -> bool:
    return get_bool_setting("clipboard_capture_enabled", False)


def record_clipboard_event(
    activity_id: int,
    text: str,
    source_window: ActiveWindow,
    copied_at: str | None = None,
    sequence_number: int | None = None,
) -> int | None:
    copied_text = str(text or "")
    if not copied_text:
        return None
    copied_time = copied_at or now_str()
    text_hash = _hash_text(copied_text)
    ts = now_str()
    with _report_uow() as uow:
        conn = uow.connection
        # This transaction-local check is the final privacy gate. It rejects an
        # event that was already drained from the adapter when the user disabled
        # capture before persistence.
        if not _capture_enabled_in_transaction(conn):
            return None
        activity = conn.execute(
            "SELECT id, status FROM activity_log WHERE id = ? AND is_deleted = 0",
            (activity_id,),
        ).fetchone()
        if not activity or activity["status"] != STATUS_NORMAL:
            return None
        existing = _find_duplicate_event(
            conn,
            int(activity_id),
            copied_time,
            text_hash,
            sequence_number,
        )
        if existing is not None:
            return existing
        cur = conn.execute(
            """
            INSERT INTO activity_clipboard_event(
                activity_id, copied_at, app_name, process_name, window_title,
                file_path_hint, copied_text, text_hash, text_length,
                clipboard_sequence, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(activity_id),
                copied_time,
                source_window.app_name or "",
                source_window.process_name or "",
                source_window.window_title or "",
                source_window.file_path_hint,
                copied_text,
                text_hash,
                len(copied_text),
                sequence_number,
                ts,
                ts,
            ),
        )
        event_id = int(cur.lastrowid)
        uow.mark_changed()
    # Open rows are refreshed immediately. If this derivation fails, the normal
    # close transaction will durably enqueue the final nonmanual activity facts.
    _attempt_clipboard_inference(int(activity_id))
    return event_id


def _capture_enabled_in_transaction(conn) -> bool:
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'clipboard_capture_enabled'"
    ).fetchone()
    if row is None:
        return False
    return str(row["value"] or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def prune_old_events(
    retention_days: int = CLIPBOARD_RETENTION_DAYS,
    now: str | None = None,
) -> int:
    cutoff = _retention_cutoff(retention_days, now)
    with _report_uow() as uow:
        cur = uow.connection.execute(
            "DELETE FROM activity_clipboard_event WHERE copied_at < ?",
            (cutoff,),
        )
        return int(cur.rowcount or 0)


def _find_duplicate_event(
    conn,
    activity_id: int,
    copied_at: str,
    text_hash: str,
    sequence_number: int | None,
) -> int | None:
    if sequence_number is not None:
        row = conn.execute(
            """
            SELECT id
            FROM activity_clipboard_event
            WHERE clipboard_sequence = ?
              AND activity_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (sequence_number, activity_id),
        ).fetchone()
        if row:
            return int(row["id"])
    row = conn.execute(
        """
        SELECT id
        FROM activity_clipboard_event
        WHERE activity_id = ?
          AND copied_at = ?
          AND text_hash = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (activity_id, copied_at, text_hash),
    ).fetchone()
    return int(row["id"]) if row else None


def _attempt_clipboard_inference(activity_id: int) -> None:
    try:
        project_inference_service.assign_project_for_activity(activity_id)
    except Exception:
        logging.exception(
            "clipboard inference failed; close-time durable retry will converge activity_id=%s",
            activity_id,
        )


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _retention_cutoff(retention_days: int, now: str | None) -> str:
    if now:
        base = datetime.strptime(now, TIME_FORMAT)
    else:
        base = datetime.now()
    return (base - timedelta(days=max(0, int(retention_days)))).strftime(
        TIME_FORMAT
    )
