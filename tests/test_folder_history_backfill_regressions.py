from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.api import rule_history_api
from worktrace.db import get_connection
from worktrace.services import (
    folder_index_service,
    folder_rule_service,
    history_mutation_job_service,
    project_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _closed_activity(title: str, start_time: str, end_time: str) -> int:
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        title,
        start_time=start_time,
    )
    activity_service.close_activity_row(activity_id, end_time)
    return activity_id


def test_folder_backfill_waits_for_first_index_without_advancing_cursor(
    temp_db,
    tmp_path,
    allow_sensitive_runtime,
):
    project_id = project_service.create_project("Deferred Folder History")
    folder = tmp_path / "DeferredHistory"
    folder.mkdir()
    (folder / "report.docx").write_text("doc", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        str(folder),
        project_id,
    )
    activity_id = _closed_activity(
        "report.docx - Word",
        "2026-06-18 09:00:00",
        "2026-06-18 09:10:00",
    )

    submitted = rule_history_api.backfill_project_rule("folder", rule_id)

    assert submitted["ok"] is True
    pending = submitted["result"]
    assert pending["status"] == "pending"
    assert pending["queued"] is True
    assert pending["processed_count"] == 0
    assert pending["updated_count"] == 0
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT cursor_activity_id, processed_count, changed_count
            FROM history_mutation_job
            WHERE id = ?
            """,
            (pending["job_id"],),
        ).fetchone()
    assert dict(row) == {
        "cursor_activity_id": 0,
        "processed_count": 0,
        "changed_count": 0,
    }

    assert folder_index_service.rebuild_folder_index(rule_id) is True
    assert history_mutation_job_service.run_pending_jobs(limit=1) == 1

    completed = history_mutation_job_service.job_result(pending["job_id"])
    assert completed["status"] == "completed"
    assert completed["updated_count"] == 1
    assert activity_service.get_activity(activity_id)["project_id"] == project_id


def test_waiting_folder_backfill_does_not_block_ready_keyword_job(
    temp_db,
    tmp_path,
    allow_sensitive_runtime,
):
    folder_project = project_service.create_project("Waiting Folder")
    folder = tmp_path / "WaitingFolder"
    folder.mkdir()
    (folder / "folder.docx").write_text("doc", encoding="utf-8")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule(
        str(folder),
        folder_project,
    )

    keyword_project = project_service.create_project("Ready Keyword")
    keyword_rule_id = rule_service.create_rule("Spec", keyword_project)
    activity_id = _closed_activity(
        "Spec.docx - Word",
        "2026-06-18 10:00:00",
        "2026-06-18 10:10:00",
    )

    folder_job = history_mutation_job_service.submit_rule_job(
        "folder",
        folder_rule_id,
        kind="rule_backfill",
        synchronous_scan_limit=0,
    )
    keyword_job = history_mutation_job_service.submit_rule_job(
        "keyword",
        keyword_rule_id,
        kind="rule_backfill",
        synchronous_scan_limit=0,
    )

    assert folder_job["status"] == "pending"
    assert keyword_job["status"] == "pending"
    assert history_mutation_job_service.run_pending_jobs(limit=1) == 1

    assert history_mutation_job_service.job_result(folder_job["job_id"])["status"] == "pending"
    keyword_result = history_mutation_job_service.job_result(keyword_job["job_id"])
    assert keyword_result["status"] == "completed"
    assert keyword_result["updated_count"] == 1
    assert activity_service.get_activity(activity_id)["project_id"] == keyword_project


def test_folder_backfill_fails_after_terminal_index_build_error(
    temp_db,
    tmp_path,
    allow_sensitive_runtime,
):
    project_id = project_service.create_project("Unavailable Folder History")
    missing_folder = tmp_path / "MissingHistoryFolder"
    rule_id = folder_rule_service.create_or_update_folder_rule(
        str(missing_folder),
        project_id,
    )
    _closed_activity(
        "missing.docx - Word",
        "2026-06-18 11:00:00",
        "2026-06-18 11:10:00",
    )

    submitted = history_mutation_job_service.submit_rule_job(
        "folder",
        rule_id,
        kind="rule_backfill",
        synchronous_scan_limit=0,
    )
    assert submitted["status"] == "pending"
    assert folder_index_service.rebuild_folder_index(rule_id) is False

    assert history_mutation_job_service.run_pending_jobs(limit=1) == 1
    failed = history_mutation_job_service.job_result(submitted["job_id"])
    assert failed["status"] == "failed"
    assert failed["error"] == "folder_index_unavailable"
    assert failed["processed_count"] == 0
