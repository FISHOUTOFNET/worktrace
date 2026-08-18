from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests.support import activity_factory as activity_service
from worktrace.api import timeline_api
from worktrace.constants import TIME_FORMAT
from worktrace.db import get_connection, now_str
from worktrace.services import (
    activity_inference_job_repository,
    activity_inference_job_service,
    folder_index_maintenance_service,
    folder_index_service,
    folder_rule_service,
    project_inference_service,
    project_service,
    rule_history_application_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _assignment(activity_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT project_id, source, is_manual, source_rule_type, source_rule_id,
                   created_at, updated_at
            FROM activity_project_assignment
            WHERE activity_id = ?
            """,
            (int(activity_id),),
        ).fetchone()
        return dict(row) if row else {}


def _one_second_after(value: str) -> str:
    return (datetime.strptime(value, TIME_FORMAT) + timedelta(seconds=1)).strftime(
        TIME_FORMAT
    )


def test_normal_inference_does_not_rewrite_resolved_rule_assignment(temp_db):
    project_parent = project_service.create_project("Parent")
    project_specific = project_service.create_project("Specific")
    parent_rule = folder_rule_service.create_or_update_folder_rule(
        r"D:\Matter",
        project_parent,
        True,
    )
    specific_rule = folder_rule_service.create_or_update_folder_rule(
        r"D:\Matter\Specific",
        project_specific,
        True,
    )
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx - Word",
        file_path_hint=r"D:\Matter\Specific\Spec.docx",
        start_time="2026-08-18 09:00:00",
    )

    first = project_inference_service.assign_project_for_activity(activity_id)
    assert first["project_id"] == project_specific
    assert first["source_rule_id"] == specific_rule

    deleted = rule_history_application_service.delete_rule(
        "folder",
        specific_rule,
        apply_to_history=False,
    )
    assert deleted["status"] == "completed"

    second = project_inference_service.assign_project_for_activity(activity_id)
    assert second["project_id"] == project_specific
    assert second["source_rule_id"] == specific_rule
    assert parent_rule != specific_rule


def test_rule_removal_gate_only_unlocks_the_exact_origin_rule(temp_db):
    project_parent = project_service.create_project("Parent")
    project_specific = project_service.create_project("Specific")
    parent_rule = folder_rule_service.create_or_update_folder_rule(
        r"D:\Matter",
        project_parent,
        True,
    )
    specific_rule = folder_rule_service.create_or_update_folder_rule(
        r"D:\Matter\Specific",
        project_specific,
        True,
    )
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx - Word",
        file_path_hint=r"D:\Matter\Specific\Spec.docx",
        start_time="2026-08-18 09:00:00",
    )
    project_inference_service.assign_project_for_activity(activity_id)

    with get_connection() as conn:
        unrelated = project_inference_service.assign_project_for_activity_in_transaction(
            conn,
            activity_id,
            exclude_rule=("folder", parent_rule),
        )
        assert unrelated["project_id"] == project_specific
        assert unrelated["source_rule_id"] == specific_rule

        exact = project_inference_service.assign_project_for_activity_in_transaction(
            conn,
            activity_id,
            exclude_rule=("folder", specific_rule),
        )
    assert exact["project_id"] == project_parent
    assert exact["source_rule_id"] == parent_rule


def test_concrete_path_upgrade_may_correct_automatic_assignment(
    temp_db,
    tmp_path,
    allow_sensitive_runtime,
):
    project_a = project_service.create_project("Indexed A")
    project_b = project_service.create_project("Concrete B")
    root_a = tmp_path / "IndexedA"
    root_a.mkdir()
    (root_a / "Matter.docx").write_text("a", encoding="utf-8")
    rule_a = folder_rule_service.create_or_update_folder_rule(
        str(root_a),
        project_a,
        True,
    )
    rule_b = folder_rule_service.create_or_update_folder_rule(
        r"D:\ConcreteB",
        project_b,
        True,
    )
    assert folder_index_service.rebuild_folder_index(rule_a)

    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Matter.docx - Word",
        start_time=now_str(),
    )
    first = project_inference_service.assign_project_for_activity(activity_id)
    assert first["project_id"] == project_a
    assert first["source_rule_id"] == rule_a

    activity_service.update_activity_file_path_hint(
        activity_id,
        r"D:\ConcreteB\Matter.docx",
    )

    after = _assignment(activity_id)
    assert after["project_id"] == project_b
    assert after["source"] == "folder_rule"
    assert after["source_rule_id"] == rule_b


def test_closed_pathless_file_waits_for_new_index_then_converges(
    temp_db,
    tmp_path,
    allow_sensitive_runtime,
):
    project_id = project_service.create_project("Closed Convergence")
    root = tmp_path / "ClosedConvergence"
    root.mkdir()
    (root / "existing.docx").write_text("existing", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        str(root),
        project_id,
        True,
    )
    assert folder_index_service.rebuild_folder_index(rule_id)

    new_file = root / "Later.docx"
    new_file.write_text("new", encoding="utf-8")
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Later.docx - Word",
        start_time=now_str(),
    )
    first = project_inference_service.assign_project_for_activity(activity_id)
    assert first["source"] == "uncategorized"
    assert first["_defer_reason"] == "folder_index_refresh"

    activity_service.close_activity_row(activity_id, now_str())
    with get_connection() as conn:
        assert activity_inference_job_repository.enqueue_closed_activity_ids(
            conn,
            [activity_id],
        ) == 1

    processed = activity_inference_job_service.process_pending_inference_jobs(
        project_inference_service.assign_project_for_activity_in_transaction,
        limit=1,
        activity_ids=[activity_id],
    )
    assert processed == 1
    with get_connection() as conn:
        deferred = conn.execute(
            """
            SELECT status, attempt_count, next_attempt_at
            FROM activity_inference_job
            WHERE activity_id = ?
            """,
            (activity_id,),
        ).fetchone()
    assert deferred is not None
    assert deferred["status"] == "pending"
    assert deferred["attempt_count"] == 0
    assert deferred["next_attempt_at"] is not None

    assert (
        folder_index_maintenance_service.request_refresh_for_unresolved_file_misses()
        == 1
    )
    assert folder_index_service.rebuild_folder_index(rule_id)
    with get_connection() as conn:
        # The schema records timestamps at second precision. Make this test's
        # causal ordering explicit instead of depending on runner wall-clock speed.
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET valid_from = ?, refresh_requested = 0,
                build_status = 'ready', status = 'ready'
            WHERE folder_rule_id = ?
            """,
            (_one_second_after(str(first["updated_at"])), rule_id),
        )
        conn.execute(
            "UPDATE activity_inference_job SET next_attempt_at = NULL WHERE activity_id = ?",
            (activity_id,),
        )

    processed = activity_inference_job_service.process_pending_inference_jobs(
        project_inference_service.assign_project_for_activity_in_transaction,
        limit=1,
        activity_ids=[activity_id],
    )
    assert processed == 1
    after = _assignment(activity_id)
    assert after["project_id"] == project_id
    assert after["source"] == "folder_rule"
    assert after["source_rule_id"] == rule_id
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone() is None


def test_timeline_project_override_does_not_mutate_activity_assignment(temp_db):
    report_date = "2026-08-18"
    automatic_project = project_service.create_project("Automatic")
    report_project = project_service.create_project("Report Override")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Automatic",
        automatic_project,
        True,
    )
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Automatic.docx - Word",
        file_path_hint=r"D:\Automatic\Automatic.docx",
        start_time=f"{report_date} 09:00:00",
    )
    project_inference_service.assign_project_for_activity(activity_id)
    activity_service.close_activity_row(activity_id, f"{report_date} 09:10:00")
    source = timeline_api.get_project_sessions_by_date(report_date)[0]

    result = timeline_api.save_timeline_session_edit(
        report_date,
        source["projection_instance_key"],
        source["projection_revision"],
        "report-project-only",
        report_project,
        False,
        None,
        "",
    )
    assert result["ok"] is True

    assignment = _assignment(activity_id)
    assert assignment["project_id"] == automatic_project
    assert assignment["source"] == "folder_rule"
    assert assignment["source_rule_id"] == rule_id
