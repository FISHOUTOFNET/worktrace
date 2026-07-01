from __future__ import annotations

import logging
from datetime import datetime, time as datetime_time, timedelta

from ..constants import STATUS_ERROR, STATUS_NORMAL, TIME_FORMAT
from ..db import get_connection, now_str
from . import project_service, session_boundary_service
from .activity_lifecycle_service import recover_close_activity, recover_cross_midnight_segment, recover_first_half_close
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
        start_dt = _parse_time(row["start_time"])
        end_dt = _parse_time(end_time)
        if start_dt and end_dt and status != STATUS_ERROR and end_dt.date() > start_dt.date():
            recovered_boundary_at = _recover_cross_midnight_row(row, end_dt)
            logging.info("recovered cross-midnight unclosed record id=%s", row["id"])
            continue
        # Non-cross-midnight recovery: route through the lifecycle facade so
        # the close-finalize helper converges project inference / automatic
        # rules on the recovered row. Previously this was a direct SQL UPDATE
        # that bypassed project inference entirely, leaving recovered rows in
        # the "uncategorized" assignment even when a concrete inferred project
        # was available.
        recover_close_activity(
            int(row["id"]),
            end_time,
            duration_seconds=duration,
            status=status,
        )
        recovered_boundary_at = end_time
        logging.info("recovered unclosed record id=%s status=%s", row["id"], status)
    if recovered_boundary_at:
        session_boundary_service.record_boundary(recovered_boundary_at, "recovered")
        set_setting("current_activity_snapshot", "")
        set_setting("pending_short_seconds", "0")
    record_restart_boundary_if_needed()


def _recover_cross_midnight_row(row, end_dt: datetime) -> str:
    start_dt = datetime.strptime(row["start_time"], TIME_FORMAT)
    first_midnight = datetime.combine(start_dt.date() + timedelta(days=1), datetime_time.min)
    first_midnight_text = first_midnight.strftime(TIME_FORMAT)
    original_project_id = row["project_id"] if project_service.is_concrete_project_id(row["project_id"]) else None
    original_id = int(row["id"])
    # Close the first half of the original row at first_midnight via the
    # lifecycle facade so the close-finalize helper converges project
    # inference / automatic rules on it (verification item 9). Previously
    # this was a direct SQL UPDATE that bypassed project inference entirely,
    # leaving the first-half row in the "uncategorized" assignment.
    recover_first_half_close(
        original_id,
        first_midnight_text,
        duration_seconds=max(0, int((first_midnight - start_dt).total_seconds())),
    )
    current_start = first_midnight
    last_activity_id: int | None = None
    while current_start < end_dt:
        next_midnight = datetime.combine(current_start.date() + timedelta(days=1), datetime_time.min)
        current_end = min(end_dt, next_midnight)
        # Create + close each recovered cross-midnight segment via the
        # lifecycle facade so the open-row state machine has a single
        # owner (no second hand-rolled create/finalize/close sequence).
        # The midnight_anchor assignment is applied inside the facade when
        # status is NORMAL and a concrete project_id is available.
        payload = {
            "app_name": row["app_name"],
            "process_name": row["process_name"],
            "window_title": row["window_title"],
            "file_path_hint": row["file_path_hint"],
            "note": row["note"],
        }
        activity_id = recover_cross_midnight_segment(
            start_time=current_start.strftime(TIME_FORMAT),
            end_time=current_end.strftime(TIME_FORMAT),
            source=row["source"],
            status=row["status"],
            payload=payload,
            project_id=original_project_id,
        )
        session_boundary_service.record_boundary(current_start.strftime(TIME_FORMAT), "midnight")
        last_activity_id = activity_id
        current_start = current_end
    return end_dt.strftime(TIME_FORMAT) if last_activity_id is not None else first_midnight_text


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


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, TIME_FORMAT)
    except ValueError:
        return None


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
