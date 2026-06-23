from __future__ import annotations

from worktrace.constants import (
    EXCLUDED_APP_NAME,
    EXCLUDED_PROCESS_NAME,
    EXCLUDED_WINDOW_TITLE,
    PRIVACY_NOTICE_TEXT,
    STATUS_EXCLUDED,
)
from worktrace.services import activity_service
from worktrace.services.resource_service import get_resource_for_activity


class TestExcludedResourcePrivacy:
    """5. Excluded records do not export real resource_path_hint / uri_host / display_name."""

    def test_excluded_resource_is_anonymous(self, temp_db):
        aid = activity_service.create_activity(
            "已排除", "excluded", "已排除窗口",
            status=STATUS_EXCLUDED,
            start_time="2026-06-18 09:00:00",
        )
        resource = get_resource_for_activity(aid)
        assert resource is not None
        assert resource["resource_kind"] == "system"
        assert resource["resource_subtype"] == "excluded"
        assert resource["display_name"] == EXCLUDED_APP_NAME
        assert resource["app_name"] == EXCLUDED_APP_NAME
        assert resource["process_name"] == EXCLUDED_PROCESS_NAME
        assert resource["window_title"] == EXCLUDED_WINDOW_TITLE
        assert resource["path_hint"] is None
        assert resource["uri_host"] is None

    def test_excluded_activity_no_real_path_in_get(self, temp_db):
        aid = activity_service.create_activity(
            "已排除", "excluded", "已排除窗口",
            status=STATUS_EXCLUDED,
            start_time="2026-06-18 09:00:00",
        )
        activity = activity_service.get_activity(aid)
        assert activity["resource_kind"] == "system"
        assert activity["resource_subtype"] == "excluded"
        assert activity["resource_display_name"] == EXCLUDED_APP_NAME
        assert activity["resource_path_hint"] is None or activity["resource_path_hint"] == ""
        assert activity["resource_uri_host"] is None or activity["resource_uri_host"] == ""


class TestPrivacyNoticeContent:
    """6. Privacy notice includes email/webpage/IDE boundary description."""

    def test_mentions_email(self):
        assert "邮件" in PRIVACY_NOTICE_TEXT

    def test_mentions_email_body_excluded(self):
        assert "邮件正文" in PRIVACY_NOTICE_TEXT

    def test_mentions_browser(self):
        assert "浏览器" in PRIVACY_NOTICE_TEXT

    def test_mentions_webpage_body_excluded(self):
        assert "网页正文" in PRIVACY_NOTICE_TEXT

    def test_mentions_ide(self):
        assert "IDE" in PRIVACY_NOTICE_TEXT

    def test_mentions_code_file_body_excluded(self):
        assert "代码文件正文" in PRIVACY_NOTICE_TEXT

    def test_mentions_browser_history_excluded(self):
        assert "浏览器历史" in PRIVACY_NOTICE_TEXT

    def test_mentions_excluded_rule_effect(self):
        assert "排除规则" in PRIVACY_NOTICE_TEXT
        assert "已排除窗口" in PRIVACY_NOTICE_TEXT

    def test_mentions_no_screenshot(self):
        assert "截图" in PRIVACY_NOTICE_TEXT
        assert "录屏" in PRIVACY_NOTICE_TEXT

    def test_mentions_no_keyboard_input(self):
        assert "键盘输入" in PRIVACY_NOTICE_TEXT
