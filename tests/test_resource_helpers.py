from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]

from worktrace.platforms.base import ActiveWindow
from worktrace.resources.resource_helpers import (
    build_path_or_name_identity,
    display_name_from_path_or_name,
    extract_file_name_from_title,
    normalize_file_name,
    normalize_for_key,
    resolve_file_candidate,
)


# extract_file_name_from_title


def test_extract_file_name_from_title_returns_last_match():
    assert extract_file_name_from_title("main.py - WorkTrace - Visual Studio Code") == "main.py"
    assert extract_file_name_from_title("合同.docx - Word") == "合同.docx"


def test_extract_file_name_from_title_returns_none_for_empty():
    assert extract_file_name_from_title(None) is None
    assert extract_file_name_from_title("") is None
    assert extract_file_name_from_title("没有文件的标题") is None


# normalize_for_key


def test_normalize_for_key_lowercases_and_keeps_at_sign():
    assert normalize_for_key("Outlook.exe") == "outlook.exe"
    assert normalize_for_key("boss@company.com") == "boss@company.com"
    assert normalize_for_key("My Project") == "my-project"


def test_normalize_for_key_empty_returns_unknown():
    assert normalize_for_key("") == "unknown"
    assert normalize_for_key("   ") == "unknown"


# build_path_or_name_identity: local path vs bare file name


def test_identity_uses_path_prefix_for_local_path():
    key = build_path_or_name_identity("D:\\Docs\\合同.docx", "office_file", "office_file_name")
    assert key.startswith("office_file:")


def test_identity_uses_name_prefix_for_bare_file_name():
    key = build_path_or_name_identity("合同.docx", "office_file", "office_file_name")
    assert key.startswith("office_file_name:")
    assert "合同.docx".casefold() in key


# display_name_from_path_or_name


def test_display_name_extracts_basename_from_path():
    assert display_name_from_path_or_name("D:\\Docs\\合同.docx") == "合同.docx"
    assert display_name_from_path_or_name("合同.docx") == "合同.docx"


# resolve_file_candidate


def test_resolve_file_candidate_prefers_hint():
    aw = ActiveWindow(
        app_name="Word",
        process_name="winword.exe",
        window_title="合同.docx - Word",
        file_path_hint="D:\\Docs\\合同.docx",
    )
    assert resolve_file_candidate(aw) == "D:\\Docs\\合同.docx"


def test_resolve_file_candidate_uses_title_path_when_no_hint():
    aw = ActiveWindow(
        app_name="Word",
        process_name="winword.exe",
        window_title="D:\\Docs\\合同.docx - Word",
    )
    assert resolve_file_candidate(aw) == "D:\\Docs\\合同.docx"


def test_resolve_file_candidate_filters_title_file_name_by_extension():
    aw = ActiveWindow(
        app_name="Word",
        process_name="winword.exe",
        window_title="合同.docx - Word",
    )
    assert resolve_file_candidate(aw, allowed_extensions=frozenset({".docx"})) == "合同.docx"
    assert resolve_file_candidate(aw, allowed_extensions=frozenset({".pdf"})) is None


def test_resolve_file_candidate_returns_none_when_nothing_found():
    aw = ActiveWindow(
        app_name="Word",
        process_name="winword.exe",
        window_title="没有文件的标题",
    )
    assert resolve_file_candidate(aw, allowed_extensions=frozenset({".docx"})) is None
