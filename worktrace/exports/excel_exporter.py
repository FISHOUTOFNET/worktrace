from __future__ import annotations

from datetime import date
from pathlib import Path

from ..formatters import format_duration
from ..services import activity_service, statistics_service


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

    logs = wb.create_sheet("Activity Logs")
    logs.append(
        [
            "日期",
            "开始时间",
            "结束时间",
            "时长",
            "状态",
            "应用",
            "活动",
            "窗口标题",
            "项目",
            "备注",
        ]
    )
    for row in reversed(activity_service.get_activities_by_range(start_date, end_date)):
        if row["is_deleted"] or row["is_hidden"]:
            continue
        logs.append(
            [
                row["start_time"][:10],
                row["start_time"],
                row["end_time"] or "",
                format_duration(row["duration_seconds"] or 0),
                row["status"],
                row["app_name"],
                activity_service.activity_display_name(row),
                row["window_title"],
                row.get("project_name") or "未归类",
                row.get("note") or "",
            ]
        )
    wb.save(out)
    return str(out)
