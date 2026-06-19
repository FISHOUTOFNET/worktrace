from worktrace.constants import EXCLUDED_WINDOW_TITLE
from worktrace.platforms.base import ActiveWindow
from worktrace.services import privacy_service


def test_privacy_keyword_matching_and_payload(temp_db):
    privacy_service.set_exclude_keywords(["银行"])
    assert privacy_service.is_excluded(ActiveWindow("App", "proc.exe", "我的银行账户"))
    payload = privacy_service.make_excluded_activity_payload()
    assert payload["window_title"] == EXCLUDED_WINDOW_TITLE
    assert payload["process_name"] == "excluded"


def test_privacy_matches_file_path_hint_and_accepts_none(temp_db):
    privacy_service.set_exclude_keywords(["客户机密"])
    assert privacy_service.is_excluded(
        ActiveWindow("Word", "winword.exe", "方案.docx - Word", "D:\\客户机密\\方案.docx")
    )
    assert not privacy_service.is_excluded(ActiveWindow("Word", "winword.exe", "方案.docx - Word"))
    assert privacy_service.make_excluded_activity_payload()["file_path_hint"] is None


def test_privacy_keyword_cache_reuses_reads_and_updates_on_set(temp_db, monkeypatch):
    privacy_service.set_exclude_keywords(["银行"])
    privacy_service.clear_exclude_keywords_cache()
    original = privacy_service.get_list_setting
    calls = {"count": 0}

    def counted_list_setting(key, default=None):
        calls["count"] += 1
        return original(key, default)

    monkeypatch.setattr(privacy_service, "get_list_setting", counted_list_setting)

    assert privacy_service.get_exclude_keywords() == ["银行"]
    assert privacy_service.get_exclude_keywords() == ["银行"]
    assert calls["count"] == 1

    privacy_service.set_exclude_keywords(["客户机密"])
    assert privacy_service.is_excluded(ActiveWindow("Word", "word.exe", "D:\\客户机密\\方案.docx"))
    assert calls["count"] == 1
