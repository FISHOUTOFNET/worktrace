from worktrace.db import get_connection
from worktrace.services import (
    activity_service,
    folder_rule_service,
    project_service,
    resource_service,
    rule_service,
)
from worktrace.services.project_inference_service import assign_project_for_activity


def _activity_with_path(path: str, title: str = "Spec.docx - Word") -> int:
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        title,
        file_path_hint=path,
        start_time="2026-06-18 09:00:00",
    )
    resource_service.refresh_activity_resource(aid)
    return aid


def test_longest_child_folder_rule_wins(temp_db):
    parent_project = project_service.create_project("Parent")
    child_project = project_service.create_project("Child")
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA", parent_project)
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA\\Sub", child_project)
    rule = folder_rule_service.find_matching_folder_rule("D:\\CaseA\\Sub\\Spec.docx")
    assert rule["project_id"] == child_project


def test_file_default_project_wins_over_folder_rule(temp_db):
    folder_project = project_service.create_project("Folder")
    file_project = project_service.create_project("File")
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA", folder_project)
    aid = _activity_with_path("D:\\CaseA\\Spec.docx")
    resource_id = activity_service.get_activity(aid)["resource_id"]
    with get_connection() as conn:
        conn.execute("UPDATE resource SET default_project_id = ? WHERE id = ?", (file_project, resource_id))
    assign_project_for_activity(aid)
    assert activity_service.get_activity(aid)["project_id"] == file_project


def test_folder_rule_wins_over_keyword_rule_and_source_is_persisted(temp_db):
    folder_project = project_service.create_project("Folder")
    keyword_project = project_service.create_project("Keyword")
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA", folder_project)
    rule_service.create_rule("Spec", keyword_project)
    aid = _activity_with_path("D:\\CaseA\\Spec.docx")
    assign_project_for_activity(aid)
    row = activity_service.get_activity(aid)
    assert row["project_id"] == folder_project
    assert row["auto_classified"] == 1
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT source FROM activity_project_assignment WHERE activity_id = ?",
            (aid,),
        ).fetchone()
    assert assignment["source"] == "folder_rule"


def test_backfill_safe_does_not_overwrite_manual_override(temp_db):
    folder_project = project_service.create_project("Folder")
    manual_project = project_service.create_project("Manual")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", folder_project)
    aid = _activity_with_path("D:\\CaseA\\Manual.docx", "Manual.docx - Word")
    activity_service.update_activity_project(aid, manual_project, manual=True)
    result = folder_rule_service.backfill_folder_rule(rule_id)
    assert result["updated_activity_count"] == 0
    assert activity_service.get_activity(aid)["project_id"] == manual_project


def test_backfill_safe_does_not_overwrite_confirmed_activity(temp_db):
    folder_project = project_service.create_project("Folder")
    confirmed_project = project_service.create_project("Confirmed")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", folder_project)
    aid = _activity_with_path("D:\\CaseA\\Confirmed.docx", "Confirmed.docx - Word")
    activity_service.update_activity_project(aid, confirmed_project, manual=False)
    activity_service.set_activity_confirmed(aid, True)
    result = folder_rule_service.backfill_folder_rule(rule_id)
    assert result["updated_activity_count"] == 0
    assert activity_service.get_activity(aid)["project_id"] == confirmed_project


def test_backfill_safe_does_not_overwrite_manual_assignment(temp_db):
    folder_project = project_service.create_project("Folder")
    manual_project = project_service.create_project("Manual")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", folder_project)
    aid = _activity_with_path("D:\\CaseA\\Assigned.docx", "Assigned.docx - Word")
    activity_service.update_activity_project(aid, manual_project, manual=True)
    result = folder_rule_service.backfill_folder_rule(rule_id)
    assert result["updated_activity_count"] == 0
    assert activity_service.get_activity(aid)["project_id"] == manual_project


def test_backfill_safe_updates_eligible_activity(temp_db):
    folder_project = project_service.create_project("Folder")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", folder_project)
    aid = _activity_with_path("D:\\CaseA\\Eligible.docx", "Eligible.docx - Word")
    result = folder_rule_service.backfill_folder_rule(rule_id)
    assert result["updated_activity_count"] == 1
    assert activity_service.get_activity(aid)["project_id"] == folder_project


def test_preview_folder_rule_conflicts_counts_folder_scope(temp_db):
    parent_project = project_service.create_project("Parent")
    child_project = project_service.create_project("Child")
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA\\Sub", child_project)
    aid = _activity_with_path("D:\\CaseA\\Manual.docx", "Manual.docx - Word")
    activity_service.update_activity_project(aid, child_project, manual=True)
    preview = folder_rule_service.preview_folder_rule_conflicts("D:\\CaseA", parent_project)
    assert preview["child_folder_rule_conflicts"] == 1
    assert preview["other_project_activity_count"] == 1
    assert preview["manual_or_confirmed_activity_count"] == 1
