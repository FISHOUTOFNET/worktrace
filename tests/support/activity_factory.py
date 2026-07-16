"""Test-only activity fact construction and production-query facade.

Tests may create durable activity facts directly through the repository without
invoking production lifecycle inference. Read methods not defined here are
forwarded to the production activity query service so existing tests can migrate
by changing only their import boundary.
"""

from __future__ import annotations

from typing import Any

from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL
from worktrace.db import get_connection, now_str
from worktrace.resources.types import DetectedResource
from worktrace.services import (
    activity_fact_repository,
    activity_service as _activity_queries,
    project_inference_service,
)


def _prepare(
    *,
    app_name: str,
    process_name: str,
    window_title: str,
    start_time: str,
    status: str,
    source: str,
    project_id: int | None,
    file_path_hint: str | None,
    resource: DetectedResource | None,
):
    return activity_fact_repository.prepare_activity(
        start_time=start_time,
        source=source,
        payload={
            "app_name": app_name,
            "process_name": process_name,
            "window_title": window_title,
            "status": status,
            "project_id": project_id,
            "file_path_hint": file_path_hint,
            "resource": resource,
        },
    )


def create_open_activity(
    *,
    app_name: str = "Word",
    process_name: str = "winword.exe",
    window_title: str = "A.docx",
    start_time: str = "2026-06-25 09:00:00",
    status: str = STATUS_NORMAL,
    source: str = SOURCE_AUTO,
    project_id: int | None = None,
    file_path_hint: str | None = None,
    note: str | None = None,
    resource: DetectedResource | None = None,
) -> int:
    del note
    prepared = _prepare(
        app_name=app_name,
        process_name=process_name,
        window_title=window_title,
        start_time=start_time,
        status=status,
        source=source,
        project_id=project_id,
        file_path_hint=file_path_hint,
        resource=resource,
    )
    with get_connection() as conn:
        return activity_fact_repository.insert_open_activity(conn, prepared)


def create_activity(
    app_name: str,
    process_name: str,
    window_title: str,
    status: str = STATUS_NORMAL,
    source: str = SOURCE_AUTO,
    start_time: str | None = None,
    project_id: int | None = None,
    file_path_hint: str | None = None,
    resource: DetectedResource | None = None,
    note: str | None = None,
    **_ignored: Any,
) -> int:
    """Compatibility vocabulary for historical test fact construction."""

    return create_open_activity(
        app_name=app_name,
        process_name=process_name,
        window_title=window_title,
        status=status,
        source=source,
        start_time=start_time or now_str(),
        project_id=project_id,
        file_path_hint=file_path_hint,
        resource=resource,
        note=note,
    )


def insert_activity_row(*args: Any, **kwargs: Any) -> int:
    return create_activity(*args, **kwargs)


def close_activity(
    activity_id: int,
    end_time: str,
    duration_seconds: int | None = None,
) -> None:
    with get_connection() as conn:
        activity_fact_repository.close_activity(
            conn,
            activity_id,
            end_time,
            duration_seconds=duration_seconds,
        )


def close_activity_row(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
    status: str | None = None,
) -> None:
    with get_connection() as conn:
        activity_fact_repository.close_activity(
            conn,
            activity_id,
            end_time,
            duration_seconds=duration_seconds,
            status=status,
        )


def close_all_open_rows(end_time: str | None = None) -> list[int]:
    with get_connection() as conn:
        return activity_fact_repository.close_all_open_activities(
            conn,
            end_time or now_str(),
        )


def set_activity_duration(activity_id: int, seconds: int) -> None:
    with get_connection() as conn:
        activity_fact_repository.checkpoint_activity_duration(
            conn,
            activity_id,
            seconds,
        )


def increment_activity_duration(activity_id: int, seconds: int) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT duration_seconds FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if row is None:
            return
        activity_fact_repository.checkpoint_activity_duration(
            conn,
            activity_id,
            int(row["duration_seconds"] or 0) + max(0, int(seconds or 0)),
        )


def reopen_activity(activity_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE activity_log
            SET end_time = NULL, updated_at = ?
            WHERE id = ? AND is_deleted = 0
            """,
            (now_str(), activity_id),
        )


def finalize_created_activity(activity_id: int) -> None:
    project_inference_service.process_new_activity(activity_id)


def apply_midnight_anchor_assignment(activity_id: int, project_id: int) -> None:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual,
                suggested_project_name, source_rule_type, source_rule_id,
                created_at, updated_at
            )
            VALUES (?, ?, 90, 'midnight_anchor', 0, NULL, NULL, NULL, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                project_id = excluded.project_id,
                confidence = excluded.confidence,
                source = excluded.source,
                is_manual = 0,
                suggested_project_name = NULL,
                source_rule_type = NULL,
                source_rule_id = NULL,
                updated_at = excluded.updated_at
            """,
            (activity_id, project_id, timestamp, timestamp),
        )


def create_closed_activity(
    *,
    day: str = "2026-06-25",
    start: str = "09:00:00",
    end: str = "09:30:00",
    app_name: str = "Word",
    process_name: str = "winword.exe",
    window_title: str = "A.docx",
    status: str = STATUS_NORMAL,
    source: str = SOURCE_AUTO,
    project_id: int | None = None,
    file_path_hint: str | None = None,
    note: str | None = None,
    resource: DetectedResource | None = None,
) -> int:
    """Insert a historical closed fact without running production inference."""

    del note
    prepared = _prepare(
        app_name=app_name,
        process_name=process_name,
        window_title=window_title,
        start_time=f"{day} {start}",
        status=status,
        source=source,
        project_id=project_id,
        file_path_hint=file_path_hint,
        resource=resource,
    )
    with get_connection() as conn:
        activity_id = activity_fact_repository.insert_open_activity(conn, prepared)
        activity_fact_repository.close_activity(conn, activity_id, f"{day} {end}")
    return activity_id


def create_finalized_activity(**kwargs: Any) -> int:
    activity_id = create_open_activity(**kwargs)
    finalize_created_activity(activity_id)
    return activity_id


def create_soft_deleted_activity(**kwargs: Any) -> int:
    activity_id = create_closed_activity(**kwargs)
    with get_connection() as conn:
        conn.execute("UPDATE activity_log SET is_deleted = 1 WHERE id = ?", (activity_id,))
    return activity_id


def create_cross_day_activity(
    *,
    start_time: str = "2026-06-25 23:00:00",
    end_time: str = "2026-06-26 01:00:00",
    app_name: str = "Word",
    process_name: str = "winword.exe",
    window_title: str = "A.docx",
    project_id: int | None = None,
) -> int:
    prepared = _prepare(
        app_name=app_name,
        process_name=process_name,
        window_title=window_title,
        start_time=start_time,
        status=STATUS_NORMAL,
        source=SOURCE_AUTO,
        project_id=project_id,
        file_path_hint=None,
        resource=None,
    )
    with get_connection() as conn:
        activity_id = activity_fact_repository.insert_open_activity(conn, prepared)
        activity_fact_repository.close_activity(conn, activity_id, end_time)
    return activity_id


def __getattr__(name: str):
    """Forward production query/edit helpers not owned by test fact fixtures."""

    return getattr(_activity_queries, name)
