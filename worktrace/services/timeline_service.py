from __future__ import annotations

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
from ..db import dict_rows, get_connection, now_str
from ..resource_patterns import extract_anchor_file_name
from . import folder_rule_service, session_boundary_service
from .activity_service import update_activities_project
from .context_service import recompute_context_assignments_for_date
from .live_time_service import snapshot_elapsed_seconds, snapshot_extra_seconds
from .project_service import get_or_create_uncategorized_project
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
    sessions = _build_sessions_from_rows(rows, uncategorized_id)
    return sorted(sessions, key=_session_sort_key, reverse=True)


def _build_sessions_from_rows(rows: list[dict], uncategorized_id: int) -> list[dict]:
    sessions: list[dict] = []
    current: list[dict] = []
    manual_groups: dict[int, list[dict]] = {}
    for row in rows:
        manual_session_id = _manual_session_id(row)
        if manual_session_id is not None:
            if current:
                sessions.append(_build_session(current, uncategorized_id))
                current = []
            manual_groups.setdefault(manual_session_id, []).append(row)
            continue
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
    for manual_session_id, group_rows in manual_groups.items():
        sessions.append(_build_session(group_rows, uncategorized_id, manual_session_id=manual_session_id))
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
    rows = _with_reporting_projects(_with_display_projects(rows, uncategorized_id))
    return [
        row
        for row in _with_report_dates(rows)
        if start_date <= str(row.get("report_date") or "") <= end_date
    ]


def get_default_report_date(today: date_type | None = None) -> str:
    return (today or date_type.today()).isoformat()


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
                "project_description": row.get("display_project_description") or "",
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
        item["project_description"] = row.get("display_project_description") or ""
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
    _sync_manual_sessions_project(session_activity_ids, project_id)


def split_session_at_activity(session_activity_ids: list[int], split_activity_id: int) -> dict:
    ordered = _ordered_session_activity_rows(session_activity_ids)
    ids = [int(row["id"]) for row in ordered]
    if int(split_activity_id) not in ids:
        raise ValueError("activity is not part of the selected session")
    split_index = ids.index(int(split_activity_id))
    if split_index <= 0 or split_index >= len(ids):
        raise ValueError("请选择第二条或之后的活动作为拆分点")
    project_id = _common_project_id(ordered)
    left_group = _manual_session_id(ordered[0]) or _create_manual_session(project_id)
    right_group = _create_manual_session(project_id)
    _assign_manual_session(ids[:split_index], left_group)
    _assign_manual_session(ids[split_index:], right_group)
    _cleanup_empty_manual_sessions()
    return {"left_manual_session_id": left_group, "right_manual_session_id": right_group}


def merge_sessions(primary_activity_ids: list[int], secondary_activity_ids: list[int]) -> dict:
    primary = _ordered_session_activity_rows(primary_activity_ids)
    secondary = _ordered_session_activity_rows(secondary_activity_ids)
    if not primary or not secondary:
        raise ValueError("请选择两个项目段")
    primary_project = _common_project_id(primary)
    secondary_project = _common_project_id(secondary)
    if primary_project != secondary_project:
        raise ValueError("只能合并同名项目段")
    target_group = _manual_session_id(primary[0]) or _manual_session_id(secondary[0]) or _create_manual_session(primary_project)
    _assign_manual_session([int(row["id"]) for row in [*primary, *secondary]], target_group)
    _cleanup_empty_manual_sessions()
    return {"manual_session_id": target_group}


def move_activity_to_project_target(
    activity_id: int,
    project_id: int,
    manual_session_id: int | None = None,
) -> None:
    update_activities_project([activity_id], project_id, manual=True)
    if manual_session_id is None:
        _clear_manual_session_for_activities([activity_id])
        return
    _ensure_manual_session_project(manual_session_id, project_id)
    _assign_manual_session([activity_id], manual_session_id)


def move_activity_to_session(activity_id: int, target_session_activity_ids: list[int]) -> dict:
    target_rows = _ordered_session_activity_rows(target_session_activity_ids)
    if not target_rows:
        raise ValueError("目标项目段不存在")
    project_id = _common_project_id(target_rows)
    target_group = _manual_session_id(target_rows[0]) or _create_manual_session(project_id)
    update_activities_project([activity_id], project_id, manual=True)
    _assign_manual_session([int(row["id"]) for row in target_rows] + [activity_id], target_group)
    _cleanup_empty_manual_sessions()
    return {"manual_session_id": target_group, "project_id": project_id}


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
    _clear_manual_session_for_activities(activity_ids)
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


