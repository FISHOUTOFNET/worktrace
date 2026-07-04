from __future__ import annotations

import json

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]

from worktrace.platforms.base import ActiveWindow
from worktrace.resources.browser_detector import BrowserDetector
from worktrace.resources.detectors import ResourceDetectorRegistry, SystemDetector, detect_resource
from worktrace.resources.email_detector import EmailDetector
from worktrace.resources.ide_detector import IdeDetector
from worktrace.resources.local_file_detector import LocalFileDetector
from worktrace.resources.office_wps_detector import OfficeWpsDetector
from worktrace.resources.resource_policy import safe_metadata_json


# 1. outlook.exe + 邮件标题 -> email/email_message

class TestEmailDetector:
    def test_outlook_email_message(self):
        aw = ActiveWindow(
            app_name="Outlook",
            process_name="outlook.exe",
            window_title="项目周报 - Outlook",
        )
        detector = EmailDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_message"
        assert result.display_name == "项目周报"
        assert result.is_anchor is True
        assert result.identity_key.startswith("email_subject:")

    def test_outlook_email_message_with_status(self):
        aw = ActiveWindow(
            app_name="Outlook",
            process_name="outlook.exe",
            window_title="Re: 合同审批 - Message (HTML) - Outlook",
        )
        detector = EmailDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_message"
        assert "合同审批" in result.display_name

    # 2. .eml path -> email/email_file
    def test_eml_file(self):
        aw = ActiveWindow(
            app_name="Outlook",
            process_name="outlook.exe",
            window_title="通知.eml - Outlook",
            file_path_hint="D:\\Emails\\通知.eml",
        )
        detector = EmailDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_file"
        assert result.display_name == "通知.eml"
        assert result.identity_key.startswith("email_file:")

    # 3. .msg path -> email/email_file
    def test_msg_file(self):
        aw = ActiveWindow(
            app_name="Outlook",
            process_name="outlook.exe",
            window_title="合同.msg - Outlook",
            file_path_hint="D:\\Emails\\合同.msg",
        )
        detector = EmailDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_file"
        assert result.display_name == "合同.msg"

    def test_thunderbird_email(self):
        aw = ActiveWindow(
            app_name="Thunderbird",
            process_name="thunderbird.exe",
            window_title="会议纪要 - Mozilla Thunderbird",
        )
        detector = EmailDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_message"

    def test_non_email_process_returns_none(self):
        aw = ActiveWindow(
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="Search",
        )
        detector = EmailDetector()
        assert detector.detect(aw) is None


# 4. chrome.exe 标题 -> browser_tab/browser_page

class TestBrowserDetector:
    def test_chrome_tab(self):
        aw = ActiveWindow(
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="GitHub - Google Chrome",
        )
        detector = BrowserDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "browser_tab"
        assert result.resource_subtype == "browser_page"
        assert result.display_name == "GitHub"
        assert result.is_anchor is True

    # 5. Edge 标题尾缀能清理
    def test_edge_title_cleanup(self):
        aw = ActiveWindow(
            app_name="Edge",
            process_name="msedge.exe",
            window_title="项目文档 - Microsoft Edge",
        )
        detector = BrowserDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.display_name == "项目文档"

    def test_firefox_title_cleanup(self):
        aw = ActiveWindow(
            app_name="Firefox",
            process_name="firefox.exe",
            window_title="Stack Overflow - Mozilla Firefox",
        )
        detector = BrowserDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.display_name == "Stack Overflow"

    def test_browser_with_uri_host(self):
        aw = ActiveWindow(
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="github.com/microsoft/vscode - Google Chrome",
        )
        detector = BrowserDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.uri_host == "github.com"
        assert "github.com" in result.identity_key

    # 6. 新标签页 is_anchor=False
    def test_new_tab_is_not_anchor(self):
        aw = ActiveWindow(
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="新标签页 - Google Chrome",
        )
        detector = BrowserDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.is_anchor is False
        assert result.resource_kind == "browser_tab"

    def test_blank_page_is_not_anchor(self):
        aw = ActiveWindow(
            app_name="Edge",
            process_name="msedge.exe",
            window_title="about:blank - Microsoft Edge",
        )
        detector = BrowserDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.is_anchor is False

    def test_new_tab_page_is_not_anchor(self):
        aw = ActiveWindow(
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="New Tab - Google Chrome",
        )
        detector = BrowserDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.is_anchor is False

    def test_non_browser_returns_none(self):
        aw = ActiveWindow(
            app_name="Word",
            process_name="winword.exe",
            window_title="Doc",
        )
        detector = BrowserDetector()
        assert detector.detect(aw) is None


# 7. Code.exe + .py path -> ide_file/code_file

