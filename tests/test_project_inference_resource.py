from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from tests.support.db_helpers import assign_activity_project
from worktrace.db import get_connection
from worktrace.services import (
    activity_fact_repair_service,
    folder_rule_service,
    project_service,
    rule_service,
)
from worktrace.services.project_inference_service import (
    _safe_classification_text,
    assign_project_for_activity,
    candidate_project_name_for_resource,
)

pytestmark = [pytest.mark.db]


class TestLocalFileFolderRule:
    def test_local_file_folder_rule(self, temp_db):
        project_id = project_service.create_project("WorkTrace")
        folder_rule_service.create_or_update_folder_rule(
            "D:\\Repo\\WorkTrace",
            project_id,
        )
        activity_id = activity_service.create_activity(
            "Code",
            "Code.exe",
            "main.py - VS Code",
            file_path_hint="D:\\Repo\\WorkTrace\\main.py",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] == "folder_rule"
        assert activity_service.get_activity(activity_id)["project_id"] == project_id


class TestOfficeDocumentFolderRule:
    def test_office_document_folder_rule(self, temp_db):
        project_id = project_service.create_project("ClientA")
        folder_rule_service.create_or_update_folder_rule("D:\\ClientA", project_id)
        activity_id = activity_service.create_activity(
            "Word",
            "winword.exe",
            "合同.docx - Word",
            file_path_hint="D:\\ClientA\\合同.docx",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] == "folder_rule"
        assert activity_service.get_activity(activity_id)["project_id"] == project_id


class TestCodeFileFolderRule:
    def test_code_file_folder_rule(self, temp_db):
        project_id = project_service.create_project("Backend")
        folder_rule_service.create_or_update_folder_rule(
            "D:\\Projects\\Backend",
            project_id,
        )
        activity_id = activity_service.create_activity(
            "Code",
            "Code.exe",
            "app.py - VS Code",
            file_path_hint="D:\\Projects\\Backend\\app.py",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] == "folder_rule"
        assert activity_service.get_activity(activity_id)["project_id"] == project_id


class TestKeywordRuleMatchesResourceDisplayName:
    def test_keyword_matches_display_name(self, temp_db):
        project_id = project_service.create_project("SpecWork")
        rule_service.create_rule("Architecture Spec", project_id)
        activity_id = activity_service.create_activity(
            "Word",
            "winword.exe",
            "Architecture Spec.docx - Word",
            file_path_hint="D:\\Docs\\Architecture Spec.docx",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] == "keyword_rule"
        assert activity_service.get_activity(activity_id)["project_id"] == project_id


class TestKeywordRuleMatchesSafeFields:
    def test_keyword_matches_path_hint(self, temp_db):
        project_id = project_service.create_project("ClientB")
        rule_service.create_rule("ClientB", project_id)
        activity_id = activity_service.create_activity(
            "Word",
            "winword.exe",
            "合同.docx - Word",
            file_path_hint="D:\\ClientB\\合同.docx",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] in ("keyword_rule", "folder_rule")
        assert activity_service.get_activity(activity_id)["project_id"] == project_id

    def test_keyword_matches_process_name(self, temp_db):
        project_id = project_service.create_project("FigmaWork")
        rule_service.create_rule("figma", project_id)
        activity_id = activity_service.create_activity(
            "Figma",
            "figma.exe",
            "Design System",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] == "keyword_rule"
        assert activity_service.get_activity(activity_id)["project_id"] == project_id


class TestManualOverrideNotOverwritten:
    def test_manual_override_preserved(self, temp_db):
        manual_project = project_service.create_project("Manual")
        rule_project = project_service.create_project("Rule")
        folder_rule_service.create_or_update_folder_rule(
            "D:\\ClientA",
            rule_project,
        )
        activity_id = activity_service.create_activity(
            "Word",
            "winword.exe",
            "合同.docx - Word",
            file_path_hint="D:\\ClientA\\合同.docx",
            start_time="2026-06-18 09:00:00",
        )
        assign_activity_project(activity_id, manual_project, manual=True)
        assign_project_for_activity(activity_id)
        row = activity_service.get_activity(activity_id)
        assert row["project_id"] == manual_project
        assert row["assignment_is_manual"] == 1


