from tests.support.db_helpers import assign_activity_project
from worktrace.db import get_connection
from worktrace.services import (
    activity_service,
    folder_rule_service,
    project_service,
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
    return aid


def test_longest_child_folder_rule_wins(temp_db):
    parent_project = project_service.create_project("Parent")
    child_project = project_service.create_project("Child")
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA", parent_project)
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA\\Sub", child_project)
    rule = folder_rule_service.find_matching_folder_rule("D:\\CaseA\\Sub\\Spec.docx")
    assert rule["project_id"] == child_project


def test_folder_rule_lookup_cache_reuses_reads_and_invalidates_on_update(temp_db, monkeypatch):
    parent_project = project_service.create_project("Parent")
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA", parent_project)
    folder_rule_service.invalidate_folder_rule_cache()
    original = folder_rule_service.get_connection
    calls = {"count": 0}

    def counted_connection():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(folder_rule_service, "get_connection", counted_connection)

    assert folder_rule_service.find_matching_folder_rule("D:\\CaseA\\Spec.docx")["project_id"] == parent_project
    assert folder_rule_service.find_matching_folder_rule("D:\\CaseA\\Other.docx")["project_id"] == parent_project
    assert calls["count"] == 1

    child_project = project_service.create_project("Child")
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA\\Sub", child_project)
    calls_after_update = calls["count"]

    assert folder_rule_service.find_matching_folder_rule("D:\\CaseA\\Sub\\Spec.docx")["project_id"] == child_project
    assert calls["count"] == calls_after_update + 1


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
    """Backfill via the safe path skips manual_override activities.

    The removed ``folder_rule_service.backfill_folder_rule`` entry was
    removed; the safe path lives in ``rule_impact_service``. This test
    keeps coverage of the manual-override skip behavior at the folder
    backfill level by exercising the new safe path.
    """
    from worktrace.db import get_connection, now_str
    from worktrace.services import rule_impact_service

    folder_project = project_service.create_project("Folder")
    manual_project = project_service.create_project("Manual")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", folder_project)
    aid = _activity_with_path("D:\\CaseA\\Manual.docx", "Manual.docx - Word")
    assign_activity_project(aid, manual_project, manual=True)
    # Close via direct SQL (bypass close_activity's automatic rule
    # re-trigger) so the activity is classified as manual_skipped rather
    # than in_progress_skipped.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET end_time = ?, duration_seconds = ?, updated_at = ? WHERE id = ?",
            ("2026-06-18 09:10:00", 600, now_str(), aid),
        )
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 0
    assert result["manual_skipped_count"] == 1
    assert activity_service.get_activity(aid)["project_id"] == manual_project


def test_backfill_safe_updates_eligible_activity(temp_db):
    """The safe path updates an eligible closed activity under the rule's folder."""
    from worktrace.db import get_connection, now_str
    from worktrace.services import rule_impact_service

    folder_project = project_service.create_project("Folder")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", folder_project)
    aid = _activity_with_path("D:\\CaseA\\Eligible.docx", "Eligible.docx - Word")
    # Close via direct SQL to bypass close_activity's automatic rule
    # re-trigger so backfill sees a closed-but-unassigned eligible activity.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET end_time = ?, duration_seconds = ?, updated_at = ? WHERE id = ?",
            ("2026-06-18 09:10:00", 600, now_str(), aid),
        )
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 1
    assert activity_service.get_activity(aid)["project_id"] == folder_project


def test_preview_folder_rule_conflicts_counts_folder_scope(temp_db):
    parent_project = project_service.create_project("Parent")
    child_project = project_service.create_project("Child")
    folder_rule_service.create_or_update_folder_rule("D:\\CaseA\\Sub", child_project)
    aid = _activity_with_path("D:\\CaseA\\Manual.docx", "Manual.docx - Word")
    assign_activity_project(aid, child_project, manual=True)
    preview = folder_rule_service.preview_folder_rule_conflicts("D:\\CaseA", parent_project)
    assert preview["child_folder_rule_conflicts"] == 1
    assert preview["other_project_activity_count"] == 1
    assert preview["manual_activity_count"] == 1
