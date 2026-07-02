from __future__ import annotations

import pytest

from worktrace.constants import EXCLUDED_APP_NAME, EXCLUDED_PROCESS_NAME, EXCLUDED_WINDOW_TITLE, STATUS_EXCLUDED
from worktrace.resources.types import DetectedResource
from worktrace.services import activity_service
from worktrace.services.resource_service import (
    attach_resource,
    create_or_update_activity_resource,
    get_resource_for_activity,
)


# 1. create_activity writes activity_resource synchronously

class TestCreateActivityWritesResource:
    def test_normal_activity_creates_resource(self, temp_db):
        aid = activity_service.create_activity(
            "微信", "WeChat.exe", "聊天",
            start_time="2026-06-23 09:00:00",
        )
        resource = get_resource_for_activity(aid)
        assert resource is not None
        assert resource["resource_kind"] == "app"
        assert resource["resource_subtype"] == "generic_app"
        assert resource["display_name"] == "微信"

    def test_idle_activity_creates_system_resource(self, temp_db):
        aid = activity_service.create_activity(
            "空闲", "idle", "用户空闲",
            status="idle",
            start_time="2026-06-23 10:00:00",
        )
        resource = get_resource_for_activity(aid)
        assert resource is not None
        assert resource["resource_kind"] == "system"
        assert resource["resource_subtype"] == "idle"

    def test_explicit_resource_parameter(self, temp_db):
        custom = DetectedResource(
            resource_kind="office_document",
            resource_subtype="word_document",
            display_name="合同.docx",
            identity_key="file:合同.docx",
            is_anchor=True,
            confidence=90,
            source="test",
            app_name="Word",
            process_name="winword.exe",
            window_title="合同.docx - Word",
            path_hint="D:\\Docs\\合同.docx",
        )
        aid = activity_service.create_activity(
            "Word", "winword.exe", "合同.docx - Word",
            resource=custom,
            start_time="2026-06-23 11:00:00",
        )
        resource = get_resource_for_activity(aid)
        assert resource is not None
        assert resource["resource_kind"] == "office_document"
        assert resource["resource_subtype"] == "word_document"
        assert resource["display_name"] == "合同.docx"
        assert resource["is_anchor"] == 1


# 2. get_activity returns resource_* fields

class TestGetActivityReturnsResourceFields:
    def test_get_activity_includes_resource_fields(self, temp_db):
        aid = activity_service.create_activity(
            "微信", "WeChat.exe", "聊天",
            start_time="2026-06-23 09:00:00",
        )
        activity = activity_service.get_activity(aid)
        assert activity is not None
        assert activity["resource_kind"] == "app"
        assert activity["resource_display_name"] == "微信"
        assert activity["resource_identity_key"].startswith("app:")

    def test_get_activity_includes_resource_fields(self, temp_db):
        aid = activity_service.create_activity(
            "微信", "WeChat.exe", "聊天",
            start_time="2026-06-23 09:00:00",
        )
        activity = activity_service.get_activity(aid)
        assert activity is not None
        assert activity["activity_display_name"] == "微信"
        assert activity["activity_identity_key"] == activity["resource_identity_key"]
        assert activity["resource_is_anchor"] is False
        assert activity["resource_path_hint"] is None

    def test_get_activities_by_range_includes_resource(self, temp_db):
        activity_service.create_activity(
            "WeChat", "WeChat.exe", "Chat",
            start_time="2026-06-23 09:00:00",
        )
        activities = activity_service.get_activities_by_range("2026-06-23", "2026-06-23")
        assert len(activities) >= 1
        first = activities[0]
        assert "resource_kind" in first
        assert first["resource_kind"] == "app"


# 3. Excluded records do not save real resource metadata

class TestExcludedResourcePrivacy:
    def test_excluded_activity_uses_anonymous_resource(self, temp_db):
        aid = activity_service.create_activity(
            "已排除", "excluded", "已排除窗口",
            status=STATUS_EXCLUDED,
            start_time="2026-06-23 09:00:00",
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


# 4. Duplicate create_or_update does not create duplicate rows

class TestNoDuplicateResourceRows:
    def test_upsert_does_not_duplicate(self, temp_db):
        aid = activity_service.create_activity(
            "Chrome", "chrome.exe", "Search",
            start_time="2026-06-23 09:00:00",
        )
        r1 = DetectedResource(
            resource_kind="app",
            resource_subtype="generic_app",
            display_name="Chrome",
            identity_key="app:chrome.exe",
            is_anchor=False,
            confidence=50,
            source="test",
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="Search",
        )
        create_or_update_activity_resource(aid, r1)

        from worktrace.db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) AS cnt FROM activity_resource WHERE activity_id = ?",
                (aid,),
            ).fetchone()
        assert rows["cnt"] == 1

    def test_upsert_updates_existing(self, temp_db):
        aid = activity_service.create_activity(
            "Chrome", "chrome.exe", "Search",
            start_time="2026-06-23 09:00:00",
        )
        updated = DetectedResource(
            resource_kind="browser_tab",
            resource_subtype="browser_page",
            display_name="Google Search",
            identity_key="app:chrome.exe",
            is_anchor=False,
            confidence=80,
            source="updated_detector",
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="Search",
        )
        create_or_update_activity_resource(aid, updated)

        resource = get_resource_for_activity(aid)
        assert resource["resource_kind"] == "browser_tab"
        assert resource["resource_subtype"] == "browser_page"
        assert resource["display_name"] == "Google Search"
        assert resource["confidence"] == 80
