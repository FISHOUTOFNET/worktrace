from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import activity_factory as activity_service
from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.services import (
    history_mutation_job_service,
    project_service,
    rule_batch_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _generation(namespace: DataGenerationNamespace) -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(conn, namespace)


def _closed_activity(title: str, minute: int = 0) -> int:
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        title,
        start_time=f"2026-07-17 14:{minute:02d}:00",
    )
    activity_service.close_activity_row(
        activity_id,
        f"2026-07-17 14:{minute + 5:02d}:00",
    )
    return activity_id


def test_bounded_rule_batch_publishes_report_once(temp_db):
    project_id = project_service.create_project("Batch UoW")
    rule_id = rule_service.create_rule("batch-uow-keyword", project_id)
    first = _closed_activity("batch-uow-keyword first", 0)
    second = _closed_activity("batch-uow-keyword second", 10)
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    result = rule_batch_service.backfill_project_rules_batch(
        [{"rule_type": "keyword", "rule_id": rule_id}]
    )

    assert result["counts"]["updated_count"] == 2
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before + 1
    with get_connection() as conn:
        assigned = {
            int(row["activity_id"]): int(row["project_id"])
            for row in conn.execute(
                "SELECT activity_id, project_id FROM activity_project_assignment "
                "WHERE activity_id IN (?, ?)",
                (first, second),
            ).fetchall()
        }
    assert assigned == {first: project_id, second: project_id}


def test_batch_enable_semantic_no_op_publishes_nothing(temp_db):
    project_id = project_service.create_project("Batch Stable")
    rule_id = rule_service.create_rule("batch-stable-keyword", project_id)
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    privacy_before = _generation(DataGenerationNamespace.PRIVACY_CATALOG)
    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    result = rule_batch_service.set_project_rules_batch_enabled(
        [{"rule_type": "keyword", "rule_id": rule_id}],
        True,
    )

    assert result["enabled"] is True
    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before
    assert _generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before


def test_history_submission_metadata_does_not_publish_business_generation(temp_db):
    project_id = project_service.create_project("History Metadata")
    rule_id = rule_service.create_rule("history-metadata", project_id)
    _closed_activity("history-metadata document", 20)
    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)
    catalog_before = _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)

    submitted = history_mutation_job_service.submit_rule_job(
        "keyword",
        rule_id,
        kind="rule_backfill",
        synchronous_scan_limit=0,
    )

    assert submitted["queued"] is True
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before
    assert _generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == catalog_before


def test_history_batch_commits_assignment_and_cursor_with_one_report_generation(temp_db):
    project_id = project_service.create_project("History Batch")
    rule_id = rule_service.create_rule("history-batch", project_id)
    activity_id = _closed_activity("history-batch document", 30)
    submitted = history_mutation_job_service.submit_rule_job(
        "keyword",
        rule_id,
        kind="rule_backfill",
        synchronous_scan_limit=0,
    )
    before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)

    result = history_mutation_job_service.run_job_batch(
        int(submitted["job_id"]),
        batch_size=1,
    )

    assert result["processed_count"] == 1
    assert result["updated_count"] == 1
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == before + 1
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        job = conn.execute(
            "SELECT cursor_activity_id, processed_count, changed_count "
            "FROM history_mutation_job WHERE id = ?",
            (int(submitted["job_id"]),),
        ).fetchone()
    assert int(assignment["project_id"]) == project_id
    assert int(job["cursor_activity_id"]) == activity_id
    assert int(job["processed_count"]) == 1
    assert int(job["changed_count"]) == 1


def test_bounded_mutation_owner_has_uow_and_facade_does_not():
    root = Path(__file__).resolve().parents[1]
    owner = root.joinpath(
        "worktrace/services/history_mutation_job_service.py"
    ).read_text(encoding="utf-8")
    facade = root.joinpath(
        "worktrace/services/rule_batch_service.py"
    ).read_text(encoding="utf-8")

    assert "DomainUnitOfWork" in owner
    assert "DomainUnitOfWork" not in facade
    assert "submit_rule_batch_job" in facade
    for source in (owner, facade):
        assert "BEGIN IMMEDIATE" not in source
        assert ".commit()" not in source
        assert ".rollback()" not in source
