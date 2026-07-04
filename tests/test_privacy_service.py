import pytest

pytestmark = [pytest.mark.security_privacy, pytest.mark.integration, pytest.mark.db]

from worktrace.constants import EXCLUDED_WINDOW_TITLE
from worktrace.platforms.base import ActiveWindow
from worktrace.services import folder_rule_service, privacy_service, project_service, rule_service


def _enable_excluded_project_with_keyword(keyword: str) -> int:
    """Enable the 排除规则 project and add a keyword rule. Returns the project id."""
    excluded_project = project_service.get_or_create_excluded_project()
    project_service.set_excluded_project_enabled(True)
    rule_service.create_rule(keyword, excluded_project)
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
        ActiveWindow("Word", "winword.exe", "方案.docx - Word", "D:\\客户机密\\方案.docx")
    )
    assert not privacy_service.is_excluded(ActiveWindow("Word", "winword.exe", "方案.docx - Word"))
    assert privacy_service.make_excluded_activity_payload()["file_path_hint"] is None


def test_exclude_project_keyword_and_folder_rules_match(temp_db):
    excluded_project = project_service.get_or_create_excluded_project()
    project_service.set_excluded_project_enabled(True)
    rule_service.create_rule("SuperSecret", excluded_project)
    folder_rule_service.create_or_update_folder_rule("D:\\PrivateFolder", excluded_project)

    assert privacy_service.is_excluded(ActiveWindow("Word", "word.exe", "SuperSecret plan"))
    assert privacy_service.is_excluded(
        ActiveWindow("Word", "word.exe", "Doc.docx - Word", "D:\\PrivateFolder\\Doc.docx")
    )
    assert privacy_service.is_excluded(
        ActiveWindow("Photoshop", "Photoshop.exe", "hero.psd - Adobe Photoshop", "D:\\PrivateFolder\\hero.psd")
    )


def test_disabled_exclude_project_stops_rule_matching(temp_db):
    excluded_project = project_service.get_or_create_excluded_project()
    rule_service.create_rule("DisabledSecret", excluded_project)
    project_service.set_excluded_project_enabled(False)

    assert not privacy_service.is_excluded(ActiveWindow("Word", "word.exe", "DisabledSecret plan"))


def test_excluded_project_defaults_disabled(temp_db):
    excluded_project = project_service.get_or_create_excluded_project()
    project = project_service.get_project(excluded_project)

    assert project is not None
    assert project["enabled"] == 0


def test_dedicated_excluded_toggle_clears_cache_and_controls_matching(temp_db, monkeypatch):
    excluded_project = project_service.get_or_create_excluded_project()
    rule_service.create_rule("CachedSecret", excluded_project)

    assert not privacy_service.is_excluded(ActiveWindow("Word", "word.exe", "CachedSecret"))

    clear_count = {"count": 0}
    original_clear = privacy_service.clear_exclude_rules_cache

    def clear_spy():
        clear_count["count"] += 1
        original_clear()

    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", clear_spy)

    project_service.set_excluded_project_enabled(True)
    assert clear_count["count"] == 1
    assert privacy_service.is_excluded(ActiveWindow("Word", "word.exe", "CachedSecret"))

    project_service.set_excluded_project_enabled(False)
    assert clear_count["count"] == 2
    assert not privacy_service.is_excluded(ActiveWindow("Word", "word.exe", "CachedSecret"))
