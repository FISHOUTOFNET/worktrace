from __future__ import annotations

from datetime import datetime
from typing import Any

from ..constants import (
    DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)
from ..db import get_connection
from .settings_service import get_int_setting

NORMAL_PROJECT_STATUS = STATUS_NORMAL
SYSTEM_STATUSES = {STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}


def is_system_status(status: str) -> bool:
    return str(status or "") in SYSTEM_STATUSES


def is_normal_project_status(status: str) -> bool:
    return str(status or "") == NORMAL_PROJECT_STATUS


def is_hard_boundary_status(status: str) -> bool:
    return is_system_status(status)


def has_hard_boundary_between(start_time: str, end_time: str) -> bool:
    """Return True when a project-continuity hard boundary exists.

    The helper is intentionally defensive: malformed/empty/reversed ranges
    return False rather than raising, so callers can use it from display and
    report code paths without turning bad historic rows into UI failures.
    """
    start = str(start_time or "")
    end = str(end_time or "")
    if not start or not end or start > end:
        return False
    if _has_unrecorded_gap(start, end):
        return True
    try:
        with get_connection() as conn:
            boundary = conn.execute(
                """
                SELECT 1
                FROM session_boundary
                WHERE occurred_at >= ? AND occurred_at <= ?
                LIMIT 1
                """,
                (start, end),
            ).fetchone()
            if boundary is not None:
                return True
            system = conn.execute(
                """
                SELECT 1
                FROM activity_log
                WHERE is_deleted = 0
                  AND status IN (?, ?, ?, ?)
                  AND start_time <= ?
                  AND COALESCE(end_time, ?) >= ?
                LIMIT 1
                """,
                (
                    STATUS_IDLE,
                    STATUS_PAUSED,
                    STATUS_EXCLUDED,
                    STATUS_ERROR,
                    end,
                    end,
                    start,
                ),
            ).fetchone()
            return system is not None
    except Exception:
        return False


def can_absorb_short_pending(
    anchor_row: dict[str, Any] | None,
    pending_snapshot_or_start_time: dict[str, Any] | str | None,
) -> bool:
    if not anchor_row:
        return False
    pending_start = _pending_start_time(pending_snapshot_or_start_time)
    pending_status = _pending_status(pending_snapshot_or_start_time)
    if pending_status and not is_normal_project_status(pending_status):
        return False
    if not pending_start:
        return False
    if int(anchor_row.get("is_deleted") or 0) or int(anchor_row.get("is_hidden") or 0):
        return False
    if not is_normal_project_status(str(anchor_row.get("status") or "")):
        return False
    anchor_start = str(anchor_row.get("start_time") or "")
    anchor_end = str(anchor_row.get("end_time") or "")
    if not anchor_start or not anchor_end:
        return False
    if anchor_start > pending_start or anchor_end > pending_start:
        return False
    return not has_hard_boundary_between(anchor_end, pending_start)


def can_merge_finished_short_activity(
    status: str,
    start_time: str,
    end_time: str,
) -> bool:
    if not is_normal_project_status(status):
        return False
    if not start_time or not end_time or start_time > end_time:
        return False
    return True


def can_carry_context_between(
    previous_row: dict[str, Any] | None,
    current_row: dict[str, Any] | None,
) -> bool:
    if not previous_row or not current_row:
        return False
    if not is_normal_project_status(str(previous_row.get("status") or "")):
        return False
    if not is_normal_project_status(str(current_row.get("status") or "")):
        return False
    boundary_start = str(previous_row.get("end_time") or previous_row.get("start_time") or "")
    boundary_end = str(current_row.get("start_time") or "")
    if not boundary_start or not boundary_end:
        return False
    return not has_hard_boundary_between(boundary_start, boundary_end)


def _pending_start_time(value: dict[str, Any] | str | None) -> str:
    if isinstance(value, dict):
        return str(value.get("start_time") or "")
    return str(value or "")


def _pending_status(value: dict[str, Any] | str | None) -> str:
    if isinstance(value, dict):
        return str(value.get("status") or "")
    return ""


def _has_unrecorded_gap(start_time: str, end_time: str) -> bool:
    try:
        start = datetime.strptime(start_time, TIME_FORMAT)
        end = datetime.strptime(end_time, TIME_FORMAT)
    except (TypeError, ValueError):
        return False
    gap_seconds = int((end - start).total_seconds())
    if gap_seconds <= 0:
        return False
    threshold = get_int_setting(
        "unrecorded_gap_boundary_seconds",
        DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    )
    threshold = max(60, int(threshold or DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS))
    return gap_seconds > threshold


__all__ = [
    "NORMAL_PROJECT_STATUS",
    "SYSTEM_STATUSES",
    "can_absorb_short_pending",
    "can_carry_context_between",
    "can_merge_finished_short_activity",
    "has_hard_boundary_between",
    "is_hard_boundary_status",
    "is_normal_project_status",
    "is_system_status",
]
