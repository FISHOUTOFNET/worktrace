from worktrace.constants import EXCLUDED_WINDOW_TITLE
from worktrace.platforms.base import ActiveWindow
from worktrace.services import privacy_service


def test_privacy_keyword_matching_and_payload(temp_db):
    privacy_service.set_exclude_keywords(["银行"])
    assert privacy_service.is_excluded(ActiveWindow("App", "proc.exe", "我的银行账户"))
    payload = privacy_service.make_excluded_activity_payload()
    assert payload["window_title"] == EXCLUDED_WINDOW_TITLE
    assert payload["process_name"] == "excluded"
