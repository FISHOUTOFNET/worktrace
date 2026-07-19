"""Direct contracts for the durable closed-activity inference outbox."""
from __future__ import annotations

from pathlib import Path

import pytest

from worktrace import db
from worktrace.constants import STATUS_NORMAL
from worktrace.platforms.base import ActiveWindow
from worktrace.services import (
    activity_inference_job_repository as jobs,
    activity_inference_job_service as consumer,
    activity_lifecycle_service,
    assignment_command_service,
    clipboard_service,
)
from worktrace.services.system_project_service import require_uncategorized_project_id

pytestmark = [
    pytest.mark.unit,
    pytest.mark.db,
    pytest.mark.contract,
    pytest.mark.collector_runtime,
]

ROOT = Path(__file__).resolve().parents[1]


def _create_activity(
    *,
    closed: bool = True,
    status: str = "normal",
    hidden: bool = False,
    deleted: bool = False,
    assignment_source: str | None = None,
    manual: bool = False,
) -> int:
    timestamp = db.now_str()
    with db.get_connection() as conn:
        activity_id = int(
            conn.execute(
                """
                INSERT INTO activity_log(
                    start_time, end_time, duration_seconds, app_name,
                    process_name, window_title, file_path_hint, status, source,
                    is_deleted, is_hidden, created_at, updated_at
                ) VALUES (
                    '2026-07-18 10:00:00', ?, ?, 'Word', 'winword.exe',
                    'Matter.docx', 'C:\\Matter\\Matter.docx', ?, 'auto', ?, ?, ?, ?
                )
                """,
                (
                    "2026-07-18 10:01:00" if closed else None,
                    60 if closed else 0,
                    status,
                    int(deleted),
                    int(hidden),
                    timestamp,
                    timestamp,
                ),
            ).lastrowid
        )
        conn.execute(
            """
            INSERT INTO activity_resource(
                activity_id, resource_kind, resource_subtype, display_name,
                identity_key, is_anchor, confidence, source, app_name,
                process_name, window_title, path_hint, uri_scheme, uri_host,
                uri_hint, metadata_json, created_at, updated_at
            ) VALUES (?, 'office_document', 'word', 'Matter.docx',
                      'office_file:c:/matter/matter.docx', 1, 100, 'detector',
                      'Word', 'winword.exe', 'Matter.docx',
                      'C:\\Matter\\Matter.docx', NULL, NULL, NULL, '{}', ?, ?)
            """,
            (activity_id, timestamp, timestamp),
        )
        if assignment_source is not None:
            project_id = require_uncategorized_project_id(conn)
            assignment_command_service.upsert_assignment(
                conn,
                activity_id=activity_id,
                project_id=project_id,
                source=assignment_source,
                confidence=100 if manual else 90,
                is_manual=manual,
            )
    return activity_id


