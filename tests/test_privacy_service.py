from __future__ import annotations

import pytest

from worktrace.constants import EXCLUDED_WINDOW_TITLE
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.generation_clock import generation
from worktrace.platforms.base import ActiveWindow
from worktrace.services import (
    privacy_service,
    project_service,
    rule_catalog_command_service,
    system_project_service,
)

pytestmark = [pytest.mark.security_privacy, pytest.mark.integration, pytest.mark.db]


def _enable_excluded_project_with_keyword(keyword: str) -> int:
    project_service.set_excluded_project_enabled(True)
    _rule_id, excluded_project = (
        rule_catalog_command_service.create_excluded_keyword_rule(keyword)
    )
    return excluded_project


def test_privacy_keyword_matching_and_payload(temp_db):
    _enable_excluded_project_with_keyword("银行")
    assert privacy_service.is_excluded(ActiveWindow("App", "proc.exe", "我的银行账户"))
    payload = privacy_service.make_excluded_activity_payload()
    assert payload["window_title"] == EXCLUDED_WINDOW_TITLE
    assert payload["process_name"] == "excluded"


def test_privacy_matches_file_path_hint_and_accepts_none(temp_db):
    _enable_excluded_project_with_keyword("客户机密")
    assert privacy_service.is_excluded(
        ActiveWindow(
            "Word",
            "winword.exe",
            "方案.docx - Word",
            "D:\\客户机密\\方案.docx",
        )
    )
    assert not privacy_service.is_excluded(
        ActiveWindow("Word", "winword.exe", "方案.docx - Word")
    )
    assert privacy_service.make_excluded_activity_payload()["file_path_hint"] is None


def test_exclude_project_keyword_and_folder_rules_match(temp_db):
    project_service.set_excluded_project_enabled(True)
    _keyword_id, excluded_project = (
        rule_catalog_command_service.create_excluded_keyword_rule("SuperSecret")
    )
    _folder_id, folder_project = (
        rule_catalog_command_service.create_or_update_excluded_folder_rule(
            r"D:\PrivateFolder"
        )
    )
    assert folder_project == excluded_project

    assert privacy_service.is_excluded(
        ActiveWindow("Word", "word.exe", "SuperSecret plan")
    )
    assert privacy_service.is_excluded(
        ActiveWindow(
            "Word",
            "word.exe",
            "Doc.docx - Word",
            r"D:\PrivateFolder\Doc.docx",
        )
    )
    assert privacy_service.is_excluded(
        ActiveWindow(
            "Photoshop",
            "Photoshop.exe",
            "hero.psd - Adobe Photoshop",
            r"D:\PrivateFolder\hero.psd",
        )
    )


def test_disabled_exclude_project_stops_rule_matching(temp_db):
    rule_catalog_command_service.create_excluded_keyword_rule("DisabledSecret")
    project_service.set_excluded_project_enabled(False)

    assert not privacy_service.is_excluded(
        ActiveWindow("Word", "word.exe", "DisabledSecret plan")
    )


def test_excluded_project_defaults_disabled(temp_db):
    excluded_project = system_project_service.require_excluded_project_id()
    project = project_service.get_project(excluded_project)

    assert project is not None
    assert project["enabled"] == 0


def test_excluded_toggle_refreshes_cache_via_privacy_generation(temp_db):
    rule_catalog_command_service.create_excluded_keyword_rule("CachedSecret")
    window = ActiveWindow("Word", "word.exe", "CachedSecret")

    assert not privacy_service.is_excluded(window)
    before = generation(DataGenerationNamespace.PRIVACY_CATALOG)

    project_service.set_excluded_project_enabled(True)
    after_enable = generation(DataGenerationNamespace.PRIVACY_CATALOG)
    assert after_enable == before + 1
    assert privacy_service.is_excluded(window)

    project_service.set_excluded_project_enabled(False)
    assert generation(DataGenerationNamespace.PRIVACY_CATALOG) == after_enable + 1
    assert not privacy_service.is_excluded(window)