def _ordered_session_activity_rows(activity_ids: list[int]) -> list[dict]:
    if not activity_ids:
        return []
    placeholders = ",".join("?" for _ in activity_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                a.id,
                a.project_id,
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                mpsa.manual_session_id
            FROM activity_log a
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            LEFT JOIN manual_project_session_activity mpsa ON mpsa.activity_id = a.id
            WHERE a.id IN ({placeholders})
              AND a.is_deleted = 0
            ORDER BY a.start_time ASC, a.id ASC
            """,
            activity_ids,
        ).fetchall()
    return dict_rows(rows)


def _common_project_id(rows: list[dict]) -> int:
    if not rows:
        raise ValueError("请选择项目段")
    uncategorized_id = get_or_create_uncategorized_project()
    project_ids = {int(row.get("effective_project_id") or row.get("project_id") or uncategorized_id) for row in rows}
    if len(project_ids) != 1:
        raise ValueError("只能操作同一项目段")
    return project_ids.pop()


def _create_manual_session(project_id: int) -> int:
    ts = now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO manual_project_session(project_id, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            (project_id, ts, ts),
        )
        return int(cur.lastrowid)


def _assign_manual_session(activity_ids: list[int], manual_session_id: int) -> None:
    if not activity_ids:
        return
    ts = now_str()
    with get_connection() as conn:
        for activity_id in activity_ids:
            conn.execute(
                """
                INSERT INTO manual_project_session_activity(activity_id, manual_session_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    manual_session_id = excluded.manual_session_id,
                    updated_at = excluded.updated_at
                """,
                (activity_id, manual_session_id, ts, ts),
            )
        conn.execute(
            "UPDATE manual_project_session SET updated_at = ? WHERE id = ?",
            (ts, manual_session_id),
        )


def _clear_manual_session_for_activities(activity_ids: list[int]) -> None:
    if not activity_ids:
        return
    placeholders = ",".join("?" for _ in activity_ids)
    with get_connection() as conn:
        conn.execute(
            f"DELETE FROM manual_project_session_activity WHERE activity_id IN ({placeholders})",
            activity_ids,
        )
    _cleanup_empty_manual_sessions()


def _sync_manual_sessions_project(activity_ids: list[int], project_id: int) -> None:
    if not activity_ids:
        return
    placeholders = ",".join("?" for _ in activity_ids)
    ts = now_str()
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT manual_session_id
            FROM manual_project_session_activity
            WHERE activity_id IN ({placeholders})
            """,
            activity_ids,
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE manual_project_session SET project_id = ?, updated_at = ? WHERE id = ?",
                (project_id, ts, int(row["manual_session_id"])),
            )


def _ensure_manual_session_project(manual_session_id: int, project_id: int) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT project_id FROM manual_project_session WHERE id = ?",
            (manual_session_id,),
        ).fetchone()
    if not row:
        raise ValueError("目标项目段不存在")
    if int(row["project_id"]) != int(project_id):
        raise ValueError("目标项目段与目标项目不一致")


