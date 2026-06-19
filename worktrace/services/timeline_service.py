from __future__ import annotations

from datetime import datetime

from ..constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED, TIME_FORMAT, UNCATEGORIZED_PROJECT
from ..db import dict_rows, get_connection, now_str
from ..resource_patterns import extract_anchor_file_name
from . import folder_rule_service
from .activity_service import update_activities_project
from .context_service import recompute_context_assignments_for_date
from .project_service import get_or_create_uncategorized_project
from .settings_service import get_int_setting

SHORT_CONTEXT_MERGE_SECONDS = 5 * 60


def get_project_sessions_by_date(date: str, include_hidden: bool = True) -> list[dict]:
    recompute_context_assignments_for_date(date)
    start = f"{date} 00:00:00"
    end = f"{date} 23:59:59"
    uncategorized_id = get_or_create_uncategorized_project()
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
              AND a.start_time BETWEEN ? AND ?
              AND (? = 1 OR a.is_hidden = 0)
            ORDER BY a.start_time ASC, a.id ASC
            """,
            (start, end, int(include_hidden)),
        ).fetchall()
    rows = _with_reporting_projects(_with_display_projects(dict_rows(rows), uncategorized_id))
    sessions: list[dict] = []
    current: list[dict] = []
    for row in rows:
        if not current:
            current = [row]
            continue
        if _can_merge(current[-1], row):
            current.append(row)
        else:
            sessions.append(_build_session(current))
            current = [row]
    if current:
        sessions.append(_build_session(current))
    return sorted(sessions, key=_session_sort_key, reverse=True)


def get_session_resource_summary(activity_ids: list[int]) -> list[dict]:
    if not activity_ids:
        return []
    rows = _load_session_rows(activity_ids)
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


def get_session_activity_details(activity_ids: list[int]) -> list[dict]:
    rows = _load_session_rows(activity_ids, newest_first=True)
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


def _load_session_rows(activity_ids: list[int], newest_first: bool = False) -> list[dict]:
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


def _build_session(rows: list[dict]) -> dict:
    first = rows[0]
    last = rows[-1]
    project_id = int(first.get("report_project_id") or first.get("effective_project_id") or get_or_create_uncategorized_project())
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
        "duration_seconds": duration,
        "activity_ids": activity_ids,
        "event_count": len(rows),
        "status": first.get("status") if len({row.get("status") for row in rows}) == 1 else "mixed",
        "status_summary": status_summary,
        "is_uncategorized": project_id == int(get_or_create_uncategorized_project()),
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
    if row.get("duration_seconds") is not None:
        return int(row.get("duration_seconds") or 0)
    start = row.get("start_time")
    if not start:
        return 0
    start_dt = datetime.strptime(start, TIME_FORMAT)
    return max(0, int((datetime.now() - start_dt).total_seconds()))
