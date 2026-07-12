from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constants import STATUS_EXCLUDED, UNCATEGORIZED_PROJECT
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
        _accumulate(by_project, project, project, duration, row.get("_activity_ids") or [], row.get("_record_key"))
        _accumulate(by_status, status or "unknown", str(row.get("status") or ""), duration, row.get("_activity_ids") or [], row.get("_record_key"))
    for contribution in snapshot.final_contributions:
        activity_id = int(contribution.get("activity_id") or 0)
        report_date = str(contribution.get("report_date") or "")
        if (report_date, activity_id) not in included_members:
            continue
        duration = int(contribution.get("duration_seconds") or 0)
        app_name = str(contribution.get("app_name") or "").strip() or _UNKNOWN_APP_LABEL
        _accumulate(by_app, app_name, app_name, duration, [activity_id], contribution.get("projection_instance_key"))
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
    sessions_by_key = {
        str(session.get("projection_instance_key") or ""): session
        for session in snapshot.final_sessions
    }
    for contribution in snapshot.final_contributions:
        session = sessions_by_key.get(str(contribution.get("projection_instance_key") or ""))
        if session and session.get("is_in_progress"):
            continue
        duration = int(contribution.get("duration_seconds") or 0)
        if duration <= 0:
            continue
        status = str(contribution.get("status") or (session or {}).get("status_code") or "normal")
        decision = decide_report_status(status, has_project_attribution=bool(contribution.get("is_report_project")))
        if not decision.exportable:
            continue
        project = "已排除" if decision.privacy_redacted else _format_contribution_project_cell(contribution)
        rows.append(
            {
                "date": str(contribution.get("report_date") or ""),
                "start_time": str(contribution.get("start_time") or contribution.get("slice_start_time") or ""),
                "end_time": str(contribution.get("end_time") or contribution.get("slice_end_time") or ""),
                "duration": format_duration(duration),
                "duration_seconds": duration,
                "project": project,
                "status": format_status_label(status),
                "status_code": status,
                "note": str((session or {}).get("session_note") or ""),
                "adjusted_duration": format_duration((session or {}).get("adjusted_duration_seconds")) if (session or {}).get("has_duration_override") else "",
                "is_adjusted": "是" if (session or {}).get("has_duration_override") else "否",
                "_activity_ids": [int(contribution.get("activity_id") or 0)],
                "_record_key": str(contribution.get("projection_instance_key") or ""),
            }
        )
    return _aggregate_export_rows(rows)


def _aggregate_export_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("date"),
            row.get("_record_key"),
            row.get("project"),
            row.get("status_code"),
            row.get("note"),
            row.get("adjusted_duration"),
            row.get("is_adjusted"),
        )
        current = grouped.get(key)
        if current is None:
            grouped[key] = dict(row)
            continue
        current["duration_seconds"] = int(current.get("duration_seconds") or 0) + int(row.get("duration_seconds") or 0)
        current["duration"] = format_duration(int(current["duration_seconds"]))
        current["start_time"] = min(str(current.get("start_time") or ""), str(row.get("start_time") or ""))
        current["end_time"] = max(str(current.get("end_time") or ""), str(row.get("end_time") or ""))
        current["_activity_ids"] = sorted(set([*(current.get("_activity_ids") or []), *(row.get("_activity_ids") or [])]))
    return sorted(
        grouped.values(),
        key=lambda item: (str(item.get("date") or ""), str(item.get("start_time") or ""), str(item.get("_record_key") or "")),
    )


def _format_session_project_cell(session: dict) -> str:
    return format_activity_project_cell(
        {
            "status": session.get("status_code") or session.get("status") or "normal",
            "is_report_project": session.get("is_report_project"),
            "report_project_name": session.get("project_name"),
        }
    )


def _format_contribution_project_cell(row: dict) -> str:
    if row.get("is_report_project"):
        return str(row.get("project_name") or row.get("report_project_name") or UNCATEGORIZED_PROJECT)
    return UNCATEGORIZED_PROJECT


def _accumulate(groups: dict[str, dict], key: str, display_name: str, duration: int, activity_ids: list[int], record_key: str | None = None) -> None:
    group = groups.setdefault(key, {"display_name": display_name, "duration_seconds": 0, "activity_ids": set(), "record_keys": set()})
    group["duration_seconds"] += duration
    if record_key:
        group["record_keys"].add(str(record_key))
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
                "record_count": len(group.get("record_keys") or []),
                "percentage": round(duration / total_duration * 100, 1) if total_duration > 0 else 0.0,
            }
        )
    return sorted(items, key=lambda item: (-int(item["duration_seconds"]), str(item["display_name"]).casefold()))


__all__ = ["StatisticsProjection", "build_statistics_projection"]
