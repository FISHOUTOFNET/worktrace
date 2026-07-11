from __future__ import annotations

import hashlib
import json

from ..db import get_connection
from ..constants import UNCATEGORIZED_PROJECT
from . import report_session_operation_engine, session_override_service
from . import project_lifecycle_policy
from .project_service import get_or_create_uncategorized_project


def get_report_sessions_by_date(
    date: str,
    *,
    include_hidden: bool = False,
    ensure_context: bool = True,
) -> list[dict]:
    return get_report_sessions_by_range(
        date,
        date,
        include_hidden=include_hidden,
        ensure_context=ensure_context,
    )


def get_visible_report_sessions_by_date(date: str, *, ensure_context: bool = True) -> list[dict]:
    """The sole UI/report projection scope: hidden raw activity is excluded."""
    return get_report_sessions_by_date(date, include_hidden=False, ensure_context=ensure_context)


def get_visible_report_sessions_for_operations_by_date(date: str, *, ensure_context: bool = True) -> list[dict]:
    """Visible canonical sessions for resolvers and contribution consumers."""
    return get_report_sessions_for_operations(
        date, date, include_hidden=False, ensure_context=ensure_context
    )


def get_report_sessions_by_range(
    start_date: str,
    end_date: str,
    *,
    include_hidden: bool = False,
    ensure_context: bool = True,
) -> list[dict]:
    sessions = get_report_sessions_for_operations(
        start_date,
        end_date,
        include_hidden=include_hidden,
        ensure_context=ensure_context,
    )
    return [_public_session(session) for session in sessions]


def get_report_sessions_for_operations(
    start_date: str,
    end_date: str,
    *,
    include_hidden: bool = True,
    ensure_context: bool = True,
) -> list[dict]:
    """Build final sessions including private, display-safe contribution slices.

    This is an internal service entry used by operation commands and summary
    aggregation.  The public session entry strips the contribution payload so
    Timeline cards never receive row-level data they do not render.
    """
    from . import timeline_service
    from . import report_session_operation_service

    if ensure_context:
        # Context writes complete before the bounded report read snapshot.
        timeline_service._ensure_context_for_report_range(start_date, end_date)
    with get_connection() as conn:
        conn.execute("BEGIN")
        uncategorized_id = get_or_create_uncategorized_project(conn=conn)
        rows = timeline_service.get_report_activity_rows(
            start_date, end_date, include_hidden=include_hidden, ensure_context=False, conn=conn
        )
        sessions = timeline_service._build_sessions_from_rows(
            rows, uncategorized_id, timeline_service._boundary_times_for_rows(rows, conn=conn)
        )
        for session in sessions:
            _attach_session_identity(session)
            _attach_raw_final_defaults(session, uncategorized_id)
        session_override_service.attach_overrides(sessions, conn=conn)
        for session in sessions:
            _finalize_session(session, uncategorized_id)
            _attach_projection_defaults(session)
        sessions = [session for session in sessions if project_lifecycle_policy.final_session_is_reportable(session)]
        _attach_contributions(sessions, rows)
        projected: list[dict] = []
        by_date: dict[str, list[dict]] = {}
        for session in sessions:
            by_date.setdefault(str(session.get("report_date") or ""), []).append(session)
        for report_date, date_sessions in by_date.items():
            ordered = sorted(date_sessions, key=timeline_service._session_sort_key, reverse=True)
            operations = report_session_operation_service.load_operations(report_date, conn=conn)
            projected.extend(report_session_operation_engine.apply_operations(ordered, operations))
    for session in projected:
        _attach_detail_revision(session)
    return sorted(projected, key=timeline_service._session_sort_key, reverse=True)


def get_projected_activity_contributions_by_range(
    start_date: str,
    end_date: str,
    *,
    include_hidden: bool = False,
    ensure_context: bool = True,
) -> list[dict]:
    from . import timeline_service
    from .activity_continuity_service import is_normal_project_status

    sessions = get_report_sessions_for_operations(
        start_date, end_date, include_hidden=include_hidden, ensure_context=ensure_context
    )
    contributions = report_session_operation_engine.build_projected_activity_contributions(sessions)
    # Structural session operations deliberately apply only to normal project
    # sessions. Status rows (idle/paused/excluded) remain raw report facts and
    # must remain in statistics totals and by-status grouping.
    status_rows = timeline_service.get_report_activity_rows(
        start_date, end_date, include_hidden=include_hidden, ensure_context=False
    )
    for row in status_rows:
        if is_normal_project_status(str(row.get("status") or "")):
            continue
        item = _display_safe_contribution(row)
        item["projection_instance_key"] = f"status:{item['report_date']}:{item['activity_id']}:{item['slice_start_time']}"
        item["projection_kind"] = "status"
        contributions.append(item)
    return contributions


