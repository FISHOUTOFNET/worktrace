"""Pure canonical session aggregation from already projected report rows."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

from ..constants import (
    DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    STATUS_NORMAL,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from ..formatters import format_status_label
from ..resources.title_parsing import extract_anchor_file_name
from .report_projection_identity import member_set_hash
from .report_status_policy import SESSION_CONTRIBUTION, decide_report_status


def build_report_sessions(
    rows: Sequence[dict],
    uncategorized_id: int,
    *,
    boundary_times: Sequence[str] = (),
    unrecorded_gap_boundary_seconds: int = DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
) -> list[dict]:
    """Group report contributions without reading settings or opening a DB.

    The caller owns the SQLite snapshot and supplies both explicit boundaries
    and the already-read unrecorded-gap threshold. This keeps the canonical
    projection a true single-transaction query and prevents a domain builder
    from depending on Timeline adapter internals.
    """
    threshold = max(60, int(unrecorded_gap_boundary_seconds))
    sessions: list[dict] = []
    current: list[dict] = []
    for row in rows:
        if not _is_session_contribution(row):
            if current:
                sessions.append(_build_session(current, uncategorized_id))
                current = []
            continue
        if not current:
            current = [row]
            continue
        if _can_merge(current[-1], row, boundary_times, threshold):
            current.append(row)
        else:
            sessions.append(_build_session(current, uncategorized_id))
            current = [row]
    if current:
        sessions.append(_build_session(current, uncategorized_id))
    return sessions


def _build_session(rows: Sequence[Mapping], uncategorized_id: int) -> dict:
    """Build one canonical session and aggregate semantics from every member."""
    if not rows:
        raise ValueError("report_session_requires_members")
    first = rows[0]
    last = rows[-1]
    duration = sum(_display_duration(row) for row in rows)
    closed_duration_seconds = sum(
        _display_duration(row)
        for row in rows
        if not bool(row.get("is_in_progress"))
    )
    activity_ids = [int(row.get("id") or row.get("activity_id") or 0) for row in rows]
    member_slices = _member_slices_for_rows(rows)
    status_summary = _status_summary(rows)
    is_in_progress = bool(last.get("is_in_progress"))
    open_activity_id = (
        int(last.get("id") or last.get("activity_id") or 0)
        if is_in_progress
        else 0
    )
    base = {
        "row_kind": "project_session",
        "project_id": int(first.get("report_project_id") or uncategorized_id),
        "project_name": str(
            first.get("report_project_name") or UNCATEGORIZED_PROJECT
        ),
        "project_description": str(
            first.get("report_project_description") or ""
        ),
        "project_is_deleted": bool(first.get("report_project_is_deleted")),
        "project_is_archived": bool(first.get("report_project_is_archived")),
        "start_time": first.get("start_time"),
        "end_time": last.get("end_time"),
        "report_date": first.get("report_date"),
        "duration_seconds": duration,
        "closed_duration_seconds": int(closed_duration_seconds),
        "open_activity_id": open_activity_id,
        "activity_ids": activity_ids,
        "member_slices": member_slices,
        "activity_member_hash": member_set_hash(
            str(first.get("report_date") or ""),
            member_slices,
        ),
        "anchor_activity_id": int(activity_ids[0]) if activity_ids else 0,
        "first_activity_id": int(activity_ids[0]) if activity_ids else None,
        "session_note": "",
        "sort_time": last.get("start_time") or first.get("start_time"),
        "event_count": len(rows),
        "status": (
            first.get("status")
            if len({row.get("status") for row in rows}) == 1
            else "mixed"
        ),
        "status_code": STATUS_NORMAL,
        "display_status": status_summary,
        "status_summary": status_summary,
        "contributes_to_totals": True,
        "live_delta_eligible": False,
        "editable": not is_in_progress,
        "exportable": not is_in_progress,
        "is_suggested_project": False,
        "is_in_progress": is_in_progress,
    }
    return _finalize_session_semantics(base, rows)


def _finalize_session_semantics(
    session: dict,
    rows: Sequence[Mapping],
) -> dict:
    """Derive session-level project semantics from all contributions.

    A session that starts with attributed idle/excluded time must not appear
    derived when it also contains an official direct contribution. Selection
    is deterministic and independent from contribution order.
    """
    keys = {str(row.get("report_project_key") or "") for row in rows}
    if len(keys) != 1:
        raise ValueError("report_session_project_key_mismatch")

    official_rows = [
        row for row in rows if bool(row.get("is_official_project"))
    ]
    representative = min(
        official_rows or list(rows),
        key=lambda row: (
            str(row.get("start_time") or ""),
            int(row.get("id") or row.get("activity_id") or 0),
        ),
    )
    kinds = {
        str(row.get("report_attribution_kind") or "none")
        for row in rows
        if str(row.get("report_attribution_kind") or "none") != "none"
    }
    if "official_direct" in kinds:
        attribution_kind = "official_direct"
    elif len(kinds) == 1:
        attribution_kind = next(iter(kinds))
    elif kinds:
        attribution_kind = "report_context_mixed"
    else:
        attribution_kind = "none"

    session.update(
        {
            "project_id": int(
                representative.get("report_project_id")
                or session.get("project_id")
                or 0
            ),
            "project_name": str(
                representative.get("report_project_name")
                or session.get("project_name")
                or UNCATEGORIZED_PROJECT
            ),
            "project_description": str(
                representative.get("report_project_description")
                or session.get("project_description")
                or ""
            ),
            "project_is_deleted": any(
                bool(row.get("report_project_is_deleted")) for row in rows
            ),
            "project_is_archived": all(
                bool(row.get("report_project_is_archived")) for row in rows
            ),
            "is_official_project": bool(official_rows),
            "report_attribution_kind": attribution_kind,
            "is_report_project": all(
                bool(row.get("is_report_project")) for row in rows
            ),
            "is_report_classified": all(
                bool(row.get("is_report_classified")) for row in rows
            ),
            "is_report_uncategorized": all(
                bool(row.get("is_report_uncategorized")) for row in rows
            ),
        }
    )
    session["is_classified"] = bool(session["is_report_classified"])
    session["is_uncategorized"] = bool(session["is_report_uncategorized"])
    return session


def _status_summary(rows: Sequence[Mapping]) -> str:
    items: list[str] = []
    for row in rows:
        status = str(row.get("status") or "")
        if status == STATUS_NORMAL:
            label = _activity_summary_label(row)
        else:
            label = format_status_label(status)
        if label and label not in items:
            items.append(label)
        if len(items) >= 3:
            break
    return "、".join(items) if items else "正常活动"


def _activity_summary_label(row: Mapping) -> str:
    activity_name = str(row.get("activity_display_name") or "").strip()
    if row.get("resource_is_anchor") and activity_name:
        return activity_name
    title_file = extract_anchor_file_name(row.get("window_title"))
    if title_file:
        return title_file
    return str(row.get("app_name") or row.get("process_name") or "").strip()


def _display_duration(row: Mapping) -> int:
    if row.get("duration_seconds") is not None:
        return int(row.get("duration_seconds") or 0)
    return 0


def _member_slices_for_rows(rows: Sequence[Mapping]) -> list[dict]:
    members: list[dict] = []
    for row in rows:
        report_date = str(row.get("report_date") or "")[:10]
        activity_id = int(row.get("id") or row.get("activity_id") or 0)
        slice_start = str(row.get("start_time") or "")
        slice_end = str(row.get("end_time") or "")
        if not report_date or activity_id <= 0 or not slice_start or not slice_end:
            continue
        members.append(
            {
                "report_date": report_date,
                "activity_id": activity_id,
                "slice_start_time": slice_start,
                "slice_end_time": slice_end,
            }
        )
    return members


def _is_session_contribution(row: Mapping) -> bool:
    decision = decide_report_status(
        str(row.get("status") or ""),
        has_project_attribution=bool(row.get("is_report_project")),
    )
    return decision.decision == SESSION_CONTRIBUTION


def _can_merge(
    previous: Mapping,
    current: Mapping,
    boundary_times: Sequence[str],
    gap_threshold_seconds: int,
) -> bool:
    if not (
        _is_session_contribution(previous)
        and _is_session_contribution(current)
    ):
        return False
    if str(previous.get("report_date") or "") != str(
        current.get("report_date") or ""
    ):
        return False
    if _crosses_explicit_boundary(previous, current, boundary_times):
        return False
    if _has_unrecorded_gap(previous, current, gap_threshold_seconds):
        return False
    return str(previous.get("report_project_key") or "") == str(
        current.get("report_project_key") or ""
    )


def _crosses_explicit_boundary(
    previous: Mapping,
    current: Mapping,
    boundary_times: Sequence[str],
) -> bool:
    start = str(previous.get("end_time") or previous.get("start_time") or "")
    end = str(current.get("start_time") or "")
    if not start or not end or start > end:
        return False
    return any(start <= str(boundary) <= end for boundary in boundary_times)


def _has_unrecorded_gap(
    previous: Mapping,
    current: Mapping,
    threshold_seconds: int,
) -> bool:
    previous_end = _parse(previous.get("end_time"))
    current_start = _parse(current.get("start_time"))
    if previous_end is None or current_start is None:
        return False
    gap_seconds = int((current_start - previous_end).total_seconds())
    return gap_seconds > max(60, int(threshold_seconds))


def _parse(value) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), TIME_FORMAT)
    except (TypeError, ValueError):
        return None


__all__ = ["build_report_sessions"]
