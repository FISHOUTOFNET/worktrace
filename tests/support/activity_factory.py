from __future__ import annotations

from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL
from worktrace.db import get_connection
from worktrace.resources.types import DetectedResource
from worktrace.services import (
    activity_fact_repository,
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


def create_finalized_activity(**kwargs) -> int:
    activity_id = create_open_activity(**kwargs)
    project_inference_service.process_new_activity(activity_id)
    return activity_id


def create_soft_deleted_activity(**kwargs) -> int:
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
