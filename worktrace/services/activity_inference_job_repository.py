"""Canonical DML owner for durable activity-inference obligations."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable

from ..constants import TIME_FORMAT
from ..db import now_str

REASON_FINALIZE = "finalize"
REASON_FACTS_CHANGED = "facts_changed"
REASON_MIGRATION_REPAIR = "migration_repair"
REASON_IMPORT_REPAIR = "import_repair"
REASONS = frozenset(
    {
        REASON_FINALIZE,
        REASON_FACTS_CHANGED,
        REASON_MIGRATION_REPAIR,
        REASON_IMPORT_REPAIR,
    }
)


class InferenceJobErrorCode(str, Enum):
    DATABASE_BUSY = "database_busy"
    DATA_REPAIR_REQUIRED = "data_repair_required"
    INFERENCE_FAILED = "inference_failed"


ERROR_CODES = frozenset(code.value for code in InferenceJobErrorCode)


def enqueue_closed_activity_ids(
    conn,
    activity_ids: Iterable[int],
    *,
    reason: str = REASON_FINALIZE,
    at_time: str | None = None,
) -> int:
    """Upsert one current derivation obligation per eligible closed activity."""

    normalized_reason = _reason(reason)
    ids = sorted({int(activity_id) for activity_id in activity_ids})
    if not ids:
        return 0
    at = str(at_time or now_str())
    placeholders = ",".join("?" for _ in ids)
    before = int(conn.total_changes)
    conn.execute(
        f"""
        INSERT INTO activity_inference_job(
            activity_id, reason, attempt_count, available_at,
            last_error_code, created_at, updated_at
        )
        SELECT activity.id, ?, 0, ?, NULL, ?, ?
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
                    AND assignment.source <> 'midnight_anchor'
                )
          )
        ON CONFLICT(activity_id) DO UPDATE SET
            reason = excluded.reason,
            attempt_count = 0,
            available_at = excluded.available_at,
            last_error_code = NULL,
            updated_at = excluded.updated_at
        """,
        (normalized_reason, at, at, at, *ids),
    )
    return max(0, int(conn.total_changes) - before)


def seed_legacy_import_jobs(conn, *, at_time: str | None = None) -> int:
    """Seed only legacy missing-assignment or explicit retry-marker semantics."""

    at = str(at_time or now_str())
    before = int(conn.total_changes)
    conn.execute(
        """
        INSERT OR IGNORE INTO activity_inference_job(
            activity_id, reason, attempt_count, available_at,
            last_error_code, created_at, updated_at
        )
        SELECT activity.id, ?, 0, ?, NULL, ?, ?
        FROM activity_log activity
        LEFT JOIN activity_project_assignment assignment
          ON assignment.activity_id = activity.id
        WHERE activity.end_time IS NOT NULL
          AND activity.status = 'normal'
          AND activity.is_hidden = 0
          AND activity.is_deleted = 0
          AND (
                assignment.activity_id IS NULL
                OR (
                    assignment.is_manual = 0
                    AND assignment.source = 'uncategorized'
                    AND assignment.confidence = -1
                )
          )
        """,
        (REASON_IMPORT_REPAIR, at, at, at),
    )
    return max(0, int(conn.total_changes) - before)


def list_due_activity_ids(
    conn,
    *,
    limit: int = 100,
    at_time: str | None = None,
    activity_ids: Iterable[int] | None = None,
) -> list[int]:
    """Return a bounded deterministic candidate set without mutating jobs."""

    normalized_limit = max(0, int(limit))
    if normalized_limit == 0:
        return []
    at = str(at_time or now_str())
    requested = (
        sorted({int(activity_id) for activity_id in activity_ids})
        if activity_ids is not None
        else None
    )
    clauses = ["available_at <= ?"]
    parameters: list[object] = [at]
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
        ORDER BY available_at, activity_id
        LIMIT ?
        """,
        tuple(parameters),
    ).fetchall()
    return [int(row["activity_id"]) for row in rows]


def due_job(conn, activity_id: int, *, at_time: str | None = None):
    """Reload one job inside the worker transaction and verify it is still due."""

    return conn.execute(
        """
        SELECT activity_id, reason, attempt_count, available_at,
               last_error_code, created_at, updated_at
        FROM activity_inference_job
        WHERE activity_id = ? AND available_at <= ?
        """,
        (int(activity_id), str(at_time or now_str())),
    ).fetchone()


def activity_is_eligible(conn, activity_id: int) -> bool:
    """Return whether authoritative durable facts still permit inference."""

    return bool(
        conn.execute(
            """
            SELECT 1
            FROM activity_log activity
            LEFT JOIN activity_project_assignment assignment
              ON assignment.activity_id = activity.id
            WHERE activity.id = ?
              AND activity.end_time IS NOT NULL
              AND activity.status = 'normal'
              AND activity.is_hidden = 0
              AND activity.is_deleted = 0
              AND (
                    assignment.activity_id IS NULL
                    OR (
                        assignment.is_manual = 0
                        AND assignment.source <> 'midnight_anchor'
                    )
              )
            """,
            (int(activity_id),),
        ).fetchone()
    )


def delete_job(conn, activity_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM activity_inference_job WHERE activity_id = ?",
        (int(activity_id),),
    )
    return cursor.rowcount == 1


def record_failure(
    conn,
    activity_id: int,
    error_code: InferenceJobErrorCode,
    *,
    at_time: str | None = None,
) -> int:
    """Persist bounded exponential backoff and return the new attempt count."""

    if not isinstance(error_code, InferenceJobErrorCode):
        raise TypeError("inference_job_error_code_required")
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
        available_at = (
            datetime.strptime(at, TIME_FORMAT) + timedelta(seconds=delay_seconds)
        ).strftime(TIME_FORMAT)
    except (TypeError, ValueError):
        available_at = at
    conn.execute(
        """
        UPDATE activity_inference_job
        SET attempt_count = ?, available_at = ?, last_error_code = ?,
            updated_at = ?
        WHERE activity_id = ?
        """,
        (
            attempts,
            available_at,
            error_code.value,
            at,
            int(activity_id),
        ),
    )
    return attempts


def _reason(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in REASONS:
        raise ValueError("invalid_activity_inference_reason")
    return normalized


__all__ = [
    "ERROR_CODES",
    "InferenceJobErrorCode",
    "REASON_FACTS_CHANGED",
    "REASON_FINALIZE",
    "REASON_IMPORT_REPAIR",
    "REASON_MIGRATION_REPAIR",
    "REASONS",
    "activity_is_eligible",
    "delete_job",
    "due_job",
    "enqueue_closed_activity_ids",
    "list_due_activity_ids",
    "record_failure",
    "seed_legacy_import_jobs",
]
