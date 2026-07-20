from __future__ import annotations

import inspect

import pytest

from worktrace.db import get_connection
from worktrace.services import (
    history_mutation_job_service,
    project_service,
    rule_planning_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _job_count() -> int:
    with get_connection() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS value FROM history_mutation_job"
            ).fetchone()["value"]
            or 0
        )


def _keyword_enabled(rule_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT enabled FROM project_rule WHERE id = ? AND rule_type = 'keyword'",
            (rule_id,),
        ).fetchone()
    return bool(int(row["enabled"] or 0))


def test_single_rule_job_is_durable_before_candidate_scan(temp_db, monkeypatch):
    project_id = project_service.create_project("Durable Single")
    rule_id = rule_service.create_rule("durable-single", project_id)
    observed_counts: list[int] = []
    original = rule_planning_service.load_candidate_activities

    def probe(conn, **kwargs):
        observed_counts.append(_job_count())
        return original(conn, **kwargs)

    monkeypatch.setattr(rule_planning_service, "load_candidate_activities", probe)

    result = history_mutation_job_service.submit_rule_job(
        "keyword",
        rule_id,
        kind="rule_backfill",
        synchronous_scan_limit=1,
    )

    assert observed_counts == [1]
    assert result["status"] == "completed"
    assert result["queued"] is False


def test_single_rule_scan_failure_keeps_durable_failed_job(temp_db, monkeypatch):
    project_id = project_service.create_project("Durable Single Failure")
    rule_id = rule_service.create_rule("durable-single-failure", project_id)

    def fail_after_commit(conn, **kwargs):
        assert _job_count() == 1
        raise RuntimeError("single_scan_failure")

    monkeypatch.setattr(
        rule_planning_service,
        "load_candidate_activities",
        fail_after_commit,
    )

    result = history_mutation_job_service.submit_rule_job(
        "keyword",
        rule_id,
        kind="rule_backfill",
        synchronous_scan_limit=1,
    )

    assert result["status"] == "failed"
    assert result["queued"] is False
    assert result["error"] == "single_scan_failure"
    assert _job_count() == 1


def test_remove_submission_disables_rule_and_inserts_job_atomically(temp_db, monkeypatch):
    project_id = project_service.create_project("Atomic Remove")
    rule_id = rule_service.create_rule("atomic-remove", project_id)

    def fail_insert(*args, **kwargs):
        conn = args[0]
        row = conn.execute(
            "SELECT enabled FROM project_rule WHERE id = ? AND rule_type = 'keyword'",
            (rule_id,),
        ).fetchone()
        assert int(row["enabled"] or 0) == 0
        raise RuntimeError("insert_failure")

    monkeypatch.setattr(history_mutation_job_service, "_insert_job", fail_insert)

    with pytest.raises(RuntimeError, match="insert_failure"):
        history_mutation_job_service.submit_rule_job(
            "keyword",
            rule_id,
            kind="rule_remove",
            synchronous_scan_limit=0,
        )

    assert _keyword_enabled(rule_id) is True
    assert _job_count() == 0


def test_ordered_batch_job_is_durable_before_candidate_scan(temp_db, monkeypatch):
    project_id = project_service.create_project("Durable Batch")
    first_id = rule_service.create_rule("durable-first", project_id)
    second_id = rule_service.create_rule("durable-second", project_id)
    observed_counts: list[int] = []
    original = rule_planning_service.load_candidate_activities

    def probe(conn, **kwargs):
        observed_counts.append(_job_count())
        return original(conn, **kwargs)

    monkeypatch.setattr(rule_planning_service, "load_candidate_activities", probe)

    result = history_mutation_job_service.submit_rule_batch_job(
        [
            {"rule_type": "keyword", "rule_id": first_id},
            {"rule_type": "keyword", "rule_id": second_id},
        ],
        max_updates=100,
        synchronous_scan_limit=101,
    )

    assert observed_counts == [1]
    assert result["status"] == "completed"
    assert result["queued"] is False
    assert len(result["rules"]) == 2


def test_batch_scan_failure_keeps_a_durable_failed_job(temp_db, monkeypatch):
    project_id = project_service.create_project("Durable Failure")
    rule_id = rule_service.create_rule("durable-failure", project_id)

    def fail_after_commit(conn, **kwargs):
        assert _job_count() == 1
        raise RuntimeError("planned_scan_failure")

    monkeypatch.setattr(
        rule_planning_service,
        "load_candidate_activities",
        fail_after_commit,
    )

    result = history_mutation_job_service.submit_rule_batch_job(
        [{"rule_type": "keyword", "rule_id": rule_id}],
        max_updates=100,
        synchronous_scan_limit=101,
    )

    assert result["status"] == "failed"
    assert result["queued"] is False
    assert result["error"] == "planned_scan_failure"
    assert _job_count() == 1


def test_single_rule_submission_has_one_exact_public_contract():
    signature = inspect.signature(history_mutation_job_service.submit_rule_job)
    assert tuple(signature.parameters) == (
        "rule_type",
        "rule_id",
        "kind",
        "synchronous_scan_limit",
    )
    assert signature.parameters["kind"].kind is inspect.Parameter.KEYWORD_ONLY
    assert (
        signature.parameters["synchronous_scan_limit"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )


def test_history_job_owner_delegates_rule_catalog_dml():
    text = open(history_mutation_job_service.__file__, encoding="utf-8").read()
    for forbidden in (
        "UPDATE project_rule",
        "UPDATE folder_project_rule",
        "DELETE FROM project_rule",
        "DELETE FROM folder_project_rule",
    ):
        assert forbidden not in text
    assert "rule_catalog_command_service as catalog" in text
    assert "catalog.set_rule_enabled_in_transaction" in text
    assert "catalog.delete_rule_in_transaction" in text
