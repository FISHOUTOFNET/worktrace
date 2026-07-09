from __future__ import annotations

from ..constants import UNCATEGORIZED_PROJECT
from . import session_override_service
from .project_service import get_or_create_uncategorized_project


def get_report_sessions_by_date(
    date: str,
    *,
    include_hidden: bool = True,
    ensure_context: bool = True,
) -> list[dict]:
    return get_report_sessions_by_range(
        date,
        date,
        include_hidden=include_hidden,
        ensure_context=ensure_context,
    )


def get_report_sessions_by_range(
    start_date: str,
    end_date: str,
    *,
    include_hidden: bool = True,
    ensure_context: bool = True,
) -> list[dict]:
    from . import timeline_service

    uncategorized_id = get_or_create_uncategorized_project()
    rows = timeline_service.get_report_activity_rows(
        start_date,
        end_date,
        include_hidden=include_hidden,
        ensure_context=ensure_context,
    )
    sessions = timeline_service._build_sessions_from_rows(
        rows,
        uncategorized_id,
        timeline_service._boundary_times_for_rows(rows),
    )
    for session in sessions:
        _attach_session_identity(session)
        _attach_raw_final_defaults(session, uncategorized_id)
    session_override_service.attach_overrides(sessions)
    for session in sessions:
        _finalize_session(session, uncategorized_id)
    return sorted(sessions, key=timeline_service._session_sort_key, reverse=True)


def resolve_current_session(
    report_date: str,
    activity_ids: list[int],
    activity_member_hash: str,
    *,
    include_hidden: bool = True,
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
