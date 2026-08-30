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
        assert result.confidence == 80


class TestBareFileNameUnknownExtension:
    @pytest.mark.parametrize(
        "file_name",
        [
            "design.dwg",
            "mockup.psd",
            "logo.ai",
            "photo.jpg",
            "recording.mp4",
            "archive.7z",
            "database.sqlite3",
        ],
    )
    def test_probable_bare_unknown_ext_is_pathless_local_file(self, file_name):
        aw = ActiveWindow(
            app_name="Some App",
            process_name="someapp.exe",
            window_title=f"{file_name} - Some App",
        )
        result = LocalFileDetector().detect(aw)

        assert result is not None
        assert result.resource_kind == "local_file"
        assert result.resource_subtype == "unknown"
        assert result.display_name == file_name
        assert result.is_anchor is True
        assert result.path_hint is None
        assert result.identity_key.startswith("file_name:")
        assert result.confidence == 65

    def test_registry_preserves_unknown_file_instead_of_generic_app(self):
        registry = ResourceDetectorRegistry()
        registry.register(SystemDetector())
        registry.register(LocalFileDetector())
        registry.register(GenericAppDetector())
        aw = ActiveWindow(
            app_name="Photos",
            process_name="photos.exe",
            window_title="evidence.heic - Photos",
        )

        result = registry.detect(aw)

        assert result.resource_kind == "local_file"
        assert result.display_name == "evidence.heic"
        assert result.is_anchor is True

    @pytest.mark.parametrize(
        "title",
        [
            "version 1.2 - Some App",
            "v2.10 - Some App",
            "example.com - Some App",
            "https://example.com/report.pdf - Some App",
        ],
    )
    def test_dotted_non_file_titles_do_not_become_files(self, title):
        aw = ActiveWindow(
            app_name="Some App",
            process_name="someapp.exe",
            window_title=title,
        )
        assert LocalFileDetector().detect(aw) is None


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
        assert result.path_hint is None
        assert result.identity_key.startswith("file_name:")
        assert result.confidence == 80

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
        aw = ActiveWindow(
            app_name="Editor",
            process_name="editor.exe",
            window_title="config.json - Editor",
            file_path_hint=r"C:\Code\config.json",
        )
        result = LocalFileDetector().detect(aw)
        assert result is not None
        assert result.resource_subtype == "text_file"


class TestOfficeExtensionDeferral:
    @pytest.mark.parametrize("ext", [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"])
    def test_office_extension_is_deferred_with_or_without_full_path(self, ext):
        with_path = ActiveWindow(
            app_name="SomeEditor",
            process_name="someeditor.exe",
            window_title=f"file{ext} - Editor",
            file_path_hint=rf"C:\Docs\file{ext}",
        )
        without_path = ActiveWindow(
            app_name="SomeEditor",
            process_name="someeditor.exe",
            window_title=f"file{ext} - Editor",
        )
        detector = LocalFileDetector()
        assert detector.detect(with_path) is None
        assert detector.detect(without_path) is None


class TestFolderRuleWithUnknownExtension:
    def test_folder_rule_matches_dwg_full_path(self, temp_db):
        project_id = project_service.create_project("Design Project")
        folder_rule_service.create_or_update_folder_rule(r"D:\Design", project_id)
        activity_id = activity_service.create_activity(
            "AutoCAD",
            "acad.exe",
            "design.dwg - AutoCAD",
            file_path_hint=r"D:\Design\design.dwg",
            start_time="2026-06-18 09:00:00",
        )

        assignment = assign_project_for_activity(activity_id)

        assert assignment["source"] == "folder_rule"
        assert assignment["project_id"] == project_id
        assert activity_service.get_activity(activity_id)["project_id"] == project_id

    def test_folder_rule_matches_psd_full_path(self, temp_db):
        project_id = project_service.create_project("Art Project")
        folder_rule_service.create_or_update_folder_rule(r"C:\Art", project_id)
        activity_id = activity_service.create_activity(
            "Photoshop",
            "photoshop.exe",
            "mockup.psd - Photoshop",
            file_path_hint=r"C:\Art\mockup.psd",
            start_time="2026-06-18 09:00:00",
        )

        assignment = assign_project_for_activity(activity_id)

        assert assignment["source"] == "folder_rule"
        assert assignment["project_id"] == project_id
