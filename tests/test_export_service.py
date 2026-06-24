from pathlib import Path

from openpyxl import load_workbook

from worktrace.services import activity_service, export_service


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
        "资源类型",
        "资源名称",
        "应用",
        "项目",
        "路径",
        "域名",
        "备注",
    ]


def test_exports_prefer_activity_file_name_for_wps_activity(temp_db, tmp_path):
    aid = activity_service.create_activity(
        "WPS Writer",
        "wps.exe",
        "合同审查意见.docx - WPS",
        file_path_hint="D:\\ClientA\\合同审查意见.docx",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-18 09:30:00")

    xlsx_path = export_service.export_excel("2026-06-18", "2026-06-18", str(tmp_path / "out.xlsx"))
    ws = load_workbook(xlsx_path)["Activity Logs"]
    headers = [cell.value for cell in ws[1]]
    name_col = headers.index("资源名称") + 1
    assert ws.cell(row=2, column=name_col).value == "合同审查意见.docx"


def test_export_all_and_clear_requires_confirmation(temp_db, tmp_path):
    path = export_service.export_all_local_data(str(tmp_path / "all.xlsx"))
    assert Path(path).exists()
    wb = load_workbook(path)
    assert "folder_project_rule" in wb.sheetnames
    assert "folder_rule_index_state" not in wb.sheetnames
    assert "folder_rule_file_index" not in wb.sheetnames
    assert "activity_resource" in wb.sheetnames
    try:
        export_service.clear_all_local_data(confirm=False)
    except ValueError:
        pass
    else:
        raise AssertionError("clear_all_local_data should require confirmation")
