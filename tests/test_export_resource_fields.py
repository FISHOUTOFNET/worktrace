from __future__ import annotations

import os
import tempfile

import pytest

from worktrace.constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED
from worktrace.exports.excel_exporter import export_excel_file
from worktrace.services import activity_service


def _insert_closed_activity(
    app_name: str, process_name: str, window_title: str,
    start: str, end: str, duration: int,
    status: str = "normal", file_path_hint: str | None = None, project_id: int | None = None,
) -> int:
    """Create a closed activity via the service layer so that the resource is
    populated synchronously by ``create_activity``.
    """
    aid = activity_service.create_activity(
        app_name,
        process_name,
        window_title,
        status=status,
        start_time=start,
        file_path_hint=file_path_hint,
        project_id=project_id,
    )
    activity_service.close_activity(aid, end, duration_seconds=duration)
    return aid


class TestExcelExportResourceFields:
    """3. Excel export includes resource name/type."""

    def test_excel_includes_resource_type_and_name(self, temp_db):
        _insert_closed_activity(
            "Word", "winword.exe", "合同.docx - Word",
            "2026-06-18 09:00:00", "2026-06-18 09:30:00", 1800,
            file_path_hint="D:\\Docs\\合同.docx",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.xlsx")
            export_excel_file("2026-06-18", "2026-06-18", path)
            from openpyxl import load_workbook
            wb = load_workbook(path)
            ws = wb["Activity Logs"]
            headers = [cell.value for cell in ws[1]]
            assert "资源类型" in headers
            assert "资源名称" in headers
            assert "路径" in headers
            assert "域名" in headers
            type_col = headers.index("资源类型")
            name_col = headers.index("资源名称")
            path_col = headers.index("路径")
            data_row = [cell.value for cell in ws[2]]
            assert data_row[type_col] == "Word 文档"
            assert data_row[name_col] == "合同.docx"
            assert "合同.docx" in str(data_row[path_col])

    def test_excel_excluded_no_real_path(self, temp_db):
        _insert_closed_activity(
            "已排除", "excluded", "已排除窗口",
            "2026-06-18 09:00:00", "2026-06-18 09:30:00", 1800,
            status="excluded",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.xlsx")
            export_excel_file("2026-06-18", "2026-06-18", path)
            from openpyxl import load_workbook
            wb = load_workbook(path)
            ws = wb["Activity Logs"]
            headers = [cell.value for cell in ws[1]]
            path_col = headers.index("路径")
            host_col = headers.index("域名")
            data_row = [cell.value for cell in ws[2]]
            assert (data_row[path_col] or "") == ""
            assert (data_row[host_col] or "") == ""

    def test_excel_activity_logs_status_and_project_display_contract(self, temp_db):
        from worktrace.services import project_service

        pid = project_service.create_project("Client")
        _insert_closed_activity(
            "Word", "winword.exe", "合同.docx - Word",
            "2026-06-18 09:00:00", "2026-06-18 09:30:00", 1800,
            project_id=pid,
            file_path_hint="D:\\Docs\\合同.docx",
        )
        for status, app, start, end in (
            (STATUS_IDLE, "空闲", "2026-06-18 09:30:00", "2026-06-18 09:40:00"),
            (STATUS_PAUSED, "已暂停", "2026-06-18 09:40:00", "2026-06-18 09:45:00"),
            (STATUS_EXCLUDED, "已排除", "2026-06-18 09:45:00", "2026-06-18 09:50:00"),
            (STATUS_ERROR, "异常", "2026-06-18 09:50:00", "2026-06-18 09:55:00"),
        ):
            _insert_closed_activity(
                app, status, f"{app}窗口",
                start, end, 300,
                status=status,
                project_id=pid,
                file_path_hint="D:\\Secret\\should-not-export.txt",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.xlsx")
            export_excel_file("2026-06-18", "2026-06-18", path)
            from openpyxl import load_workbook
            wb = load_workbook(path)
            ws = wb["Activity Logs"]
            headers = [cell.value for cell in ws[1]]
            status_col = headers.index("状态")
            project_col = headers.index("项目")
            path_col = headers.index("路径")
            host_col = headers.index("域名")
            rows = [[cell.value for cell in row] for row in ws.iter_rows(min_row=2)]

            by_status = {row[status_col]: row for row in rows}
            assert set(by_status) == {"正常", "空闲", "已暂停", "已排除", "异常"}
            assert by_status["正常"][project_col] == "Client"
            assert by_status["正常"][path_col]
            for label in ("空闲", "已暂停", "已排除", "异常"):
                assert by_status[label][project_col] == "—"
                assert (by_status[label][path_col] or "") == ""
                assert (by_status[label][host_col] or "") == ""
            for raw in ("normal", "idle", "paused", "excluded", "error"):
                assert raw not in by_status
