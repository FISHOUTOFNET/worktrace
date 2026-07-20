"""Durable scheduling state for closed-activity project inference.

This module is the sole runtime DML owner for ``activity_inference_job``.
Activity facts and their inference jobs are created in the same caller-owned
transaction. Consumers complete assignments and delete jobs atomically.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable

from ..constants import TIME_FORMAT
from ..db import now_str
from ..write_gate import DATABASE_MAINTENANCE_ERROR
from .activity_inference_policy import is_closed_activity_inference_eligible


class InferenceJobReason(str, Enum):
    CLOSED_ACTIVITY = "closed_activity"


class InferenceJobStatus(str, Enum):
    PENDING = "pending"
    FAILED = "failed"


class InferenceFailureCode(str, Enum):
    DATA_REPAIR_REQUIRED = "data_repair_required"
    DATABASE_BUSY = "database_busy"
    DATABASE_GENERATION_CHANGED = "database_generation_changed"
    DATABASE_MAINTENANCE_IN_PROGRESS = DATABASE_MAINTENANCE_ERROR
    UNEXPECTED_FAILURE = "unexpected_failure"


def enqueue_closed_activity_ids(
    conn,
    activity_ids: Iterable[int],
    *,
    reason: InferenceJobReason = InferenceJobReason.CLOSED_ACTIVITY,
    at_time: str | None = None,
) -> int:
    """Insert missing jobs for activities accepted by the canonical policy."""

    if reason is not InferenceJobReason.CLOSED_ACTIVITY:
        raise TypeError("inference_job_reason_required")
    ids = sorted({int(activity_id) for activity_id in activity_ids})
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT activity.id,
               activity.end_time,
               activity.status,
               activity.is_hidden,
               activity.is_deleted,
               assignment.activity_id AS assignment_activity_id,
               assignment.is_manual,
               assignment.source
        FROM activity_log activity
        LEFT JOIN activity_project_assignment assignment
          ON assignment.activity_id = activity.id
        WHERE activity.id IN ({placeholders})
        ORDER BY activity.id
        """,
        tuple(ids),
    ).fetchall()
    eligible_ids = [
        int(row["id"])
        for row in rows
        if is_closed_activity_inference_eligible(
            row,
            None if row["assignment_activity_id"] is None else row,
        )
    ]
    if not eligible_ids:
        return 0

    at = str(at_time or now_str())
    inserted = 0
    for activity_id in eligible_ids:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO activity_inference_job(
                activity_id, reason, status, attempt_count, next_attempt_at,
                last_error_code, created_at, updated_at
            ) VALUES (?, ?, ?, 0, NULL, NULL, ?, ?)
            """,
            (
                activity_id,
                reason.value,
                InferenceJobStatus.PENDING.value,
                at,
                at,
            ),
        )
        inserted += max(0, int(cursor.rowcount or 0))
    return inserted


def list_runnable_jobs(
    conn,
    *,
    limit: int = 100,
    at_time: str | None = None,
    activity_ids: Iterable[int] | None = None,
) -> list[dict[str, object]]:
    """Return a bounded deterministic set of due jobs without mutating them."""

    normalized_limit = max(0, int(limit))
    if normalized_limit == 0:
        return []
    at = str(at_time or now_str())
    requested = (
        sorted({int(activity_id) for activity_id in activity_ids})
        if activity_ids is not None
        else None
    )
    clauses = [
        "status IN (?, ?)",
        "(next_attempt_at IS NULL OR next_attempt_at <= ?)",
    ]
    parameters: list[object] = [
        InferenceJobStatus.PENDING.value,
        InferenceJobStatus.FAILED.value,
        at,
    ]
    if requested is not None:
        if not requested:
            return []
        placeholders = ",".join("?" for _ in requested)
        clauses.append(f"activity_id IN ({placeholders})")
        parameters.extend(requested)
    parameters.append(normalized_limit)
    rows = conn.execute(
        f"""
        SELECT activity_id, reason, status, attempt_count,
               next_attempt_at, last_error_code
        FROM activity_inference_job
        WHERE {' AND '.join(clauses)}
        ORDER BY activity_id
        LIMIT ?
        """,
        tuple(parameters),
    ).fetchall()
    return [dict(row) for row in rows]


def read_activity_and_assignment(conn, activity_id: int):
    """Read the facts required by the canonical eligibility policy."""

    return conn.execute(
        """
        SELECT activity.id,
               activity.end_time,
               activity.status,
               activity.is_hidden,
               activity.is_deleted,
               assignment.activity_id AS assignment_activity_id,
               assignment.is_manual,
               assignment.source
        FROM activity_log activity
        LEFT JOIN activity_project_assignment assignment
          ON assignment.activity_id = activity.id
        WHERE activity.id = ?
        """,
        (int(activity_id),),
    ).fetchone()


def delete_job(conn, activity_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM activity_inference_job WHERE activity_id = ?",
        (int(activity_id),),
    )
    return cursor.rowcount == 1


def record_failure(
    conn,
    activity_id: int,
    error_code: InferenceFailureCode,
    *,
    at_time: str | None = None,
) -> int:
    """Persist a bounded exponential retry schedule and return attempt count."""

    if not isinstance(error_code, InferenceFailureCode):
        raise TypeError("inference_failure_code_required")
    at = str(at_time or now_str())
    row = conn.execute(
        "SELECT attempt_count FROM activity_inference_job WHERE activity_id = ?",
        (int(activity_id),),
    ).fetchone()
    if row is None:
        return 0
    attempts = max(0, int(row["attempt_count"] or 0)) + 1
    delay_seconds = min(3600, 2 ** min(attempts, 11))
    try:
        next_attempt = (
            datetime.strptime(at, TIME_FORMAT) + timedelta(seconds=delay_seconds)
        ).strftime(TIME_FORMAT)
    except (TypeError, ValueError):
        next_attempt = at
    conn.execute(
        """
        UPDATE activity_inference_job
        SET status = ?, attempt_count = ?, next_attempt_at = ?,
            last_error_code = ?, updated_at = ?
        WHERE activity_id = ?
        """,
        (
            InferenceJobStatus.FAILED.value,
            attempts,
            next_attempt,
            error_code.value,
            at,
            int(activity_id),
        ),
    )
    return attempts


def clear_all_jobs(conn) -> int:
    """Clear all inference progress inside the caller-owned transaction."""

    cursor = conn.execute("DELETE FROM activity_inference_job")
    return max(0, int(cursor.rowcount or 0))


__all__ = [
    "InferenceFailureCode",
    "InferenceJobReason",
    "InferenceJobStatus",
    "clear_all_jobs",
    "delete_job",
    "enqueue_closed_activity_ids",
    "list_runnable_jobs",
    "read_activity_and_assignment",
    "record_failure",
]
