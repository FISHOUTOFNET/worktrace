from __future__ import annotations

from typing import Any, Mapping

from ..constants import EXCLUDED_APP_NAME, STATUS_EXCLUDED, UNCATEGORIZED_PROJECT
from . import project_lifecycle_policy
from .report_projection_identity import base_projection_key, member_identity_key, member_set_hash, projection_revision
from .report_projection_model import thaw_value


def get_report_sessions_by_date(
    date: str,
) -> list[dict]:
    return get_report_sessions_by_range(date, date)


def get_visible_report_sessions_by_date(date: str) -> list[dict]:
    """The sole UI/report projection scope: hidden raw activity is excluded."""
    return get_report_sessions_by_date(date)


def get_visible_report_sessions_for_operations_by_date(date: str) -> list[dict]:
    """Visible canonical sessions for resolvers and contribution consumers."""
    return get_report_sessions_for_operations(date, date)


def get_report_sessions_by_range(
    start_date: str,
    end_date: str,
) -> list[dict]:
    return [public_session_dto(session) for session in get_report_sessions_for_operations(start_date, end_date)]


def _mutable_record(value: Mapping[str, Any]) -> dict[str, Any]:
    """Thaw one canonical record into a detached plain-data adapter value."""
    result = thaw_value(value)
    if not isinstance(result, dict):
        raise TypeError("canonical record must thaw to dict")
    return result