class TestIdeDetector:
    def test_vscode_python_file(self):
        aw = ActiveWindow(
            app_name="Visual Studio Code",
            process_name="Code.exe",
            window_title="main.py - WorkTrace - Visual Studio Code",
            file_path_hint="D:\\Repo\\WorkTrace\\main.py",
        )
        detector = IdeDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "ide_file"
        assert result.resource_subtype == "code_file"
        assert result.display_name == "main.py"
        assert result.is_anchor is True
        assert result.identity_key.startswith("ide_file:")

    def test_vscode_without_path_hint(self):
        aw = ActiveWindow(
            app_name="Visual Studio Code",
            process_name="Code.exe",
            window_title="utils.py - MyProject - Visual Studio Code",
        )
        detector = IdeDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "ide_file"
        assert result.resource_subtype == "code_file"
        assert result.display_name == "utils.py"

    # 8. PyCharm 标题含文件名 -> ide_file/code_file 或 ide_workspace
    def test_pycharm_code_file(self):
        aw = ActiveWindow(
            app_name="PyCharm",
            process_name="pycharm64.exe",
            window_title="app.py – MyProject – PyCharm",
            file_path_hint="D:\\Projects\\MyProject\\app.py",
        )
        detector = IdeDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "ide_file"
        assert result.resource_subtype == "code_file"
        assert result.display_name == "app.py"

    def test_pycharm_workspace_only(self):
        aw = ActiveWindow(
            app_name="PyCharm",
            process_name="pycharm64.exe",
            window_title="MyProject – PyCharm",
        )
        detector = IdeDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "ide_file"
        assert result.resource_subtype == "ide_workspace"
        assert result.display_name == "MyProject"

    def test_cursor_code_file(self):
        aw = ActiveWindow(
            app_name="Cursor",
            process_name="Cursor.exe",
            window_title="server.ts - Backend - Cursor",
            file_path_hint="D:\\Backend\\server.ts",
        )
        detector = IdeDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "ide_file"
        assert result.resource_subtype == "code_file"

    def test_non_ide_returns_none(self):
        aw = ActiveWindow(
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="Search",
        )
        detector = IdeDetector()
        assert detector.detect(aw) is None

    def test_ide_no_code_file_no_workspace_returns_none(self):
        aw = ActiveWindow(
            app_name="Visual Studio Code",
            process_name="Code.exe",
            window_title="Visual Studio Code",
        )
        detector = IdeDetector()
        assert detector.detect(aw) is None


# 9. All detectors don't save body-like metadata keys

class TestNoBodyMetadata:
    def test_safe_metadata_json_removes_body_keys(self):
        metadata = {
            "subject": "项目周报",
            "from": "boss@company.com",
            "body": "secret email body",
            "html_body": "<p>secret</p>",
            "email_body": "secret",
            "content": "secret content",
        }
        result = safe_metadata_json(metadata)
        assert result is not None
        parsed = json.loads(result)
        assert "subject" in parsed
        assert "from" in parsed
        assert "body" not in parsed
        assert "html_body" not in parsed
        assert "email_body" not in parsed
        assert "content" not in parsed


# Registry order test

class TestRegistryOrder:
    def test_full_registry_order(self):
        registry = ResourceDetectorRegistry()
        registry.register(SystemDetector())
        registry.register(OfficeWpsDetector())
        registry.register(EmailDetector())
        registry.register(IdeDetector())
        registry.register(BrowserDetector())
        registry.register(LocalFileDetector())
        from worktrace.resources.detectors import GenericAppDetector
        registry.register(GenericAppDetector())

        # System
        aw_idle = ActiveWindow(app_name="空闲", process_name="idle", window_title="用户空闲")
        assert registry.detect(aw_idle).resource_kind == "system"

        # Office
        aw_word = ActiveWindow(
            app_name="Word", process_name="winword.exe",
            window_title="合同.docx - Word", file_path_hint="D:\\Docs\\合同.docx",
        )
        assert registry.detect(aw_word).resource_kind == "office_document"

        # Email
        aw_outlook = ActiveWindow(
            app_name="Outlook", process_name="outlook.exe",
            window_title="周报 - Outlook",
        )
        assert registry.detect(aw_outlook).resource_kind == "email"

        # IDE
        aw_code = ActiveWindow(
            app_name="VS Code", process_name="Code.exe",
            window_title="main.py - VS Code", file_path_hint="D:\\Repo\\main.py",
        )
        assert registry.detect(aw_code).resource_kind == "ide_file"

        # Browser
        aw_chrome = ActiveWindow(
            app_name="Chrome", process_name="chrome.exe",
            window_title="Search - Google Chrome",
        )
        assert registry.detect(aw_chrome).resource_kind == "browser_tab"

        # Local file (non-IDE, non-Office)
        aw_acrobat = ActiveWindow(
            app_name="Acrobat", process_name="acrobat.exe",
            window_title="doc.pdf", file_path_hint="D:\\Docs\\doc.pdf",
        )
        assert registry.detect(aw_acrobat).resource_kind == "local_file"

        # Generic app fallback
        aw_wechat = ActiveWindow(
            app_name="微信", process_name="WeChat.exe", window_title="聊天",
        )
        assert registry.detect(aw_wechat).resource_kind == "app"

    def test_detect_resource_convenience_function(self):
        aw = ActiveWindow(
            app_name="Outlook", process_name="outlook.exe",
            window_title="项目周报 - Outlook",
        )
        result = detect_resource(aw)
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_message"
