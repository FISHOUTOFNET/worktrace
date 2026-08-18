"""Pure eligibility policy for durable closed-activity inference."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNRESOLVED_ASSIGNMENT_SOURCES = frozenset(
    {"", "uncategorized", "suggested_project_name"}
)


def _value(record: Mapping[str, Any] | Any | None, key: str, default: Any = None) -> Any:
    if record is None:
        return default
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return getattr(record, key, default)


def is_assignment_unresolved(
    assignment: Mapping[str, Any] | Any | None,
) -> bool:
    """Return whether ordinary automatic inference may still fill the assignment."""

    if assignment is None:
        return True
    if bool(int(_value(assignment, "is_manual", 0) or 0)):
        return False
    source = str(_value(assignment, "source", "") or "").strip()
    return source in UNRESOLVED_ASSIGNMENT_SOURCES


def is_closed_activity_inference_eligible(
    activity: Mapping[str, Any] | Any | None,
    assignment: Mapping[str, Any] | Any | None = None,
) -> bool:
    """Return whether a closed activity may be processed by the durable consumer."""

    if activity is None:
        return False
    if _value(activity, "end_time") is None:
        return False
    if str(_value(activity, "status", "") or "") != "normal":
        return False
    if bool(int(_value(activity, "is_hidden", 0) or 0)):
        return False
    if bool(int(_value(activity, "is_deleted", 0) or 0)):
        return False
    return is_assignment_unresolved(assignment)


__all__ = [
    "UNRESOLVED_ASSIGNMENT_SOURCES",
    "is_assignment_unresolved",
    "is_closed_activity_inference_eligible",
]
