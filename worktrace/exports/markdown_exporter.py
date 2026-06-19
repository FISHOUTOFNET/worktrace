from __future__ import annotations

from datetime import date
from pathlib import Path

from ..formatters import format_current_duration, format_duration
from ..services import activity_service, statistics_service


def _validate_date_range(start_date: str, end_date: str) -> None:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("日期格式必须为 YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")


def _activity_line(row: dict) -> str:
    start = row["start_time"]
    end = row["end_time"] or ""
    time_range = f"{start[11:16]}-{end[11:16] if end else ''}"
    project = row.get("project_name") or "未归类"
    resource = activity_service.activity_display_name(row)
    title = row.get("window_title") or ""
    activity_text = resource if not title or title == resource else f"{resource}｜{title}"
    note = row.get("note") or ""
    note_text = f"；备注：{note}" if note else ""
    return (
        f"- {start[:10]} {time_range}｜{format_duration(row['duration_seconds'])}｜"
        f"{row['status']}｜{activity_text}｜{project}{note_text}"
    )


def export_markdown_file(start_date: str, end_date: str, path: str) -> str:
    _validate_date_range(start_date, end_date)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    project_rows = statistics_service.get_project_stats(start_date, end_date)
    activities = [
        row for row in activity_service.get_activities_by_range(start_date, end_date)
        if not row["is_deleted"] and not row["is_hidden"]
    ]

    project_summary = "\n".join(
        f"- {row['project']}：总计 {format_duration(row['total_duration'])}，记录 {row['record_count']} 条"
        for row in project_rows
    ) or "- 暂无"

    details = "\n".join(_activity_line(row) for row in reversed(activities)) or "- 暂无"

    text = "\n".join(
        [
            "# WorkTrace 周报草稿",
            "",
            f"日期范围：{start_date} 至 {end_date}",
            "",
            "## 项目维度汇总",
            "",
            project_summary,
            "",
            "## 明细列表",
            "",
            details,
            "",
        ]
    )
    out.write_text(text, encoding="utf-8")
    return str(out)