def _insert_job(activity_id: int, *, status: str = "pending") -> None:
    timestamp = db.now_str()
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO activity_inference_job(
                activity_id, reason, status, attempt_count, next_attempt_at,
                last_error_code, created_at, updated_at
            ) VALUES (?, 'closed_activity', ?, 0, NULL, NULL, ?, ?)
            """,
            (activity_id, status, timestamp, timestamp),
        )


def _job(activity_id: int):
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        return dict(row) if row else None


def test_repository_enqueues_only_canonical_closed_activity_eligibility(temp_db):
    eligible = _create_activity()
    open_id = _create_activity(closed=False)
    hidden = _create_activity(hidden=True)
    deleted = _create_activity(deleted=True)
    idle = _create_activity(status="idle")
    manual = _create_activity(assignment_source="manual", manual=True)
    midnight = _create_activity(assignment_source="midnight_anchor")

    with db.get_connection() as conn:
        inserted = jobs.enqueue_closed_activity_ids(
            conn,
            [eligible, open_id, hidden, deleted, idle, manual, midnight],
        )
        rows = conn.execute(
            "SELECT activity_id FROM activity_inference_job ORDER BY activity_id"
        ).fetchall()
    assert inserted == 1
    assert [int(row["activity_id"]) for row in rows] == [eligible]


def test_duplicate_enqueue_returns_zero(temp_db):
    activity_id = _create_activity()
    with db.get_connection() as conn:
        assert jobs.enqueue_closed_activity_ids(conn, [activity_id]) == 1
        assert jobs.enqueue_closed_activity_ids(conn, [activity_id, activity_id]) == 0


def test_enqueue_does_not_scan_existing_outbox_for_single_new_activity(temp_db):
    existing_ids = [_create_activity() for _ in range(50)]
    target_id = _create_activity()
    with db.get_connection() as conn:
        assert jobs.enqueue_closed_activity_ids(conn, existing_ids) == len(existing_ids)
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        assert jobs.enqueue_closed_activity_ids(conn, [target_id]) == 1
        conn.set_trace_callback(None)

    normalized = [" ".join(statement.casefold().split()) for statement in statements]
    assert not any(
        "count(*)" in statement and "activity_inference_job" in statement
        for statement in normalized
    )
    assert sum(
        statement.startswith("insert or ignore into activity_inference_job")
        for statement in normalized
    ) == 1


def test_enqueue_preserves_existing_failed_job_backoff(temp_db):
    activity_id = _create_activity()
    with db.get_connection() as conn:
        assert jobs.enqueue_closed_activity_ids(conn, [activity_id]) == 1
        conn.execute(
            """
            UPDATE activity_inference_job
            SET status = 'failed', attempt_count = 4,
                next_attempt_at = '2099-01-01 00:00:00',
                last_error_code = 'database_busy'
            WHERE activity_id = ?
            """,
            (activity_id,),
        )
        assert jobs.enqueue_closed_activity_ids(conn, [activity_id]) == 0
        row = conn.execute(
            """
            SELECT status, attempt_count, next_attempt_at, last_error_code
            FROM activity_inference_job
            WHERE activity_id = ?
            """,
            (activity_id,),
        ).fetchone()
    assert dict(row) == {
        "status": "failed",
        "attempt_count": 4,
        "next_attempt_at": "2099-01-01 00:00:00",
        "last_error_code": "database_busy",
    }


def test_close_and_job_enqueue_commit_atomically(temp_db, monkeypatch):
    activity_id = _create_activity(closed=False)

    def fail_enqueue(*_args, **_kwargs):
        raise RuntimeError("enqueue failed")

    monkeypatch.setattr(
        jobs,
        "enqueue_closed_activity_ids",
        fail_enqueue,
    )
    with pytest.raises(RuntimeError, match="enqueue failed"):
        activity_lifecycle_service.close_activity(
            activity_id,
            "2026-07-18 10:01:00",
            duration_seconds=60,
        )

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT end_time FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        assert row["end_time"] is None
        assert _job(activity_id) is None


def test_consumer_assignment_and_job_delete_commit_together(temp_db):
    activity_id = _create_activity()
    with db.get_connection() as conn:
        jobs.enqueue_closed_activity_ids(conn, [activity_id])

    def infer(conn, target_id):
        project_id = require_uncategorized_project_id(conn)
        assignment_command_service.upsert_assignment(
            conn,
            activity_id=target_id,
            project_id=project_id,
            source="uncategorized",
            confidence=0,
        )
        return {"activity_id": target_id}

    assert consumer.process_pending_inference_jobs(infer, limit=10) == 1
    with db.get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        assert conn.execute(
            "SELECT 1 FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone() is None


def test_consumer_rolls_back_assignment_when_job_completion_fails(
    temp_db,
    monkeypatch,
):
    activity_id = _create_activity()
    with db.get_connection() as conn:
        jobs.enqueue_closed_activity_ids(conn, [activity_id])

    def infer(conn, target_id):
        assignment_command_service.upsert_assignment(
            conn,
            activity_id=target_id,
            project_id=require_uncategorized_project_id(conn),
            source="uncategorized",
            confidence=0,
        )
        return {}

    monkeypatch.setattr(
        jobs,
        "delete_job",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("delete failed")),
    )
    assert consumer.process_pending_inference_jobs(infer, limit=1) == 0
    with db.get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone() is None
        row = conn.execute(
            "SELECT status, attempt_count FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert row["status"] == "failed"
    assert row["attempt_count"] == 1


def test_consumer_failure_retains_job_with_bounded_backoff(temp_db):
    activity_id = _create_activity()
    with db.get_connection() as conn:
        jobs.enqueue_closed_activity_ids(conn, [activity_id])

    def fail(_conn, _activity_id):
        raise RuntimeError("inference failed")

    assert consumer.process_pending_inference_jobs(fail, limit=1) == 0
    row = _job(activity_id)
    assert row["status"] == "failed"
    assert row["attempt_count"] == 1
    assert row["next_attempt_at"] is not None
    assert row["last_error_code"] == "unexpected_failure"


def test_manual_assignment_is_never_overwritten_and_stale_job_is_deleted(temp_db):
    activity_id = _create_activity(assignment_source="manual", manual=True)
    _insert_job(activity_id)
    calls: list[int] = []

    assert consumer.process_pending_inference_jobs(
        lambda _conn, target: calls.append(target) or {},
        limit=1,
    ) == 1
    assert calls == []
    assert _job(activity_id) is None
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert row["source"] == "manual"
    assert row["is_manual"] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hidden": True},
        {"deleted": True},
        {"status": "idle"},
        {"assignment_source": "midnight_anchor"},
    ],
)
def test_consumer_drops_jobs_that_are_no_longer_eligible(temp_db, kwargs):
    activity_id = _create_activity(**kwargs)
    _insert_job(activity_id)
    assert consumer.process_pending_inference_jobs(
        lambda *_args: pytest.fail("stale job must not infer"),
        limit=1,
    ) == 1
    assert _job(activity_id) is None


def test_open_activity_never_receives_closed_activity_job(temp_db):
    activity_id = _create_activity(closed=False)
    with db.get_connection() as conn:
        assert jobs.enqueue_closed_activity_ids(conn, [activity_id]) == 0
    assert _job(activity_id) is None


def test_clipboard_closed_row_enqueues_but_open_row_only_syncs(
    temp_db,
    monkeypatch,
):
    closed_id = _create_activity()
    open_id = _create_activity(closed=False)
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE settings SET value = 'true' WHERE key = 'clipboard_capture_enabled'"
        )
    synced: list[int] = []
    monkeypatch.setattr(
        "worktrace.services.project_inference_service.sync_persisted_open_activity_project",
        lambda activity_id: synced.append(activity_id) or {},
    )
    window = ActiveWindow(
        app_name="Word",
        process_name="winword.exe",
        window_title="Matter.docx",
        file_path_hint="C:\\Matter\\Matter.docx",
    )

    assert clipboard_service.record_clipboard_event(closed_id, "closed fact", window)
    assert clipboard_service.record_clipboard_event(open_id, "open fact", window)
    assert _job(closed_id) is not None
    assert _job(open_id) is None
    assert synced == [open_id]


def test_job_schema_and_runtime_have_no_legacy_state_or_second_consumer() -> None:
    schema = (ROOT / "worktrace/schema_internal.sql").read_text(encoding="utf-8")
    runtime = (ROOT / "worktrace/runtime/app_runtime.py").read_text(encoding="utf-8")
    lifecycle = (
        ROOT / "worktrace/services/activity_lifecycle_service.py"
    ).read_text(encoding="utf-8")
    assert "reason TEXT NOT NULL CHECK(reason = 'closed_activity')" in schema
    assert "status TEXT NOT NULL CHECK(status IN ('pending', 'failed'))" in schema
    assert "legacy_retry" not in schema
    assert "retry_pending_inference" not in runtime
    assert "process_new_activity" not in lifecycle
    assert runtime.index("self.start_collector()") < runtime.index(
        "self.start_background_workers()"
    )


def test_published_versions_are_current_only() -> None:
    from worktrace.services import secure_backup_service

    assert db.CURRENT_SCHEMA_VERSION == 11
    assert secure_backup_service.PAYLOAD_VERSION == 5
    assert "activity_inference_job" not in secure_backup_service.EXPORT_TABLES
    assert "activity_inference_job" in secure_backup_service.EXCLUDED_TABLES
