from __future__ import annotations

import json

import pytest

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import (
    EXCLUDED_APP_NAME,
    EXCLUDED_PROCESS_NAME,
    EXCLUDED_WINDOW_TITLE,
    STATUS_EXCLUDED,
)
from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow
from worktrace.resources.email_detector import EmailDetector
from worktrace.resources.ide_detector import IdeDetector
from worktrace.resources.types import DetectedResource
from worktrace.services import activity_service, privacy_service, settings_service
from worktrace.services.project_inference_service import (
    assign_project_for_activity,
    candidate_project_name_for_resource,
)
from worktrace.services.resource_service import (
    create_or_update_activity_resource,
    get_resource_for_activity,
)


# ---------------------------------------------------------------------------
# 1. Excluded resource is forced anonymous even when a real resource is passed
# ---------------------------------------------------------------------------


class TestExcludedResourceForcedAnonymous:
    def test_excluded_resource_forced_anonymous_even_when_resource_passed(self, temp_db):
        real_resource = DetectedResource(
            resource_kind="office_document",
            resource_subtype="word_document",
            display_name="机密合同.docx",
            identity_key="office_file:d:\\secret\\机密合同.docx",
            is_anchor=True,
            confidence=90,
            source="test",
            app_name="Word",
            process_name="winword.exe",
            window_title="机密合同.docx - Word",
            path_hint="D:\\secret\\机密合同.docx",
        )
        aid = activity_service.create_activity(
            "Word",
            "winword.exe",
            "机密合同.docx - Word",
            status=STATUS_EXCLUDED,
            resource=real_resource,
            start_time="2026-06-24 09:00:00",
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
        assert resource["metadata_json"] is None

    def test_create_or_update_activity_resource_anonymizes_excluded(self, temp_db):
        aid = activity_service.create_activity(
            "已排除",
            "excluded",
            "已排除窗口",
            status=STATUS_EXCLUDED,
            start_time="2026-06-24 09:00:00",
        )
        real_resource = DetectedResource(
            resource_kind="browser_tab",
            resource_subtype="browser_page",
            display_name="Secret Bank",
            identity_key="browser_host_title:secretbank.com:secret-bank",
            is_anchor=True,
            confidence=75,
            source="browser_detector",
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="Secret Bank - Google Chrome",
            uri_host="secretbank.com",
        )
        create_or_update_activity_resource(aid, real_resource)
        resource = get_resource_for_activity(aid)
        assert resource is not None
        assert resource["resource_kind"] == "system"
        assert resource["resource_subtype"] == "excluded"
        assert resource["display_name"] == EXCLUDED_APP_NAME
        assert resource["app_name"] == EXCLUDED_APP_NAME
        assert resource["uri_host"] is None
        assert resource["path_hint"] is None


# ---------------------------------------------------------------------------
# 2. privacy_service.is_resource_excluded
# ---------------------------------------------------------------------------


class TestResourceExclusion:
    def test_resource_exclusion_browser_host(self, temp_db):
        privacy_service.set_exclude_keywords(["secretbank.com"])
        resource = DetectedResource(
            resource_kind="browser_tab",
            resource_subtype="browser_page",
            display_name="Secret Bank",
            identity_key="browser_host_title:secretbank.com:secret-bank",
            is_anchor=True,
            confidence=75,
            source="browser_detector",
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="Secret Bank - Google Chrome",
            uri_host="secretbank.com",
        )
        assert privacy_service.is_resource_excluded(resource) is True

        safe_resource = DetectedResource(
            resource_kind="browser_tab",
            resource_subtype="browser_page",
            display_name="GitHub",
            identity_key="browser_host_title:github.com:github",
            is_anchor=True,
            confidence=75,
            source="browser_detector",
            app_name="Chrome",
            process_name="chrome.exe",
            window_title="GitHub - Google Chrome",
            uri_host="github.com",
        )
        assert privacy_service.is_resource_excluded(safe_resource) is False

    def test_resource_exclusion_email_title(self, temp_db):
        privacy_service.set_exclude_keywords(["机密邮件"])
        resource = DetectedResource(
            resource_kind="email",
            resource_subtype="email_message",
            display_name="机密邮件主题",
            identity_key="email_subject:机密邮件主题|outlook.exe",
            is_anchor=True,
            confidence=80,
            source="email_detector",
            app_name="Outlook",
            process_name="outlook.exe",
            window_title="机密邮件主题 - Outlook",
        )
        assert privacy_service.is_resource_excluded(resource) is True

    def test_resource_exclusion_ide_workspace(self, temp_db):
        privacy_service.set_exclude_keywords(["SecretProject"])
        resource = DetectedResource(
            resource_kind="ide_file",
            resource_subtype="ide_workspace",
            display_name="SecretProject",
            identity_key="ide_workspace:code.exe:secretproject",
            is_anchor=True,
            confidence=60,
            source="ide_detector",
            app_name="VS Code",
            process_name="Code.exe",
            window_title="SecretProject - Visual Studio Code",
        )
        assert privacy_service.is_resource_excluded(resource) is True

    def test_collector_anonymizes_resource_with_excluded_browser_host(self, temp_db):
        privacy_service.set_exclude_keywords(["secretbank.com"])
        machine = CollectorStateMachine()
        machine.transition_to(
            "recording",
            ActiveWindow(
                "Chrome",
                "chrome.exe",
                "secretbank.com - Google Chrome",
            ),
            at_time="2026-06-24 09:00:00",
        )
        machine.transition_to(
            "recording",
            ActiveWindow(
                "Chrome",
                "chrome.exe",
                "secretbank.com - Google Chrome",
            ),
            at_time="2026-06-24 09:01:00",
        )
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM activity_log WHERE status = 'excluded' LIMIT 1"
            ).fetchone()
        assert row is not None
        resource = get_resource_for_activity(int(row["id"]))
        assert resource is not None
        assert resource["resource_kind"] == "system"
        assert resource["resource_subtype"] == "excluded"
        assert resource["display_name"] == EXCLUDED_APP_NAME
        assert resource["uri_host"] is None


