from __future__ import annotations

from bisect import bisect_left
from datetime import date as date_type, datetime, time as datetime_time, timedelta

from ..constants import (
    DEFAULT_CONTEXT_CARRY_MINUTES,
    DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    REPORT_CONTEXT_SHORT_MERGE_SECONDS,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from ..db import dict_rows, get_connection
from ..path_utils import split_file_path
from ..resources.title_parsing import extract_anchor_file_name
from . import folder_rule_service, session_boundary_service, session_note_service
from .activity_service import update_activities_project
from .anchor_predicates import is_file_context_anchor
from .context_service import recompute_context_assignments_for_date
from .project_service import get_or_create_uncategorized_project
from .resource_service import attach_resource
from .settings_service import get_int_setting

def get_project_sessions_by_date(date: str, include_hidden: bool = True, ensure_context: bool = True) -> list[dict]:
    return get_project_sessions_by_range(date, date, include_hidden=include_hidden, ensure_context=ensure_context)


def get_project_sessions_by_range(
    start_date: str,
    end_date: str,
    include_hidden: bool = True,
    ensure_context: bool = True,
) -> list[dict]:
    uncategorized_id = get_or_create_uncategorized_project()
    rows = get_report_activity_rows(start_date, end_date, include_hidden=include_hidden, ensure_context=ensure_context)
    sessions = _build_sessions_from_rows(rows, uncategorized_id, _boundary_times_for_rows(rows))
    session_note_service.attach_session_user_fields(sessions)
    return sorted(sessions, key=_session_sort_key, reverse=True)


def _build_sessions_from_rows(rows: list[dict], uncategorized_id: int, boundary_times: list[str] | None = None) -> list[dict]:
    sessions: list[dict] = []
    current: list[dict] = []
    for row in rows:
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


def get_report_activity_rows(
    start_date: str,
    end_date: str,
    include_hidden: bool = True,
    ensure_context: bool = True,
) -> list[dict]:
    if ensure_context:
        _ensure_context_for_report_range(start_date, end_date)
    uncategorized_id = get_or_create_uncategorized_project()
    rows = _load_activity_rows_for_report_range(start_date, end_date, include_hidden)
    boundary_times = _boundary_times_for_rows(rows)
    rows = _with_reporting_projects(_with_display_projects(rows, uncategorized_id), boundary_times)
    return [
        row
        for row in _with_report_dates(rows)
        if start_date <= str(row.get("report_date") or "") <= end_date
    ]


def get_default_report_date(today: date_type | None = None) -> str:
    return (today or date_type.today()).isoformat()


def get_session_activity_details(
    activity_ids: list[int],
    report_date: str | None = None,
    ensure_context: bool = True,
) -> list[dict]:
    rows = _load_session_rows(activity_ids, newest_first=True, report_date=report_date, ensure_context=ensure_context)
    details = []
    for row in rows:
        item = dict(row)
        item["duration_seconds"] = _display_duration(row)
        item["project_id"] = row.get("effective_project_id")
        item["project_name"] = row.get("display_project_name") or UNCATEGORIZED_PROJECT
        item["project_description"] = row.get("display_project_description") or ""
        item["official_project_name"] = row.get("effective_project_name") or UNCATEGORIZED_PROJECT
        item["activity_display_name"] = row.get("activity_display_name") or row.get("app_name") or "未知活动"
        # Ensure is_in_progress is set for both paths: the report path
        # already sets it from the pre-projection end_time, while the direct
        # path computes it from the raw end_time (NULL for open activities).
        if "is_in_progress" not in item:
            item["is_in_progress"] = _parse_row_time(row.get("end_time")) is None
        details.append(item)
    return details


def get_session_anchor_folders(activity_ids: list[int]) -> list[str]:
    """Return the local anchor folders for the given session activities.

    Reuses the shared file-context-anchor predicate so that browser tabs
    / email / code files are not treated as session anchor folders, while
    file-context anchors (docx / pdf / xlsx / ...) still surface their
    parent directory. The row's project state is intentionally NOT
    required to be concrete: this function only returns the explainable
    anchor folder for the session, regardless of whether the activity has
    been assigned to a project.
    """
    if not activity_ids:
        return []
    placeholders = ",".join("?" for _ in activity_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM activity_log a
            WHERE a.id IN ({placeholders})
              AND a.is_deleted = 0
            ORDER BY a.start_time, a.id
            """,
            activity_ids,
        ).fetchall()
    folders = []
    for row in [attach_resource(item) for item in dict_rows(rows)]:
        if not is_file_context_anchor(row):
            continue
        path_hint = (row.get("resource_path_hint") or "").strip()
        folder = ""
        if path_hint:
            full_path, parent_dir, _ = split_file_path(path_hint)
            folder = parent_dir
        if folder and folder not in folders:
            folders.append(folder)
    return folders


def update_session_project(session_activity_ids: list[int], project_id: int) -> None:
    update_activities_project(session_activity_ids, project_id, manual=True)


def update_session_note(report_date: str, first_activity_id: int, note: str) -> None:
    session_note_service.set_session_note(report_date, first_activity_id, note)


def update_session_note_and_duration(
    report_date: str,
    first_activity_id: int,
    note: str,
    adjusted_duration_seconds: int | None,
) -> None:
    session_note_service.set_session_user_fields(
        report_date, first_activity_id, note, adjusted_duration_seconds
    )


def update_activity_group_project(
    activity_ids: list[int],
    project_id: int,
) -> None:
    ids = [int(activity_id) for activity_id in activity_ids]
    if not ids:
        return
    update_activities_project(ids, project_id, manual=True)


def preview_session_project_update(session_activity_ids: list[int], project_id: int) -> dict:
    if not session_activity_ids:
        return {
            "folder_rule_conflicts": [],
            "unassigned_anchor_files": [],
        }
    if int(project_id) == int(get_or_create_uncategorized_project()):
        return {
            "folder_rule_conflicts": [],
            "unassigned_anchor_files": [],
        }
    placeholders = ",".join("?" for _ in session_activity_ids)
    with get_connection() as conn:
        rows = [
            attach_resource(row)
            for row in dict_rows(
                conn.execute(
                    f"""
                    SELECT a.*
                    FROM activity_log a
                    WHERE a.id IN ({placeholders})
                      AND a.is_deleted = 0
                    ORDER BY a.start_time, a.id
                    """,
                    session_activity_ids,
                ).fetchall()
            )
        ]

    folder_rule_conflicts = []
    unassigned_anchor_files = []
    for row in rows:
        if not row.get("resource_is_anchor"):
            continue
        target_path = row.get("resource_path_hint") or ""
        if target_path:
            _, parent_dir, _ = split_file_path(target_path)
            target_path = target_path or parent_dir
        rule = folder_rule_service.find_matching_folder_rule(target_path)
        if rule:
            if int(rule["project_id"]) != int(project_id):
                folder_rule_conflicts.append(_anchor_preview_item(row, rule.get("project_name")))
            continue
        unassigned_anchor_files.append(_anchor_preview_item(row, None))
    return {
        "folder_rule_conflicts": folder_rule_conflicts,
        "unassigned_anchor_files": unassigned_anchor_files,
    }


def _load_activity_rows_for_report_range(start_date: str, end_date: str, include_hidden: bool) -> list[dict]:
    load_start_day = date_type.fromisoformat(start_date) - timedelta(days=1)
    load_start = f"{load_start_day.isoformat()} 00:00:00"
    # Project report dates can carry into the day after the requested range.
    load_end_day = date_type.fromisoformat(end_date) + timedelta(days=2)
    load_end = f"{load_end_day.isoformat()} 00:00:00"
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.*,
                apa.suggested_project_name,
                apa.source AS assignment_source,
                apa.is_manual AS assignment_is_manual,
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                p.name AS effective_project_name,
                p.description AS effective_project_description
            FROM activity_log a
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            LEFT JOIN project p ON p.id = COALESCE(apa.project_id, a.project_id)
            WHERE a.is_deleted = 0
              AND (a.start_time >= ? OR a.end_time IS NULL OR a.end_time >= ?)
              AND (a.end_time IS NULL OR a.start_time <= ?)
              AND (? = 1 OR a.is_hidden = 0)
            ORDER BY a.start_time ASC, a.id ASC
            """,
            (load_start, load_start, load_end, int(include_hidden)),
        ).fetchall()
    return [attach_resource(row) for row in dict_rows(rows)]


def _load_session_rows(
    activity_ids: list[int],
    newest_first: bool = False,
    report_date: str | None = None,
    ensure_context: bool = True,
) -> list[dict]:
    if report_date:
        activity_set = {int(activity_id) for activity_id in activity_ids}
        rows = [
            row
            for row in get_report_activity_rows(
                report_date,
                report_date,
                include_hidden=True,
                ensure_context=ensure_context,
            )
            if int(row["id"]) in activity_set
        ]
        return sorted(rows, key=lambda row: (row.get("start_time") or "", int(row["id"])), reverse=newest_first)
    placeholders = ",".join("?" for _ in activity_ids)
    order_direction = "DESC" if newest_first else "ASC"
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                a.*,
                apa.suggested_project_name,
                apa.source AS assignment_source,
                apa.is_manual AS assignment_is_manual,
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                p.name AS effective_project_name,
                p.description AS effective_project_description
            FROM activity_log a
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            LEFT JOIN project p ON p.id = COALESCE(apa.project_id, a.project_id)
            WHERE a.id IN ({placeholders})
            ORDER BY a.start_time {order_direction}, a.id {order_direction}
            """,
            activity_ids,
        ).fetchall()
    return _with_display_projects(
        [attach_resource(row) for row in dict_rows(rows)],
        get_or_create_uncategorized_project(),
    )


def _can_merge(previous: dict, current: dict, boundary_times: list[str] | None = None) -> bool:
    if not (_can_participate_in_report_session(previous) and _can_participate_in_report_session(current)):
        return False
    if str(previous.get("report_date") or "") != str(current.get("report_date") or ""):
        return False
    if _has_session_boundary_between(previous, current, boundary_times):
        return False
    return str(previous.get("report_project_key") or "") == str(current.get("report_project_key") or "")


def _build_session(rows: list[dict], uncategorized_id: int) -> dict:
    first = rows[0]
    last = rows[-1]
    project_id = int(first.get("report_project_id") or first.get("effective_project_id") or uncategorized_id)
    project_name = first.get("report_project_name") or first.get("display_project_name") or UNCATEGORIZED_PROJECT
    project_description = first.get("report_project_description") or first.get("display_project_description") or ""
    duration = sum(_display_duration(row) for row in rows)
    activity_ids = [int(row["id"]) for row in rows]
    status_summary = _status_summary(rows)
    session_id = f"{first['id']}-{last['id']}"
    # A session is in-progress if its last row is still open. The flag is
    # set by _split_calendar_report_rows from the original (pre-projection)
    # end_time so it reflects DB state, not the projected display end_time.
    is_in_progress = bool(last.get("is_in_progress"))
    return {
        "session_id": session_id,
        "project_id": project_id,
        "project_name": project_name,
        "project_description": project_description,
        "start_time": first.get("start_time"),
        "end_time": last.get("end_time"),
        "report_date": first.get("report_date"),
        "duration_seconds": duration,
        "activity_ids": activity_ids,
        "first_activity_id": int(activity_ids[0]) if activity_ids else None,
        "session_note": "",
        "sort_time": last.get("start_time") or first.get("start_time"),
        "event_count": len(rows),
        "status": first.get("status") if len({row.get("status") for row in rows}) == 1 else "mixed",
        "status_summary": status_summary,
        "is_uncategorized": project_id == int(uncategorized_id),
        "is_suggested_project": bool(first.get("report_is_suggested_project", first.get("is_suggested_project"))),
        "is_in_progress": is_in_progress,
    }


def _with_display_projects(rows: list[dict], uncategorized_id: int) -> list[dict]:
    for row in rows:
        _attach_display_project(row, uncategorized_id)
    return rows


def _with_reporting_projects(rows: list[dict], boundary_times: list[str] | None = None) -> list[dict]:
    for row in rows:
        _attach_original_report_project(row)
    carry_minutes = max(0, get_int_setting("context_carry_minutes", DEFAULT_CONTEXT_CARRY_MINUTES))
    if carry_minutes <= 0:
        return rows
    for anchor_index, anchor in enumerate(rows):
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
    row["report_project_id"] = row.get("effective_project_id")
    row["report_project_name"] = row.get("display_project_name") or UNCATEGORIZED_PROJECT
    row["report_project_description"] = row.get("display_project_description") or ""
    row["report_project_key"] = row.get("display_project_key") or ""
    row["report_is_suggested_project"] = bool(row.get("is_suggested_project"))
    row["report_context_merged"] = False


def _attach_merged_report_project(row: dict, anchor: dict) -> None:
    row["report_project_id"] = anchor.get("effective_project_id")
    row["report_project_name"] = anchor.get("display_project_name") or UNCATEGORIZED_PROJECT
    row["report_project_description"] = anchor.get("display_project_description") or ""
    row["report_project_key"] = anchor.get("display_project_key") or ""
    row["report_is_suggested_project"] = bool(anchor.get("is_suggested_project"))
    row["report_context_merged"] = True


def _find_short_context_merge(
    rows: list[dict],
    anchor_index: int,
    carry_minutes: int,
    boundary_times: list[str] | None = None,
) -> list[int] | None:
    anchor = rows[anchor_index]
    anchor_key = str(anchor.get("display_project_key") or "")
    interrupt_indices: list[int] = []
    after_interrupt_block = False
    for pos in range(anchor_index + 1, len(rows)):
        row = rows[pos]
        if _has_session_boundary_between(rows[pos - 1], row, boundary_times):
            return None
        if _is_project_anchor(row) and str(row.get("display_project_key") or "") == anchor_key:
            if (
                interrupt_indices
                and _seconds_for_rows(rows, interrupt_indices) < REPORT_CONTEXT_SHORT_MERGE_SECONDS
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
    return None


def _is_project_anchor(row: dict) -> bool:
    """A row that can act as a session anchor for timeline / report merge.

    Reuses the shared file-context-anchor predicate so the timeline layer
    does not duplicate the file-extension / browser / email rules. Project
    anchors additionally require the display project to be a concrete
    (non-uncategorized) project. The ``midnight_anchor`` source keeps its
    existing allow-when-concrete-project behavior.

    Direct assignment anchors are NOT promoted to project anchors here:
    they participate in context carry (``context_service``) but the
    timeline session concept only treats file-context anchors (and
    midnight anchors) as session boundaries.
    """
    if row.get("status") != STATUS_NORMAL:
        return False
    if row.get("assignment_source") == "midnight_anchor":
        return (row.get("display_project_name") or UNCATEGORIZED_PROJECT) != UNCATEGORIZED_PROJECT
    if not is_file_context_anchor(row):
        return False
    return (row.get("display_project_name") or UNCATEGORIZED_PROJECT) != UNCATEGORIZED_PROJECT


def _is_same_report_project_normal(row: dict, anchor_key: str) -> bool:
    return row.get("status") == STATUS_NORMAL and str(row.get("display_project_key") or "") == anchor_key


def _is_short_merge_interrupt(row: dict, anchor_key: str) -> bool:
    if row.get("status") == STATUS_IDLE:
        return True
    return row.get("status") == STATUS_NORMAL and str(row.get("display_project_key") or "") != anchor_key


def _seconds_for_rows(rows: list[dict], indexes: list[int]) -> int:
    return sum(_display_duration(rows[index]) for index in indexes)


def _can_participate_in_report_session(row: dict) -> bool:
    return row.get("status") == STATUS_NORMAL or bool(row.get("report_context_merged"))


def _anchor_context_time(row: dict) -> str:
    return row.get("end_time") or row.get("start_time")


def _minutes_between(start: str, end: str) -> float:
    start_dt = datetime.strptime(start, TIME_FORMAT)
    end_dt = datetime.strptime(end, TIME_FORMAT)
    return max(0.0, (end_dt - start_dt).total_seconds() / 60)


def _has_session_boundary_between(previous: dict, current: dict, boundary_times: list[str] | None = None) -> bool:
    if _has_unrecorded_gap_between(previous, current):
        return True
    boundary_start = previous.get("end_time") or previous.get("start_time") or ""
    boundary_end = current.get("start_time") or ""
    if not boundary_start or not boundary_end:
        return False
    if boundary_times is not None:
        return _has_boundary_time_between(boundary_times, str(boundary_start), str(boundary_end))
    return session_boundary_service.has_boundary_between(str(boundary_start), str(boundary_end))


def _boundary_times_for_rows(rows: list[dict]) -> list[str]:
    ranges = [
        str(value)
        for row in rows
        for value in (row.get("start_time"), row.get("end_time"))
        if value
    ]
    if not ranges:
        return []
    boundaries = session_boundary_service.list_boundaries(min(ranges), max(ranges))
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


def _ensure_context_for_report_range(start_date: str, end_date: str) -> None:
    current = date_type.fromisoformat(start_date) - timedelta(days=1)
    final = date_type.fromisoformat(end_date)
    while current <= final:
        recompute_context_assignments_for_date(current.isoformat())
        current += timedelta(days=1)


def _attach_display_project(row: dict, uncategorized_id: int) -> None:
    project_id = int(row.get("effective_project_id") or uncategorized_id)
    suggested = str(row.get("suggested_project_name") or "").strip()
    if project_id == int(uncategorized_id) and suggested:
        row["display_project_name"] = suggested
        row["display_project_description"] = ""
        row["display_project_key"] = f"suggested:{suggested.casefold()}"
        row["is_suggested_project"] = True
        return
    row["display_project_name"] = row.get("effective_project_name") or UNCATEGORIZED_PROJECT
    row["display_project_description"] = row.get("effective_project_description") or ""
    row["display_project_key"] = f"project:{project_id}"
    row["is_suggested_project"] = False


def _anchor_preview_item(row: dict, current_project_name: str | None) -> dict:
    path_hint = row.get("resource_path_hint") or ""
    parent_dir = ""
    if path_hint:
        _, parent_dir, _ = split_file_path(path_hint)
    return {
        "activity_id": int(row["id"]),
        "display_name": row.get("activity_display_name") or "未知文件",
        "full_path": path_hint,
        "parent_dir": parent_dir,
        "current_project_name": current_project_name or "",
    }


def _session_sort_key(session: dict) -> tuple[str, int]:
    first_id = str(session.get("session_id") or "0").split("-", 1)[0]
    try:
        start_id = int(first_id)
    except ValueError:
        start_id = 0
    return (str(session.get("sort_time") or session.get("start_time") or ""), start_id)


_STATUS_DISPLAY_NAMES = {
    STATUS_IDLE: "空闲",
    STATUS_PAUSED: "已暂停",
    STATUS_EXCLUDED: "已排除",
    STATUS_ERROR: "异常",
}


def _status_summary(rows: list[dict]) -> str:
    items = []
    for row in rows:
        status = row.get("status")
        if status == STATUS_NORMAL:
            label = _activity_summary_label(row)
        else:
            label = _STATUS_DISPLAY_NAMES.get(status, str(status or ""))
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
    live_duration = _live_duration_for_row(row)
    if live_duration is not None:
        stored = int(row.get("duration_seconds") or 0)
        return max(stored, live_duration)
    if row.get("duration_seconds") is not None:
        return int(row.get("duration_seconds") or 0)
    return 0


def _live_duration_for_row(row: dict) -> int | None:
    """Return the live seconds for a persisted open DB row.

    Routes through the unified live-display model
    (``live_display_service.persisted_open_live_seconds``) so the
    persisted-open live duration uses the same snapshot matching and
    elapsed-seconds computation as the rest of the live-display
    pipeline. Returns ``None`` when the row is closed or does not match
    the current snapshot's ``persisted_activity_id``.

    Historical-date suppression (Section 三): when the row's
    ``report_date`` is not today, the function MUST return ``None`` so
    the historical Timeline / Details total is NOT polluted by the
    current open row's live sample seconds. Only today's open row is
    eligible for the live-duration injection; the page-scoped live clock
    is fully suppressed by ``activity_display_model_service`` for past
    dates, and the row-level duration must follow the same rule.
    """
    if row.get("end_time") is not None:
        return None
    try:
        row_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        return None
    if row_id <= 0:
        return None
    # Historical-date suppression: a row whose report_date is not today
    # MUST NOT receive a live-duration injection. Fall back to deriving
    # report_date from ``start_time`` when absent (defensive).
    row_report_date = str(row.get("report_date") or "")
    if not row_report_date:
        start_dt = _parse_row_time(row.get("start_time"))
        if start_dt is not None:
            row_report_date = start_dt.date().isoformat()
    today_str = get_default_report_date()
    if row_report_date and row_report_date != today_str:
        return None
    snapshot = _read_current_activity_snapshot()
    if not snapshot:
        return None
    from .live_display_service import persisted_open_live_seconds

    live = persisted_open_live_seconds(snapshot, row)
    return live if live > 0 else None


def _read_current_activity_snapshot() -> dict | None:
    from .settings_service import get_setting

    raw = get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return None
    import json

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _parse_row_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), TIME_FORMAT)
    except ValueError:
        return None
