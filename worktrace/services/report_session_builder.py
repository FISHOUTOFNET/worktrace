"""Pure canonical session aggregation from already projected report rows."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Mapping, Sequence

from ..constants import (
    DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from ..formatters import format_status_label
from ..resources.title_parsing import extract_anchor_file_name
from .context_service import BoundaryIndex
from .report_projection_identity import member_set_hash
from .report_status_policy import SESSION_CONTRIBUTION, decide_report_status

SHORT_PROJECT_RETURN_MERGE_SECONDS = 5 * 60


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
    boundary_index = BoundaryIndex(boundary_times)
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
        if _can_merge(current[-1], row, boundary_index, threshold):
            current.append(row)
        else:
            sessions.append(_build_session(current, uncategorized_id))
            current = [row]
    if current:
        sessions.append(_build_session(current, uncategorized_id))
    return sessions


def merge_short_project_returns(
    sessions: Sequence[dict],
    *,
    boundary_times: Sequence[str] = (),
    protected_member_sets: Sequence[frozenset[tuple[str, int, str]]] = (),
    interval_rows: Sequence[Mapping] = (),
    unrecorded_gap_boundary_seconds: int = DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    max_interruption_seconds: int = SHORT_PROJECT_RETURN_MERGE_SECONDS,
) -> list[dict]:
    """Greedily merge short returns to the same concrete project.

    A return is measured by wall clock from the current project session's end
    to the next session for that project. Intermediate project sessions and
    soft status rows inside that interval become members of the merged canonical
    session. Only caller-supplied semantic boundaries block this second-stage
    merge; collection lifecycle boundaries such as restart/sleep are
    intentionally not inferred here.

    Existing durable operation bindings are supplied as member sets. A merge
    that would change a strict-subset binding is skipped so historical edits
    keep their exact replay identity. Operations already bound to the complete
    merged member set remain valid.

    Adjacent same-project sessions are only rejoined when their gap is within
    the canonical unrecorded-gap threshold (for example a technical lifecycle
    boundary) or when a real interval row exists between them. This preserves
    explicit data-gap semantics while still allowing short sleep/restart and
    privacy/status interruptions to collapse naturally.
    """
    threshold = max(0, int(max_interruption_seconds))
    gap_threshold = max(0, int(unrecorded_gap_boundary_seconds))
    boundary_index = BoundaryIndex(boundary_times)
    protected = tuple(frozenset(item) for item in protected_member_sets if item)
    interval_source = tuple(dict(row) for row in interval_rows)
    result: list[dict] = []
    index = 0
    total = len(sessions)

    while index < total:
        current = deepcopy(dict(sessions[index]))
        consumed = index
        if not _is_short_return_anchor(current):
            result.append(current)
            index += 1
            continue

        while True:
            matched_index: int | None = None
            cursor = consumed + 1
            while cursor < total:
                candidate = sessions[cursor]
                if str(candidate.get("report_date") or "") != str(
                    current.get("report_date") or ""
                ):
                    break
                interruption = _session_gap_seconds(current, candidate)
                if interruption is None or interruption > threshold:
                    break
                if _crosses_session_boundary(current, candidate, boundary_index):
                    break
                if _same_concrete_project(current, candidate):
                    if bool(candidate.get("is_in_progress")):
                        break
                    if cursor == consumed + 1:
                        interval_members = _interval_row_member_identity_set(
                            current,
                            candidate,
                            interval_source,
                        )
                        if not interval_members and interruption > gap_threshold:
                            break
                    matched_index = cursor
                    break
                cursor += 1

            if matched_index is None:
                break

            group = [
                current,
                *(deepcopy(dict(item)) for item in sessions[consumed + 1 : matched_index + 1]),
            ]
            candidate_members = _group_member_identity_set(group)
            candidate_members = candidate_members.union(
                _interval_row_member_identity_set(
                    current,
                    sessions[matched_index],
                    interval_source,
                )
            )
            if _protected_merge_conflict(
                frozenset(candidate_members),
                protected,
            ):
                break
            current = _merge_short_return_group(group)
            consumed = matched_index

        result.append(current)
        index = consumed + 1

    return _attach_short_return_interval_rows(result, interval_source)


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
        "report_project_key": str(first.get("report_project_key") or ""),
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


def _is_short_return_anchor(session: Mapping) -> bool:
    return bool(
        str(session.get("row_kind") or "project_session") == "project_session"
        and bool(session.get("is_report_project"))
        and int(session.get("project_id") or 0) > 0
        and not bool(session.get("project_is_deleted"))
        and not bool(session.get("is_in_progress"))
    )


def _same_concrete_project(left: Mapping, right: Mapping) -> bool:
    return bool(
        _is_short_return_anchor(left)
        and bool(right.get("is_report_project"))
        and int(right.get("project_id") or 0) == int(left.get("project_id") or 0)
        and not bool(right.get("project_is_deleted"))
    )


def _session_gap_seconds(left: Mapping, right: Mapping) -> int | None:
    left_end = _parse_time(left.get("end_time"))
    right_start = _parse_time(right.get("start_time"))
    if left_end is None or right_start is None or right_start < left_end:
        return None
    return int((right_start - left_end).total_seconds())


def _crosses_session_boundary(
    left: Mapping,
    right: Mapping,
    boundary_index: BoundaryIndex,
) -> bool:
    start = str(left.get("end_time") or left.get("start_time") or "")
    end = str(right.get("start_time") or "")
    return boundary_index.crosses(start, end)


def _merge_short_return_group(group: Sequence[Mapping]) -> dict:
    if len(group) < 2:
        raise ValueError("short_return_merge_requires_return")
    first = group[0]
    last = group[-1]
    if not _same_concrete_project(first, last):
        raise ValueError("short_return_merge_project_mismatch")

    merged = deepcopy(dict(first))
    activity_ids: list[int] = []
    member_slices: list[dict] = []
    for session in group:
        for activity_id in session.get("activity_ids") or []:
            value = int(activity_id or 0)
            if value > 0 and value not in activity_ids:
                activity_ids.append(value)
        member_slices.extend(
            deepcopy(dict(member)) for member in session.get("member_slices") or []
        )

    duration = _wall_clock_span_seconds(first, last)
    if duration is None:
        duration = sum(max(0, int(item.get("duration_seconds") or 0)) for item in group)

    merged.update(
        {
            "start_time": first.get("start_time"),
            "end_time": last.get("end_time"),
            "duration_seconds": duration,
            "closed_duration_seconds": duration,
            "open_activity_id": 0,
            "activity_ids": activity_ids,
            "member_slices": member_slices,
            "activity_member_hash": member_set_hash(
                str(first.get("report_date") or ""),
                member_slices,
            ),
            "anchor_activity_id": int(activity_ids[0]) if activity_ids else 0,
            "first_activity_id": int(activity_ids[0]) if activity_ids else None,
            "sort_time": last.get("start_time") or first.get("start_time"),
            "event_count": sum(max(0, int(item.get("event_count") or 0)) for item in group),
            "status": (
                first.get("status")
                if len({str(item.get("status") or "") for item in group}) == 1
                else "mixed"
            ),
            "status_code": STATUS_NORMAL,
            "contributes_to_totals": True,
            "live_delta_eligible": False,
            "editable": all(bool(item.get("editable", True)) for item in group),
            "exportable": all(bool(item.get("exportable", True)) for item in group),
            "is_in_progress": False,
            "_wall_clock_duration_seconds": duration,
            "_short_project_return_merged": True,
        }
    )

    anchor_sessions = (first, last)
    if any(bool(item.get("is_official_project")) for item in anchor_sessions):
        merged["is_official_project"] = True
        merged["report_attribution_kind"] = "official_direct"
    return merged


def _attach_short_return_interval_rows(
    sessions: Sequence[dict],
    rows: Sequence[Mapping],
) -> list[dict]:
    if not rows:
        return [deepcopy(dict(session)) for session in sessions]
    result = [deepcopy(dict(session)) for session in sessions]
    for session in result:
        if not bool(session.get("_short_project_return_merged")):
            continue
        existing = set(_session_member_identity_set(session))
        start = _parse_time(session.get("start_time"))
        end = _parse_time(session.get("end_time"))
        if start is None or end is None or end <= start:
            continue
        for row in rows:
            if str(row.get("report_date") or "") != str(session.get("report_date") or ""):
                continue
            if str(row.get("status") or "") == STATUS_PAUSED:
                continue
            row_start = _parse_time(row.get("start_time"))
            row_end = _parse_time(row.get("end_time")) or row_start
            if row_start is None or row_end is None:
                continue
            if row_start >= end or row_end <= start:
                continue
            identity = _row_member_identity(row)
            if identity is None or identity in existing:
                continue
            existing.add(identity)
            activity_id = identity[1]
            session["activity_ids"].append(activity_id)
            session["member_slices"].append(
                {
                    "report_date": identity[0],
                    "activity_id": activity_id,
                    "slice_start_time": identity[2],
                    "slice_end_time": str(row.get("end_time") or identity[2]),
                }
            )
            session["event_count"] = int(session.get("event_count") or 0) + 1
        session["member_slices"].sort(
            key=lambda item: (
                str(item.get("slice_start_time") or ""),
                int(item.get("activity_id") or 0),
            )
        )
        ordered_ids: list[int] = []
        for member in session["member_slices"]:
            activity_id = int(member.get("activity_id") or 0)
            if activity_id > 0 and activity_id not in ordered_ids:
                ordered_ids.append(activity_id)
        session["activity_ids"] = ordered_ids
        session["activity_member_hash"] = member_set_hash(
            str(session.get("report_date") or ""),
            session["member_slices"],
        )
        session["anchor_activity_id"] = int(ordered_ids[0]) if ordered_ids else 0
        session["first_activity_id"] = int(ordered_ids[0]) if ordered_ids else None
    return result


def _interval_row_member_identity_set(
    left: Mapping,
    right: Mapping,
    rows: Sequence[Mapping],
) -> frozenset[tuple[str, int, str]]:
    start = _parse_time(left.get("end_time"))
    end = _parse_time(right.get("start_time"))
    if start is None or end is None or end < start:
        return frozenset()
    report_date = str(left.get("report_date") or "")
    result: set[tuple[str, int, str]] = set()
    for row in rows:
        if str(row.get("report_date") or "") != report_date:
            continue
        if str(row.get("status") or "") == STATUS_PAUSED:
            continue
        row_start = _parse_time(row.get("start_time"))
        row_end = _parse_time(row.get("end_time")) or row_start
        if row_start is None or row_end is None:
            continue
        if row_start >= end or row_end <= start:
            continue
        identity = _row_member_identity(row)
        if identity is not None:
            result.add(identity)
    return frozenset(result)


def _row_member_identity(row: Mapping) -> tuple[str, int, str] | None:
    report_date = str(row.get("report_date") or "")[:10]
    activity_id = int(row.get("id") or row.get("activity_id") or 0)
    start = str(row.get("start_time") or row.get("slice_start_time") or "")
    if not report_date or activity_id <= 0 or not start:
        return None
    return report_date, activity_id, start


def _wall_clock_span_seconds(first: Mapping, last: Mapping) -> int | None:
    start = _parse_time(first.get("start_time"))
    end = _parse_time(last.get("end_time"))
    if start is None or end is None or end < start:
        return None
    return int((end - start).total_seconds())


def _group_member_identity_set(
    group: Sequence[Mapping],
) -> frozenset[tuple[str, int, str]]:
    result: set[tuple[str, int, str]] = set()
    for session in group:
        result.update(_session_member_identity_set(session))
    return frozenset(result)


def _session_member_identity_set(
    session: Mapping,
) -> frozenset[tuple[str, int, str]]:
    return frozenset(
        (
            str(member.get("report_date") or session.get("report_date") or "")[:10],
            int(member.get("activity_id") or member.get("id") or 0),
            str(member.get("slice_start_time") or member.get("start_time") or ""),
        )
        for member in session.get("member_slices") or []
        if int(member.get("activity_id") or member.get("id") or 0) > 0
    )


def _protected_merge_conflict(
    candidate_members: frozenset[tuple[str, int, str]],
    protected_member_sets: Sequence[frozenset[tuple[str, int, str]]],
) -> bool:
    for protected in protected_member_sets:
        if protected == candidate_members or not protected.intersection(candidate_members):
            continue
        # A protected superset may be the eventual identity of a later greedy
        # extension. Let the candidate grow until it reaches that exact set.
        if candidate_members.issubset(protected):
            continue
        return True
    return False


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
        slice_end = str(row.get("end_time") or slice_start)
        if not report_date or activity_id <= 0 or not slice_start:
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
    boundary_index: BoundaryIndex,
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
    if _crosses_explicit_boundary(previous, current, boundary_index):
        return False
    if _has_unrecorded_gap(previous, current, gap_threshold_seconds):
        return False
    return str(previous.get("report_project_key") or "") == str(
        current.get("report_project_key") or ""
    )


def _crosses_explicit_boundary(
    previous: Mapping,
    current: Mapping,
    boundary_index: BoundaryIndex,
) -> bool:
    start = str(previous.get("end_time") or previous.get("start_time") or "")
    end = str(current.get("start_time") or "")
    return boundary_index.crosses(start, end)


def _has_unrecorded_gap(
    previous: Mapping,
    current: Mapping,
    threshold_seconds: int,
) -> bool:
    previous_end = _parse_time(previous.get("end_time"))
    current_start = _parse_time(current.get("start_time"))
    if previous_end is None or current_start is None:
        return False
    gap = int((current_start - previous_end).total_seconds())
    return gap > max(0, int(threshold_seconds))


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), TIME_FORMAT)
    except ValueError:
        return None


__all__ = [
    "SHORT_PROJECT_RETURN_MERGE_SECONDS",
    "build_report_sessions",
    "merge_short_project_returns",
]
