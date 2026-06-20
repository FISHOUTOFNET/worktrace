from __future__ import annotations

import json
from datetime import date as date_type, datetime, time as datetime_time, timedelta

from ..constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED, TIME_FORMAT, UNCATEGORIZED_PROJECT
from ..db import dict_rows, get_connection, now_str
from ..resource_patterns import extract_anchor_file_name
from . import folder_rule_service
from .activity_service import update_activities_project
from .context_service import recompute_context_assignments_for_date
from .project_service import get_or_create_uncategorized_project
from .settings_service import get_int_setting, get_setting

SHORT_CONTEXT_MERGE_SECONDS = 5 * 60


def get_project_sessions_by_date(date: str, include_hidden: bool = True, ensure_context: bool = True) -> list[dict]:
    uncategorized_id = get_or_create_uncategorized_project()
    rows = get_report_activity_rows(date, date, include_hidden=include_hidden, ensure_context=ensure_context)
    sessions: list[dict] = []
    current: list[dict] = []
    for row in rows:
        if not current:
            current = [row]
            continue
        if _can_merge(current[-1], row):
            current.append(row)
        else:
            sessions.append(_build_session(current, uncategorized_id))
            current = [row]
    if current:
        sessions.append(_build_session(current, uncategorized_id))
    return sorted(sessions, key=_session_sort_key, reverse=True)


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
    rows = _with_reporting_projects(_with_display_projects(rows, uncategorized_id))
    return [
        row
        for row in _with_report_dates(rows)
        if start_date <= str(row.get("report_date") or "") <= end_date
    ]


def get_default_report_date(today: date_type | None = None) -> str:
    target_today = today or date_type.today()
    snapshot = _read_current_activity_snapshot()
    if snapshot:
        report_date = _snapshot_report_date(snapshot, target_today)
        if report_date:
            return report_date
    return target_today.isoformat()


def get_session_resource_summary(
    activity_ids: list[int],
    report_date: str | None = None,
    ensure_context: bool = True,
) -> list[dict]:
    if not activity_ids:
        return []
    rows = _load_session_rows(activity_ids, report_date=report_date, ensure_context=ensure_context)
    groups: dict[int, dict] = {}
    for row in rows:
        resource_id = int(row["resource_id"] or 0)
        if not resource_id:
            continue
        group = groups.setdefault(
            resource_id,
            {
                "resource_id": resource_id,
                "resource_key": row.get("canonical_key") or "",
                "resource_role": row.get("resource_role") or "auxiliary",
                "resource_type": row.get("resource_type") or "unknown",
                "display_name": row.get("resource_display_name") or row.get("app_name") or "未知资源",
                "app_name": row.get("resource_app_name") or row.get("app_name") or "",
                "process_name": row.get("resource_process_name") or row.get("process_name") or "",
                "total_duration_seconds": 0,
                "activity_ids": [],
                "event_count": 0,
                "project_id": row.get("effective_project_id"),
                "project_name": row.get("display_project_name") or UNCATEGORIZED_PROJECT,
                "official_project_name": row.get("effective_project_name") or UNCATEGORIZED_PROJECT,
                "is_suggested_project": bool(row.get("is_suggested_project")),
                "can_remember_for_future": row.get("resource_role") == "anchor",
            },
        )
        group["total_duration_seconds"] += _display_duration(row)
        group["activity_ids"].append(int(row["id"]))
        group["event_count"] += 1
    return sorted(
        groups.values(),
        key=lambda item: (-int(item["total_duration_seconds"]), str(item["display_name"]).casefold()),
    )


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
        item["official_project_name"] = row.get("effective_project_name") or UNCATEGORIZED_PROJECT
        item["resource_display_name"] = row.get("resource_display_name") or row.get("app_name") or "未知资源"
        details.append(item)
    return details