# ---------------------------------------------------------------------------
# 3. EmailDetector detects email_file from window_title .eml/.msg
# ---------------------------------------------------------------------------


class TestEmailFileFromWindowTitle:
    def test_outlook_eml_file_from_title(self):
        aw = ActiveWindow(
            app_name="Outlook",
            process_name="outlook.exe",
            window_title="通知.eml - Outlook",
        )
        detector = EmailDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_file"
        assert result.display_name == "通知.eml"
        assert result.identity_key.startswith("email_file_name:")
        assert result.path_hint is None
        assert result.is_anchor is True

    def test_outlook_msg_file_from_title(self):
        aw = ActiveWindow(
            app_name="Outlook",
            process_name="outlook.exe",
            window_title="合同.msg - Outlook",
        )
        detector = EmailDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_file"
        assert result.display_name == "合同.msg"
        assert result.identity_key.startswith("email_file_name:")
        assert result.path_hint is None

    def test_non_email_process_eml_file_from_title(self):
        aw = ActiveWindow(
            app_name="Explorer",
            process_name="explorer.exe",
            window_title="通知.eml",
        )
        detector = EmailDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_file"
        assert result.display_name == "通知.eml"
        assert result.identity_key.startswith("email_file_name:")
        assert result.path_hint is None

    def test_eml_file_with_full_path_still_uses_path_identity(self):
        aw = ActiveWindow(
            app_name="Outlook",
            process_name="outlook.exe",
            window_title="通知.eml - Outlook",
            file_path_hint="D:\\Emails\\通知.eml",
        )
        detector = EmailDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "email"
        assert result.resource_subtype == "email_file"
        assert result.display_name == "通知.eml"
        assert result.identity_key.startswith("email_file:")
        assert result.path_hint == "D:\\Emails\\通知.eml"


# ---------------------------------------------------------------------------
# 4. IDE workspace is_anchor=True and suggests project
# ---------------------------------------------------------------------------


class TestIdeWorkspaceAnchorAndProject:
    def test_ide_workspace_is_anchor_and_suggests_project(self):
        aw = ActiveWindow(
            app_name="PyCharm",
            process_name="pycharm64.exe",
            window_title="MyProject – PyCharm",
        )
        detector = IdeDetector()
        result = detector.detect(aw)
        assert result is not None
        assert result.resource_kind == "ide_file"
        assert result.resource_subtype == "ide_workspace"
        assert result.display_name == "MyProject"
        assert result.is_anchor is True
        assert result.confidence == 60

        resource_dict = {
            "is_anchor": int(result.is_anchor),
            "path_hint": result.path_hint or "",
            "resource_kind": result.resource_kind,
            "resource_subtype": result.resource_subtype,
            "display_name": result.display_name,
        }
        candidate = candidate_project_name_for_resource(resource_dict)
        assert candidate == "MyProject"

    def test_assign_project_for_activity_uses_workspace_name(self, temp_db):
        aid = activity_service.create_activity(
            "PyCharm",
            "pycharm64.exe",
            "MyProject – PyCharm",
            start_time="2026-06-24 09:00:00",
        )
        assignment = assign_project_for_activity(aid)
        assert assignment["source"] == "suggested_project_name"
        assert assignment["suggested_project_name"] == "MyProject"


