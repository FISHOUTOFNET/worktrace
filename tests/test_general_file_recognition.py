from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]

from worktrace.platforms.base import ActiveWindow
from worktrace.resources.browser_detector import BrowserDetector
from worktrace.resources.detectors import detect_resource
from worktrace.resources.ide_detector import IdeDetector


def test_browser_title_only_pdf_remains_browser_page():
    active = ActiveWindow(
        app_name="Edge",
        process_name="msedge.exe",
        window_title="report.pdf - Microsoft Edge",
    )

    result = detect_resource(active)

    assert result.resource_kind == "browser_tab"
    assert result.display_name == "report.pdf"


def test_browser_with_authoritative_local_path_defers_to_local_file():
    active = ActiveWindow(
        app_name="Edge",
        process_name="msedge.exe",
        window_title="report.pdf - Microsoft Edge",
        file_path_hint=r"D:\Cases\report.pdf",
    )

    assert BrowserDetector().detect(active) is None
    result = detect_resource(active)
    assert result.resource_kind == "local_file"
    assert result.resource_subtype == "pdf"
    assert result.display_name == "report.pdf"
    assert result.path_hint == r"D:\Cases\report.pdf"


@pytest.mark.parametrize("file_name", ["Dockerfile", "README", ".env", ".gitignore"])
def test_ide_recognizes_extensionless_and_dotfiles(file_name):
    active = ActiveWindow(
        app_name="Visual Studio Code",
        process_name="Code.exe",
        window_title=f"{file_name} - WorkTrace - Visual Studio Code",
    )

    result = IdeDetector().detect(active)

    assert result is not None
    assert result.resource_kind == "ide_file"
    assert result.resource_subtype == "code_file"
    assert result.display_name == file_name
    assert result.is_anchor is True


def test_ide_defers_non_code_probable_file_to_local_file_detector():
    active = ActiveWindow(
        app_name="Visual Studio Code",
        process_name="Code.exe",
        window_title="evidence.jpg - WorkTrace - Visual Studio Code",
    )

    assert IdeDetector().detect(active) is None
    result = detect_resource(active)
    assert result.resource_kind == "local_file"
    assert result.resource_subtype == "unknown"
    assert result.display_name == "evidence.jpg"


def test_ide_defers_authoritative_non_code_path_to_local_file_detector():
    active = ActiveWindow(
        app_name="Visual Studio Code",
        process_name="Code.exe",
        window_title="evidence.psd - WorkTrace - Visual Studio Code",
        file_path_hint=r"D:\Cases\evidence.psd",
    )

    assert IdeDetector().detect(active) is None
    result = detect_resource(active)
    assert result.resource_kind == "local_file"
    assert result.path_hint == r"D:\Cases\evidence.psd"
