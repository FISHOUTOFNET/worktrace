from __future__ import annotations

import pytest

from worktrace.path_utils import extract_file_path_from_title

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


def test_http_url_is_not_parsed_as_windows_drive_path():
    assert extract_file_path_from_title("https://example.com/report.pdf - Some App") is None


def test_real_drive_path_still_parses_after_url_guard():
    assert (
        extract_file_path_from_title(r"Open C:\Cases\Matter A\report.pdf - Reader")
        == r"C:\Cases\Matter A\report.pdf"
    )


def test_file_url_may_still_expose_embedded_windows_path():
    assert (
        extract_file_path_from_title("file:///C:/Cases/report.pdf - Browser")
        == "C:/Cases/report.pdf"
    )
