from __future__ import annotations

import sqlite3
import threading

import pytest

from worktrace.api import timeline_api
from worktrace.db import get_connection
from worktrace.services import activity_service, project_service
from worktrace.services import report_session_operation_service as mutations
from worktrace.services import secure_backup_service
from worktrace.services.report_projection_identity import DURABLE_REVISION_PREFIX
from worktrace.services.report_projection_snapshot_service import (
    build_visible_snapshot,
    snapshot_read_scope,
)
from worktrace.services.settings_service import set_setting
from worktrace.write_gate import DATABASE_WRITE_GATE

DATE = "2026-07-02"
pytestmark = [pytest.mark.db, pytest.mark.integration]


def _closed(start: str, end: str, project_id: int, *, app: str = "App") -> int:
    activity_id = activity_service.create_activity(
        app,
        app.lower() + ".exe",
        app,
        project_id=project_id,
        start_time=f"{DATE} {start}",
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.close_activity(activity_id, f"{DATE} {end}")
    return activity_id


def test_committed_edit_survives_project_presentation_changes(temp_db):
    project_id = project_service.create_project("Original", "before")
    _closed("09:00:00", "09:10:00", project_id)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    result = mutations.edit_session(
        DATE,
        str(source["projection_instance_key"]),
        str(source["projection_revision"]),
        "durable-edit-before-rename",
        project_id=None,
        adjusted_duration_seconds=None,
        note="persisted note",
    )
    assert result.outcome_type == "operation_committed"
    before_rename = build_visible_snapshot(DATE, DATE)
    entry_revision = str(before_rename.final_sessions[0]["projection_revision"])

    project_service.update_project(project_id, "Renamed", "after")
    project_service.set_project_enabled(project_id, False)
    after_rename = build_visible_snapshot(DATE, DATE)

    assert len(after_rename.final_sessions) == 1
    assert after_rename.final_sessions[0]["project_name"] == "Renamed"
    assert after_rename.final_sessions[0]["session_note"] == "persisted note"
    assert after_rename.final_sessions[0]["projection_revision"] == entry_revision
    assert after_rename.snapshot_revision != before_rename.snapshot_revision
    assert after_rename.operation_diagnostics[0].state == "applied"


def test_snapshot_read_scope_builds_one_snapshot_per_range(temp_db, monkeypatch):
    project_id = project_service.create_project("P")
    _closed("09:00:00", "09:01:00", project_id)
    from worktrace.services import report_projection_snapshot_service as snapshots

    calls = 0
    original = snapshots._build_snapshot

    def counted(conn, start_date, end_date):
        nonlocal calls
        calls += 1
        return original(conn, start_date, end_date)

    monkeypatch.setattr(snapshots, "_build_snapshot", counted)
    with snapshot_read_scope():
        first = snapshots.build_visible_snapshot(DATE, DATE)
        second = snapshots.build_visible_snapshot(DATE, DATE)
    assert first is second
    assert calls == 1

    third = snapshots.build_visible_snapshot(DATE, DATE)
    assert third is not first
    assert calls == 2


def test_canonical_builder_reads_unrecorded_gap_seconds_not_context_minutes(temp_db):
    project_id = project_service.create_project("P")
    _closed("09:00:00", "09:01:00", project_id, app="A")
    _closed("09:05:00", "09:06:00", project_id, app="B")
    set_setting("context_carry_minutes", "15")
    set_setting("unrecorded_gap_boundary_seconds", "60")
    assert len(build_visible_snapshot(DATE, DATE).final_sessions) == 2

    set_setting("unrecorded_gap_boundary_seconds", "600")
    assert len(build_visible_snapshot(DATE, DATE).final_sessions) == 1


def test_canonical_snapshot_records_are_recursively_immutable(temp_db):
    project_id = project_service.create_project("P")
    _closed("09:00:00", "09:01:00", project_id)
    snapshot = build_visible_snapshot(DATE, DATE)
    with pytest.raises(TypeError):
        snapshot.final_sessions[0]["project_name"] = "mutated"
    with pytest.raises(TypeError):
        snapshot.final_sessions[0]["member_slices"][0]["activity_id"] = 999


def test_timeline_selectable_project_api_is_live(temp_db):
    project_id = project_service.create_project("Selectable")
    projects = timeline_api.list_selectable_projects()
    assert any(int(item["id"]) == project_id for item in projects)


def test_global_write_gate_blocks_service_writes_from_other_threads(temp_db):
    outcome: list[str] = []

    def writer() -> None:
        try:
            project_service.create_project("Blocked")
        except sqlite3.OperationalError as exc:
            outcome.append(str(exc))

    with DATABASE_WRITE_GATE.acquire():
        thread = threading.Thread(target=writer)
        thread.start()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert outcome == ["secure_import_in_progress"]
    assert project_service.get_project_by_name("Blocked") is None


def test_database_generation_rejects_stale_background_results_until_fresh_read(temp_db):
    read_complete = threading.Event()
    replacement_complete = threading.Event()
    outcomes: list[str] = []

    def stale_worker() -> None:
        with get_connection() as conn:
            conn.execute("SELECT COUNT(*) FROM project").fetchone()
        read_complete.set()
        assert replacement_complete.wait(timeout=5)
        try:
            project_service.create_project("StaleWrite")
        except sqlite3.OperationalError as exc:
            outcomes.append(str(exc))
        assert project_service.get_project_by_name("StaleWrite") is None
        project_service.create_project("FreshWrite")
        outcomes.append("fresh_write_ok")

    thread = threading.Thread(target=stale_worker)
    thread.start()
    assert read_complete.wait(timeout=5)
    with DATABASE_WRITE_GATE.acquire():
        pass
    replacement_complete.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert outcomes == ["database_generation_changed", "fresh_write_ok"]
    assert project_service.get_project_by_name("FreshWrite") is not None


def test_secure_validation_accepts_open_activity_with_null_duration(temp_db):
    project_id = project_service.create_project("P")
    activity_service.create_activity(
        "Open",
        "open.exe",
        "Open",
        project_id=project_id,
        start_time=f"{DATE} 08:00:00",
    )
    with get_connection() as conn:
        secure_backup_service._validate_staging_database(conn)


def test_secure_validation_rejects_semantically_invalid_activity_without_operations(temp_db):
    project_id = project_service.create_project("P")
    activity_id = _closed("09:00:00", "09:01:00", project_id)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET duration_seconds = 30 WHERE id = ?",
            (activity_id,),
        )
        with pytest.raises(secure_backup_service.BackupCorruptedError):
            secure_backup_service._validate_staging_database(conn)


def test_secure_validation_replays_member_bound_operation_after_admission_revision_changes(
    temp_db,
):
    """Admission revisions are write guards, not long-term replay identity."""

    project_id = project_service.create_project("P")
    activity_id = _closed("09:00:00", "09:01:00", project_id)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO report_session_operation(
                report_date, sequence, operation_type, source_instance_key,
                source_expected_revision, payload_json, created_at
            ) VALUES (?, 1, 'hide_session', ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                DATE,
                str(source["projection_instance_key"]),
                DURABLE_REVISION_PREFIX
                + "0" * (40 - len(DURABLE_REVISION_PREFIX)),
                '{"payload_version":4}',
            ),
        )
        conn.execute(
            """
            INSERT INTO report_session_operation_member(
                operation_id, role, activity_id, report_date,
                slice_start_time, display_order
            ) VALUES (?, 'source', ?, ?, ?, 0)
            """,
            (int(cursor.lastrowid), activity_id, DATE, f"{DATE} 09:00:00"),
        )
        secure_backup_service._validate_staging_database(conn)
