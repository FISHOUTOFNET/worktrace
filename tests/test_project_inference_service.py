from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.services import activity_service, project_inference_service, project_service, rule_service
from worktrace.services.project_inference_service import assign_project_for_activity


def test_anchor_default_project_classifies_activity(temp_db):
    pid = project_service.create_project("Client A")
    aid = activity_service.create_activity("Word", "winword.exe", "合同.docx", start_time="2026-06-18 09:00:00")
    assign_project_for_activity(aid)
    resource_id = activity_service.get_activity(aid)["resource_id"]
    from worktrace.db import get_connection, now_str

    with get_connection() as conn:
        conn.execute(
            "UPDATE resource SET default_project_id = ?, updated_at = ? WHERE id = ?",
            (pid, now_str(), resource_id),
        )
    assign_project_for_activity(aid)
    assert activity_service.get_activity(aid)["project_id"] == pid


def test_keyword_rules_only_match_anchor_files(temp_db):
    pid = project_service.create_project("Writing")
    rule_service.create_rule("Spec", pid)
    anchor = activity_service.create_activity("Word", "winword.exe", "Architecture Spec.docx", start_time="2026-06-18 09:00:00")
    auxiliary = activity_service.create_activity("Spec App", "spec.exe", "Dashboard", start_time="2026-06-18 09:10:00")
    rule_service.apply_rules_to_activity(anchor)
    rule_service.apply_rules_to_activity(auxiliary)
    assert activity_service.get_activity(anchor)["project_id"] == pid
    assert activity_service.get_activity(auxiliary)["project_name"] == UNCATEGORIZED_PROJECT


def test_keyword_rule_cache_reuses_reads_and_invalidates_on_create(temp_db, monkeypatch):
    project = project_service.create_project("Writing")
    rule_service.create_rule("Spec", project)
    project_inference_service.invalidate_keyword_rule_cache()
    original = project_inference_service.get_connection
    calls = {"count": 0}

    def counted_connection():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(project_inference_service, "get_connection", counted_connection)

    assert project_inference_service._enabled_keyword_rules()[0]["pattern"] == "spec"
    assert project_inference_service._enabled_keyword_rules()[0]["pattern"] == "spec"
    assert calls["count"] == 1

    other_project = project_service.create_project("Other")
    rule_service.create_rule("Other", other_project)

    patterns = [row["pattern"] for row in project_inference_service._enabled_keyword_rules()]
    assert patterns == ["spec", "other"]
    assert calls["count"] == 2


def test_manual_override_is_not_overwritten(temp_db):
    manual_project = project_service.create_project("Manual")
    rule_project = project_service.create_project("Rule")
    rule_service.create_rule("Spec", rule_project)
    aid = activity_service.create_activity("Word", "winword.exe", "Spec.docx", start_time="2026-06-18 09:00:00")
    activity_service.update_activity_project(aid, manual_project, manual=True)
    assign_project_for_activity(aid)
    row = activity_service.get_activity(aid)
    assert row["project_id"] == manual_project
    assert row["manual_override"] == 1