class TestMissingResourceRepairBoundary:
    def test_old_activity_requires_durable_resource_repair(self, temp_db):
        project_id = project_service.create_project("ClientA")
        folder_rule_service.create_or_update_folder_rule("D:\\ClientA", project_id)
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO activity_log(
                    start_time, end_time, duration_seconds, app_name, process_name,
                    window_title, file_path_hint, status, source, is_deleted, is_hidden,
                    created_at, updated_at
                )
                VALUES ('2026-06-18 09:00:00', '2026-06-18 09:30:00', 1800,
                        'Word', 'winword.exe', '合同.docx - Word', 'D:\\ClientA\\合同.docx',
                        'normal', 'auto', 0, 0,
                        '2026-06-18 09:00:00', '2026-06-18 09:00:00')
                """
            )
            activity_id = int(cursor.lastrowid)

        with pytest.raises(ValueError, match="data_repair_required"):
            assign_project_for_activity(activity_id)

        assert activity_fact_repair_service.repair_missing_activity_resources() == 1
        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] == "folder_rule"
        assert assignment["project_id"] == project_id


class TestNonNormalNotClassified:
    def test_idle_not_classified(self, temp_db):
        project_id = project_service.create_project("ClientA")
        folder_rule_service.create_or_update_folder_rule("D:\\ClientA", project_id)
        activity_id = activity_service.create_activity(
            "空闲",
            "idle",
            "用户空闲",
            status="idle",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] == "uncategorized"

    def test_excluded_not_classified(self, temp_db):
        project_id = project_service.create_project("BankWork")
        rule_service.create_rule("银行", project_id)
        activity_id = activity_service.create_activity(
            "BankApp",
            "bank.exe",
            "银行真实标题",
            status="excluded",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] == "uncategorized"


class TestSafeClassificationText:
    def test_includes_safe_fields(self):
        activity = {"window_title": "My Window", "file_path_hint": "D:\\file.docx"}
        resource = {
            "display_name": "file.docx",
            "resource_kind": "office_document",
            "resource_subtype": "word_document",
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "file.docx - Word",
            "path_hint": "D:\\file.docx",
            "uri_host": None,
        }
        text = _safe_classification_text(activity, resource)
        assert "file.docx" in text
        assert "office_document" in text
        assert "word_document" in text
        assert "winword.exe" in text
        assert "d:\\file.docx" in text

    def test_does_not_include_body_fields(self):
        activity = {"window_title": "My Window", "file_path_hint": ""}
        resource = {
            "display_name": "file.docx",
            "resource_kind": "office_document",
            "resource_subtype": "word_document",
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "file.docx - Word",
            "path_hint": None,
            "uri_host": None,
        }
        text = _safe_classification_text(activity, resource)
        assert "body" not in text
        assert "content" not in text
        assert "email_body" not in text


class TestCandidateProjectNameForResource:
    def test_anchor_file_with_path(self):
        resource = {
            "is_anchor": 1,
            "path_hint": "D:\\ClientA\\合同.docx",
            "resource_kind": "office_document",
            "display_name": "合同.docx",
        }
        assert candidate_project_name_for_resource(resource) == "ClientA"

    def test_browser_tab_no_suggestion(self):
        resource = {
            "is_anchor": 0,
            "path_hint": None,
            "resource_kind": "browser_tab",
            "display_name": "Search",
        }
        assert candidate_project_name_for_resource(resource) is None

    def test_generic_app_no_suggestion(self):
        resource = {
            "is_anchor": 0,
            "path_hint": None,
            "resource_kind": "app",
            "display_name": "微信",
        }
        assert candidate_project_name_for_resource(resource) is None
