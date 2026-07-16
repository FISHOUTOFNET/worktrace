"""Origin tracking and recoverable historical rule mutation regressions."""

from __future__ import annotations

from datetime import datetime

import pytest

from worktrace.api import rule_api
from worktrace.db import get_connection, now_str
from worktrace.services import (
    activity_service,
    folder_rule_service,
    history_mutation_job_service,
    project_inference_service,
    project_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _closed_activity(title: str = "Spec document") -> int:
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        title,
        start_time="2026-06-18 09:00:00",
    )
    duration = int(
        (
            datetime(2026, 6, 18, 9, 10)
            - datetime(2026, 6, 18, 9)
        ).total_seconds()
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET end_time = ?, duration_seconds = ?, updated_at = ? WHERE id = ?",
            ("2026-06-18 09:10:00", duration, now_str(), activity_id),
        )
    return activity_id


def test_future_inference_and_history_apply_record_exact_keyword_origin(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    activity_id = _closed_activity()

    project_inference_service.assign_project_for_activity(activity_id)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT source, source_rule_type, source_rule_id FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert dict(row) == {
        "source": "keyword_rule",
        "source_rule_type": "keyword",
        "source_rule_id": rule_id,
    }

    result = rule_api.backfill_project_rule("keyword", rule_id)
    assert result["ok"] is True


def test_delete_history_reassigns_only_exact_non_manual_rule_origin(temp_db):
    first_project = project_service.create_project("First")
    second_project = project_service.create_project("Second")
    first_rule = rule_service.create_rule("Spec", first_project)
    second_rule = rule_service.create_rule("Spec", second_project)
    activity_id = _closed_activity()
    project_inference_service.assign_project_for_activity(activity_id)

    manual_activity_id = _closed_activity("Spec manual")
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_project_assignment SET project_id = ?, source = 'manual', is_manual = 1, source_rule_type = NULL, source_rule_id = NULL, updated_at = ? WHERE activity_id = ?",
            (first_project, now_str(), manual_activity_id),
        )

    result = rule_api.delete_project_keyword_rule(first_rule, True)
    assert result["ok"] is True
    assert result["rule"]["history_updated"] is True
    with get_connection() as conn:
        reassigned = conn.execute(
            "SELECT project_id, source_rule_type, source_rule_id FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        manual = conn.execute(
            "SELECT project_id, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (manual_activity_id,),
        ).fetchone()
    assert dict(reassigned) == {
        "project_id": second_project,
        "source_rule_type": "keyword",
        "source_rule_id": second_rule,
    }
    assert dict(manual) == {"project_id": first_project, "is_manual": 1}


def test_delete_rule_rejects_non_bool_history_flag(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    for invalid in (None, 1, "true", [], {}):
        assert rule_api.delete_project_keyword_rule(rule_id, invalid) == {
            "ok": False,
            "error": "invalid_input",
        }


def test_delete_keyword_rule_rolls_back_when_direct_reassignment_fails(
    temp_db,
    monkeypatch,
):
    first_project = project_service.create_project("First")
    second_project = project_service.create_project("Second")
    first_rule = rule_service.create_rule("Spec", first_project)
    second_rule = rule_service.create_rule("Spec", second_project)
    activity_id = _closed_activity()
    project_inference_service.assign_project_for_activity(activity_id)

    def boom(*args, **kwargs):
        raise RuntimeError("reassignment boom")

    monkeypatch.setattr(
        project_inference_service,
        "_assign_project_for_activity_in_transaction",
        boom,
    )

    result = rule_api.delete_project_keyword_rule(first_rule, True)

    assert result == {"ok": False, "error": "operation_failed"}
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id, source_rule_id FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        rule = conn.execute(
            "SELECT id, enabled FROM project_rule WHERE id = ?",
            (first_rule,),
        ).fetchone()
    assert dict(assignment) == {
        "project_id": first_project,
        "source_rule_id": first_rule,
    }
    assert dict(rule) == {"id": first_rule, "enabled": 1}
    assert second_rule != first_rule


def test_delete_keyword_rule_rolls_back_when_final_delete_fails(
    temp_db,
    monkeypatch,
):
    first_project = project_service.create_project("First")
    second_project = project_service.create_project("Second")
    first_rule = rule_service.create_rule("Spec", first_project)
    rule_service.create_rule("Spec", second_project)
    activity_id = _closed_activity()
    project_inference_service.assign_project_for_activity(activity_id)

    def boom(*args, **kwargs):
        raise RuntimeError("delete boom")

    monkeypatch.setattr(
        history_mutation_job_service,
        "_finalize_rule_in_transaction",
        boom,
    )

    result = rule_api.delete_project_keyword_rule(first_rule, True)

    assert result == {"ok": False, "error": "operation_failed"}
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id, source_rule_id FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        rule = conn.execute(
            "SELECT id, enabled FROM project_rule WHERE id = ?",
            (first_rule,),
        ).fetchone()
    assert dict(assignment) == {
        "project_id": first_project,
        "source_rule_id": first_rule,
    }
    assert dict(rule) == {"id": first_rule, "enabled": 1}


def test_delete_folder_rule_rolls_back_index_and_rule_when_final_stage_fails(
    temp_db,
    monkeypatch,
):
    project = project_service.create_project("Folder Project")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client",
        project,
    )

    with get_connection() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM folder_rule_index_state WHERE folder_rule_id = ?",
                (rule_id,),
            ).fetchone()[0]
            == 1
        )

    def boom_after_index_delete(conn, job, payload):
        conn.execute(
            "DELETE FROM folder_rule_index_state WHERE folder_rule_id = ?",
            (int(payload["rule_id"]),),
        )
        raise RuntimeError("index delete boom")

    monkeypatch.setattr(
        history_mutation_job_service,
        "_finalize_rule_in_transaction",
        boom_after_index_delete,
    )

    result = rule_api.delete_project_folder_rule(rule_id, True)

    assert result == {"ok": False, "error": "operation_failed"}
    with get_connection() as conn:
        rule = conn.execute(
            "SELECT id, enabled FROM folder_project_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
        index_state = conn.execute(
            "SELECT folder_rule_id FROM folder_rule_index_state WHERE folder_rule_id = ?",
            (rule_id,),
        ).fetchone()
    assert dict(rule) == {"id": rule_id, "enabled": 1}
    assert index_state is not None
