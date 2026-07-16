"""Regression tests for the architecture scalability hardening cutover."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from tests.support import activity_factory as activity_service
from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL
from worktrace.db import get_connection
from worktrace.services import (
    activity_fact_repository,
    folder_index_service,
    folder_rule_service,
    history_mutation_job_service,
    project_service,
    rule_service,
)
from worktrace.services.activity_lifecycle_service import (
    persist_open_activity,
    start_activity,
)
from worktrace.services.project_inference_service import get_assignment_for_activity

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.collector_runtime,
]


def _normal_payload(title: str = "Document") -> dict:
    return {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": title,
        "status": STATUS_NORMAL,
    }


def test_open_fact_insert_rolls_back_as_one_unit(temp_db, monkeypatch):
    """Activity, assignment and resource must never become partially visible."""

    def fail_resource_write(*_args, **_kwargs):
        raise RuntimeError("resource write failed")

    monkeypatch.setattr(
        activity_fact_repository,
        "create_or_update_activity_resource",
        fail_resource_write,
    )

    with pytest.raises(RuntimeError, match="resource write failed"):
        persist_open_activity(
            start_time="2026-07-16 09:00:00",
            source=SOURCE_AUTO,
            payload=_normal_payload(),
        )
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM activity_project_assignment"
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM activity_resource"
        ).fetchone()["c"] == 0


def test_open_row_invariant_and_lifecycle_transition_owner(temp_db):
    first = persist_open_activity(
        start_time="2026-07-16 09:00:00",
        source=SOURCE_AUTO,
        payload=_normal_payload("First"),
    )

    with pytest.raises(sqlite3.IntegrityError):
        activity_service.create_activity(
            "Word",
            "winword.exe",
            "Fixture second open row",
            start_time="2026-07-16 09:01:00",
        )
    assert activity_service.get_activity(first)["end_time"] is None

    second = start_activity(
        start_time="2026-07-16 09:05:00",
        source=SOURCE_AUTO,
        payload=_normal_payload("Second"),
    )

    with get_connection() as conn:
        open_rows = conn.execute(
            "SELECT id FROM activity_log WHERE end_time IS NULL"
        ).fetchall()
    assert [int(row["id"]) for row in open_rows] == [second]
    assert activity_service.get_activity(first)["end_time"] == "2026-07-16 09:05:00"


def test_failed_folder_generation_preserves_previous_active_index(
    temp_db,
    tmp_path: Path,
    monkeypatch,
):
    project_id = project_service.create_project("Indexed Project")
    folder = tmp_path / "Indexed"
    folder.mkdir()
    indexed_file = folder / "brief.docx"
    indexed_file.write_text("content", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        str(folder),
        project_id,
    )
    assert folder_index_service.rebuild_folder_index(rule_id)

    before = folder_index_service.lookup_indexed_paths_for_file_name("brief.docx")
    assert [Path(row["file_path"]) for row in before] == [indexed_file]
    with get_connection() as conn:
        active_before = int(
            conn.execute(
                "SELECT active_generation FROM folder_rule_index_state WHERE folder_rule_id = ?",
                (rule_id,),
            ).fetchone()["active_generation"]
        )

    def broken_scan(*_args, **_kwargs):
        raise RuntimeError("scan interrupted")
        yield  # pragma: no cover

    monkeypatch.setattr(folder_index_service, "_iter_files", broken_scan)
    assert folder_index_service.rebuild_folder_index(rule_id) is False

    after = folder_index_service.lookup_indexed_paths_for_file_name("brief.docx")
    assert [Path(row["file_path"]) for row in after] == [indexed_file]
    with get_connection() as conn:
        state = conn.execute(
            """
            SELECT status, active_generation, building_generation, build_status
            FROM folder_rule_index_state WHERE folder_rule_id = ?
            """,
            (rule_id,),
        ).fetchone()
    assert int(state["active_generation"]) == active_before
    assert state["building_generation"] is None
    assert state["status"] == "ready"
    assert state["build_status"] == "error"


def test_history_backfill_resumes_from_cursor_in_bounded_batches(temp_db):
    project_id = project_service.create_project("Client Alpha")
    rule_id = rule_service.create_rule("alpha matter", project_id)

    activity_ids: list[int] = []
    for index in range(3):
        start_minute = index * 10
        activity_id = activity_service.create_activity(
            "Word",
            "winword.exe",
            f"alpha matter document {index}",
            start_time=f"2026-07-16 10:{start_minute:02d}:00",
        )
        activity_service.close_activity_row(
            activity_id,
            f"2026-07-16 10:{start_minute + 5:02d}:00",
        )
        activity_ids.append(activity_id)

    submitted = history_mutation_job_service.submit_rule_job(
        "rule_backfill",
        "keyword",
        rule_id,
        synchronous_limit=0,
    )
    assert submitted["queued"] is True

    first_batch = history_mutation_job_service.run_job_batch(
        int(submitted["job_id"]),
        batch_size=1,
    )
    assert first_batch["status"] == "running"
    assert first_batch["processed_count"] == 1
    assert first_batch["updated_count"] == 1

    completed = history_mutation_job_service.run_job_to_completion(
        int(submitted["job_id"])
    )
    assert completed["status"] == "completed"
    assert completed["processed_count"] == 3
    assert completed["updated_count"] == 3
    assert all(
        int(get_assignment_for_activity(activity_id)["project_id"]) == project_id
        for activity_id in activity_ids
    )
