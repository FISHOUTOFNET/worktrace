from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]

from worktrace.platforms.base import ActiveWindow
from worktrace.resources.detectors import (
    GenericAppDetector,
    ResourceDetectorRegistry,
    SystemDetector,
    detect_resource,
)
from worktrace.resources.local_file_detector import LocalFileDetector
from worktrace.resources.office_wps_detector import OfficeWpsDetector


# 1. winword.exe + 合同.docx -> office_document/word_document

class TestOfficeWpsDetector:
    def test_winword_docx_with_path_hint(self):
        aw = ActiveWindow(
            app_name="winword.exe",
            process_name="winword.exe",
            window_title="合同.docx - Word",
            file_path_hint="D:\\Docs\\合同.docx",
        )
        detector = OfficeWpsDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "word_document"
        assert result.display_name == "合同.docx"
        assert result.is_anchor is True
        assert result.identity_key.startswith("office_file:")
        assert result.path_hint == "D:\\Docs\\合同.docx"

    def test_winword_docx_title_only(self):
        aw = ActiveWindow(
            app_name="winword.exe",
            process_name="winword.exe",
            window_title="合同.docx - Word",
        )
        detector = OfficeWpsDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "word_document"
        assert result.display_name == "合同.docx"

    # 2. excel.exe + 表.xlsx -> office_document/spreadsheet
    def test_excel_xlsx(self):
        aw = ActiveWindow(
            app_name="excel.exe",
            process_name="excel.exe",
            window_title="费用表.xlsx - Excel",
            file_path_hint="D:\\Work\\费用表.xlsx",
        )
        detector = OfficeWpsDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "spreadsheet"
        assert result.display_name == "费用表.xlsx"

    # 3. wps.exe + .docx -> office_document/word_document, display_name not wps.exe
    def test_wps_docx_path_hint(self):
        aw = ActiveWindow(
            app_name="wps.exe",
            process_name="wps.exe",
            window_title="合同审查意见.docx - WPS",
            file_path_hint="D:\\ClientA\\合同审查意见.docx",
        )
        detector = OfficeWpsDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "word_document"
        assert result.display_name == "合同审查意见.docx"
        assert result.display_name != "wps.exe"

    # 4. wps.exe + .xlsx -> spreadsheet
    def test_wps_xlsx_path_hint(self):
        aw = ActiveWindow(
            app_name="et.exe",
            process_name="et.exe",
            window_title="数据表.xlsx - WPS",
            file_path_hint="D:\\Work\\数据表.xlsx",
        )
        detector = OfficeWpsDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "spreadsheet"
        assert result.display_name == "数据表.xlsx"

    def test_kwps_docx(self):
        aw = ActiveWindow(
            app_name="kwps.exe",
            process_name="kwps.exe",
            window_title="报告.docx - WPS",
            file_path_hint="D:\\Docs\\报告.docx",
        )
        detector = OfficeWpsDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "word_document"

    def test_powerpoint_pptx(self):
        aw = ActiveWindow(
            app_name="powerpnt.exe",
            process_name="powerpnt.exe",
            window_title="答辩材料.pptx - PowerPoint",
            file_path_hint="D:\\Slides\\答辩材料.pptx",
        )
        detector = OfficeWpsDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "presentation"

    def test_non_office_process_returns_none(self):
        aw = ActiveWindow(
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="Search",
        )
        detector = OfficeWpsDetector()
        assert detector.detect(aw) is None

    def test_office_without_file_returns_none(self):
        aw = ActiveWindow(
            app_name="winword.exe",
            process_name="winword.exe",
            window_title="Word",
        )
        detector = OfficeWpsDetector()
        assert detector.detect(aw) is None

    def test_wps_title_only_docx(self):
        aw = ActiveWindow(
            app_name="wps.exe",
            process_name="wps.exe",
            window_title="汇报材料.docx - WPS 文字",
        )
        detector = OfficeWpsDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "word_document"
        assert result.display_name == "汇报材料.docx"
        assert result.display_name != "wps.exe"


# 5. .py file -> local_file/code_file

