"""ActivityLifecycle Command Facade — sole owner of open-row transitions."""

from __future__ import annotations

import logging
from typing import Any

from ..constants import STATUS_NORMAL
from ..db import get_connection, now_str
from . import activity_service


def _mark_inference_retry_safely(activity_id: int) -> None:
    try:
        from .assignment_command_service import mark_inference_retry
        from .project_inference_service import _get_uncategorized_project_id

        with get_connection() as conn:
            mark_inference_retry(
                conn,
                activity_id,
                _get_uncategorized_project_id(conn),
            )
    except Exception:
        logging.exception(
            "close-finalize inference retry marker failed for activity_id=%s",
            activity_id,
        )


def finalize_closed_activity_ids(closed_ids: list[int]) -> None:
    """Run project inference / automatic rules after close transactions."""
    if not closed_ids:
        return
    from .project_inference_service import process_new_activity

    for aid in closed_ids:
        try:
            process_new_activity(aid)
        except Exception:
            logging.exception(
                "close-finalize inference failed for activity_id=%s",
                aid,
            )
            _mark_inference_retry_safely(aid)


def start_activity(*, start_time: str, source: str, payload: dict[str, Any]) -> int:
    close_all_open_activities(start_time)
    return activity_service.insert_activity_row(
        start_time=start_time, source=source, **payload
    )


def persist_open_activity(
    *, start_time: str, source: str, payload: dict[str, Any]
) -> int:
    return _persist_open_activity_unchecked(
        start_time=start_time, source=source, payload=payload
    )


def force_persist_open_activity_for_clipboard(
    *, start_time: str, source: str, payload: dict[str, Any]
) -> int | None:
    if payload.get("status") != STATUS_NORMAL:
        return None
    return persist_open_activity(
        start_time=start_time, source=source, payload=payload
    )


def _persist_open_activity_unchecked(
    *, start_time: str, source: str, payload: dict[str, Any]
) -> int:
    activity_id = activity_service.insert_activity_row(
        start_time=start_time, source=source, **payload
    )
    activity_service.finalize_created_activity(activity_id)
    _sync_open_row_project_safely(activity_id, status=payload.get("status"))
    return activity_id


def close_activity(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
) -> None:
    safe_end = _safe_end_time(activity_id, end_time)
    activity_service.close_activity_row(
        activity_id, safe_end, duration_seconds=duration_seconds
    )
    finalize_closed_activity_ids([activity_id])


def close_all_open_activities(end_time: str | None = None) -> list[int]:
    requested_end = end_time or now_str()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, start_time FROM activity_log "
            "WHERE end_time IS NULL ORDER BY id"
        ).fetchall()
    closed_ids: list[int] = []
    for row in rows:
        activity_id = int(row["id"])
        safe_end = max(str(requested_end or ""), str(row["start_time"] or ""))
        activity_service.close_activity_row(activity_id, safe_end)
        closed_ids.append(activity_id)
    finalize_closed_activity_ids(closed_ids)
    return closed_ids


def persist_midnight_anchor(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
    project_id: int,
) -> int:
    activity_id = activity_service.insert_activity_row(
        start_time=start_time, source=source, **payload
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.apply_midnight_anchor_assignment(activity_id, int(project_id))
    return activity_id


def recover_close_activity(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
    status: str | None = None,
) -> None:
    safe_end = _safe_end_time(activity_id, end_time)
    activity_service.close_activity_row(
        activity_id,
        safe_end,
        duration_seconds=duration_seconds,
        status=status,
    )
    finalize_closed_activity_ids([activity_id])


def recover_cross_midnight_segment(
    *,
    start_time: str,
    end_time: str,
    source: str,
    status: str,
    payload: dict[str, Any],
    project_id: int | None = None,
) -> int:
    activity_id = activity_service.insert_activity_row(
        start_time=start_time,
        source=source,
        status=status,
        **payload,
    )
    activity_service.finalize_created_activity(activity_id)
    if status == STATUS_NORMAL and project_id is not None:
        activity_service.apply_midnight_anchor_assignment(activity_id, int(project_id))
    close_activity(activity_id, end_time)
    return activity_id


def recover_first_half_close(
    activity_id: int, end_time: str, duration_seconds: int
) -> None:
    close_activity(activity_id, end_time, duration_seconds=duration_seconds)


def _safe_end_time(activity_id: int, requested_end: str) -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT start_time FROM activity_log WHERE id = ?", (int(activity_id),)
        ).fetchone()
    if not row:
        return str(requested_end or "")
    return max(str(requested_end or ""), str(row["start_time"] or ""))


def _sync_open_row_project_safely(
    activity_id: int, *, status: str | None
) -> None:
    if status != STATUS_NORMAL:
        return
    from .project_inference_service import sync_persisted_open_activity_project

    try:
        sync_persisted_open_activity_project(activity_id)
    except Exception:
        logging.exception(
            "open-row project sync failed for activity_id=%s", activity_id
        )


__all__ = [
    "close_activity",
    "close_all_open_activities",
    "finalize_closed_activity_ids",
    "force_persist_open_activity_for_clipboard",
    "persist_midnight_anchor",
    "persist_open_activity",
    "recover_close_activity",
    "recover_cross_midnight_segment",
    "recover_first_half_close",
    "start_activity",
]
