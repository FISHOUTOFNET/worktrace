from pathlib import Path

from openpyxl import load_workbook

from worktrace.exports.markdown_exporter import format_duration
from worktrace.services import activity_service, export_service


def test_format_duration_chinese_output():
    assert format_duration(0) == "0秒"
    assert format_duration(30) == "30秒"
    assert format_duration(300) == "5分钟"
    assert format_duration(4800) == "1小时20分钟"
    assert format_duration(7380) == "2小时3分钟"


def test_excel_export_file_creation(temp_db, tmp_path):
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    path = export_service.export_excel("2026-06-18", "2026-06-18", str(tmp_path / "out.xlsx"))
    assert Path(path).exists()
    wb = load_workbook(path)
    assert "Summary" in wb.sheetnames
    assert "Activity Logs" in wb.sheetnames
    headers = [cell.value for cell in wb["Activity Logs"][1]]
    assert headers == [
        "日期",
        "开始时间",
        "结束时间",
        "时长",
        "状态",
        "应用",
        "窗口标题",
        "项目",
        "是否计费",
        "是否确认",
        "备注",
    ]


def test_markdown_export_content(temp_db, tmp_path):
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    path = export_service.export_markdown("2026-06-18", "2026-06-18", str(tmp_path / "out.md"))
    text = Path(path).read_text(encoding="utf-8")
    assert "WorkTrace 周报草稿" in text
    assert "日期范围：2026-06-18 至 2026-06-18" in text
    assert "项目维度汇总" in text
    assert "未归类：总计 30分钟" in text
    assert "未确认记录提醒" in text


def test_export_all_and_clear_requires_confirmation(temp_db, tmp_path):
    path = export_service.export_all_local_data(str(tmp_path / "all.xlsx"))
    assert Path(path).exists()
    wb = load_workbook(path)
    assert "folder_project_rule" in wb.sheetnames
    try:
        export_service.clear_all_local_data(confirm=False)
    except ValueError:
        pass
    else:
        raise AssertionError("clear_all_local_data should require confirmation")