def get_report_sessions_for_operations(
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Build detached mutable copies of final canonical sessions.

    The canonical snapshot recursively freezes its records. Adapter consumers
    must cross this boundary through one recursive thaw rather than selectively
    converting known list fields, otherwise future nested values can leak tuple
    or frozen mapping implementations into public/service contracts.
    """
    from .report_projection_snapshot_service import build_visible_snapshot

    projected = [
        _mutable_record(session)
        for session in build_visible_snapshot(start_date, end_date).final_sessions
        if project_lifecycle_policy.final_session_is_reportable(session)
    ]
    for session in projected:
        _attach_detail_revision(session)
    return projected


def get_projected_activity_contributions_by_range(
    start_date: str,
    end_date: str,
) -> list[dict]:
    from .report_projection_snapshot_service import build_visible_snapshot

    return [
        _mutable_record(item)
        for item in build_visible_snapshot(start_date, end_date).final_contributions
    ]


def _attach_session_identity(session: dict) -> None:
    members = list(session.get("member_slices") or [])
    report_date = str(session.get("report_date") or "")[:10]
    member_hash = member_set_hash(report_date, members)
    activity_ids = [int(aid) for aid in session.get("activity_ids") or []]
    session["activity_member_hash"] = member_hash
    session["anchor_activity_id"] = int(activity_ids[0]) if activity_ids else 0
    session["first_activity_id"] = session["anchor_activity_id"] or None


def _attach_projection_defaults(session: dict) -> None:
    member_hash = str(session.get("activity_member_hash") or "")
    session.update(
        {
            "projection_instance_key": base_projection_key(str(session.get("report_date") or ""), session.get("member_slices") or []),
            "projection_kind": "base",
            "operation_id": None,
            "origin_activity_member_hashes": [member_hash] if member_hash else [],
            "can_hide": bool(session.get("editable")),
            "can_merge_previous": False,
            "can_merge_next": False,
            "can_split": False,
            "can_copy": bool(session.get("editable")),
            "can_hide_activity": bool(session.get("editable")),
        }
    )


def _attach_contributions(sessions: list[dict], rows: list[dict]) -> None:
    by_member = {
        _member_key_from_row(row): _display_safe_contribution(row)
        for row in rows
        if _member_key_from_row(row)[1] > 0
    }
    for session in sessions:
        session["_projection_contributions"] = [
            dict(by_member[key])
            for key in (_member_key(member) for member in session.get("member_slices") or [])
            if key in by_member
        ]


def _display_safe_contribution(row: Mapping[str, Any]) -> dict:
    activity_id = int(row.get("id") or row.get("activity_id") or 0)
    report_date = str(row.get("report_date") or "")
    slice_start = str(row.get("start_time") or "")
    status = str(row.get("status") or "")
    privacy_redacted = status == STATUS_EXCLUDED

    if privacy_redacted:
        app_name = ""
        process_name = ""
        activity_display_name = EXCLUDED_APP_NAME
        activity_identity_key = f"excluded:{report_date}:{activity_id}:{slice_start}"
        resource_identity_key = ""
        resource_kind = ""
        resource_subtype = ""
        resource_display_name = ""
    else:
        app_name = str(row.get("app_name") or "")
        process_name = str(row.get("process_name") or "")
        activity_display_name = str(row.get("activity_display_name") or row.get("app_name") or "未知活动")
        activity_identity_key = str(row.get("activity_identity_key") or row.get("resource_identity_key") or "")
        resource_identity_key = str(row.get("resource_identity_key") or "")
        resource_kind = str(row.get("resource_kind") or "")
        resource_subtype = str(row.get("resource_subtype") or "")
        resource_display_name = str(row.get("resource_display_name") or "")

    return {
        "activity_id": activity_id,
        "report_date": report_date,
        "slice_start_time": slice_start,
        "slice_end_time": str(row.get("end_time") or ""),
        "start_time": slice_start,
        "end_time": str(row.get("end_time") or ""),
        "duration_seconds": int(row.get("report_duration_seconds") or row.get("duration_seconds") or 0),
        "app_name": app_name,
        "process_name": process_name,
        "status": status,
        "is_in_progress": bool(row.get("is_in_progress")),
        "activity_display_name": activity_display_name,
        "activity_identity_key": activity_identity_key,
        "resource_identity_key": resource_identity_key,
        "resource_kind": resource_kind,
        "resource_subtype": resource_subtype,
        "resource_display_name": resource_display_name,
        "privacy_redacted": privacy_redacted,
        "display_project_id": int(row.get("display_project_id") or 0),
        "display_project_name": str(row.get("display_project_name") or UNCATEGORIZED_PROJECT),
        "display_project_description": str(row.get("display_project_description") or ""),
        "report_project_id": int(row.get("report_project_id") or 0),
        "report_project_name": str(row.get("report_project_name") or UNCATEGORIZED_PROJECT),
        "report_project_description": str(row.get("report_project_description") or ""),
        "is_report_project": bool(row.get("is_report_project")),
        "is_report_classified": bool(row.get("is_report_classified")),
        "is_report_uncategorized": bool(row.get("is_report_uncategorized")),
        "report_attribution_kind": str(row.get("report_attribution_kind") or "none"),
        "is_official_project": bool(row.get("is_official_project")),
    }


def _member_key(member: Mapping[str, Any]) -> tuple[str, int, str]:
    return member_identity_key(dict(member))


def _member_key_from_row(row: Mapping[str, Any]) -> tuple[str, int, str]:
    return _member_key(row)


def _attach_detail_revision(session: dict) -> None:
    """Revision of detail structure, intentionally excluding live elapsed seconds."""
    session["projection_revision"] = projection_revision(session)


_PUBLIC_SESSION_FIELDS = (
    "row_kind", "report_date", "projection_instance_key", "projection_revision",
    "projection_kind", "operation_id", "project_id", "project_name",
    "project_description", "project_is_deleted", "project_is_archived",
    "project_is_enabled", "is_official_project", "report_attribution_kind",
    "is_report_project", "is_report_classified", "is_report_uncategorized",
    "is_classified", "is_uncategorized", "contributes_to_totals",
    "start_time", "end_time", "duration_seconds", "closed_duration_seconds",
    "adjusted_duration_seconds", "has_duration_override", "session_note",
    "has_project_override", "is_in_progress", "editable", "exportable",
    "activity_ids", "member_slices", "anchor_activity_id", "first_activity_id",
    "event_count", "status", "status_code", "status_summary", "can_hide",
    "can_copy", "can_hide_activity", "can_merge_previous", "can_merge_next",
    "can_split",
)


def public_session_dto(session: Mapping[str, Any]) -> dict:
    """Return an allowlisted, recursively plain WebView/report DTO."""
    selected = {field: session.get(field) for field in _PUBLIC_SESSION_FIELDS}
    result = thaw_value(selected)
    if not isinstance(result, dict):
        raise TypeError("public session DTO must be dict")
    return result


def _attach_raw_final_defaults(session: dict, uncategorized_id: int) -> None:
    session["project_id"] = int(session.get("project_id") or uncategorized_id)
    session["project_name"] = str(session.get("project_name") or UNCATEGORIZED_PROJECT)
    session["project_description"] = str(session.get("project_description") or "")
    session["adjusted_duration_seconds"] = None
    session["has_project_override"] = False
    session["has_duration_override"] = False
    session["project_is_deleted"] = bool(session.get("project_is_deleted"))
    session["project_is_archived"] = bool(session.get("project_is_archived"))
    session["session_note"] = ""


def _finalize_session(session: dict, uncategorized_id: int) -> None:
    original_closed_duration = int(session.get("closed_duration_seconds") or 0)
    display_duration = int(session.get("duration_seconds") or 0)
    session["duration_seconds"] = display_duration
    if bool(session.get("is_in_progress")):
        session["closed_duration_seconds"] = original_closed_duration
    else:
        session["closed_duration_seconds"] = display_duration
    project_id = int(session.get("project_id") or uncategorized_id)
    session["project_id"] = project_id
    session["project_name"] = str(session.get("project_name") or UNCATEGORIZED_PROJECT)
    session["project_description"] = str(session.get("project_description") or "")
    session["project_is_deleted"] = bool(session.get("project_is_deleted"))
    session["project_is_archived"] = bool(session.get("project_is_archived"))
    is_uncat = project_id == int(uncategorized_id)
    if bool(session.get("has_project_override")):
        is_report_project = not is_uncat
        is_report_classified = not is_uncat
        is_report_uncategorized = is_uncat
    else:
        is_report_project = bool(session.get("is_report_project", not is_uncat))
        is_report_classified = bool(session.get("is_report_classified", is_report_project))
        is_report_uncategorized = bool(session.get("is_report_uncategorized", not is_report_project))
    session["is_report_project"] = is_report_project
    session["is_report_classified"] = is_report_classified
    session["is_report_uncategorized"] = is_report_uncategorized
    session["is_classified"] = is_report_classified
    session["is_uncategorized"] = is_report_uncategorized
    session["editable"] = bool(session.get("editable", True)) and not bool(session.get("is_in_progress"))
    session["exportable"] = bool(session.get("exportable", True)) and not bool(session.get("is_in_progress"))