def resolve_current_session(
    report_date: str,
    activity_ids: list[int],
    activity_member_hash: str,
    *,
    include_hidden: bool = False,
    ensure_context: bool = True,
) -> dict:
    ids = {int(aid) for aid in activity_ids}
    if not report_date or not ids or not activity_member_hash:
        raise ValueError("invalid_session_identity")
    sessions = get_report_sessions_by_date(
        report_date,
        include_hidden=include_hidden,
        ensure_context=ensure_context,
    )
    for session in sessions:
        if str(session.get("activity_member_hash") or "") != str(activity_member_hash):
            continue
        if {int(aid) for aid in session.get("activity_ids") or []} != ids:
            continue
        if not bool(session.get("editable", False)):
            raise ValueError("not_project_activity")
        return session
    raise ValueError("session_identity_conflict")


def _attach_session_identity(session: dict) -> None:
    members = list(session.get("member_slices") or [])
    report_date = str(session.get("report_date") or "")[:10]
    member_hash = session_override_service.activity_member_hash(report_date, members)
    activity_ids = [int(aid) for aid in session.get("activity_ids") or []]
    session["activity_member_hash"] = member_hash
    session["anchor_activity_id"] = int(activity_ids[0]) if activity_ids else 0
    session["first_activity_id"] = session["anchor_activity_id"] or None


def _attach_projection_defaults(session: dict) -> None:
    member_hash = str(session.get("activity_member_hash") or "")
    session.update(
        {
            "projection_instance_key": f"base:{member_hash}",
            "projection_kind": "base",
            "operation_id": None,
            "operation_group_key": None,
            "origin_activity_member_hashes": [member_hash] if member_hash else [],
            "operation_match_state": "active",
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


def _display_safe_contribution(row: dict) -> dict:
    return {
        "activity_id": int(row.get("id") or row.get("activity_id") or 0),
        "report_date": str(row.get("report_date") or ""),
        "slice_start_time": str(row.get("start_time") or ""),
        "slice_end_time": str(row.get("end_time") or ""),
        "start_time": str(row.get("start_time") or ""),
        "end_time": str(row.get("end_time") or ""),
        "duration_seconds": int(row.get("report_duration_seconds") or row.get("duration_seconds") or 0),
        "app_name": str(row.get("app_name") or ""),
        "process_name": str(row.get("process_name") or ""),
        "status": str(row.get("status") or ""),
        "is_in_progress": bool(row.get("is_in_progress")),
        "activity_display_name": str(row.get("activity_display_name") or row.get("app_name") or "未知活动"),
        "activity_identity_key": str(row.get("activity_identity_key") or row.get("resource_identity_key") or ""),
        "resource_identity_key": str(row.get("resource_identity_key") or ""),
        "resource_kind": str(row.get("resource_kind") or ""),
        "resource_subtype": str(row.get("resource_subtype") or ""),
        "resource_display_name": str(row.get("resource_display_name") or ""),
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


def _member_key(member: dict) -> tuple[str, int, str]:
    return session_override_service.member_identity_key(member)


def _member_key_from_row(row: dict) -> tuple[str, int, str, str]:
    return _member_key(row)


def _attach_detail_revision(session: dict) -> None:
    """Revision of detail structure, intentionally excluding live elapsed seconds."""
    payload = {
        "kind": session.get("projection_kind"),
        "key": session.get("projection_instance_key"),
        "members": [_member_key(member) for member in session.get("member_slices") or []],
        "project": session.get("project_id"),
        "override": session.get("override_id"),
        "adjusted": session.get("adjusted_duration_seconds"),
        "note": session.get("session_note"),
        "open": bool(session.get("is_in_progress")),
        "contributions": [
            (_member_key(row), row.get("activity_identity_key"), row.get("report_project_id"), row.get("activity_display_name"))
            for row in session.get("_projection_contributions") or []
        ],
    }
    session["session_detail_revision"] = hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _public_session(session: dict) -> dict:
    return {key: value for key, value in session.items() if not key.startswith("_projection_")}


def _attach_raw_final_defaults(session: dict, uncategorized_id: int) -> None:
    raw_project_id = int(session.get("project_id") or uncategorized_id)
    raw_project_name = str(session.get("project_name") or UNCATEGORIZED_PROJECT)
    raw_project_description = str(session.get("project_description") or "")
    raw_duration = int(session.get("duration_seconds") or 0)
    session["raw_assignment_project_id"] = raw_project_id
    session["raw_assignment_project_name"] = raw_project_name
    session["raw_assignment_project_description"] = raw_project_description
    session["raw_duration_seconds"] = raw_duration
    session["display_duration_seconds"] = raw_duration
    session["adjusted_duration_seconds"] = None
    session["override_id"] = None
    session["override_match_state"] = None
    session["has_project_override"] = False
    session["has_duration_override"] = False
    session["project_is_deleted"] = bool(session.get("project_is_deleted"))
    session["project_is_archived"] = bool(session.get("project_is_archived"))
    session["session_note"] = ""


def _finalize_session(session: dict, uncategorized_id: int) -> None:
    original_closed_duration = int(session.get("closed_duration_seconds") or 0)
    display_duration = int(
        session.get("display_duration_seconds")
        if session.get("display_duration_seconds") is not None
        else session.get("raw_duration_seconds")
        or 0
    )
    session["duration_seconds"] = display_duration
    session["display_duration_seconds"] = display_duration
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