# ---------------------------------------------------------------------------
# 5. Current activity snapshot uses resource display name
# ---------------------------------------------------------------------------


def _snapshot():
    return json.loads(settings_service.get_setting("current_activity_snapshot", "") or "{}")


class TestCurrentSnapshotUsesResourceDisplayName:
    def test_browser_tab_snapshot_shows_tab_title(self, temp_db):
        machine = CollectorStateMachine()
        machine.transition_to(
            "recording",
            ActiveWindow("Chrome", "chrome.exe", "GitHub - Google Chrome"),
            at_time="2026-06-24 09:00:00",
        )
        snap = _snapshot()
        assert snap["resource_kind"] == "browser_tab"
        assert snap["resource_display_name"] == "GitHub"
        assert snap["activity_display_name"] == "GitHub"
        # Should not be the generic app name "Chrome"
        assert snap["activity_display_name"] != "Chrome"

    def test_email_snapshot_shows_email_subject(self, temp_db):
        machine = CollectorStateMachine()
        machine.transition_to(
            "recording",
            ActiveWindow("Outlook", "outlook.exe", "项目周报 - Outlook"),
            at_time="2026-06-24 09:00:00",
        )
        snap = _snapshot()
        assert snap["resource_kind"] == "email"
        assert snap["resource_display_name"] == "项目周报"
        assert snap["activity_display_name"] == "项目周报"
        assert snap["activity_display_name"] != "Outlook"

    def test_ide_snapshot_shows_workspace_or_file(self, temp_db):
        machine = CollectorStateMachine()
        machine.transition_to(
            "recording",
            ActiveWindow("PyCharm", "pycharm64.exe", "MyProject – PyCharm"),
            at_time="2026-06-24 09:00:00",
        )
        snap = _snapshot()
        assert snap["resource_kind"] == "ide_file"
        assert snap["resource_subtype"] == "ide_workspace"
        assert snap["resource_display_name"] == "MyProject"
        assert snap["activity_display_name"] == "MyProject"
        assert snap["inferred_project_name"] == "MyProject"


# ---------------------------------------------------------------------------
# 6. update_activity_file_path_hint syncs activity_resource
# ---------------------------------------------------------------------------


class TestUpdateFilePathHintUpdatesActivityResource:
    def test_update_file_path_hint_updates_activity_resource(self, temp_db):
        # Create a name-only resource via title (no file_path_hint)
        aid = activity_service.create_activity(
            "Word",
            "winword.exe",
            "合同.docx - Word",
            start_time="2026-06-24 09:00:00",
        )
        resource = get_resource_for_activity(aid)
        assert resource is not None
        assert resource["resource_kind"] == "office_document"
        assert resource["path_hint"] is None
        assert resource["identity_key"].startswith("office_file_name:")

        # Now supplement with a full path
        activity_service.update_activity_file_path_hint(aid, "D:\\Docs\\合同.docx")

        resource = get_resource_for_activity(aid)
        assert resource is not None
        assert resource["path_hint"] == "D:\\Docs\\合同.docx"
        assert resource["identity_key"].startswith("office_file:")
        assert resource["display_name"] == "合同.docx"
        assert resource["resource_kind"] == "office_document"

    def test_update_file_path_hint_keeps_excluded_anonymous(self, temp_db):
        aid = activity_service.create_activity(
            "已排除",
            "excluded",
            "已排除窗口",
            status=STATUS_EXCLUDED,
            start_time="2026-06-24 09:00:00",
        )
        activity_service.update_activity_file_path_hint(aid, "D:\\Docs\\合同.docx")
        resource = get_resource_for_activity(aid)
        assert resource is not None
        assert resource["resource_kind"] == "system"
        assert resource["resource_subtype"] == "excluded"
        assert resource["path_hint"] is None
        assert resource["display_name"] == EXCLUDED_APP_NAME


# ---------------------------------------------------------------------------
# 7. email_metadata_capture_enabled default is seeded
# ---------------------------------------------------------------------------


class TestEmailMetadataCaptureDefaultSeeded:
    def test_email_metadata_capture_default_seeded(self, temp_db):
        value = settings_service.get_setting("email_metadata_capture_enabled")
        assert value == "false"

    def test_email_metadata_capture_default_disabled_via_helper(self, temp_db):
        assert EmailDetector.is_email_metadata_capture_enabled() is False
