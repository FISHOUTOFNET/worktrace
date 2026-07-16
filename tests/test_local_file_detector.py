from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

from tests.support import activity_factory as activity_service
from worktrace.platforms.base import ActiveWindow
from worktrace.resources.detectors import (
    GenericAppDetector,
    ResourceDetectorRegistry,
    SystemDetector,
)
from worktrace.resources.local_file_detector import LocalFileDetector
from worktrace.services import folder_rule_service, project_service
from worktrace.services.project_inference_service import assign_project_for_activity


# Full local path with non-whitelisted extension -> local_file anchor

class TestFullLocalPathUnknownExtension:
    @pytest.mark.parametrize(
        "file_path,window_title,app_name,process_name",
        [
            (r"C:\Cases\A\design.dwg", "design.dwg - AutoCAD", "AutoCAD", "acad.exe"),
            (r"C:\Cases\A\mockup.psd", "mockup.psd - Photoshop", "Photoshop", "photoshop.exe"),
            (r"C:\Cases\A\logo.ai", "logo.ai - Illustrator", "Illustrator", "illustrator.exe"),
            (r"C:\Cases\A\book.indd", "book.indd - InDesign", "InDesign", "indesign.exe"),
            (r"C:\Cases\A\part.sldprt", "part.sldprt - SolidWorks", "SolidWorks", "sldworks.exe"),
            (r"C:\Cases\A\render.png", "render.png - Photos", "Photos", "photos.exe"),
            (r"C:\Cases\A\photo.jpg", "photo.jpg - Photos", "Photos", "photos.exe"),
            (r"C:\Cases\A\archive.zip", "archive.zip - Explorer", "Explorer", "explorer.exe"),
        ],
    )
    def test_full_path_unknown_ext_is_local_file_anchor(
        self, file_path, window_title, app_name, process_name
    ):
        aw = ActiveWindow(
            app_name=app_name,
            process_name=process_name,
            window_title=window_title,
            file_path_hint=file_path,
        )
        result = LocalFileDetector().detect(aw)

        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "unknown"
        assert result.is_anchor is True
        assert result.path_hint == file_path
        assert result.identity_key.startswith("file_path:")

    def test_dwg_full_path_identity_is_path_based(self):
        aw = ActiveWindow(
            app_name="AutoCAD",
            process_name="acad.exe",
            window_title="design.dwg - AutoCAD",
            file_path_hint=r"C:\Cases\A\design.dwg",
        )
        result = LocalFileDetector().detect(aw)
        assert result is not None
        # Path-based identity must differ from a bare-name identity.
        assert result.identity_key.startswith("file_path:")
        assert "file_name:" not in result.identity_key

    def test_psd_full_path_anchor(self):
        aw = ActiveWindow(
            app_name="Photoshop",
            process_name="photoshop.exe",
            window_title="mockup.psd - Photoshop",
            file_path_hint=r"C:\Cases\A\mockup.psd",
        )
        result = LocalFileDetector().detect(aw)
        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "unknown"
        assert result.is_anchor is True
        assert result.path_hint == r"C:\Cases\A\mockup.psd"


# Bare file name with unknown extension -> NOT local_file

class TestBareFileNameUnknownExtension:
    def test_bare_unknown_ext_not_detected_by_local_file_detector(self):
        aw = ActiveWindow(
            app_name="Some App",
            process_name="someapp.exe",
            window_title="design.dwg - Some App",
        )
        assert LocalFileDetector().detect(aw) is None

    def test_bare_unknown_ext_falls_back_to_generic_app_in_registry(self):
        registry = ResourceDetectorRegistry()
        registry.register(SystemDetector())
        registry.register(LocalFileDetector())
        registry.register(GenericAppDetector())
        aw = ActiveWindow(
            app_name="Some App",
            process_name="someapp.exe",
            window_title="design.dwg - Some App",
        )
        result = registry.detect(aw)
        assert result.resource_kind == "app"
        assert result.resource_subtype == "generic_app"
        assert result.is_anchor is False


# Existing whitelist behavior preserved

