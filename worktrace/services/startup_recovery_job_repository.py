"""Durable progress owner for bounded cross-midnight startup recovery."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from ..constants import TIME_FORMAT
from ..db import now_str


class RecoveryFailureCode(str, Enum):
    DATABASE_BUSY = "database_busy"
    DATABASE_GENERATION_CHANGED = "database_generation_changed"
    SECURE_IMPORT_IN_PROGRESS = "secure_import_in_progress"
    UNEXPECTED_FAILURE = "unexpected_failure"


def enqueue_continuation(
    conn,
    *,
    source_activity_id: int,
    cursor_time: str,
    end_time: str,
    source: str,
    activity_status: str,
    app_name: str,
    process_name: str,
    window_title: str,
    file_path_hint: str | None,
    project_id: int | None,
    at_time: str | None = None,
) -> int:
    timestamp = str(at_time or now_str())
    cursor = conn.execute(
        """
        INSERT INTO startup_recovery_job(
            source_activity_id, cursor_time, end_time, source,
            activity_status, app_name, process_name, window_title,
            file_path_hint, project_id, status, attempt_count,
            next_attempt_at, last_error_code, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, ?, ?)
        ON CONFLICT(source_activity_id) DO NOTHING
        """,
        (
            int(source_activity_id),
            str(cursor_time),
            str(end_time),
            str(source),
            str(activity_status),
            str(app_name or ""),
            str(process_name or ""),
            str(window_title or ""),
            None if file_path_hint is None else str(file_path_hint),
            None if project_id is None else int(project_id),
            timestamp,
            timestamp,
        ),
    )
    return max(0, int(cursor.rowcount or 0))


def list_runnable_jobs(
    conn,
    *,
    limit: int = 1,
    at_time: str | None = None,
) -> list[dict[str, object]]:
    normalized_limit = max(0, int(limit))
    if normalized_limit == 0:
        return []
    timestamp = str(at_time or now_str())
    rows = conn.execute(
        """
        SELECT *
        FROM startup_recovery_job
        WHERE status IN ('pending', 'failed')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY id
        LIMIT ?
        """,
        (timestamp, normalized_limit),
    ).fetchall()
    return [dict(row) for row in rows]


def advance_job(
    conn,
    *,
    job_id: int,
    cursor_time: str,
    completed: bool,
    at_time: str | None = None,
) -> None:
    if completed:
        cursor = conn.execute(
            "DELETE FROM startup_recovery_job WHERE id = ?",
            (int(job_id),),
        )
        if cursor.rowcount != 1:
            raise ValueError("startup_recovery_job_missing")
        return
    timestamp = str(at_time or now_str())
    cursor = conn.execute(
        """
        UPDATE startup_recovery_job
        SET cursor_time = ?, status = 'pending', attempt_count = 0,
            next_attempt_at = NULL, last_error_code = NULL, updated_at = ?
        WHERE id = ?
        """,
        (str(cursor_time), timestamp, int(job_id)),
    )
    if cursor.rowcount != 1:
        raise ValueError("startup_recovery_job_missing")


def record_failure(
    conn,
    *,
    job_id: int,
    error_code: RecoveryFailureCode,
    at_time: str | None = None,
) -> int:
    if not isinstance(error_code, RecoveryFailureCode):
        raise TypeError("startup_recovery_failure_code_required")
    timestamp = str(at_time or now_str())
    row = conn.execute(
        "SELECT attempt_count FROM startup_recovery_job WHERE id = ?",
        (int(job_id),),
    ).fetchone()
    if row is None:
        return 0
    attempts = max(0, int(row["attempt_count"] or 0)) + 1
    delay_seconds = min(3600, 2 ** min(attempts, 11))
    try:
        next_attempt = (
            datetime.strptime(timestamp, TIME_FORMAT) + timedelta(seconds=delay_seconds)
        ).strftime(TIME_FORMAT)
    except (TypeError, ValueError):
        next_attempt = timestamp
    conn.execute(
        """
        UPDATE startup_recovery_job
        SET status = 'failed', attempt_count = ?, next_attempt_at = ?,
            last_error_code = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            attempts,
            next_attempt,
            error_code.value,
            timestamp,
            int(job_id),
        ),
    )
    return attempts


def clear_all_jobs(conn) -> int:
    """Clear replacement-invalid progress through the sole runtime DML owner."""

    cursor = conn.execute("DELETE FROM startup_recovery_job")
    return max(0, int(cursor.rowcount or 0))


__all__ = [
    "RecoveryFailureCode",
    "advance_job",
    "clear_all_jobs",
    "enqueue_continuation",
    "list_runnable_jobs",
    "record_failure",
]