class TestLocalFileDetector:
    def test_py_file_with_path(self):
        aw = ActiveWindow(
            app_name="Code.exe",
            process_name="Code.exe",
            window_title="main.py - Visual Studio Code",
            file_path_hint="D:\\Repo\\WorkTrace\\main.py",
        )
        detector = LocalFileDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "code_file"
        assert result.display_name == "main.py"
        assert result.is_anchor is True
        assert result.identity_key.startswith("file_path:")

    def test_js_file(self):
        aw = ActiveWindow(
            app_name="Code.exe",
            process_name="Code.exe",
            window_title="app.js - Visual Studio Code",
            file_path_hint="D:\\Project\\app.js",
        )
        detector = LocalFileDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "code_file"

    # 6. .pdf file -> local_file/pdf
    def test_pdf_file(self):
        aw = ActiveWindow(
            app_name="Acrobat.exe",
            process_name="acrobat.exe",
            window_title="产品实际结构.pdf - Adobe Acrobat",
            file_path_hint="D:\\Docs\\产品实际结构.pdf",
        )
        detector = LocalFileDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "pdf"
        assert result.display_name == "产品实际结构.pdf"

    def test_md_file(self):
        aw = ActiveWindow(
            app_name="Code.exe",
            process_name="Code.exe",
            window_title="README.md - Visual Studio Code",
            file_path_hint="D:\\Project\\README.md",
        )
        detector = LocalFileDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "markdown_file"

    def test_csv_file(self):
        aw = ActiveWindow(
            app_name="excel.exe",
            process_name="excel.exe",
            window_title="data.csv - Excel",
            file_path_hint="D:\\Data\\data.csv",
        )
        # CSV is in both OfficeWpsDetector and LocalFileDetector extensions.
        # OfficeWpsDetector runs first and should claim it.
        office_detector = OfficeWpsDetector()
        result = office_detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "spreadsheet"

    def test_non_local_file_returns_none(self):
        aw = ActiveWindow(
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="Search",
        )
        detector = LocalFileDetector()
        assert detector.detect(aw) is None

    def test_office_extension_not_handled_by_local_file(self):
        aw = ActiveWindow(
            app_name="winword.exe",
            process_name="winword.exe",
            window_title="合同.docx - Word",
            file_path_hint="D:\\Docs\\合同.docx",
        )
        detector = LocalFileDetector()
        result = detector.detect(aw)
        # .docx is not in _LOCAL_FILE_EXTENSIONS, so LocalFileDetector should return None
        assert result is None

    def test_title_only_py_file(self):
        aw = ActiveWindow(
            app_name="Code.exe",
            process_name="Code.exe",
            window_title="utils.py - Visual Studio Code",
        )
        detector = LocalFileDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "code_file"
        assert result.display_name == "utils.py"


# 7. No file info -> generic_app fallback

class TestRegistryWithFileDetectors:
    def test_registry_order(self):
        registry = ResourceDetectorRegistry()
        registry.register(SystemDetector())
        registry.register(OfficeWpsDetector())
        registry.register(LocalFileDetector())
        registry.register(GenericAppDetector())

        # System detector catches idle
        aw_idle = ActiveWindow(app_name="空闲", process_name="idle", window_title="用户空闲")
        result = registry.detect(aw_idle)
        assert result.resource_kind == "system"

        # Office detector catches winword
        aw_word = ActiveWindow(
            app_name="winword.exe", process_name="winword.exe",
            window_title="合同.docx - Word",
            file_path_hint="D:\\Docs\\合同.docx",
        )
        result = registry.detect(aw_word)
        assert result.resource_kind == "office_document"

        # Local file detector catches .py
        aw_py = ActiveWindow(
            app_name="Code.exe", process_name="Code.exe",
            window_title="main.py - VS Code",
            file_path_hint="D:\\Repo\\main.py",
        )
        result = registry.detect(aw_py)
        assert result.resource_kind == "local_file"

        # Generic app fallback
        aw_chat = ActiveWindow(app_name="微信", process_name="WeChat.exe", window_title="聊天")
        result = registry.detect(aw_chat)
        assert result.resource_kind == "app"
        assert result.resource_subtype == "generic_app"

    def test_detect_resource_convenience(self):
        aw = ActiveWindow(
            app_name="winword.exe",
            process_name="winword.exe",
            window_title="合同.docx - Word",
            file_path_hint="D:\\Docs\\合同.docx",
        )
        result = detect_resource(aw)
        assert result.resource_kind == "office_document"
        assert result.resource_subtype == "word_document"
        assert result.display_name == "合同.docx"
