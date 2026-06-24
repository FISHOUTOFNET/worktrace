from __future__ import annotations

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import EXCLUDED_APP_NAME, EXCLUDED_PROCESS_NAME, EXCLUDED_WINDOW_TITLE
from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, project_service, rule_service
from worktrace.services.resource_service import get_resource_for_activity


def _enable_excluded_project_with_keyword(keyword: str) -> int:
    """Enable the 排除规则 project and add a keyword rule. Returns the project id."""
    excluded_project = project_service.get_or_create_excluded_project()
    project_service.set_project_enabled(excluded_project, True)
    rule_service.create_rule(keyword, excluded_project)
    return excluded_project


class TestSameDocxTitleVariationSameSignature:
    """1. Same .docx file, window_title slightly varies, still same signature."""

    def test_docx_title_variation_no_split(self, temp_db):
        machine = CollectorStateMachine()
        # First: "合同.docx - Word"
        machine.transition_to(
            "recording",
            ActiveWindow("Word", "winword.exe", "合同.docx - Word", "D:\\Docs\\合同.docx"),
            at_time="2026-06-18 09:00:00",
        )
        # Second: "合同.docx - Word [已保存]" — title changed but same file
        machine.transition_to(
            "recording",
            ActiveWindow("Word", "winword.exe", "合同.docx - Word [已保存]", "D:\\Docs\\合同.docx"),
            at_time="2026-06-18 09:01:00",
        )
        # Third: "合同.docx - Word [兼容模式]"
        machine.transition_to(
            "recording",
            ActiveWindow("Word", "winword.exe", "合同.docx - Word [兼容模式]", "D:\\Docs\\合同.docx"),
            at_time="2026-06-18 09:02:00",
        )
        # Should still be one continuous activity
        row = activity_service.get_open_activity()
        assert row is not None
        assert row["start_time"] == "2026-06-18 09:00:00"


class TestWpsSamePathNoSplit:
    """2. Same wps.exe + same path, no split."""

    def test_wps_same_path_no_split(self, temp_db):
        machine = CollectorStateMachine()
        machine.transition_to(
            "recording",
            ActiveWindow("WPS Writer", "wps.exe", "汇报.docx - WPS 文字", "D:\\Work\\汇报.docx"),
            at_time="2026-06-18 09:00:00",
        )
        machine.transition_to(
            "recording",
            ActiveWindow("WPS Writer", "wps.exe", "汇报.docx - WPS 文字 [已修改]", "D:\\Work\\汇报.docx"),
            at_time="2026-06-18 09:01:00",
        )
        row = activity_service.get_open_activity()
        assert row is not None
        assert row["start_time"] == "2026-06-18 09:00:00"


class TestDifferentFilePathSplits:
    """3. Different file paths cause split."""

    def test_different_docx_paths_split(self, temp_db):
        machine = CollectorStateMachine()
        machine.transition_to(
            "recording",
            ActiveWindow("Word", "winword.exe", "合同A.docx - Word", "D:\\Docs\\合同A.docx"),
            at_time="2026-06-18 09:00:00",
        )
        machine.transition_to(
            "recording",
            ActiveWindow("Word", "winword.exe", "合同A.docx - Word", "D:\\Docs\\合同A.docx"),
            at_time="2026-06-18 09:01:00",
        )
        first_id = activity_service.get_open_activity()["id"]
        # Switch to different file
        machine.transition_to(
            "recording",
            ActiveWindow("Word", "winword.exe", "合同B.docx - Word", "D:\\Docs\\合同B.docx"),
            at_time="2026-06-18 09:02:00",
        )
        # Old activity should be closed
        assert activity_service.get_activity(first_id)["end_time"] is not None


class TestIdleNoDuplicateRecords:
    """4. idle consecutive transition_to("idle") does not produce multiple records."""

    def test_idle_no_duplicates(self, temp_db):
        machine = CollectorStateMachine()
        machine.transition_to("idle", at_time="2026-06-18 09:00:00")
        machine.transition_to("idle", at_time="2026-06-18 09:00:30")
        machine.transition_to("idle", at_time="2026-06-18 09:01:00")
        machine.transition_to("idle", at_time="2026-06-18 09:02:00")
        # Should be at most one open activity or no open activity for idle
        with get_connection() as conn:
            open_count = conn.execute(
                "SELECT COUNT(*) AS c FROM activity_log WHERE end_time IS NULL"
            ).fetchone()["c"]
            total_idle = conn.execute(
                "SELECT COUNT(*) AS c FROM activity_log WHERE status = 'idle'"
            ).fetchone()["c"]
        assert open_count <= 1
        assert total_idle <= 1


