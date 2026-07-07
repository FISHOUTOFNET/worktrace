from __future__ import annotations

import pytest

from worktrace.formatters import (
    format_activity_display_name,
    format_resource_type,
    format_status_label,
)


class TestFormatResourceType:
    """1. Resource type Chinese display is correct."""

    def test_office_word(self):
        assert format_resource_type("office_document", "word_document") == "Word 文档"

    def test_office_spreadsheet(self):
        assert format_resource_type("office_document", "spreadsheet") == "表格"

    def test_office_presentation(self):
        assert format_resource_type("office_document", "presentation") == "演示文稿"

    def test_office_pdf(self):
        assert format_resource_type("office_document", "pdf") == "PDF"

    def test_local_file_pdf(self):
        assert format_resource_type("local_file", "pdf") == "PDF"

    def test_local_file_code(self):
        assert format_resource_type("local_file", "code_file") == "代码文件"

    def test_email_message(self):
        assert format_resource_type("email", "email_message") == "邮件"

    def test_email_file(self):
        assert format_resource_type("email", "email_file") == "邮件文件"

    def test_browser_tab(self):
        assert format_resource_type("browser_tab", "browser_page") == "浏览器标签页"

    def test_ide_file(self):
        assert format_resource_type("ide_file", "code_file") == "IDE 文件"

    def test_ide_workspace(self):
        assert format_resource_type("ide_file", "ide_workspace") == "IDE 工作区"

    def test_generic_app(self):
        assert format_resource_type("app", "generic_app") == "普通应用"

    def test_system_idle(self):
        assert format_resource_type("system", "idle") == "空闲"

    def test_system_paused(self):
        assert format_resource_type("system", "paused") == "已暂停"

    def test_system_excluded(self):
        assert format_resource_type("system", "excluded") == "已排除"

    def test_system_error(self):
        assert format_resource_type("system", "error") == "异常"

    def test_unknown_kind_fallback(self):
        assert format_resource_type("something", "unknown") == "something"

    def test_none_values(self):
        assert format_resource_type(None, None) == "未知"


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("normal", "正常"),
        ("idle", "空闲"),
        ("paused", "已暂停"),
        ("excluded", "已排除"),
        ("error", "异常"),
        ("unknown", "未知状态"),
        (None, "未知状态"),
    ],
)
def test_format_status_label_contract(status, label):
    assert format_status_label(status) == label


class TestFormatActivityDisplayName:
    """2. Old activity without resource doesn't crash UI."""

    def test_prefers_resource_display_name(self):
        row = {
            "resource_display_name": "合同.docx",
            "activity_display_name": "wps.exe",
            "window_title": "合同.docx - WPS",
            "app_name": "wps.exe",
        }
        assert format_activity_display_name(row) == "合同.docx"

    def test_fallback_to_activity_display_name(self):
        row = {
            "activity_display_name": "Chrome",
            "window_title": "Search - Chrome",
            "app_name": "chrome.exe",
        }
        assert format_activity_display_name(row) == "Chrome"

    def test_fallback_to_window_title(self):
        row = {
            "window_title": "Search",
            "app_name": "chrome.exe",
        }
        assert format_activity_display_name(row) == "Search"

    def test_fallback_to_app_name(self):
        row = {
            "app_name": "微信",
            "process_name": "WeChat.exe",
        }
        assert format_activity_display_name(row) == "微信"

    def test_fallback_to_process_name(self):
        row = {
            "process_name": "unknown.exe",
        }
        assert format_activity_display_name(row) == "unknown.exe"

    def test_empty_row(self):
        assert format_activity_display_name({}) == "未知"

    def test_old_activity_no_resource_fields(self):
        """Old activity without any resource_* fields still works."""
        row = {
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "合同.docx - Word",
        }
        assert format_activity_display_name(row) == "合同.docx - Word"
