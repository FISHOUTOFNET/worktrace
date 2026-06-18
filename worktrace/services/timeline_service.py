from __future__ import annotations

from datetime import datetime

from ..constants import STATUS_NORMAL, TIME_FORMAT, UNCATEGORIZED_PROJECT
from ..db import dict_rows, get_connection, now_str
from .activity_service import update_activities_project
from .context_service import recompute_context_assignments_for_date
from .project_service import get_or_create_uncategorized_project


def get_project_sessions_by_date(date: str) -> list[dict]:
    recompute_context_assignments_for_date(date)
    start = f"{date} 00:00:00"
    end = f"{date} 23:59:59"
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.*,
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                p.name AS effective_project_name
            FROM activity_log a
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            LEFT JOIN project p ON p.id = COALESCE(apa.project_id, a.project_id)
            WHERE a.is_deleted = 0
              AND a.start_time BETWEEN ? AND ?
            ORDER BY a.start_time ASC, a.id ASC
            """,
            (start, end),
        ).fetchall()
    sessions: list[dict] = []
    current: list[dict] = []
    for row in dict_rows(rows):
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
                "project_name": row.get("effective_project_name") or UNCATEGORIZED_PROJECT,
                "unconfirmed_count": 0,
                "can_remember_for_future": row.get("resource_role") == "anchor",
            },
        )
        group["total_duration_seconds"] += _display_duration(row)
        group["activity_ids"].append(int(row["id"]))
        group["event_count"] += 1
        if not int(row.get("is_confirmed") or 0):
            group["unconfirmed_count"] += 1
    return sorted(
        groups.values(),
        key=lambda item: (-int(item["total_duration_seconds"]), str(item["display_name"]).casefold()),
    )


def get_session_activity_details(activity_ids: list[int]) -> list[dict]:
    rows = _load_session_rows(activity_ids)
    details = []
    for row in rows:
        item = dict(row)
        item["duration_seconds"] = _display_duration(row)
        item["project_id"] = row.get("effective_project_id")
        item["project_name"] = row.get("effective_project_name") or UNCATEGORIZED_PROJECT
        item["resource_display_name"] = row.get("resource_display_name") or row.get("app_name") or "未知资源"
        details.append(item)
    return details


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


def _load_session_rows(activity_ids: list[int]) -> list[dict]:
    placeholders = ",".join("?" for _ in activity_ids)
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
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                p.name AS effective_project_name
            FROM activity_log a
            LEFT JOIN resource r ON r.id = a.resource_id
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            LEFT JOIN project p ON p.id = COALESCE(apa.project_id, a.project_id)
            WHERE a.id IN ({placeholders})
            ORDER BY a.start_time ASC, a.id ASC
            """,
            activity_ids,
        ).fetchall()
    return dict_rows(rows)


def _can_merge(previous: dict, current: dict) -> bool:
    if previous["status"] != STATUS_NORMAL or current["status"] != STATUS_NORMAL:
        return False
    return int(previous.get("effective_project_id") or 0) == int(current.get("effective_project_id") or 0)


def _build_session(rows: list[dict]) -> dict:
    first = rows[0]
    last = rows[-1]
    project_id = int(first.get("effective_project_id") or get_or_create_uncategorized_project())
    project_name = first.get("effective_project_name") or UNCATEGORIZED_PROJECT
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
        "is_uncategorized": project_name == UNCATEGORIZED_PROJECT,
        "has_unconfirmed": any(not int(row.get("is_confirmed") or 0) for row in rows),
    }


def _session_sort_key(session: dict) -> tuple[str, int]:
    first_id = str(session.get("session_id") or "0").split("-", 1)[0]
    try:
        start_id = int(first_id)
    except ValueError:
        start_id = 0
    return (str(session.get("start_time") or ""), start_id)


def _status_summary(rows: list[dict]) -> str:
    if all(row.get("status") == STATUS_NORMAL for row in rows):
        apps = []
        for row in rows:
            app = row.get("app_name") or ""
            if app and app not in apps:
                apps.append(app)
            if len(apps) >= 3:
                break
        return "、".join(apps) if apps else "正常活动"
    return "、".join(sorted({str(row.get("status") or "") for row in rows if row.get("status")}))


def _display_duration(row: dict) -> int:
    if row.get("duration_seconds") is not None:
        return int(row.get("duration_seconds") or 0)
    start = row.get("start_time")
    if not start:
        return 0
    start_dt = datetime.strptime(start, TIME_FORMAT)
    return max(0, int((datetime.now() - start_dt).total_seconds()))