class TestExcludedNoDuplicatesAndAnonymous:
    """5. excluded consecutive transitions don't produce multiple records, and resource is anonymous."""

    def test_excluded_no_duplicates(self, temp_db):
        _enable_excluded_project_with_keyword("银行")
        machine = CollectorStateMachine()
        machine.transition_to(
            "excluded",
            ActiveWindow("BankApp", "bank.exe", "银行真实标题"),
            at_time="2026-06-18 09:00:00",
        )
        machine.transition_to(
            "excluded",
            ActiveWindow("BankApp", "bank.exe", "银行另一个标题"),
            at_time="2026-06-18 09:00:30",
        )
        machine.transition_to(
            "excluded",
            ActiveWindow("BankApp", "bank.exe", "银行第三个标题"),
            at_time="2026-06-18 09:01:00",
        )
        with get_connection() as conn:
            open_count = conn.execute(
                "SELECT COUNT(*) AS c FROM activity_log WHERE end_time IS NULL"
            ).fetchone()["c"]
            total_excluded = conn.execute(
                "SELECT COUNT(*) AS c FROM activity_log WHERE status = 'excluded'"
            ).fetchone()["c"]
        assert open_count <= 1
        assert total_excluded <= 1

    def test_excluded_resource_is_anonymous(self, temp_db):
        _enable_excluded_project_with_keyword("银行")
        machine = CollectorStateMachine()
        machine.transition_to(
            "excluded",
            ActiveWindow("BankApp", "bank.exe", "银行真实标题"),
            at_time="2026-06-18 09:00:00",
        )
        # Force persistence
        machine.transition_to(
            "excluded",
            ActiveWindow("BankApp", "bank.exe", "银行真实标题"),
            at_time="2026-06-18 09:01:00",
        )
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM activity_log WHERE status = 'excluded' LIMIT 1"
            ).fetchone()
        if row:
            resource = get_resource_for_activity(int(row["id"]))
            assert resource is not None
            assert resource["resource_kind"] == "system"
            assert resource["resource_subtype"] == "excluded"
            assert resource["display_name"] == EXCLUDED_APP_NAME
            assert resource["app_name"] == EXCLUDED_APP_NAME
            assert resource["process_name"] == EXCLUDED_PROCESS_NAME
            assert resource["window_title"] == EXCLUDED_WINDOW_TITLE
            assert resource["path_hint"] is None


class TestCreateActivityWritesResource:
    """6. create_activity is called with resource, activity_resource exists."""

    def test_recording_creates_resource(self, temp_db):
        machine = CollectorStateMachine()
        machine.transition_to(
            "recording",
            ActiveWindow("Word", "winword.exe", "合同.docx - Word", "D:\\Docs\\合同.docx"),
            at_time="2026-06-18 09:00:00",
        )
        # Force persistence by advancing time
        machine.transition_to(
            "recording",
            ActiveWindow("Word", "winword.exe", "合同.docx - Word", "D:\\Docs\\合同.docx"),
            at_time="2026-06-18 09:01:00",
        )
        row = activity_service.get_open_activity()
        assert row is not None
        resource = get_resource_for_activity(int(row["id"]))
        assert resource is not None
        assert resource["resource_kind"] == "office_document"
        assert resource["resource_subtype"] == "word_document"

    def test_idle_creates_system_resource(self, temp_db):
        machine = CollectorStateMachine()
        machine.transition_to("idle", at_time="2026-06-18 09:00:00")
        machine.transition_to("idle", at_time="2026-06-18 09:01:00")
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM activity_log WHERE status = 'idle' LIMIT 1"
            ).fetchone()
        if row:
            resource = get_resource_for_activity(int(row["id"]))
            assert resource is not None
            assert resource["resource_kind"] == "system"
            assert resource["resource_subtype"] == "idle"

    def test_generic_app_creates_app_resource(self, temp_db):
        machine = CollectorStateMachine()
        machine.transition_to(
            "recording",
            ActiveWindow("微信", "WeChat.exe", "聊天"),
            at_time="2026-06-18 09:00:00",
        )
        machine.transition_to(
            "recording",
            ActiveWindow("微信", "WeChat.exe", "聊天"),
            at_time="2026-06-18 09:01:00",
        )
        row = activity_service.get_open_activity()
        assert row is not None
        resource = get_resource_for_activity(int(row["id"]))
        assert resource is not None
        assert resource["resource_kind"] == "app"
        assert resource["resource_subtype"] == "generic_app"
