"""Transactional repository for durable activity facts.

This module owns SQL primitives that must participate in one caller-controlled
transaction. Resource detection is prepared before the write lock is acquired;
the repository only persists already-resolved facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from ..db import now_str
from ..platforms.base import ActiveWindow
from ..resources.resource_builders import make_system_resource
from ..resources.types import DetectedResource
from .resource_service import create_or_update_activity_resource


@dataclass(frozen=True)
class PreparedActivity:
    start_time: str
    source: str
    app_name: str
    process_name: str
    window_title: str
    file_path_hint: str | None
    status: str
    resource: DetectedResource
    initial_project_id: int | None = None
    assignment_source: str | None = None
    assignment_confidence: int | None = None
    assignment_is_manual: bool = False


def prepare_activity(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
    initial_project_id: int | None = None,
    assignment_source: str | None = None,
    assignment_confidence: int | None = None,
    assignment_is_manual: bool = False,
) -> PreparedActivity:
    """Resolve non-SQL activity inputs before a write transaction starts."""

    app_name = str(payload.get("app_name") or "")
    process_name = str(payload.get("process_name") or "")
    window_title = str(payload.get("window_title") or "")
    file_path_hint = payload.get("file_path_hint")
    status = str(payload.get("status") or STATUS_NORMAL)
    resource = payload.get("resource")
    if not isinstance(resource, DetectedResource):
        resource = _detect_resource(
            app_name=app_name,
            process_name=process_name,
            window_title=window_title,
            file_path_hint=file_path_hint,
            status=status,
            start_time=start_time,
        )

    payload_project_id = payload.get("project_id")
    resolved_project_id = (
        int(initial_project_id)
        if initial_project_id is not None
        else (
            int(payload_project_id)
            if payload_project_id is not None
            else None
        )
    )
    payload_manual = (
        initial_project_id is None
        and payload_project_id is not None
        and assignment_source is None
    )
    resolved_manual = bool(assignment_is_manual or payload_manual)
    resolved_source = assignment_source or (
        "manual" if resolved_manual else None
    )
    resolved_confidence = assignment_confidence
    if resolved_confidence is None and resolved_manual:
        resolved_confidence = 100

    return PreparedActivity(
        start_time=str(start_time),
        source=str(source),
        app_name=app_name,
        process_name=process_name,
        window_title=window_title,
        file_path_hint=str(file_path_hint) if file_path_hint else None,
        status=status,
        resource=resource,
        initial_project_id=resolved_project_id,
        assignment_source=resolved_source,
        assignment_confidence=resolved_confidence,
        assignment_is_manual=resolved_manual,
    )


def insert_open_activity(conn, prepared: PreparedActivity) -> int:
    """Insert activity, assignment, resource and zero-second checkpoint atomically."""

    timestamp = now_str()
    cursor = conn.execute(
        """
        INSERT INTO activity_log(
            start_time, end_time, duration_seconds, app_name, process_name,
            window_title, file_path_hint, status, source, is_deleted, is_hidden,
            created_at, updated_at
        )
        VALUES (?, NULL, 0, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
        """,
        (
            prepared.start_time,
            prepared.app_name,
            prepared.process_name,
            prepared.window_title,
            prepared.file_path_hint,
            prepared.status,
            prepared.source,
            timestamp,
            timestamp,
        ),
    )
    activity_id = int(cursor.lastrowid)
    project_id = prepared.initial_project_id
    if project_id is None:
        row = conn.execute(
            "SELECT id FROM project WHERE name = ?",
            (UNCATEGORIZED_PROJECT,),
        ).fetchone()
        if row is None:
            raise ValueError("activity_context_not_ready")
        project_id = int(row["id"])
    effective_source = prepared.assignment_source or (
        "manual" if prepared.assignment_is_manual else "uncategorized"
    )
    confidence = (
        int(prepared.assignment_confidence)
        if prepared.assignment_confidence is not None
        else (100 if prepared.assignment_is_manual else 0)
    )
    conn.execute(
        """
        INSERT INTO activity_project_assignment(
            activity_id, project_id, confidence, source, is_manual,
            suggested_project_name, source_rule_type, source_rule_id,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
        """,
        (
            activity_id,
            project_id,
            confidence,
            effective_source,
            int(prepared.assignment_is_manual),
            timestamp,
            timestamp,
        ),
    )
    create_or_update_activity_resource(
        activity_id,
        prepared.resource,
        conn=conn,
    )
    return activity_id


def close_activity(
    conn,
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
    status: str | None = None,
) -> bool:
    """Close one activity inside the caller's transaction."""

    row = conn.execute(
        """
        SELECT start_time, status, duration_seconds, end_time
        FROM activity_log
        WHERE id = ?
        """,
        (int(activity_id),),
    ).fetchone()
    if row is None or row["end_time"] is not None:
        return False
    safe_end = max(str(end_time or ""), str(row["start_time"] or ""))
    duration, reversed_clock = _duration_seconds(
        str(row["start_time"]),
        safe_end,
    )
    duration = max(duration, int(row["duration_seconds"] or 0))
    if duration_seconds is not None:
        duration = max(duration, max(0, int(duration_seconds)))
    effective_status = (
        str(status)
        if status is not None
        else (STATUS_ERROR if reversed_clock else str(row["status"]))
    )
    conn.execute(
        """
        UPDATE activity_log
        SET end_time = ?, duration_seconds = ?, status = ?, updated_at = ?
        WHERE id = ? AND end_time IS NULL
        """,
        (safe_end, duration, effective_status, now_str(), int(activity_id)),
    )
    return True


def close_all_open_activities(conn, end_time: str) -> list[int]:
    """Close every open row atomically and return the affected ids."""

    rows = conn.execute(
        """
        SELECT id, start_time
        FROM activity_log
        WHERE end_time IS NULL
        ORDER BY id
        """
    ).fetchall()
    closed: list[int] = []
    for row in rows:
        activity_id = int(row["id"])
        safe_end = max(str(end_time or ""), str(row["start_time"] or ""))
        if close_activity(conn, activity_id, safe_end):
            closed.append(activity_id)
    return closed


def checkpoint_activity_duration(
    conn,
    activity_id: int,
    duration_seconds: int,
) -> bool:
    """Persist a monotonic crash-recovery checkpoint for one open activity."""

    row = conn.execute(
        """
        SELECT duration_seconds, end_time
        FROM activity_log
        WHERE id = ? AND is_deleted = 0
        """,
        (int(activity_id),),
    ).fetchone()
    if row is None or row["end_time"] is not None:
        return False
    duration = max(
        int(row["duration_seconds"] or 0),
        max(0, int(duration_seconds or 0)),
    )
    cursor = conn.execute(
        """
        UPDATE activity_log
        SET duration_seconds = ?
        WHERE id = ? AND end_time IS NULL AND is_deleted = 0
        """,
        (duration, int(activity_id)),
    )
    return cursor.rowcount == 1


def _detect_resource(
    *,
    app_name: str,
    process_name: str,
    window_title: str,
    file_path_hint: str | None,
    status: str,
    start_time: str,
) -> DetectedResource:
    if status == STATUS_EXCLUDED:
        return make_system_resource(STATUS_EXCLUDED)
    if status in {STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR}:
        return make_system_resource(status, app_name, process_name, window_title)
    from ..resources.detectors import detect_resource

    return detect_resource(
        ActiveWindow(
            app_name=app_name,
            process_name=process_name,
            window_title=window_title,
            file_path_hint=file_path_hint,
            activity_start_time=start_time,
        )
    )


def _duration_seconds(start_time: str, end_time: str) -> tuple[int, bool]:
    start = datetime.strptime(start_time, TIME_FORMAT)
    end = datetime.strptime(end_time, TIME_FORMAT)
    value = int((end - start).total_seconds())
    return (max(0, value), value < 0)


__all__ = [
    "PreparedActivity",
    "checkpoint_activity_duration",
    "close_activity",
    "close_all_open_activities",
    "insert_open_activity",
    "prepare_activity",
]