def get_session_anchor_folders(activity_ids: list[int]) -> list[str]:
    if not activity_ids:
        return []
    placeholders = ",".join("?" for _ in activity_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT r.parent_dir, r.full_path
            FROM activity_log a
            JOIN resource r ON r.id = a.resource_id
            WHERE a.id IN ({placeholders})
              AND a.is_deleted = 0
              AND r.resource_role = 'anchor'
              AND r.resource_type = 'file'
            ORDER BY r.parent_dir COLLATE NOCASE, r.full_path COLLATE NOCASE
            """,
            activity_ids,
        ).fetchall()
    folders = []
    for row in rows:
        folder = (row["parent_dir"] or "").strip()
        if not folder and row["full_path"]:
            folder = str(row["full_path"]).rsplit("\\", 1)[0]
        if folder and folder not in folders:
            folders.append(folder)
    return folders


def update_session_project(session_activity_ids: list[int], project_id: int) -> None:
    update_activities_project(session_activity_ids, project_id, manual=True)


def preview_session_project_update(session_activity_ids: list[int], project_id: int) -> dict:
    if not session_activity_ids:
        return {
            "file_project_conflicts": [],
            "folder_rule_conflicts": [],
            "unassigned_anchor_files": [],
        }
    if int(project_id) == int(get_or_create_uncategorized_project()):
        return {
            "file_project_conflicts": [],
            "folder_rule_conflicts": [],
            "unassigned_anchor_files": [],
        }
    placeholders = ",".join("?" for _ in session_activity_ids)
    with get_connection() as conn:
        rows = dict_rows(
            conn.execute(
                f"""
                SELECT DISTINCT
                    r.id AS resource_id,
                    r.display_name,
                    r.full_path,
                    r.parent_dir,
                    r.default_project_id,
                    p.name AS default_project_name
                FROM activity_log a
                JOIN resource r ON r.id = a.resource_id
                LEFT JOIN project p ON p.id = r.default_project_id
                WHERE a.id IN ({placeholders})
                  AND a.is_deleted = 0
                  AND r.resource_role = 'anchor'
                  AND r.resource_type = 'file'
                ORDER BY r.display_name COLLATE NOCASE, r.id
                """,
                session_activity_ids,
            ).fetchall()
        )

    file_project_conflicts = []
    folder_rule_conflicts = []
    unassigned_anchor_files = []
    for row in rows:
        default_project_id = row.get("default_project_id")
        if default_project_id and int(default_project_id) != int(project_id):
            file_project_conflicts.append(_anchor_preview_item(row, row.get("default_project_name")))
            continue
        if default_project_id:
            continue
        target_path = row.get("full_path") or row.get("parent_dir") or ""
        rule = folder_rule_service.find_matching_folder_rule(target_path)
        if rule:
            if int(rule["project_id"]) != int(project_id):
                folder_rule_conflicts.append(_anchor_preview_item(row, rule.get("project_name")))
            continue
        unassigned_anchor_files.append(_anchor_preview_item(row, None))
    return {
        "file_project_conflicts": file_project_conflicts,
        "folder_rule_conflicts": folder_rule_conflicts,
        "unassigned_anchor_files": unassigned_anchor_files,
    }


def update_resource_project_for_session(
    session_activity_ids: list[int],
    resource_id: int,
    project_id: int,
    remember_for_future: bool = False,
) -> None:
    if not session_activity_ids:
        return
    placeholders = ",".join("?" for _ in session_activity_ids)
    with get_connection() as conn:
        resource = conn.execute("SELECT * FROM resource WHERE id = ?", (resource_id,)).fetchone()
        if not resource:
            raise ValueError(f"resource not found: {resource_id}")
        if remember_for_future and resource["resource_role"] != "anchor":
            raise ValueError("auxiliary resources cannot be remembered for future")
        rows = conn.execute(
            f"""
            SELECT id
            FROM activity_log
            WHERE id IN ({placeholders}) AND resource_id = ? AND is_deleted = 0
            ORDER BY start_time ASC, id ASC
            """,
            [*session_activity_ids, resource_id],
        ).fetchall()
        activity_ids = [int(row["id"]) for row in rows]
    update_activities_project(activity_ids, project_id, manual=True)
    if remember_for_future:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE resource
                SET default_project_id = ?, updated_at = ?
                WHERE id = ? AND resource_role = 'anchor'
                """,
                (project_id, now_str(), resource_id),
            )


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
                r.display_name AS resource_display_name,
                r.resource_role,
                r.resource_type,
                apa.suggested_project_name,
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                p.name AS effective_project_name
            FROM activity_log a
            LEFT JOIN resource r ON r.id = a.resource_id
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
    return dict_rows(rows)


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
                r.canonical_key,
                r.resource_role,
                r.resource_type,
                r.display_name AS resource_display_name,
                r.app_name AS resource_app_name,
                r.process_name AS resource_process_name,
                apa.suggested_project_name,
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                p.name AS effective_project_name
            FROM activity_log a
            LEFT JOIN resource r ON r.id = a.resource_id
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            LEFT JOIN project p ON p.id = COALESCE(apa.project_id, a.project_id)
            WHERE a.id IN ({placeholders})
            ORDER BY a.start_time {order_direction}, a.id {order_direction}
            """,
            activity_ids,
        ).fetchall()
    return _with_display_projects(dict_rows(rows), get_or_create_uncategorized_project())


def _can_merge(previous: dict, current: dict) -> bool:
    if not (_can_participate_in_report_session(previous) and _can_participate_in_report_session(current)):
        return False
    return str(previous.get("report_project_key") or "") == str(current.get("report_project_key") or "")


def _build_session(rows: list[dict], uncategorized_id: int) -> dict:
    first = rows[0]
    last = rows[-1]
    project_id = int(first.get("report_project_id") or first.get("effective_project_id") or uncategorized_id)
    project_name = first.get("report_project_name") or first.get("display_project_name") or UNCATEGORIZED_PROJECT
    duration = sum(_display_duration(row) for row in rows)
    activity_ids = [int(row["id"]) for row in rows]
    status_summary = _status_summary(rows)
    return {
        "session_id": f"{first['id']}-{last['id']}",
        "project_id": project_id,
        "project_name": project_name,
        "start_time": first.get("start_time"),
        "end_time": last.get("end_time"),
        "report_date": first.get("report_date"),
        "duration_seconds": duration,
        "activity_ids": activity_ids,
        "event_count": len(rows),
        "status": first.get("status") if len({row.get("status") for row in rows}) == 1 else "mixed",
        "status_summary": status_summary,
        "is_uncategorized": project_id == int(uncategorized_id),
        "is_suggested_project": bool(first.get("report_is_suggested_project", first.get("is_suggested_project"))),
    }


def _with_display_projects(rows: list[dict], uncategorized_id: int) -> list[dict]:
    for row in rows:
        _attach_display_project(row, uncategorized_id)
    return rows


def _with_reporting_projects(rows: list[dict]) -> list[dict]:
    for row in rows:
        _attach_original_report_project(row)
    carry_minutes = max(0, get_int_setting("context_carry_minutes", 15))
    if carry_minutes <= 0:
        return rows
    for anchor_index, anchor in enumerate(rows):
        if not _is_project_anchor(anchor):
            continue
        merge = _find_short_context_merge(rows, anchor_index, carry_minutes)
        if merge is None:
            continue
        for interrupt_index in merge:
            _attach_merged_report_project(rows[interrupt_index], anchor)
    return rows


def _with_report_dates(rows: list[dict]) -> list[dict]:
    report_rows: list[dict] = []
    carry_project_key: str | None = None
    carry_report_date: str | None = None
    carry_active = False
    for row in rows:
        if _is_project_day_carry_row(row):
            start_day = _date_part(row.get("start_time"))
            key = str(row.get("report_project_key") or "")
            same_active_project = carry_active and carry_project_key == key and carry_report_date
            report_date = carry_report_date if same_active_project else start_day
            carry_project_key = str(row.get("report_project_key") or "")
            carry_report_date = report_date
            carry_active = bool(same_active_project) or _row_crosses_midnight(row)
            item = dict(row)
            item["report_date"] = report_date
            item["report_duration_seconds"] = _display_duration(row)
            item["report_slice"] = False
            report_rows.append(item)
            continue
        report_rows.extend(_split_calendar_report_rows(row))
    return report_rows


def _split_calendar_report_rows(row: dict) -> list[dict]:
    start_dt = _parse_row_time(row.get("start_time"))
    if start_dt is None:
        return []
    duration = _display_duration(row)
    if duration <= 0:
        item = dict(row)
        item["report_date"] = start_dt.date().isoformat()
        item["report_duration_seconds"] = 0
        item["report_slice"] = False
        return [item]

    end_dt = _parse_row_time(row.get("end_time"))
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
        rows.append(item)
        current_start = current_end
    return rows


def _is_project_day_carry_row(row: dict) -> bool:
    return (
        row.get("status") == STATUS_NORMAL
        and (row.get("report_project_name") or UNCATEGORIZED_PROJECT) != UNCATEGORIZED_PROJECT
    )


def _row_crosses_midnight(row: dict) -> bool:
    start_dt = _parse_row_time(row.get("start_time"))
    if start_dt is None:
        return False
    duration = _display_duration(row)
    end_dt = _parse_row_time(row.get("end_time"))
    if end_dt is None or end_dt < start_dt:
        end_dt = start_dt + timedelta(seconds=duration)
    return end_dt.date() > start_dt.date()


def _attach_original_report_project(row: dict) -> None:
    row["report_project_id"] = row.get("effective_project_id")
    row["report_project_name"] = row.get("display_project_name") or UNCATEGORIZED_PROJECT
    row["report_project_key"] = row.get("display_project_key") or ""
    row["report_is_suggested_project"] = bool(row.get("is_suggested_project"))
    row["report_context_merged"] = False


def _attach_merged_report_project(row: dict, anchor: dict) -> None:
    row["report_project_id"] = anchor.get("effective_project_id")
    row["report_project_name"] = anchor.get("display_project_name") or UNCATEGORIZED_PROJECT
    row["report_project_key"] = anchor.get("display_project_key") or ""
    row["report_is_suggested_project"] = bool(anchor.get("is_suggested_project"))
    row["report_context_merged"] = True


def _find_short_context_merge(rows: list[dict], anchor_index: int, carry_minutes: int) -> list[int] | None:
    anchor = rows[anchor_index]
    anchor_key = str(anchor.get("display_project_key") or "")
    interrupt_indices: list[int] = []
    after_interrupt_block = False
    for pos in range(anchor_index + 1, len(rows)):
        row = rows[pos]
        if _is_project_anchor(row) and str(row.get("display_project_key") or "") == anchor_key:
            if (
                interrupt_indices
                and _seconds_for_rows(rows, interrupt_indices) < SHORT_CONTEXT_MERGE_SECONDS
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
    return (
        row.get("status") == STATUS_NORMAL
        and row.get("resource_role") == "anchor"
        and (row.get("display_project_name") or UNCATEGORIZED_PROJECT) != UNCATEGORIZED_PROJECT
    )


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
        row["display_project_key"] = f"suggested:{suggested.casefold()}"
        row["is_suggested_project"] = True
        return
    row["display_project_name"] = row.get("effective_project_name") or UNCATEGORIZED_PROJECT
    row["display_project_key"] = f"project:{project_id}"
    row["is_suggested_project"] = False


def _anchor_preview_item(row: dict, current_project_name: str | None) -> dict:
    return {
        "resource_id": int(row["resource_id"]),
        "display_name": row.get("display_name") or "未知文件",
        "full_path": row.get("full_path") or "",
        "parent_dir": row.get("parent_dir") or "",
        "current_project_name": current_project_name or "",
    }


def _session_sort_key(session: dict) -> tuple[str, int]:
    first_id = str(session.get("session_id") or "0").split("-", 1)[0]
    try:
        start_id = int(first_id)
    except ValueError:
        start_id = 0
    return (str(session.get("start_time") or ""), start_id)


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
    resource_name = str(row.get("resource_display_name") or "").strip()
    if row.get("resource_role") == "anchor" and resource_name:
        return resource_name
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
    start = row.get("start_time")
    if not start:
        return 0
    start_dt = datetime.strptime(start, TIME_FORMAT)
    return max(0, int((datetime.now() - start_dt).total_seconds()))


def _live_duration_for_row(row: dict) -> int | None:
    if row.get("end_time") is not None:
        return None
    try:
        row_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        return None
    snapshot = _read_current_activity_snapshot()
    if not snapshot:
        return None
    try:
        snapshot_id = int(snapshot.get("persisted_activity_id") or 0)
    except (TypeError, ValueError):
        return None
    if snapshot_id != row_id:
        return None
    return _snapshot_elapsed_seconds(snapshot) + _snapshot_extra_seconds(snapshot)


def _read_current_activity_snapshot() -> dict | None:
    raw = get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _snapshot_report_date(snapshot: dict, today: date_type) -> str | None:
    status = str(snapshot.get("status") or STATUS_NORMAL)
    project_name = str(snapshot.get("inferred_project_name") or UNCATEGORIZED_PROJECT)
    if status != STATUS_NORMAL or project_name == UNCATEGORIZED_PROJECT:
        return today.isoformat()

    persisted_id = _snapshot_persisted_id(snapshot)
    if persisted_id:
        start_day = _snapshot_start_date(snapshot) or today
        first_day = min(start_day, today - timedelta(days=1))
        rows = get_report_activity_rows(
            first_day.isoformat(),
            today.isoformat(),
            include_hidden=True,
            ensure_context=False,
        )
        for row in rows:
            if int(row["id"]) == persisted_id:
                return str(row.get("report_date") or today.isoformat())

    start_day = _snapshot_start_date(snapshot)
    if start_day and start_day < today:
        return start_day.isoformat()
    return today.isoformat()


def _snapshot_persisted_id(snapshot: dict) -> int | None:
    try:
        value = int(snapshot.get("persisted_activity_id") or 0)
    except (TypeError, ValueError):
        return None
    return value or None


def _snapshot_start_date(snapshot: dict) -> date_type | None:
    start = _parse_row_time(snapshot.get("start_time"))
    return start.date() if start else None


def _snapshot_elapsed_seconds(snapshot: dict) -> int:
    fallback = _safe_int(snapshot.get("elapsed_seconds"))
    start = _parse_row_time(snapshot.get("start_time"))
    if start is None:
        return fallback
    seconds = int((datetime.now() - start).total_seconds())
    if 0 <= seconds <= 36 * 60 * 60:
        return seconds
    return fallback


def _snapshot_extra_seconds(snapshot: dict) -> int:
    return _safe_int(snapshot.get("extra_seconds"))


def _safe_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _date_part(value: str | None) -> str:
    parsed = _parse_row_time(value)
    if parsed is None:
        return date_type.today().isoformat()
    return parsed.date().isoformat()


def _parse_row_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), TIME_FORMAT)
    except ValueError:
        return None
