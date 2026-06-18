from __future__ import annotations

import logging
from datetime import datetime

from ..constants import STATUS_ERROR, TIME_FORMAT
from ..db import get_connection, now_str
from .settings_service import get_setting


def recover_unclosed_records() -> None:
    heartbeat = get_setting("last_collector_heartbeat", "") or ""
    fallback_now = now_str()
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
                SET end_time = ?, duration_seconds = ?, status = ?, is_confirmed = 0, updated_at = ?
                WHERE id = ?
                """,
                (end_time, duration, status, now_str(), row["id"]),
            )
            logging.info("recovered unclosed record id=%s status=%s", row["id"], status)


def detect_time_jump(last_loop_time: str, now: str, threshold_minutes: int = 5) -> bool:
    try:
        last_dt = datetime.strptime(last_loop_time, TIME_FORMAT)
        now_dt = datetime.strptime(now, TIME_FORMAT)
    except ValueError:
        return True
    return (now_dt - last_dt).total_seconds() > max(1, threshold_minutes) * 60


def mark_record_error(activity_id: int, reason: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE activity_log
            SET status = ?, is_confirmed = 0, note = COALESCE(note || CHAR(10), '') || ?, updated_at = ?
            WHERE id = ?
            """,
            (STATUS_ERROR, f"系统标记异常：{reason}", now_str(), activity_id),
        )
    logging.warning("marked activity id=%s error reason=%s", activity_id, reason)
