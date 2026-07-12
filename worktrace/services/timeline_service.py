from __future__ import annotations

from bisect import bisect_left
from datetime import date as date_type, datetime, time as datetime_time, timedelta

from ..constants import (
    DEFAULT_CONTEXT_CARRY_MINUTES,
    DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    STATUS_NORMAL,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from ..db import dict_rows, get_connection
from ..formatters import format_status_label
from ..resources.title_parsing import extract_anchor_file_name
from . import clipboard_service, report_session_projection_service, session_boundary_service
from .activity_continuity_service import (
    has_hard_boundary_between,
    is_hard_boundary_status,
    is_report_short_context_duration,
)
from .context_service import ReportContextProjection
from .project_attribution_policy import official_project_fields, report_project_fields
from .report_projection_identity import member_set_hash
from .report_status_policy import SESSION_CONTRIBUTION, decide_report_status
from .resource_service import attach_resource
from .settings_service import get_int_setting

def get_project_sessions_by_date(date: str) -> list[dict]:
    return get_project_sessions_by_range(date, date)


def get_project_sessions_by_range(
    start_date: str,
    end_date: str,
) -> list[dict]:
    return report_session_projection_service.get_report_sessions_by_range(
        start_date,
        end_date,
    )


def _build_sessions_from_rows(rows: list[dict], uncategorized_id: int, boundary_times: list[str] | None = None) -> list[dict]:
    sessions: list[dict] = []
    current: list[dict] = []
    for row in rows:
        if not _is_project_session_row(row):
            if current:
                sessions.append(_build_session(current, uncategorized_id))
                current = []
            continue
        if not current:
            current = [row]
            continue
        if _can_merge(current[-1], row, boundary_times):
            current.append(row)
        else:
            sessions.append(_build_session(current, uncategorized_id))
            current = [row]
    if current:
        sessions.append(_build_session(current, uncategorized_id))
    return sessions


def _is_project_session_row(row: dict) -> bool:
    decision = decide_report_status(
        str(row.get("status") or ""),
        has_project_attribution=bool(row.get("is_report_project")),
    )
    return decision.decision == SESSION_CONTRIBUTION


def get_report_activity_rows(
    start_date: str,
    end_date: str,
    include_hidden: bool = False,
    conn=None,
) -> list[dict]:
    uncategorized_id = _uncategorized_project_id(conn)
    rows = _load_activity_rows_for_report_range(start_date, end_date, include_hidden, conn=conn)
    boundary_times = _boundary_times_for_rows(rows, conn=conn)
    rows = _with_display_projects(rows, uncategorized_id)
    activity_ids = [int(row.get("id") or 0) for row in rows if int(row.get("id") or 0)]
    if conn is None:
        with get_connection() as read_conn:
            clipboard_times = clipboard_service.clipboard_times_for_activity_ids(read_conn, activity_ids)
            carry_minutes = max(0, get_int_setting("context_carry_minutes", DEFAULT_CONTEXT_CARRY_MINUTES, conn=read_conn))
    else:
        clipboard_times = clipboard_service.clipboard_times_for_activity_ids(conn, activity_ids)
        carry_minutes = max(0, get_int_setting("context_carry_minutes", DEFAULT_CONTEXT_CARRY_MINUTES, conn=conn))
    rows = list(
        ReportContextProjection.build(
            rows,
            carry_minutes=carry_minutes,
            boundary_times=boundary_times,
            clipboard_times=clipboard_times,
        ).rows
    )
    return [
        row
        for row in _with_report_dates(rows)
        if start_date <= str(row.get("report_date") or "") <= end_date
    ]


def _uncategorized_project_id(conn=None) -> int:
    if conn is not None:
        row = conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()
        if not row:
            raise ValueError("report_context_not_ready")
        return int(row["id"])
    with get_connection() as read_conn:
        row = read_conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()
        if not row:
            raise ValueError("report_context_not_ready")
        return int(row["id"])


def get_default_report_date(today: date_type | None = None) -> str:
    return (today or date_type.today()).isoformat()


def _load_activity_rows_for_report_range(start_date: str, end_date: str, include_hidden: bool, *, conn=None) -> list[dict]:
    load_start_day = date_type.fromisoformat(start_date) - timedelta(days=1)
    load_start = f"{load_start_day.isoformat()} 00:00:00"
    # Project report dates can carry into the day after the requested range.
    load_end_day = date_type.fromisoformat(end_date) + timedelta(days=2)
    load_end = f"{load_end_day.isoformat()} 00:00:00"
    if conn is None:
        with get_connection() as read_conn:
            rows = read_conn.execute(
                """
                SELECT
                    a.*, apa.suggested_project_name, apa.source AS assignment_source,
                    apa.is_manual AS assignment_is_manual, apa.project_id AS effective_project_id,
                    p.name AS effective_project_name, p.description AS effective_project_description,
                    COALESCE(p.is_archived, 0) AS effective_project_is_archived,
                    COALESCE(p.is_deleted, 0) AS effective_project_is_deleted
                FROM activity_log a LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
                LEFT JOIN project p ON p.id = apa.project_id
                WHERE a.is_deleted = 0 AND (a.start_time >= ? OR a.end_time IS NULL OR a.end_time >= ?)
                  AND (a.end_time IS NULL OR a.start_time <= ?) AND (? = 1 OR a.is_hidden = 0)
                ORDER BY a.start_time ASC, a.id ASC
                """, (load_start, load_start, load_end, int(include_hidden))
            ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT
                a.*,
                apa.suggested_project_name,
                apa.source AS assignment_source,
                apa.is_manual AS assignment_is_manual,
                apa.project_id AS effective_project_id,
                p.name AS effective_project_name,
                p.description AS effective_project_description,
                COALESCE(p.is_archived, 0) AS effective_project_is_archived,
                COALESCE(p.is_deleted, 0) AS effective_project_is_deleted
            FROM activity_log a
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            LEFT JOIN project p ON p.id = apa.project_id
            WHERE a.is_deleted = 0
              AND (a.start_time >= ? OR a.end_time IS NULL OR a.end_time >= ?)
              AND (a.end_time IS NULL OR a.start_time <= ?)
              AND (? = 1 OR a.is_hidden = 0)
            ORDER BY a.start_time ASC, a.id ASC
            """,
            (load_start, load_start, load_end, int(include_hidden)),
        ).fetchall()
    return [attach_resource(row, conn=conn) for row in dict_rows(rows)]


def _can_merge(previous: dict, current: dict, boundary_times: list[str] | None = None) -> bool:
    if not (_can_participate_in_report_session(previous) and _can_participate_in_report_session(current)):
        return False
    if str(previous.get("report_date") or "") != str(current.get("report_date") or ""):
        return False
    if _has_session_boundary_between(previous, current, boundary_times):
        return False
    if _has_unrecorded_gap_between(previous, current):
        return False
    return str(previous.get("report_project_key") or "") == str(current.get("report_project_key") or "")


def _build_session(rows: list[dict], uncategorized_id: int) -> dict:
    first = rows[0]
    last = rows[-1]
    project_id = int(first.get("report_project_id") or uncategorized_id)
    project_name = first.get("report_project_name") or UNCATEGORIZED_PROJECT
    project_description = first.get("report_project_description") or ""
    project_is_deleted = bool(first.get("report_project_is_deleted"))
    project_is_archived = bool(first.get("report_project_is_archived"))
    is_report_project = bool(first.get("is_report_project"))
    is_report_classified = bool(first.get("is_report_classified"))
    is_report_uncategorized = bool(first.get("is_report_uncategorized"))
    is_official = bool(first.get("is_official_project"))
    duration = sum(_display_duration(row) for row in rows)
    closed_duration_seconds = sum(
        _display_duration(row) for row in rows if not bool(row.get("is_in_progress"))
    )
    activity_ids = [int(row["id"]) for row in rows]
    member_slices = _member_slices_for_rows(rows)
    status_summary = _status_summary(rows)
    # A session is in-progress if its last row is still open. The flag is
    # set by _split_calendar_report_rows from the original (pre-projection)
    # end_time so it reflects DB state, not the projected display end_time.
    is_in_progress = bool(last.get("is_in_progress"))
    open_activity_id = int(last.get("id") or 0) if is_in_progress else 0
    return {
        "row_kind": "project_session",
        "project_id": project_id,
        "project_name": project_name,
        "project_description": project_description,
        "project_is_deleted": project_is_deleted,
        "project_is_archived": project_is_archived,
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
        "status": first.get("status") if len({row.get("status") for row in rows}) == 1 else "mixed",
        "status_code": STATUS_NORMAL,
        "display_status": status_summary,
        "status_summary": status_summary,
        "contributes_to_totals": True,
        "live_delta_eligible": False,
        "editable": not is_in_progress,
        "exportable": not is_in_progress,
        "is_uncategorized": not is_report_project,
        "is_classified": is_report_project,
        "is_report_project": is_report_project,
        "is_report_classified": is_report_classified,
        "is_report_uncategorized": is_report_uncategorized,
        "is_official_project": is_official,
        "report_attribution_kind": first.get("report_attribution_kind") or "none",
        "is_suggested_project": False,
        "is_in_progress": is_in_progress,
    }


def _with_display_projects(rows: list[dict], uncategorized_id: int) -> list[dict]:
    for row in rows:
        _attach_display_project(row, uncategorized_id)
    return rows


def _with_reporting_projects(rows: list[dict], boundary_times: list[str] | None = None, *, conn=None) -> list[dict]:
    for row in rows:
        _attach_original_report_project(row)
    carry_minutes = max(0, get_int_setting("context_carry_minutes", DEFAULT_CONTEXT_CARRY_MINUTES, conn=conn))
    if carry_minutes <= 0:
        return rows
    for anchor_index, anchor in enumerate(rows):
        if _is_midnight_report_anchor(anchor):
            merge = _find_midnight_context_merge(rows, anchor_index, carry_minutes, boundary_times)
            if merge is not None:
                for interrupt_index in merge:
                    _attach_merged_report_project(rows[interrupt_index], anchor)
            continue
        if not _is_project_anchor(anchor):
            continue
        merge = _find_short_context_merge(rows, anchor_index, carry_minutes, boundary_times)
        if merge is None:
            continue
        for interrupt_index in merge:
            _attach_merged_report_project(rows[interrupt_index], anchor)
    return rows


def _with_report_dates(rows: list[dict]) -> list[dict]:
    report_rows: list[dict] = []
    for row in rows:
        report_rows.extend(_split_calendar_report_rows(row))
    return report_rows


def _split_calendar_report_rows(row: dict) -> list[dict]:
    start_dt = _parse_row_time(row.get("start_time"))
    if start_dt is None:
        return []
    duration = _display_duration(row)
    # Detect in-progress activities (original end_time is NULL) BEFORE the
    # projection overwrites end_time with a live value. The flag is preserved
    # on every split row so downstream consumers can distinguish open from
    # closed activities even though the projected end_time is non-null.
    raw_end_dt = _parse_row_time(row.get("end_time"))
    is_in_progress = raw_end_dt is None
    if duration <= 0:
        item = dict(row)
        item["report_date"] = start_dt.date().isoformat()
        item["report_duration_seconds"] = 0
        item["report_slice"] = False
        item["is_in_progress"] = is_in_progress
        return [item]

    end_dt = raw_end_dt
    if end_dt is None or end_dt < start_dt:
        end_dt = start_dt + timedelta(seconds=duration)

    rows: list[dict] = []
    current_start = start_dt
    while current_start < end_dt:
        next_midnight = datetime.combine(current_start.date() + timedelta(days=1), datetime_time.min)
        current_end = min(end_dt, next_midnight)
        seconds = max(0, int((current_end - current_start).total_seconds()))
        if seconds <= 0:
            break
        item = dict(row)
        item["start_time"] = current_start.strftime(TIME_FORMAT)
        item["end_time"] = current_end.strftime(TIME_FORMAT)
        item["duration_seconds"] = seconds
        item["report_date"] = current_start.date().isoformat()
        item["report_duration_seconds"] = seconds
        item["report_slice"] = True
        item["is_in_progress"] = is_in_progress
        rows.append(item)
        current_start = current_end
    return rows


def _attach_original_report_project(row: dict) -> None:
    """Keep report/history attribution separate from official display fields."""
    row["report_is_suggested_project"] = False
    row["report_context_merged"] = False


def _attach_merged_report_project(row: dict, anchor: dict) -> None:
    """Merge a short-interrupt row onto an anchor's official report project.

    Only the anchor's OFFICIAL report project is merged — a non-official
    anchor (candidate / derived / uncategorized) never propagates a
    project name onto interrupt rows.
    """
    if not anchor.get("is_report_project"):
        # Non-report anchor: do not merge a project name. Keep the row's own
        # report project.
        return
    row["report_project_id"] = anchor.get("report_project_id")
    row["report_project_name"] = anchor.get("report_project_name") or UNCATEGORIZED_PROJECT
    row["report_project_description"] = anchor.get("report_project_description") or ""
    row["report_project_key"] = anchor.get("report_project_key") or ""
    row["report_project_is_deleted"] = bool(anchor.get("report_project_is_deleted"))
    row["report_project_is_archived"] = bool(anchor.get("report_project_is_archived"))
    row["report_is_suggested_project"] = False
    row["report_context_merged"] = True
    row["report_attribution_kind"] = "report_context_short_gap"
    row["is_report_project"] = True
    row["is_report_classified"] = True
    row["is_report_uncategorized"] = False


def _find_short_context_merge(
    rows: list[dict],
    anchor_index: int,
    carry_minutes: int,
    boundary_times: list[str] | None = None,
) -> list[int] | None:
    anchor = rows[anchor_index]
    anchor_key = str(anchor.get("report_project_key") or "")
    interrupt_indices: list[int] = []
    after_interrupt_block = False
    for pos in range(anchor_index + 1, len(rows)):
        row = rows[pos]
        if _has_session_boundary_between(rows[pos - 1], row, boundary_times):
            return None
        if is_hard_boundary_status(str(row.get("status") or "")):
            return None
        if _is_project_anchor(row) and str(row.get("report_project_key") or "") == anchor_key:
            if (
                interrupt_indices
                and is_report_short_context_duration(_seconds_for_rows(rows, interrupt_indices))
                and _minutes_between(_anchor_context_time(anchor), row["start_time"]) <= carry_minutes
            ):
                return interrupt_indices
            return None
        if _is_same_report_project_normal(row, anchor_key):
            if interrupt_indices:
                after_interrupt_block = True
            continue
        if _is_short_merge_interrupt(row, anchor_key):
            if after_interrupt_block:
                return None
            interrupt_indices.append(pos)
            continue
        return None
    if (
        interrupt_indices
        and str(anchor.get("assignment_source") or "") == "midnight_anchor"
        and is_report_short_context_duration(_seconds_for_rows(rows, interrupt_indices))
        and _minutes_between(_anchor_context_time(anchor), rows[interrupt_indices[-1]]["start_time"]) <= carry_minutes
    ):
        return interrupt_indices
    return None


def _is_project_anchor(row: dict) -> bool:
    """A row that can act as a session anchor for timeline / report merge.

    Only official direct project rows anchor report-level short-interrupt
    merges; context-derived rows must not chain.
    """
    if str(row.get("status") or "") != STATUS_NORMAL:
        return False
    return bool(row.get("is_official_project"))


def _is_midnight_report_anchor(row: dict) -> bool:
    if str(row.get("status") or "") != STATUS_NORMAL:
        return False
    return str(row.get("assignment_source") or "") == "midnight_anchor" and bool(row.get("is_report_project"))


def _find_midnight_context_merge(
    rows: list[dict],
    anchor_index: int,
    carry_minutes: int,
    boundary_times: list[str] | None = None,
) -> list[int] | None:
    anchor = rows[anchor_index]
    interrupt_indices: list[int] = []
    for pos in range(anchor_index + 1, len(rows)):
        row = rows[pos]
        if _has_session_boundary_between(rows[pos - 1], row, boundary_times):
            return None
        if is_hard_boundary_status(str(row.get("status") or "")):
            return None
        if _is_project_anchor(row) or _is_midnight_report_anchor(row):
            break
        if _is_short_merge_interrupt(row, str(anchor.get("report_project_key") or "")):
            interrupt_indices.append(pos)
            continue
        break
    if (
        interrupt_indices
        and is_report_short_context_duration(_seconds_for_rows(rows, interrupt_indices))
        and _minutes_between(_anchor_context_time(anchor), rows[interrupt_indices[-1]]["start_time"]) <= carry_minutes
    ):
        return interrupt_indices
    return None


def _is_same_report_project_normal(row: dict, anchor_key: str) -> bool:
    return str(row.get("status") or "") == STATUS_NORMAL and str(row.get("report_project_key") or "") == anchor_key


def _is_short_merge_interrupt(row: dict, anchor_key: str) -> bool:
    if _is_candidate_project_row(row):
        return False
    return (
        str(row.get("status") or "") == STATUS_NORMAL
        and not bool(row.get("is_report_project"))
        and str(row.get("report_project_key") or "") != anchor_key
    )


def _is_candidate_project_row(row: dict) -> bool:
    return (
        str(row.get("assignment_source") or "").strip() == "suggested_project_name"
        or str(row.get("project_attribution_kind") or "").strip() == "candidate"
    )


def _seconds_for_rows(rows: list[dict], indexes: list[int]) -> int:
    return sum(_display_duration(rows[index]) for index in indexes)


def _can_participate_in_report_session(row: dict) -> bool:
    return _is_project_session_row(row)


def _anchor_context_time(row: dict) -> str:
    return row.get("end_time") or row.get("start_time")


def _minutes_between(start: str, end: str) -> float:
    start_dt = datetime.strptime(start, TIME_FORMAT)
    end_dt = datetime.strptime(end, TIME_FORMAT)
    return max(0.0, (end_dt - start_dt).total_seconds() / 60)


def _has_session_boundary_between(previous: dict, current: dict, boundary_times: list[str] | None = None) -> bool:
    boundary_start = previous.get("end_time") or previous.get("start_time") or ""
    boundary_end = current.get("start_time") or ""
    if not boundary_start or not boundary_end:
        return False
    if boundary_times is not None:
        return _has_boundary_time_between(boundary_times, str(boundary_start), str(boundary_end))
    return has_hard_boundary_between(str(boundary_start), str(boundary_end))


def _boundary_times_for_rows(rows: list[dict], *, conn=None) -> list[str]:
    ranges = [
        str(value)
        for row in rows
        for value in (row.get("start_time"), row.get("end_time"))
        if value
    ]
    if not ranges:
        return []
    boundaries = session_boundary_service.list_boundaries(min(ranges), max(ranges), conn=conn)
    return [str(row["occurred_at"]) for row in boundaries if row.get("occurred_at")]


def _has_boundary_time_between(boundary_times: list[str], start_time: str, end_time: str) -> bool:
    if not start_time or not end_time or start_time > end_time:
        return False
    index = bisect_left(boundary_times, start_time)
    return index < len(boundary_times) and boundary_times[index] <= end_time


def _has_unrecorded_gap_between(previous: dict, current: dict) -> bool:
    previous_end = _parse_row_time(previous.get("end_time"))
    current_start = _parse_row_time(current.get("start_time"))
    if previous_end is None or current_start is None:
        return False
    gap_seconds = int((current_start - previous_end).total_seconds())
    if gap_seconds <= 0:
        return False
    threshold = max(
        60,
        get_int_setting("context_carry_minutes", DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS // 60) * 60,
    )
    return gap_seconds > threshold


def _attach_display_project(row: dict, uncategorized_id: int) -> None:
    """Attach display-safe project fields to a row using the attribution policy.

    Only official sources (``manual`` / ``keyword_rule`` / ``folder_rule``)
    surface the real project name as ``display_project_name``. Candidate
    (``suggested_project_name``), derived (``anchor_context`` /
    ``same_project_context`` / ``clipboard_transition_context`` /
    ``midnight_anchor``) and uncategorized sources all resolve to
    ``UNCATEGORIZED_PROJECT`` in the formal display project column.

    Internal effective project id/name are preserved on the row for
    context-inference and anchor algorithms, but never exposed as the
    official project.
    """
    official = official_project_fields(row, uncategorized_id)
    report = report_project_fields(row, uncategorized_id)
    row.update(official)
    row.update(report)
    row["is_suggested_project"] = False


def _session_sort_key(session: dict) -> tuple[str, int]:
    activity_ids = [int(value) for value in session.get("activity_ids") or []]
    start_id = min(activity_ids) if activity_ids else 0
    return (str(session.get("sort_time") or session.get("start_time") or ""), start_id)


def _status_summary(rows: list[dict]) -> str:
    items = []
    for row in rows:
        status = row.get("status")
        if status == STATUS_NORMAL:
            label = _activity_summary_label(row)
        else:
            label = format_status_label(status)
        if label and label not in items:
            items.append(label)
        if len(items) >= 3:
            break
    return "、".join(items) if items else "正常活动"


def _activity_summary_label(row: dict) -> str:
    activity_name = str(row.get("activity_display_name") or "").strip()
    if row.get("resource_is_anchor") and activity_name:
        return activity_name
    title_file = extract_anchor_file_name(row.get("window_title"))
    if title_file:
        return title_file
    return str(row.get("app_name") or row.get("process_name") or "").strip()


def _display_duration(row: dict) -> int:
    """Return the DB / report row's own duration.

    Timeline / Statistics / Export are DB-only / report-only layers.
    Live projection is the sole responsibility of
    ``activity_display_model_service`` + ``view_model_service``.
    This function MUST NOT read settings or the live snapshot, and MUST
    NOT call any live-display helper.
    """
    if row.get("duration_seconds") is not None:
        return int(row.get("duration_seconds") or 0)
    return 0


def _member_slices_for_rows(rows: list[dict]) -> list[dict]:
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


def _parse_row_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), TIME_FORMAT)
    except ValueError:
        return None
