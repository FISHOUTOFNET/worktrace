"""Idempotent repair of missing durable activity-resource facts."""

from __future__ import annotations

import logging
from typing import Any

from ..constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED
from ..db import get_connection
from ..platforms.base import ActiveWindow
from ..resources.detectors import detect_resource
from ..resources.resource_builders import make_system_resource
from ..resources.types import DetectedResource
from .resource_service import create_or_update_activity_resource

DEFAULT_BATCH_SIZE = 200


def repair_missing_activity_resources(batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Persist resource facts for every activity that predates resource storage.

    The operation is restartable without a separate cursor: each committed batch
    removes its rows from the missing-resource query. Detection occurs before the
    write transaction so SQLite is not held while platform-independent parsing
    runs.
    """

    size = max(1, int(batch_size))
    repaired = 0
    while True:
        rows = _load_missing_rows(size)
        if not rows:
            return repaired
        prepared = [(int(row["id"]), _resource_for_row(row)) for row in rows]
        with get_connection() as conn:
            for activity_id, resource in prepared:
                create_or_update_activity_resource(activity_id, resource, conn=conn)
        repaired += len(prepared)
        logging.info(
            "activity resource fact repair committed batch=%s total=%s",
            len(prepared),
            repaired,
        )


def _load_missing_rows(limit: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.app_name, a.process_name, a.window_title,
                   a.file_path_hint, a.start_time, a.status
            FROM activity_log a
            LEFT JOIN activity_resource ar ON ar.activity_id = a.id
            WHERE ar.activity_id IS NULL
            ORDER BY a.id
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def _resource_for_row(row: dict[str, Any]) -> DetectedResource:
    status = str(row.get("status") or "")
    app_name = str(row.get("app_name") or "")
    process_name = str(row.get("process_name") or "")
    window_title = str(row.get("window_title") or "")
    if status == STATUS_EXCLUDED:
        return make_system_resource(STATUS_EXCLUDED)
    if status in {STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR}:
        return make_system_resource(status, app_name, process_name, window_title)
    try:
        return detect_resource(
            ActiveWindow(
                app_name=app_name,
                process_name=process_name,
                window_title=window_title,
                file_path_hint=row.get("file_path_hint"),
                activity_start_time=str(row.get("start_time") or "") or None,
            )
        )
    except Exception:
        logging.exception(
            "activity resource fact repair detection failed activity_id=%s",
            int(row.get("id") or 0),
        )
        return _unknown_resource(row)


def _unknown_resource(row: dict[str, Any]) -> DetectedResource:
    activity_id = int(row.get("id") or 0)
    app_name = str(row.get("app_name") or "")
    process_name = str(row.get("process_name") or "")
    display_name = app_name or process_name or "未知"
    return DetectedResource(
        resource_kind="unknown",
        resource_subtype="unknown",
        display_name=display_name,
        identity_key=f"activity:{activity_id}",
        is_anchor=False,
        confidence=0,
        source="repair_unknown",
        app_name=app_name,
        process_name=process_name,
        window_title="",
    )


__all__ = ["repair_missing_activity_resources"]