class TestWhitelistPreserved:
    def test_full_path_pdf_still_pdf(self):
        aw = ActiveWindow(
            app_name="Reader",
            process_name="acrobat.exe",
            window_title="report.pdf - Reader",
            file_path_hint=r"C:\Reports\report.pdf",
        )
        result = LocalFileDetector().detect(aw)
        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "pdf"
        assert result.is_anchor is True
        assert result.path_hint == r"C:\Reports\report.pdf"

    def test_bare_pdf_name_still_pdf(self):
        aw = ActiveWindow(
            app_name="Reader",
            process_name="acrobat.exe",
            window_title="report.pdf - Reader",
        )
        result = LocalFileDetector().detect(aw)
        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "pdf"
        assert result.is_anchor is True
        # Bare name -> no path_hint, name-based identity.
        assert result.path_hint is None
        assert result.identity_key.startswith("file_name:")

    @pytest.mark.parametrize(
        "file_path,expected_subtype",
        [
            (r"C:\Notes\readme.txt", "text_file"),
            (r"C:\Notes\guide.md", "markdown_file"),
            (r"C:\Data\export.csv", "csv_file"),
            (r"C:\Code\main.py", "code_file"),
            (r"C:\Code\app.ts", "code_file"),
        ],
    )
    def test_known_extensions_keep_subtypes(self, file_path, expected_subtype):
        aw = ActiveWindow(
            app_name="Editor",
            process_name="editor.exe",
            window_title="file - Editor",
            file_path_hint=file_path,
        )
        result = LocalFileDetector().detect(aw)
        assert result is not None
        assert result.resource_subtype == expected_subtype

    def test_whitelisted_other_extension_full_path_is_text_file(self):
        # .json is whitelisted but has no dedicated subtype -> text_file.
        aw = ActiveWindow(
            app_name="Editor",
            process_name="editor.exe",
            window_title="config.json - Editor",
            file_path_hint=r"C:\Code\config.json",
        )
        result = LocalFileDetector().detect(aw)
        assert result is not None
        assert result.resource_subtype == "text_file"


# Office document extensions are deferred to OfficeWpsDetector / FallbackFileDetector

class TestOfficeExtensionDeferral:
    @pytest.mark.parametrize("ext", [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"])
    def test_office_extension_full_path_deferred(self, ext):
        # Office extensions have dedicated detectors with specific subtypes
        # (word_document, spreadsheet, presentation). LocalFileDetector must
        # defer them so they don't degrade to "unknown".
        aw = ActiveWindow(
            app_name="SomeEditor",
            process_name="someeditor.exe",
            window_title=f"file{ext} - Editor",
            file_path_hint=rf"C:\Docs\file{ext}",
        )
        assert LocalFileDetector().detect(aw) is None


# Folder rule inference for unknown-extension full paths

class TestFolderRuleWithUnknownExtension:
    def test_folder_rule_matches_dwg_full_path(self, temp_db):
        pid = project_service.create_project("Design Project")
        folder_rule_service.create_or_update_folder_rule(r"D:\Design", pid)
        aid = activity_service.create_activity(
            "AutoCAD",
            "acad.exe",
            "design.dwg - AutoCAD",
            file_path_hint=r"D:\Design\design.dwg",
            start_time="2026-06-18 09:00:00",
        )

        assignment = assign_project_for_activity(aid)

        assert assignment["source"] == "folder_rule"
        assert assignment["project_id"] == pid
        assert activity_service.get_activity(aid)["project_id"] == pid

    def test_folder_rule_matches_psd_full_path(self, temp_db):
        pid = project_service.create_project("Art Project")
        folder_rule_service.create_or_update_folder_rule(r"C:\Art", pid)
        aid = activity_service.create_activity(
            "Photoshop",
            "photoshop.exe",
            "mockup.psd - Photoshop",
            file_path_hint=r"C:\Art\mockup.psd",
            start_time="2026-06-18 09:00:00",
        )

        assignment = assign_project_for_activity(aid)

        assert assignment["source"] == "folder_rule"
        assert assignment["project_id"] == pid

    def test_folder_rule_matches_nested_unknown_ext_full_path(self, temp_db):
        pid = project_service.create_project("Engineering")
        folder_rule_service.create_or_update_folder_rule(r"D:\Engineering", pid)
        aid = activity_service.create_activity(
            "SolidWorks",
            "sldworks.exe",
            "bracket.sldprt - SolidWorks",
            file_path_hint=r"D:\Engineering\Assembly\bracket.sldprt",
            start_time="2026-06-18 09:00:00",
        )

        assignment = assign_project_for_activity(aid)

        assert assignment["source"] == "folder_rule"
        assert assignment["project_id"] == pid
