from __future__ import annotations

from datetime import date
from pathlib import Path

from ..formatters import (
    format_activity_project_cell,
    format_duration,
    format_status_label,
)
from ..services import statistics_service, timeline_service


def _validate_date_range(start_date: str, end_date: str) -> None:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("日期格式必须为 YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")


def export_excel_file(start_date: str, end_date: str, path: str) -> str:
    from openpyxl import Workbook

    _validate_date_range(start_date, end_date)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(
        [
            "Project",
            "Total Duration",
            "Project Record Count",
        ]
    )
    for row in statistics_service.get_project_stats(start_date, end_date):
        ws.append(
            [
                row["project"],
                format_duration(row["total_duration"]),
                row["record_count"],
            ]
        )

    sessions_sheet = wb.create_sheet("Sessions")
    sessions_sheet.append(
        [
            "日期",
            "开始时间",
            "结束时间",
            "时长",
            "项目",
            "状态",
            "备注",
            "修正时长",
            "是否已修正",
        ]
    )
    sessions = timeline_service.get_project_sessions_by_range(
        start_date,
        end_date,
        include_hidden=False,
        ensure_context=True,
    )
    for session in sessions:
        if session.get("is_in_progress"):
            continue
        duration_seconds = int(
            session.get("display_duration_seconds")
            or session.get("duration_seconds")
            or 0
        )
        adjusted_seconds = session.get("adjusted_duration_seconds")
        has_adjusted = bool(session.get("has_duration_override"))
        sessions_sheet.append(
            [
                session.get("report_date") or str(session.get("start_time") or "")[:10],
                session.get("start_time") or "",
                session.get("end_time") or "",
                format_duration(duration_seconds),
                _format_session_project_cell(session),
                format_status_label(session.get("status_code") or session.get("status")),
                session.get("session_note") or "",
                format_duration(adjusted_seconds) if has_adjusted else "",
                "是" if has_adjusted else "否",
            ]
        )
    wb.save(out)
    return str(out)


def _format_session_project_cell(session: dict) -> str:
    return format_activity_project_cell(
        {
            "status": session.get("status_code") or session.get("status") or "normal",
            "is_report_project": session.get("is_report_project"),
            "report_project_name": session.get("project_name"),
        }
    )
