from __future__ import annotations

import logging
from datetime import datetime

from ..constants import STATUS_ERROR, TIME_FORMAT
from ..db import get_connection, now_str
from . import session_boundary_service
from .settings_service import get_setting, set_setting


def recover_unclosed_records() -> None:
    heartbeat = get_setting("last_collector_heartbeat", "") or ""
    fallback_now = now_str()
    recovered_boundary_at: str | None = None
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM activity_log WHERE end_time IS NULL ORDER BY id").fetchall()
        for row in rows:
            end_time = heartbeat or fallback_now
            status = row["status"] if heartbeat else STATUS_ERROR
            try:
                duration = int(
                    (
                        datetime.strptime(end_time, TIME_FORMAT)
                        - datetime.strptime(row["start_time"], TIME_FORMAT)
                    ).total_seconds()
                )
            except ValueError:
                duration = 0
                status = STATUS_ERROR
            if duration < 0:
                duration = 0
                status = STATUS_ERROR
                end_time = fallback_now
            conn.execute(
                """
                UPDATE activity_log
                SET end_time = ?, duration_seconds = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (end_time, duration, status, now_str(), row["id"]),
            )
            recovered_boundary_at = end_time
            logging.info("recovered unclosed record id=%s status=%s", row["id"], status)
    if recovered_boundary_at:
        session_boundary_service.record_boundary(recovered_boundary_at, "recovered")
        set_setting("current_activity_snapshot", "")
        set_setting("pending_short_seconds", "0")
    record_restart_boundary_if_needed()


def record_restart_boundary_if_needed() -> None:
    candidate = _latest_known_shutdown_boundary()
    if not candidate:
        return
    if session_boundary_service.has_boundary_between(candidate, candidate):
        return
    session_boundary_service.record_boundary(candidate, "restart")


def _latest_known_shutdown_boundary() -> str | None:
    candidates = [
        get_setting("last_shutdown_at", "") or "",
        get_setting("last_collector_heartbeat", "") or "",
    ]
    parsed: list[tuple[datetime, str]] = []
    for candidate in candidates:
        try:
            parsed.append((datetime.strptime(candidate, TIME_FORMAT), candidate))
        except ValueError:
            continue
    if not parsed:
        return None
    now = datetime.strptime(now_str(), TIME_FORMAT)
    past_candidates = [item for item in parsed if item[0] <= now]
    if not past_candidates:
        return None
    return max(past_candidates, key=lambda item: item[0])[1]


def detect_time_jump(last_loop_time: str, now: str, threshold_seconds: int = 300) -> bool:
    try:
        last_dt = datetime.strptime(last_loop_time, TIME_FORMAT)
        now_dt = datetime.strptime(now, TIME_FORMAT)
    except ValueError:
        return True
    return (now_dt - last_dt).total_seconds() > max(1, threshold_seconds)


def mark_record_error(activity_id: int, reason: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE activity_log
            SET status = ?, note = COALESCE(note || CHAR(10), '') || ?, updated_at = ?
            WHERE id = ?
            """,
            (STATUS_ERROR, f"系统标记异常：{reason}", now_str(), activity_id),
        )
    logging.warning("marked activity id=%s error reason=%s", activity_id, reason)
