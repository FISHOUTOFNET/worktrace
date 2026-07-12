from __future__ import annotations

from pathlib import Path

from ..services import statistics_service
from ..services.report_projection_snapshot_service import build_visible_snapshot
from ..services.statistics_projection import build_statistics_projection


def export_excel_file(start_date: str, end_date: str, path: str) -> str:
    """Write the same canonical export records used by CSV."""
    from openpyxl import Workbook

    statistics_service.validate_statistics_date_range(start_date, end_date)
    analytics = build_statistics_projection(build_visible_snapshot(start_date, end_date))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    summary.append(["项目", "总时长秒数", "记录数"])
    for group in analytics.by_project:
        summary.append([group["display_name"], group["duration_seconds"], group["record_count"]])
    sheet = workbook.create_sheet("Sessions")
    columns = (
        ("date", "日期"), ("start_time", "开始时间"), ("end_time", "结束时间"),
        ("duration", "时长"), ("duration_seconds", "时长秒数"), ("project", "项目"),
        ("status", "状态"), ("note", "备注"), ("adjusted_duration", "修正时长"),
        ("is_adjusted", "是否已修正"),
    )
    sheet.append([label for _, label in columns])
    for record in analytics.export_records:
        sheet.append([record.get(field, "") for field, _ in columns])
    workbook.save(out)
    return str(out)


__all__ = ["export_excel_file"]
