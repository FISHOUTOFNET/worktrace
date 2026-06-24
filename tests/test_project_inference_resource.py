from __future__ import annotations

from worktrace.services import activity_service, folder_rule_service, project_inference_service, project_service, rule_service
from worktrace.services.project_inference_service import (
    _safe_classification_text,
    assign_project_for_activity,
    candidate_project_name_for_resource,
)


class TestLocalFileFolderRule:
    """1. local_file with path_hint, folder rule hits first."""

    def test_local_file_folder_rule(self, temp_db):
        pid = project_service.create_project("WorkTrace")
        folder_rule_service.create_or_update_folder_rule("D:\\Repo\\WorkTrace", pid)
        aid = activity_service.create_activity(
            "Code", "Code.exe", "main.py - VS Code",
            file_path_hint="D:\\Repo\\WorkTrace\\main.py",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(aid)
        assert assignment["source"] == "folder_rule"
        assert activity_service.get_activity(aid)["project_id"] == pid


class TestOfficeDocumentFolderRule:
    """2. office_document with path_hint, folder rule hits."""

    def test_office_document_folder_rule(self, temp_db):
        pid = project_service.create_project("ClientA")
        folder_rule_service.create_or_update_folder_rule("D:\\ClientA", pid)
        aid = activity_service.create_activity(
            "Word", "winword.exe", "合同.docx - Word",
            file_path_hint="D:\\ClientA\\合同.docx",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(aid)
        assert assignment["source"] == "folder_rule"
        assert activity_service.get_activity(aid)["project_id"] == pid


class TestCodeFileFolderRule:
    """3. code_file with path_hint, folder rule hits."""

    def test_code_file_folder_rule(self, temp_db):
        pid = project_service.create_project("Backend")
        folder_rule_service.create_or_update_folder_rule("D:\\Projects\\Backend", pid)
        aid = activity_service.create_activity(
            "Code", "Code.exe", "app.py - VS Code",
            file_path_hint="D:\\Projects\\Backend\\app.py",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(aid)
        assert assignment["source"] == "folder_rule"
        assert activity_service.get_activity(aid)["project_id"] == pid


class TestKeywordRuleMatchesResourceDisplayName:
    """4. keyword rule can match resource_display_name."""

    def test_keyword_matches_display_name(self, temp_db):
        pid = project_service.create_project("SpecWork")
        rule_service.create_rule("Architecture Spec", pid)
        aid = activity_service.create_activity(
            "Word", "winword.exe", "Architecture Spec.docx - Word",
            file_path_hint="D:\\Docs\\Architecture Spec.docx",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(aid)
        assert assignment["source"] == "keyword_rule"
        assert activity_service.get_activity(aid)["project_id"] == pid


class TestKeywordRuleMatchesSafeFields:
    """5. keyword rule can match uri_host/path_hint etc."""

    def test_keyword_matches_path_hint(self, temp_db):
        pid = project_service.create_project("ClientB")
        rule_service.create_rule("ClientB", pid)
        aid = activity_service.create_activity(
            "Word", "winword.exe", "合同.docx - Word",
            file_path_hint="D:\\ClientB\\合同.docx",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(aid)
        # folder_rule would also match if there was one, but keyword should match path_hint
        assert assignment["source"] in ("keyword_rule", "folder_rule")
        assert activity_service.get_activity(aid)["project_id"] == pid

    def test_keyword_matches_process_name(self, temp_db):
        pid = project_service.create_project("FigmaWork")
        rule_service.create_rule("figma", pid)
        aid = activity_service.create_activity(
            "Figma", "figma.exe", "Design System",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(aid)
        assert assignment["source"] == "keyword_rule"
        assert activity_service.get_activity(aid)["project_id"] == pid


class TestManualOverrideNotOverwritten:
    """6. manual_override=1 is not overwritten."""

    def test_manual_override_preserved(self, temp_db):
        manual_project = project_service.create_project("Manual")
        rule_project = project_service.create_project("Rule")
        folder_rule_service.create_or_update_folder_rule("D:\\ClientA", rule_project)
        aid = activity_service.create_activity(
            "Word", "winword.exe", "合同.docx - Word",
            file_path_hint="D:\\ClientA\\合同.docx",
            start_time="2026-06-18 09:00:00",
        )
        activity_service.update_activity_project(aid, manual_project, manual=True)
        assign_project_for_activity(aid)
        row = activity_service.get_activity(aid)
        assert row["project_id"] == manual_project
        assert row["manual_override"] == 1


class TestOldActivityFallback:
    """7. old activity without resource row can still infer project."""

    def test_old_activity_without_resource(self, temp_db):
        pid = project_service.create_project("ClientA")
        folder_rule_service.create_or_update_folder_rule("D:\\ClientA", pid)
        # Insert activity_log directly, bypassing create_activity to simulate old data without resource
        from worktrace.db import get_connection
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO activity_log(
                    start_time, end_time, duration_seconds, app_name, process_name,
                    window_title, file_path_hint, status, source, is_deleted, is_hidden,
                    auto_classified, manual_override, project_id, note,
                    created_at, updated_at
                )
                VALUES ('2026-06-18 09:00:00', '2026-06-18 09:30:00', 1800,
                        'Word', 'winword.exe', '合同.docx - Word', 'D:\\ClientA\\合同.docx',
                        'normal', 'auto', 0, 0, 0, 0, 1, NULL,
                        '2026-06-18 09:00:00', '2026-06-18 09:00:00')
                """
            )
            activity_id = int(cur.lastrowid)

        assignment = assign_project_for_activity(activity_id)
        assert assignment["source"] == "folder_rule"
        assert assignment["project_id"] == pid


class TestNonNormalNotClassified:
    """8. non-normal status is not classified to a project."""

    def test_idle_not_classified(self, temp_db):
        pid = project_service.create_project("ClientA")
        folder_rule_service.create_or_update_folder_rule("D:\\ClientA", pid)
        aid = activity_service.create_activity(
            "空闲", "idle", "用户空闲",
            status="idle",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(aid)
        assert assignment["source"] == "uncategorized"

    def test_excluded_not_classified(self, temp_db):
        pid = project_service.create_project("BankWork")
        rule_service.create_rule("银行", pid)
        aid = activity_service.create_activity(
            "BankApp", "bank.exe", "银行真实标题",
            status="excluded",
            start_time="2026-06-18 09:00:00",
        )
        assignment = assign_project_for_activity(aid)
        assert assignment["source"] == "uncategorized"


class TestSafeClassificationText:
    """Test _safe_classification_text only includes safe fields."""

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
        # Should not contain any body/content fields
        assert "body" not in text
        assert "content" not in text
        assert "email_body" not in text


class TestCandidateProjectNameForResource:
    """Test candidate_project_name_for_resource."""

    def test_anchor_file_with_path(self):
        resource = {
            "is_anchor": 1,
            "path_hint": "D:\\ClientA\\合同.docx",
            "resource_kind": "office_document",
            "display_name": "合同.docx",
        }
        name = candidate_project_name_for_resource(resource)
        assert name == "ClientA"

    def test_browser_tab_no_suggestion(self):
        resource = {
            "is_anchor": 0,
            "path_hint": None,
            "resource_kind": "browser_tab",
            "display_name": "Search",
        }
        name = candidate_project_name_for_resource(resource)
        assert name is None

    def test_generic_app_no_suggestion(self):
        resource = {
            "is_anchor": 0,
            "path_hint": None,
            "resource_kind": "app",
            "display_name": "微信",
        }
        name = candidate_project_name_for_resource(resource)
        assert name is None