def _cleanup_empty_manual_sessions() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM manual_project_session
            WHERE NOT EXISTS (
                SELECT 1
                FROM manual_project_session_activity mpsa
                WHERE mpsa.manual_session_id = manual_project_session.id
            )
            """
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
                mpsa.manual_session_id,
                apa.suggested_project_name,
                apa.source AS assignment_source,
                apa.is_manual AS assignment_is_manual,
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                p.name AS effective_project_name,
                p.description AS effective_project_description
            FROM activity_log a
            LEFT JOIN resource r ON r.id = a.resource_id
            LEFT JOIN manual_project_session_activity mpsa ON mpsa.activity_id = a.id
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
                mpsa.manual_session_id,
                apa.suggested_project_name,
                apa.source AS assignment_source,
                apa.is_manual AS assignment_is_manual,
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                p.name AS effective_project_name,
                p.description AS effective_project_description
            FROM activity_log a
            LEFT JOIN resource r ON r.id = a.resource_id
            LEFT JOIN manual_project_session_activity mpsa ON mpsa.activity_id = a.id
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
    if str(previous.get("report_date") or "") != str(current.get("report_date") or ""):
        return False
    if _has_session_boundary_between(previous, current):
        return False
    return str(previous.get("report_project_key") or "") == str(current.get("report_project_key") or "")


def _build_session(rows: list[dict], uncategorized_id: int, manual_session_id: int | None = None) -> dict:
    first = rows[0]
    last = rows[-1]
    project_id = int(first.get("report_project_id") or first.get("effective_project_id") or uncategorized_id)
    project_name = first.get("report_project_name") or first.get("display_project_name") or UNCATEGORIZED_PROJECT
    project_description = first.get("report_project_description") or first.get("display_project_description") or ""
    duration = sum(_display_duration(row) for row in rows)
    activity_ids = [int(row["id"]) for row in rows]
    status_summary = _status_summary(rows)
    session_id = f"manual-{manual_session_id}" if manual_session_id is not None else f"{first['id']}-{last['id']}"
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
        "sort_time": last.get("start_time") or first.get("start_time"),
        "event_count": len(rows),
        "status": first.get("status") if len({row.get("status") for row in rows}) == 1 else "mixed",
        "status_summary": status_summary,
        "is_uncategorized": project_id == int(uncategorized_id),
        "is_suggested_project": bool(first.get("report_is_suggested_project", first.get("is_suggested_project"))),
        "manual_session_id": manual_session_id,
        "is_manual_session": manual_session_id is not None,
    }


def _with_display_projects(rows: list[dict], uncategorized_id: int) -> list[dict]:
    for row in rows:
        _attach_display_project(row, uncategorized_id)
    return rows


def _with_reporting_projects(rows: list[dict]) -> list[dict]:
    for row in rows:
        _attach_original_report_project(row)
    carry_minutes = max(0, get_int_setting("context_carry_minutes", DEFAULT_CONTEXT_CARRY_MINUTES))
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
    for row in rows:
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


def _attach_original_report_project(row: dict) -> None:
    row["report_project_id"] = row.get("effective_project_id")
    row["report_project_name"] = row.get("display_project_name") or UNCATEGORIZED_PROJECT
    row["report_project_description"] = row.get("display_project_description") or ""
    manual_session_id = _manual_session_id(row)
    row["report_project_key"] = f"manual:{manual_session_id}" if manual_session_id is not None else row.get("display_project_key") or ""
    row["report_is_suggested_project"] = bool(row.get("is_suggested_project"))
    row["report_context_merged"] = False


def _attach_merged_report_project(row: dict, anchor: dict) -> None:
    row["report_project_id"] = anchor.get("effective_project_id")
    row["report_project_name"] = anchor.get("display_project_name") or UNCATEGORIZED_PROJECT
    row["report_project_description"] = anchor.get("display_project_description") or ""
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
        if _has_session_boundary_between(rows[pos - 1], row):
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
    return (
        row.get("status") == STATUS_NORMAL
        and (row.get("resource_role") == "anchor" or row.get("assignment_source") == "midnight_anchor")
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


def _has_session_boundary_between(previous: dict, current: dict) -> bool:
    if _has_unrecorded_gap_between(previous, current):
        return True
    boundary_start = previous.get("end_time") or previous.get("start_time") or ""
    boundary_end = current.get("start_time") or ""
    if not boundary_start or not boundary_end:
        return False
    return session_boundary_service.has_boundary_between(str(boundary_start), str(boundary_end))


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
    return {
        "resource_id": int(row["resource_id"]),
        "display_name": row.get("display_name") or "未知文件",
        "full_path": row.get("full_path") or "",
        "parent_dir": row.get("parent_dir") or "",
        "current_project_name": current_project_name or "",
    }


def _manual_session_id(row: dict) -> int | None:
    value = row.get("manual_session_id")
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed or None


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


def _snapshot_elapsed_seconds(snapshot: dict) -> int:
    return snapshot_elapsed_seconds(snapshot)


def _snapshot_extra_seconds(snapshot: dict) -> int:
    return snapshot_extra_seconds(snapshot)


def _parse_row_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), TIME_FORMAT)
    except ValueError:
        return None
