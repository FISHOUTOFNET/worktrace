"""Timeline, activity, and live-time facade for the UI.

Wraps ``timeline_service``, the activity-editing helpers from
``activity_service``, the project-selection helper from ``project_service``,
and the pure live-time helpers from ``live_time_service``.
"""

from __future__ import annotations

from typing import Any

from ..services import activity_service, project_service, timeline_service
from ..services.live_time_service import (
    is_unconfirmed_snapshot,
    short_activity_carry_duration,
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
    snapshot_seconds_for_date_range,
    snapshot_signature,
    sync_short_activity_carry,
)


# --- timeline / sessions -------------------------------------------------

def get_default_report_date() -> str:
    return timeline_service.get_default_report_date()


def get_project_sessions_by_date(
    date: str,
    include_hidden: bool = True,
    ensure_context: bool = True,
) -> list[dict[str, Any]]:
    return timeline_service.get_project_sessions_by_date(
        date,
        include_hidden=include_hidden,
        ensure_context=ensure_context,
    )


def get_project_sessions_by_range(
    start_date: str,
    end_date: str,
    include_hidden: bool = True,
    ensure_context: bool = True,
) -> list[dict[str, Any]]:
    return timeline_service.get_project_sessions_by_range(
        start_date,
        end_date,
        include_hidden=include_hidden,
        ensure_context=ensure_context,
    )


def get_session_activity_details(
    activity_ids: list[int],
    report_date: str | None = None,
    ensure_context: bool = True,
) -> list[dict[str, Any]]:
    return timeline_service.get_session_activity_details(
        activity_ids,
        report_date=report_date,
        ensure_context=ensure_context,
    )


def get_session_anchor_folders(activity_ids: list[int]) -> list[str]:
    return timeline_service.get_session_anchor_folders(activity_ids)


def update_session_project(session_activity_ids: list[int], project_id: int) -> None:
    timeline_service.update_session_project(session_activity_ids, project_id)


def update_session_note(report_date: str, first_activity_id: int, note: str) -> None:
    timeline_service.update_session_note(report_date, first_activity_id, note)


def update_activity_group_project(activity_ids: list[int], project_id: int) -> None:
    timeline_service.update_activity_group_project(activity_ids, project_id)


def preview_session_project_update(
    session_activity_ids: list[int],
    project_id: int,
) -> dict[str, Any]:
    return timeline_service.preview_session_project_update(session_activity_ids, project_id)


# --- activity editing ----------------------------------------------------

def update_activity_note(activity_id: int, note: str) -> None:
    activity_service.update_activity_note(activity_id, note)


def soft_delete_activity(activity_id: int) -> None:
    activity_service.soft_delete_activity(activity_id)


# --- project selection (for timeline menus) ------------------------------

def list_selectable_projects() -> list[dict[str, Any]]:
    return project_service.list_selectable_projects()


# --- live-time helpers (pure functions over snapshot dicts) --------------

def get_snapshot_elapsed_seconds(snapshot: dict[str, Any] | None) -> int:
    return snapshot_elapsed_seconds(snapshot)


def get_snapshot_extra_seconds(snapshot: dict[str, Any] | None) -> int:
    return snapshot_extra_seconds(snapshot)


def get_snapshot_persisted_id(snapshot: dict[str, Any] | None) -> int | None:
    return snapshot_persisted_id(snapshot)


def get_snapshot_seconds_for_date_range(
    snapshot: dict[str, Any] | None,
    start_date: str,
    end_date: str,
) -> int:
    return snapshot_seconds_for_date_range(snapshot, start_date, end_date)


def get_snapshot_signature(snapshot: dict[str, Any] | None) -> tuple | None:
    return snapshot_signature(snapshot)


def sync_short_activity_carry_value(
    carry: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return sync_short_activity_carry(carry, previous, current)


def get_short_activity_carry_duration(
    carry: dict[str, Any] | None,
    activity_ids: list[int],
    duration_seconds: int,
    report_date: str,
    snapshot: dict[str, Any] | None,
) -> int | None:
    return short_activity_carry_duration(
        carry,
        activity_ids,
        duration_seconds,
        report_date,
        snapshot,
    )


def is_snapshot_unconfirmed(snapshot: dict[str, Any] | None) -> bool:
    return is_unconfirmed_snapshot(snapshot)


__all__ = [
    "get_default_report_date",
    "get_project_sessions_by_date",
    "get_project_sessions_by_range",
    "get_session_activity_details",
    "get_session_anchor_folders",
    "get_short_activity_carry_duration",
    "get_snapshot_elapsed_seconds",
    "get_snapshot_extra_seconds",
    "get_snapshot_persisted_id",
    "get_snapshot_seconds_for_date_range",
    "get_snapshot_signature",
    "is_snapshot_unconfirmed",
    "list_selectable_projects",
    "preview_session_project_update",
    "soft_delete_activity",
    "sync_short_activity_carry_value",
    "update_activity_group_project",
    "update_activity_note",
    "update_session_note",
    "update_session_project",
]
