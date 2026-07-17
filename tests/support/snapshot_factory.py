from __future__ import annotations

from datetime import datetime, timedelta

from worktrace.constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)


def current_activity_snapshot(
    *,
    elapsed_seconds: int = 120,
    status: str = STATUS_NORMAL,
    is_persisted: bool = False,
    persisted_activity_id: int = 0,
    project_name: str = "TestProject",
    start_time: str | None = None,
    app_name: str = "AppA",
    process_name: str = "AppA.exe",
    window_title: str = "Window",
) -> dict:
    if start_time is None:
        start = datetime.now() - timedelta(seconds=elapsed_seconds)
        start_time = start.strftime(TIME_FORMAT)
    is_uncategorized = project_name in {"", "未归类"}
    return {
        "app_name": app_name,
        "process_name": process_name,
        "window_title": window_title,
        "start_time": start_time,
        "elapsed_seconds": elapsed_seconds,
        "status": status,
        "is_persisted": is_persisted,
        "persisted_activity_id": persisted_activity_id,
        "display_project": {
            "id": None,
            "name": project_name,
            "description": "",
            "source": "uncategorized" if is_uncategorized else "keyword_rule",
            "is_uncategorized": is_uncategorized,
            "is_suggested_project": False,
        },
    }


def normal_snapshot(**kwargs) -> dict:
    kwargs.setdefault("status", STATUS_NORMAL)
    return current_activity_snapshot(**kwargs)


def persisted_open_snapshot(activity_id: int, **kwargs) -> dict:
    return current_activity_snapshot(
        is_persisted=True,
        persisted_activity_id=activity_id,
        **kwargs,
    )


def unpersisted_normal_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(is_persisted=False, **kwargs)


def idle_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(status=STATUS_IDLE, **kwargs)


def paused_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(status=STATUS_PAUSED, **kwargs)


def excluded_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(status=STATUS_EXCLUDED, **kwargs)


def error_snapshot(**kwargs) -> dict:
    return current_activity_snapshot(status=STATUS_ERROR, **kwargs)
