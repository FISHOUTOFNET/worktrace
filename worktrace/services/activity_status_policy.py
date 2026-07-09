from __future__ import annotations

from ..constants import (
    REPORT_CONTEXT_SHORT_MERGE_SECONDS,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)

ACTIVITY_FACT_STATUSES = {
    STATUS_NORMAL,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_PAUSED,
    STATUS_ERROR,
}
USER_OBSERVABLE_STATUSES = set(ACTIVITY_FACT_STATUSES)
PROJECT_ATTRIBUTABLE_STATUSES = {STATUS_NORMAL}
DURATION_COUNTED_STATUSES = {STATUS_NORMAL}
REPORTABLE_STATUSES = set(ACTIVITY_FACT_STATUSES)
EXPORTABLE_STATUSES = set(ACTIVITY_FACT_STATUSES)
COLLECTOR_HEALTH_STATUSES = {"healthy", "degraded", "failing", "stopped"}


def normalize_status(status: str) -> str:
    return str(status or "").strip()


def is_activity_fact_status(status: str) -> bool:
    return normalize_status(status) in ACTIVITY_FACT_STATUSES


def is_user_observable_status(status: str) -> bool:
    return normalize_status(status) in USER_OBSERVABLE_STATUSES


def is_project_attributable_status(status: str) -> bool:
    return normalize_status(status) in PROJECT_ATTRIBUTABLE_STATUSES


def is_status_duration_counted(status: str) -> bool:
    return normalize_status(status) in DURATION_COUNTED_STATUSES


def is_status_reportable(status: str) -> bool:
    return normalize_status(status) in REPORTABLE_STATUSES


def is_status_exportable(status: str) -> bool:
    return normalize_status(status) in EXPORTABLE_STATUSES


def can_status_soft_carry(status: str, duration_seconds: int) -> bool:
    value = normalize_status(status)
    seconds = max(0, int(duration_seconds or 0))
    if value in {STATUS_EXCLUDED, STATUS_IDLE, STATUS_ERROR}:
        return seconds <= REPORT_CONTEXT_SHORT_MERGE_SECONDS
    return value == STATUS_NORMAL


def does_status_require_boundary(
    status: str,
    duration_seconds: int,
    reason: str | None = None,
) -> bool:
    value = normalize_status(status)
    if value == STATUS_PAUSED:
        return True
    if value in {STATUS_IDLE, STATUS_ERROR}:
        return not can_status_soft_carry(value, duration_seconds)
    return False


def is_recovery_error_status(status: str) -> bool:
    return normalize_status(status) == STATUS_ERROR


def is_collector_health_status(status: str) -> bool:
    return False


def is_interrupt_status(status: str) -> bool:
    value = normalize_status(status)
    return value in {STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR}


__all__ = [
    "ACTIVITY_FACT_STATUSES",
    "COLLECTOR_HEALTH_STATUSES",
    "DURATION_COUNTED_STATUSES",
    "EXPORTABLE_STATUSES",
    "PROJECT_ATTRIBUTABLE_STATUSES",
    "REPORTABLE_STATUSES",
    "USER_OBSERVABLE_STATUSES",
    "can_status_soft_carry",
    "does_status_require_boundary",
    "is_activity_fact_status",
    "is_collector_health_status",
    "is_interrupt_status",
    "is_project_attributable_status",
    "is_recovery_error_status",
    "is_status_duration_counted",
    "is_status_exportable",
    "is_status_reportable",
    "is_user_observable_status",
    "normalize_status",
]
