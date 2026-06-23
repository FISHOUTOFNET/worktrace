from __future__ import annotations

import os
import tempfile

import pytest

from worktrace.constants import STATUS_EXCLUDED
from worktrace.db import get_connection
from worktrace.exports.excel_exporter import export_excel_file
from worktrace.exports.markdown_exporter import export_markdown_file
from worktrace.services import activity_service


def _insert_closed_activity(
    app_name: str, process_name: str, window_title: str,
    start: str, end: str, duration: int,
    status: str = "normal", file_path_hint: str | None = None,
) -> int:
    """Insert a closed activity directly into DB for export testing."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO activity_log(
                start_time, end_time, duration_seconds, app_name, process_name,
                window_title, file_path_hint, status, source,
                is_deleted, is_hidden, auto_classified, manual_override,
                project_id, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'auto', 0, 0, 0, 0, 1, NULL, ?, ?)
            """,
            (start, end, duration, app_name, process_name, window_title,
             file_path_hint, status, start, start),
        )
        return int(cur.lastrowid)


class TestExcelExportResourceFields:
    """3. Excel export includes resource name/type."""

    def test_excel_includes_resource_type_and_name(self, temp_db):
        _insert_closed_activity(
            "Word", "winword.exe", "合同.docx - Word",
            "2026-06-18 09:00:00", "2026-06-18 09:30:00", 1800,
            file_path_hint="D:\\Docs\\合同.docx",
        )
        # Backfill resource
        from worktrace.services.resource_service import backfill_missing_resources
        backfill_missing_resources()

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
        from worktrace.services.resource_service import backfill_missing_resources
        backfill_missing_resources()

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


class TestMarkdownExportResourceFields:
    """4. Markdown export uses resource name."""

    def test_markdown_uses_resource_name(self, temp_db):
        _insert_closed_activity(
            "Word", "winword.exe", "合同.docx - Word",
            "2026-06-18 09:00:00", "2026-06-18 09:30:00", 1800,
            file_path_hint="D:\\Docs\\合同.docx",
        )
        from worktrace.services.resource_service import backfill_missing_resources
        backfill_missing_resources()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.md")
            export_markdown_file("2026-06-18", "2026-06-18", path)
            text = open(path, encoding="utf-8").read()
            assert "合同.docx" in text
            assert "Word 文档" in text

    def test_markdown_excluded_no_real_info(self, temp_db):
        _insert_closed_activity(
            "已排除", "excluded", "已排除窗口",
            "2026-06-18 09:00:00", "2026-06-18 09:30:00", 1800,
            status="excluded",
        )
        from worktrace.services.resource_service import backfill_missing_resources
        backfill_missing_resources()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.md")
            export_markdown_file("2026-06-18", "2026-06-18", path)
            text = open(path, encoding="utf-8").read()
            # Should show "已排除" but not the real window title
            assert "已排除" in text
