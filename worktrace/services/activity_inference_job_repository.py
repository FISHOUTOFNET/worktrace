"""Durable scheduling state for closed-activity project inference.

This module is the sole DML owner for ``activity_inference_job``.  Activity
facts and their inference jobs are created in the same caller-owned transaction;
consumers may fail or the process may exit without losing the derivation request.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from ..constants import TIME_FORMAT
from ..db import now_str

JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_FAILED = "failed"

_ELIGIBLE_ASSIGNMENT_SOURCES = ("uncategorized", "suggested_project_name")


def enqueue_closed_activity_ids(
    conn,
    activity_ids: Iterable[int],
    *,
    at_time: str | None = None,
) -> int:
    """Insert missing jobs for eligible closed activities.

    Eligibility is evaluated from durable facts inside the caller's transaction.
    Manual and midnight-anchor assignments are never scheduled for inference.
    """

    ids = sorted({int(activity_id) for activity_id in activity_ids})
    if not ids:
        return 0
    at = str(at_time or now_str())
    placeholders = ",".join("?" for _ in ids)
    cursor = conn.execute(
        f"""
        INSERT OR IGNORE INTO activity_inference_job(
            activity_id, status, attempt_count, next_attempt_at,
            last_error_code, created_at, updated_at
        )
        SELECT
            activity.id, ?, 0, NULL, NULL, ?, ?
        FROM activity_log activity
        LEFT JOIN activity_project_assignment assignment
          ON assignment.activity_id = activity.id
        WHERE activity.id IN ({placeholders})
          AND activity.end_time IS NOT NULL
          AND activity.status = 'normal'
          AND activity.is_hidden = 0
          AND activity.is_deleted = 0
          AND (
                assignment.activity_id IS NULL
                OR (
                    assignment.is_manual = 0
                    AND assignment.source IN (?, ?)
                )
          )
        """,
        (
            JOB_PENDING,
            at,
            at,
            *ids,
            *_ELIGIBLE_ASSIGNMENT_SOURCES,
        ),
    )
    return max(0, int(cursor.rowcount or 0))


def seed_missing_jobs(conn, *, at_time: str | None = None) -> int:
    """Create jobs for eligible historic rows during an explicit migration."""

    rows = conn.execute(
        """
        SELECT activity.id
        FROM activity_log activity
        LEFT JOIN activity_project_assignment assignment
          ON assignment.activity_id = activity.id
        LEFT JOIN activity_inference_job job
          ON job.activity_id = activity.id
        WHERE job.activity_id IS NULL
          AND activity.end_time IS NOT NULL
          AND activity.status = 'normal'
          AND activity.is_hidden = 0
          AND activity.is_deleted = 0
          AND (
                assignment.activity_id IS NULL
                OR (
                    assignment.is_manual = 0
                    AND assignment.source IN (?, ?)
                )
          )
        ORDER BY activity.id
        """,
        _ELIGIBLE_ASSIGNMENT_SOURCES,
    ).fetchall()
    return enqueue_closed_activity_ids(
        conn,
        (int(row["id"]) for row in rows),
        at_time=at_time,
    )


def recover_interrupted_jobs(conn, *, at_time: str | None = None) -> int:
    """Return transactionally interrupted claims to the runnable state."""

    at = str(at_time or now_str())
    cursor = conn.execute(
        """
        UPDATE activity_inference_job
        SET status = ?, next_attempt_at = NULL, updated_at = ?
        WHERE status = ?
        """,
        (JOB_PENDING, at, JOB_RUNNING),
    )
    return max(0, int(cursor.rowcount or 0))


def list_runnable_activity_ids(
    conn,
    *,
    limit: int = 100,
    at_time: str | None = None,
    activity_ids: Iterable[int] | None = None,
) -> list[int]:
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
    parameters: list[object] = [JOB_PENDING, JOB_FAILED, at]
    if requested is not None:
        if not requested:
            return []
        placeholders = ",".join("?" for _ in requested)
        clauses.append(f"activity_id IN ({placeholders})")
        parameters.extend(requested)
    parameters.append(normalized_limit)
    rows = conn.execute(
        f"""
        SELECT activity_id
        FROM activity_inference_job
        WHERE {' AND '.join(clauses)}
        ORDER BY activity_id
        LIMIT ?
        """,
        tuple(parameters),
    ).fetchall()
    return [int(row["activity_id"]) for row in rows]


def mark_running(conn, activity_id: int, *, at_time: str | None = None) -> bool:
    at = str(at_time or now_str())
    cursor = conn.execute(
        """
        UPDATE activity_inference_job
        SET status = ?, updated_at = ?
        WHERE activity_id = ? AND status IN (?, ?)
        """,
        (
            JOB_RUNNING,
            at,
            int(activity_id),
            JOB_PENDING,
            JOB_FAILED,
        ),
    )
    return cursor.rowcount == 1


def delete_completed_job(conn, activity_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM activity_inference_job WHERE activity_id = ?",
        (int(activity_id),),
    )
    return cursor.rowcount == 1


def record_failure(
    conn,
    activity_id: int,
    error_code: str,
    *,
    at_time: str | None = None,
) -> int:
    """Persist a bounded exponential retry schedule and return attempt count."""

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
            JOB_FAILED,
            attempts,
            next_attempt,
            _safe_error_code(error_code),
            at,
            int(activity_id),
        ),
    )
    return attempts


def _safe_error_code(value: str) -> str:
    normalized = str(value or "inference_failed").strip()
    return (normalized or "inference_failed")[:120]


__all__ = [
    "JOB_FAILED",
    "JOB_PENDING",
    "JOB_RUNNING",
    "delete_completed_job",
    "enqueue_closed_activity_ids",
    "list_runnable_activity_ids",
    "mark_running",
    "record_failure",
    "recover_interrupted_jobs",
    "seed_missing_jobs",
]
