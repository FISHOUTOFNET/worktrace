"""Contracts for current-only schema initialization and test-only reset."""
from __future__ import annotations

import sqlite3

import pytest

from tests.support.database import reset_database
from worktrace import db
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT

pytestmark = [pytest.mark.db, pytest.mark.contract]

EXPECTED_TABLES = {
    "project",
    "activity_log",
    "settings",
    "session_boundary",
    "folder_project_rule",
    "folder_rule_index_state",
    "folder_rule_file_index",
    "project_rule",
    "history_mutation_job",
    "history_mutation_job_rule",
    "activity_inference_job",
    "activity_project_assignment",
    "activity_clipboard_event",
    "report_session_operation",
    "report_session_operation_member",
    "report_mutation_request",
    "activity_resource",
    "data_generation_state",
    "activity_resource_repair_job",
}

EXPECTED_DEFAULT_SETTINGS = {
    "poll_interval_seconds",
    "idle_threshold_seconds",
    "collector_status",
    "last_collector_heartbeat",
    "last_shutdown_at",
    "export_path",
    "ui_refresh_seconds",
    "user_paused",
    "context_carry_minutes",
    "clipboard_capture_enabled",
}

REMOVED_RUNTIME_SETTINGS = {
    "current_activity_snapshot",
    "pending_short_seconds",
    "pending_short_carry_provenance",
}


def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _get_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def test_initialize_empty_database_sets_exact_current_schema(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.initialize_database(db_path)

    with db.get_connection() as conn:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 12
        assert db.schema_fingerprint(conn) == db.expected_schema_fingerprint()
        assert EXPECTED_TABLES.issubset(_get_tables(conn))
        assert "source_rule_type" in _get_columns(
            conn, "activity_project_assignment"
        )
        assert "activity_inference_job" in _get_tables(conn)


def test_current_schema_initialization_is_idempotent_and_preserves_data(tmp_path):
    from tests.support import activity_factory as activity_service

    db_path = str(tmp_path / "test.db")
    db.initialize_database(db_path)
    activity_id = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Search",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity_id)

    db.initialize_database(db_path)

    with db.get_connection() as conn:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 12
        assert db.schema_fingerprint(conn) == db.expected_schema_fingerprint()
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 1


@pytest.mark.parametrize("version", [1, 4, 8, 9, 10, 11])
def test_initialize_rejects_every_non_current_schema(tmp_path, version):
    db_path = str(tmp_path / f"schema-{version}.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE preserved_user_data(id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO preserved_user_data(id) VALUES (1)")
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="database_schema_incompatible"):
        db.initialize_database(db_path)

    verify = sqlite3.connect(db_path)
    try:
        assert verify.execute(
            "SELECT COUNT(*) FROM preserved_user_data"
        ).fetchone()[0] == 1
    finally:
        verify.close()


def test_initialize_rejects_current_version_with_wrong_fingerprint(tmp_path):
    db_path = str(tmp_path / "invalid-v12.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE incomplete(id INTEGER PRIMARY KEY)")
        conn.execute("PRAGMA user_version = 12")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="database_schema_incompatible"):
        db.initialize_database(db_path)


def test_initialize_database_surfaces_current_schema_index_failures(
    tmp_path,
    monkeypatch,
):
    db_path = str(tmp_path / "bad-index.db")
    monkeypatch.setattr(
        db,
        "read_schema_indexes_sql",
        lambda: "CREATE INDEX broken_index ON missing_table(id);",
    )

    with pytest.raises(sqlite3.OperationalError):
        db.initialize_database(db_path)


def test_initialize_seeds_default_settings_and_projects(temp_db):
    with db.get_connection() as conn:
        keys = {
            row["key"]
            for row in conn.execute("SELECT key FROM settings").fetchall()
        }
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?",
            (UNCATEGORIZED_PROJECT,),
        ).fetchone()
        excluded = conn.execute(
            "SELECT * FROM project WHERE name = ?",
            (EXCLUDED_PROJECT,),
        ).fetchone()

    assert EXPECTED_DEFAULT_SETTINGS.issubset(keys)
    assert not (keys & REMOVED_RUNTIME_SETTINGS)
    assert uncategorized is not None
    assert uncategorized["created_by"] == "system"
    assert uncategorized["enabled"] == 1
    assert excluded is not None
    assert excluded["created_by"] == "system"
    assert excluded["enabled"] == 0


def test_test_reset_clears_current_business_data_and_rebuilds_defaults(temp_db):
    from tests.support import activity_factory as activity_service

    activity_id = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Search",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity_id)
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO activity_inference_job(
                activity_id, reason, status, attempt_count, next_attempt_at,
                last_error_code, created_at, updated_at
            ) VALUES (?, 'closed_activity', 'pending', 0, NULL, NULL, ?, ?)
            """,
            (activity_id, db.now_str(), db.now_str()),
        )

    reset_database()

    with db.get_connection() as conn:
        for table in (
            "activity_log",
            "activity_project_assignment",
            "activity_inference_job",
            "activity_clipboard_event",
            "activity_resource",
            "report_session_operation",
            "report_session_operation_member",
            "folder_project_rule",
            "folder_rule_index_state",
            "folder_rule_file_index",
            "history_mutation_job",
            "history_mutation_job_rule",
            "project_rule",
        ):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        keys = {
            row["key"]
            for row in conn.execute("SELECT key FROM settings").fetchall()
        }
        assert conn.execute(
            "SELECT 1 FROM project WHERE name = ?",
            (UNCATEGORIZED_PROJECT,),
        ).fetchone()
        assert conn.execute(
            "SELECT 1 FROM project WHERE name = ?",
            (EXCLUDED_PROJECT,),
        ).fetchone()

    assert EXPECTED_DEFAULT_SETTINGS.issubset(keys)
    assert not (keys & REMOVED_RUNTIME_SETTINGS)
