from __future__ import annotations

from datetime import datetime
from typing import Any

from ..constants import (
    DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    REPORT_CONTEXT_SHORT_MERGE_SECONDS,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)
from ..db import get_connection
from .settings_service import get_int_setting, get_setting
from .activity_status_policy import (
    does_status_require_boundary,
    is_project_attributable_status,
)

NORMAL_PROJECT_STATUS = STATUS_NORMAL
SYSTEM_STATUSES = {STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}


def is_system_status(status: str) -> bool:
    return str(status or "") in SYSTEM_STATUSES


def is_normal_project_status(status: str) -> bool:
    return is_project_attributable_status(str(status or ""))


def is_report_short_context_duration(seconds: int) -> bool:
    return 0 <= int(seconds or 0) <= REPORT_CONTEXT_SHORT_MERGE_SECONDS


def is_hard_boundary_status(status: str) -> bool:
    return does_status_require_boundary(str(status or ""), 0)


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
    if is_true_unrecorded_gap_boundary(start, end):
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
            rows = conn.execute(
                """
                SELECT status, start_time, end_time
                FROM activity_log
                WHERE is_deleted = 0
                  AND status IN (?, ?, ?, ?)
                  AND start_time <= ?
                  AND COALESCE(end_time, ?) >= ?
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
            ).fetchall()
            for row in rows:
                duration = _row_overlap_seconds(dict(row), start, end)
                if does_status_require_boundary(str(row["status"] or ""), duration):
                    return True
            return False
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


def is_true_unrecorded_gap_boundary(start_time: str, end_time: str) -> bool:
    return _has_unrecorded_gap(start_time, end_time) and not is_soft_collector_gap(start_time, end_time)


def is_soft_collector_gap(start_time: str, end_time: str) -> bool:
    return is_same_resource_stall_recovery_gap(start_time, end_time)


def is_same_resource_stall_recovery_gap(start_time: str, end_time: str) -> bool:
    """Whether a long gap is a recovered collector gap on one resource.

    This is intentionally a narrow exception to the unrecorded-gap rule: it
    needs health/recovery evidence, two trustworthy matching identities, and
    no recorded hard boundary.  It must never turn a user/runtime boundary
    into collector continuity merely because an app name happens to match.
    """
    if not start_time or not end_time or start_time >= end_time:
        return False
    if _has_explicit_boundary_between(start_time, end_time):
        return False
    if _has_boundary_status_between(start_time, end_time):
        return False
    if not _has_collector_recovery_evidence(start_time, end_time):
        return False

    previous = _last_normal_activity_before(start_time)
    current = _current_snapshot()
    if not previous or not current:
        return False
    if not is_normal_project_status(str(previous.get("status") or "")):
        return False
    if not is_normal_project_status(str(current.get("status") or "")):
        return False
    previous_identity = _resource_identity(previous)
    current_identity = _resource_identity(current)
    return bool(previous_identity and current_identity and previous_identity == current_identity)


def _has_collector_recovery_evidence(start_time: str, end_time: str) -> bool:
    health = str(get_setting("collector_health_state", "") or "").lower()
    if health in {"degraded", "failing"}:
        return True
    recovery_at = str(get_setting("collector_last_recovery_at", "") or "")
    failure_at = str(get_setting("collector_last_recovery_failure_at", "") or get_setting("collector_last_failure_at", "") or "")
    # A recovery may complete just after the recovered observation.  Requiring
    # the failure to lie in the gap and the recovery not to precede it keeps
    # old, unrelated failures from softening later unknown gaps.
    return bool(
        failure_at
        and start_time <= failure_at <= end_time
        and recovery_at
        and recovery_at >= failure_at
    )


def _has_explicit_boundary_between(start_time: str, end_time: str) -> bool:
    try:
        with get_connection() as conn:
            return conn.execute(
                """
                SELECT 1 FROM session_boundary
                WHERE occurred_at >= ? AND occurred_at <= ?
                LIMIT 1
                """,
                (start_time, end_time),
            ).fetchone() is not None
    except Exception:
        return True


def _has_boundary_status_between(start_time: str, end_time: str) -> bool:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT status, start_time, end_time
                FROM activity_log
                WHERE is_deleted = 0
                  AND status IN (?, ?, ?, ?)
                  AND start_time <= ?
                  AND COALESCE(end_time, ?) >= ?
                """,
                (STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR, end_time, end_time, start_time),
            ).fetchall()
        return any(
            does_status_require_boundary(str(row["status"] or ""), _row_overlap_seconds(dict(row), start_time, end_time))
            for row in rows
        )
    except Exception:
        return True


def _last_normal_activity_before(start_time: str) -> dict[str, Any] | None:
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM activity_log
                WHERE is_deleted = 0
                  AND status = ?
                  AND end_time IS NOT NULL
                  AND end_time <= ?
                ORDER BY end_time DESC, id DESC
                LIMIT 1
                """,
                (STATUS_NORMAL, start_time),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _current_snapshot() -> dict[str, Any] | None:
    import json

    raw = get_setting("current_activity_snapshot", "") or ""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _resource_identity(value: dict[str, Any]) -> str:
    """Use the same established identity precedence as the live clock."""
    for field in (
        "resource_identity_key",
        "activity_identity_key",
        "resource_display_name",
        "activity_display_name",
        "app_name",
        "process_name",
    ):
        identity = str(value.get(field) or "").strip().lower()
        if identity:
            return identity
    return ""


def _row_overlap_seconds(row: dict[str, Any], start_time: str, end_time: str) -> int:
    try:
        start = max(
            datetime.strptime(str(row.get("start_time") or start_time), TIME_FORMAT),
            datetime.strptime(start_time, TIME_FORMAT),
        )
        end = min(
            datetime.strptime(str(row.get("end_time") or end_time), TIME_FORMAT),
            datetime.strptime(end_time, TIME_FORMAT),
        )
    except (TypeError, ValueError):
        return 0
    return max(0, int((end - start).total_seconds()))


__all__ = [
    "NORMAL_PROJECT_STATUS",
    "SYSTEM_STATUSES",
    "can_absorb_short_pending",
    "can_carry_context_between",
    "can_merge_finished_short_activity",
    "has_hard_boundary_between",
    "is_same_resource_stall_recovery_gap",
    "is_soft_collector_gap",
    "is_true_unrecorded_gap_boundary",
    "is_hard_boundary_status",
    "is_normal_project_status",
    "is_system_status",
]
