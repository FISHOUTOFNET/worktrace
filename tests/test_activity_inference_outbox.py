from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from worktrace.db import get_connection
from worktrace.services import (
    activity_inference_job_repository as jobs,
    activity_inference_job_service as worker,
    assignment_command_service,
)

pytestmark = [pytest.mark.db, pytest.mark.contract]
ROOT = Path(__file__).resolve().parents[1]


def _insert_closed_activity(conn, *, status: str = "normal") -> int:
    timestamp = "2026-07-18 10:00:00"
    cursor = conn.execute(
        """
        INSERT INTO activity_log(
            start_time, end_time, duration_seconds, app_name, process_name,
            window_title, status, source, is_hidden, is_deleted,
            created_at, updated_at
        ) VALUES (?, ?, 60, 'Word', 'winword.exe', 'Doc', ?, 'test', 0, 0, ?, ?)
        """,
        (timestamp, "2026-07-18 10:01:00", status, timestamp, timestamp),
    )
    activity_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO activity_resource(
            activity_id, resource_kind, resource_subtype, display_name,
            identity_key, is_anchor, confidence, source, app_name,
            process_name, window_title, metadata_json, created_at, updated_at
        ) VALUES (?, 'app', 'generic', 'Doc', ?, 1, 100, 'test',
                  'Word', 'winword.exe', 'Doc', '{}', ?, ?)
        """,
        (activity_id, f"app:{activity_id}", timestamp, timestamp),
    )
    return activity_id


def test_enqueue_resets_backoff_and_preserves_created_at(temp_db):
    with get_connection() as conn:
        activity_id = _insert_closed_activity(conn)
        assert jobs.enqueue_closed_activity_ids(
            conn,
            [activity_id],
            at_time="2026-07-18 10:02:00",
        ) == 1
        jobs.record_failure(
            conn,
            activity_id,
            jobs.InferenceJobErrorCode.INFERENCE_FAILED,
            at_time="2026-07-18 10:03:00",
        )
        created_at = conn.execute(
            "SELECT created_at FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()[0]
        jobs.enqueue_closed_activity_ids(
            conn,
            [activity_id],
            reason=jobs.REASON_FACTS_CHANGED,
            at_time="2026-07-18 10:04:00",
        )
        row = conn.execute(
            "SELECT * FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert row["reason"] == jobs.REASON_FACTS_CHANGED
    assert row["attempt_count"] == 0
    assert row["available_at"] == "2026-07-18 10:04:00"
    assert row["last_error_code"] is None
    assert row["created_at"] == created_at


def test_worker_commits_assignment_and_job_delete_together(temp_db):
    with get_connection() as conn:
        activity_id = _insert_closed_activity(conn)
        jobs.enqueue_closed_activity_ids(conn, [activity_id])

    def infer(conn, target_id: int) -> dict:
        assignment_command_service.upsert_assignment(
            conn,
            activity_id=target_id,
            project_id=None,
            source="uncategorized",
            confidence=0,
        )
        return {"activity_id": target_id}

    assert worker.process_pending_inference_jobs(infer, limit=10) == 1
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone() is None
        assert conn.execute(
            "SELECT source FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()[0] == "uncategorized"


def test_failure_rolls_back_assignment_and_retains_job(temp_db):
    with get_connection() as conn:
        activity_id = _insert_closed_activity(conn)
        jobs.enqueue_closed_activity_ids(conn, [activity_id])

    def fail_after_write(conn, target_id: int) -> dict:
        assignment_command_service.upsert_assignment(
            conn,
            activity_id=target_id,
            project_id=None,
            source="uncategorized",
            confidence=0,
        )
        raise RuntimeError("controlled failure")

    assert worker.process_pending_inference_jobs(fail_after_write, limit=10) == 0
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone() is None
        row = conn.execute(
            "SELECT attempt_count, last_error_code FROM activity_inference_job "
            "WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert row["attempt_count"] == 1
    assert row["last_error_code"] == jobs.InferenceJobErrorCode.INFERENCE_FAILED.value


def test_manual_and_midnight_assignments_are_not_enqueued(temp_db):
    with get_connection() as conn:
        manual_id = _insert_closed_activity(conn)
        midnight_id = _insert_closed_activity(conn)
        for activity_id, source, manual in (
            (manual_id, "manual", 1),
            (midnight_id, "midnight_anchor", 0),
        ):
            assignment_command_service.upsert_assignment(
                conn,
                activity_id=activity_id,
                project_id=None,
                source=source,
                confidence=100,
                is_manual=bool(manual),
            )
        assert jobs.enqueue_closed_activity_ids(
            conn,
            [manual_id, midnight_id],
        ) == 0


def test_outbox_has_no_claim_state_or_global_execution_lock():
    repository_source = (
        ROOT / "worktrace/services/activity_inference_job_repository.py"
    ).read_text(encoding="utf-8")
    worker_source = (
        ROOT / "worktrace/services/activity_inference_job_service.py"
    ).read_text(encoding="utf-8")
    assignment_source = (
        ROOT / "worktrace/services/assignment_command_service.py"
    ).read_text(encoding="utf-8")
    assert "_EXECUTION_LOCK" not in worker_source
    assert "recover_interrupted" not in worker_source
    assert "mark_running" not in repository_source
    assert "status TEXT" not in repository_source
    assert "activity_inference_job_repository" not in assignment_source
    assert "INFERENCE_RETRY_CONFIDENCE" not in assignment_source


def test_error_code_boundary_rejects_arbitrary_strings(temp_db):
    with get_connection() as conn:
        activity_id = _insert_closed_activity(conn)
        jobs.enqueue_closed_activity_ids(conn, [activity_id])
        with pytest.raises(TypeError, match="inference_job_error_code_required"):
            jobs.record_failure(
                conn,
                activity_id,
                "C:/secret/client.txt",  # type: ignore[arg-type]
            )
