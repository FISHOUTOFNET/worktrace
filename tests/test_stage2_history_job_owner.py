from __future__ import annotations

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
        "rule_backfill",
        "keyword",
        rule_id,
        synchronous_limit=1,
    )

    assert observed_counts == [1]
    assert result["status"] == "completed"
    assert result["queued"] is False


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
