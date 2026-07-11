"""Origin tracking and precise historical rule removal regressions."""

from __future__ import annotations

from datetime import datetime

from worktrace.api import rule_api
from worktrace.db import get_connection, now_str
from worktrace.services import activity_service, project_inference_service, project_service, rule_service


def _closed_activity(title: str = "Spec document") -> int:
    activity_id = activity_service.create_activity(
        "Word", "winword.exe", title,
        start_time="2026-06-18 09:00:00",
    )
    duration = int((datetime(2026, 6, 18, 9, 10) - datetime(2026, 6, 18, 9)).total_seconds())
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
    assert dict(row) == {"source": "keyword_rule", "source_rule_type": "keyword", "source_rule_id": rule_id}

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
    assert dict(reassigned) == {"project_id": second_project, "source_rule_type": "keyword", "source_rule_id": second_rule}
    assert dict(manual) == {"project_id": first_project, "is_manual": 1}


def test_delete_rule_rejects_non_bool_history_flag(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    for invalid in (None, 1, "true", [], {}):
        assert rule_api.delete_project_keyword_rule(rule_id, invalid) == {"ok": False, "error": "invalid_input"}
