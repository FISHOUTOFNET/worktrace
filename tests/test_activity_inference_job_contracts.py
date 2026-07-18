"""Contracts for durable inference scheduling and explicit Collector retries."""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

import pytest

from worktrace.collector import collector_health
from worktrace.db import get_connection
from worktrace.schema_migrations import migrate_10_to_11
from worktrace.services import (
    activity_lifecycle_service,
    assignment_command_service,
    project_inference_service,
    project_service,
)

pytestmark = [pytest.mark.db, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]


def _payload(title: str = "Architecture Spec.docx") -> dict[str, object]:
    return {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": title,
        "file_path_hint": f"D:\\Client\\{title}",
        "status": "normal",
    }


def test_close_commit_keeps_inference_job_when_immediate_consumer_fails(
    temp_db,
    monkeypatch,
):
    activity_id = activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-18 09:00:00",
        source="auto",
        payload=_payload(),
    )
    original = project_inference_service.process_pending_inference_jobs

    def fail_after_commit(*_args, **_kwargs):
        raise RuntimeError("simulated_process_exit")

    monkeypatch.setattr(
        project_inference_service,
        "process_pending_inference_jobs",
        fail_after_commit,
    )
    activity_lifecycle_service.close_activity(
        activity_id,
        "2026-07-18 09:05:00",
    )

    with get_connection() as conn:
        job = conn.execute(
            "SELECT status, attempt_count FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        activity = conn.execute(
            "SELECT end_time FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    assert activity["end_time"] == "2026-07-18 09:05:00"
    assert dict(job) == {"status": "pending", "attempt_count": 0}

    monkeypatch.setattr(
        project_inference_service,
        "process_pending_inference_jobs",
        original,
    )
    assert original(limit=1, activity_ids=[activity_id]) == 1
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone() is None
        assignment = conn.execute(
            "SELECT source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert assignment is not None
    assert int(assignment["is_manual"] or 0) == 0


def test_manual_assignment_is_not_scheduled_for_inference(temp_db, monkeypatch):
    project_id = project_service.create_project("Manual Project")
    activity_id = activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-18 10:00:00",
        source="auto",
        payload=_payload("Manual.docx"),
    )
    assignment_command_service.assign_with_uow(
        activity_id=activity_id,
        project_id=project_id,
        source="manual",
        confidence=100,
        is_manual=True,
    )
    monkeypatch.setattr(
        project_inference_service,
        "process_pending_inference_jobs",
        lambda *_args, **_kwargs: 0,
    )
    activity_lifecycle_service.close_activity(
        activity_id,
        "2026-07-18 10:05:00",
    )
    with get_connection() as conn:
        job = conn.execute(
            "SELECT 1 FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        assignment = conn.execute(
            "SELECT project_id, source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert job is None
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "manual"
    assert int(assignment["is_manual"]) == 1


def test_v10_migration_seeds_only_eligible_closed_rows(temp_db):
    eligible = activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-18 11:00:00",
        source="auto",
        payload=_payload("Eligible.docx"),
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET end_time = '2026-07-18 11:05:00' WHERE id = ?",
            (eligible,),
        )

    manual = activity_lifecycle_service.persist_open_activity(
        start_time="2026-07-18 11:10:00",
        source="auto",
        payload=_payload("ManualMigration.docx"),
    )
    project_id = project_service.create_project("Migration Manual")
    assignment_command_service.assign_with_uow(
        activity_id=manual,
        project_id=project_id,
        source="manual",
        confidence=100,
        is_manual=True,
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET end_time = '2026-07-18 11:15:00' WHERE id = ?",
            (manual,),
        )
        conn.execute("DROP TABLE activity_inference_job")
        migrate_10_to_11(conn)
        ids = {
            int(row["activity_id"])
            for row in conn.execute(
                "SELECT activity_id FROM activity_inference_job"
            ).fetchall()
        }
    assert eligible in ids
    assert manual not in ids


def test_collector_retries_only_explicit_transient_failures():
    for fatal in (
        ValueError("bad payload"),
        RuntimeError("broken invariant"),
        IndexError("bad index"),
        sqlite3.DatabaseError("database disk image is malformed"),
    ):
        assert collector_health.is_transient_failure(fatal) is False

    assert collector_health.is_transient_failure(
        sqlite3.OperationalError("database is locked")
    ) is True
    assert collector_health.is_transient_failure(
        sqlite3.OperationalError("secure_import_in_progress")
    ) is True
    assert collector_health.is_transient_failure(
        collector_health.TransientCollectorError("temporary adapter failure")
    ) is True


def test_inference_job_has_one_live_dml_owner():
    pattern = re.compile(
        r"\b(INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)"
        r"\s+activity_inference_job\b",
        re.IGNORECASE,
    )
    owners: set[str] = set()
    for path in sorted((ROOT / "worktrace").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and pattern.search(node.value)
            for node in ast.walk(tree)
        ):
            owners.add(path.relative_to(ROOT).as_posix())
    assert owners == {
        "worktrace/schema_migrations.py",
        "worktrace/services/activity_inference_job_repository.py",
    }
