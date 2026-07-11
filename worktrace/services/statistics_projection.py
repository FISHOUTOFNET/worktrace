from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constants import STATUS_EXCLUDED, STATUS_PAUSED, UNCATEGORIZED_PROJECT
from ..formatters import format_activity_project_cell, format_duration, format_status_label
from .report_projection_snapshot_service import ReportProjectionSnapshot
from .report_status_policy import decide_report_status

_UNKNOWN_APP_LABEL = "未知应用"


@dataclass(frozen=True)
class StatisticsProjection:
    snapshot_revision: str
    total_duration_seconds: int
    project_duration_seconds: int
    classified_duration_seconds: int
    uncategorized_duration_seconds: int
    excluded_duration_seconds: int
    activity_count: int
    session_count: int
    export_row_count: int
    by_project: list[dict[str, Any]]
    by_app: list[dict[str, Any]]
    by_status: list[dict[str, Any]]
    export_rows: list[dict[str, Any]]


def build_statistics_projection(snapshot: ReportProjectionSnapshot) -> StatisticsProjection:
    export_rows = _build_export_rows(snapshot)
    included_members: set[tuple[str, int]] = set()
    by_project: dict[str, dict] = {}
    by_app: dict[str, dict] = {}
    by_status: dict[str, dict] = {}
    total = 0
    project_duration = 0
    classified = 0
    uncategorized = 0
    excluded = 0
    for row in export_rows:
        duration = int(row.get("duration_seconds") or 0)
        total += duration
        for activity_id in row.get("_activity_ids") or []:
            included_members.add((str(row.get("date") or ""), int(activity_id)))
        project = str(row.get("project") or UNCATEGORIZED_PROJECT)
        status = str(row.get("status_code") or "")
        if status == STATUS_EXCLUDED:
            excluded += duration
        elif project == UNCATEGORIZED_PROJECT:
            uncategorized += duration
        else:
            classified += duration
            project_duration += duration
        _accumulate(by_project, project, project, duration, row.get("_activity_ids") or [])
        _accumulate(by_status, status or "unknown", str(row.get("status") or ""), duration, row.get("_activity_ids") or [])
    for contribution in snapshot.final_contributions:
        activity_id = int(contribution.get("activity_id") or 0)
        report_date = str(contribution.get("report_date") or "")
        if (report_date, activity_id) not in included_members:
            continue
        duration = int(contribution.get("duration_seconds") or 0)
        app_name = str(contribution.get("app_name") or "").strip() or _UNKNOWN_APP_LABEL
        _accumulate(by_app, app_name, app_name, duration, [activity_id])
    return StatisticsProjection(
        snapshot_revision=snapshot.snapshot_revision,
        total_duration_seconds=total,
        project_duration_seconds=project_duration,
        classified_duration_seconds=classified,
        uncategorized_duration_seconds=uncategorized,
        excluded_duration_seconds=excluded,
        activity_count=len(included_members),
        session_count=sum(1 for session in snapshot.final_sessions if not session.get("is_in_progress")),
        export_row_count=len(export_rows),
        by_project=_build_groups(by_project, total),
        by_app=_build_groups(by_app, total),
        by_status=_build_groups(by_status, total),
        export_rows=[
            {key: value for key, value in row.items() if not key.startswith("_") and key != "status_code"}
            for row in export_rows
        ],
    )


def _build_export_rows(snapshot: ReportProjectionSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for session in snapshot.final_sessions:
        if session.get("is_in_progress"):
            continue
        duration = int(session.get("display_duration_seconds") or session.get("duration_seconds") or 0)
        if duration <= 0:
            continue
        status = str(session.get("status_code") or session.get("status") or "normal")
        if status == STATUS_PAUSED:
            continue
        rows.append(
            {
                "date": str(session.get("report_date") or ""),
                "start_time": str(session.get("start_time") or ""),
                "end_time": str(session.get("end_time") or ""),
                "duration": format_duration(duration),
                "duration_seconds": duration,
                "project": _format_session_project_cell(session),
                "status": format_status_label(status),
                "status_code": status,
                "note": str(session.get("session_note") or ""),
                "adjusted_duration": format_duration(session.get("adjusted_duration_seconds")) if session.get("has_duration_override") else "",
                "is_adjusted": "是" if session.get("has_duration_override") else "否",
                "_activity_ids": [int(aid) for aid in session.get("activity_ids") or [] if int(aid) > 0],
            }
        )
    for row in snapshot.status_rows:
        status = str(row.get("status") or "")
        decision = decide_report_status(status, has_project_attribution=False)
        if not decision.exportable or decision.decision != "standalone_status":
            continue
        duration = int(row.get("duration_seconds") or 0)
        if duration <= 0:
            continue
        rows.append(
            {
                "date": str(row.get("report_date") or str(row.get("start_time") or "")[:10]),
                "start_time": str(row.get("start_time") or ""),
                "end_time": str(row.get("end_time") or ""),
                "duration": format_duration(duration),
                "duration_seconds": duration,
                "project": "已排除",
                "status": format_status_label(status),
                "status_code": status,
                "note": "",
                "adjusted_duration": "",
                "is_adjusted": "否",
                "_activity_ids": [int(row.get("activity_id") or row.get("id") or 0)],
            }
        )
    return rows


def _format_session_project_cell(session: dict) -> str:
    return format_activity_project_cell(
        {
            "status": session.get("status_code") or session.get("status") or "normal",
            "is_report_project": session.get("is_report_project"),
            "report_project_name": session.get("project_name"),
        }
    )


def _accumulate(groups: dict[str, dict], key: str, display_name: str, duration: int, activity_ids: list[int]) -> None:
    group = groups.setdefault(key, {"display_name": display_name, "duration_seconds": 0, "activity_ids": set()})
    group["duration_seconds"] += duration
    for activity_id in activity_ids:
        if activity_id:
            group["activity_ids"].add(int(activity_id))


def _build_groups(groups: dict[str, dict], total_duration: int) -> list[dict[str, Any]]:
    items = []
    for key, group in groups.items():
        duration = int(group["duration_seconds"])
        items.append(
            {
                "key": key,
                "display_name": str(group["display_name"]),
                "duration_seconds": duration,
                "activity_count": len(group["activity_ids"]),
                "percentage": round(duration / total_duration * 100, 1) if total_duration > 0 else 0.0,
            }
        )
    return sorted(items, key=lambda item: (-int(item["duration_seconds"]), str(item["display_name"]).casefold()))


__all__ = ["StatisticsProjection", "build_statistics_projection"]
