"""Tests for current schema initialization and reset."""
from __future__ import annotations

from worktrace import db
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT


# Tables that must exist after initialize_database on an empty database.
EXPECTED_TABLES = {
    "project",
    "activity_log",
    "settings",
    "session_boundary",
    "folder_project_rule",
    "folder_rule_index_state",
    "folder_rule_file_index",
    "project_rule",
    "activity_project_assignment",
    "activity_clipboard_event",
    "project_session_note",
    "activity_resource",
}

# Default settings that must be seeded on a fresh database.
EXPECTED_DEFAULT_SETTINGS = {
    "poll_interval_seconds",
    "idle_threshold_seconds",
    "current_activity_snapshot",
    "pending_short_seconds",
    "collector_status",
    "last_collector_heartbeat",
    "last_shutdown_at",
    "first_run_notice_accepted",
    "export_path",
    "ui_refresh_seconds",
    "user_paused",
    "context_carry_minutes",
    "clipboard_capture_enabled",
}


def _get_tables(conn) -> set[str]:
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }


def test_initialize_creates_all_current_schema_tables(temp_db):
    with db.get_connection() as conn:
        tables = _get_tables(conn)

    assert EXPECTED_TABLES.issubset(tables)


def test_initialize_seeds_default_settings(temp_db):
    with db.get_connection() as conn:
        keys = {
            row["key"]
            for row in conn.execute("SELECT key FROM settings").fetchall()
        }

    assert EXPECTED_DEFAULT_SETTINGS.issubset(keys)


def test_initialize_seeds_default_projects(temp_db):
    with db.get_connection() as conn:
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)
        ).fetchone()
        excluded = conn.execute(
            "SELECT * FROM project WHERE name = ?", (EXCLUDED_PROJECT,)
        ).fetchone()

    assert uncategorized is not None
    assert uncategorized["created_by"] == "system"
    assert uncategorized["enabled"] == 1
    assert excluded is not None
    assert excluded["created_by"] == "system"
    assert excluded["enabled"] == 0
    assert excluded["description"] == "命中后匿名记录"


def test_repeated_initialize_does_not_error_or_destroy_data(temp_db):
    from worktrace.services import activity_service

    aid = activity_service.create_activity(
        "Edge", "msedge.exe", "Search", start_time="2026-06-18 09:00:00"
    )
    activity_service.finalize_created_activity(aid)

    # Second init should not fail or lose existing data.
    db.initialize_database(temp_db)

    with db.get_connection() as conn:
        activity_count = conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"]
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)
        ).fetchone()

    assert activity_count == 1
    assert uncategorized is not None


def test_reset_database_clears_business_data_and_rebuilds_defaults(temp_db):
    from worktrace.services import activity_service

    aid = activity_service.create_activity(
        "Edge", "msedge.exe", "Search", start_time="2026-06-18 09:00:00"
    )
    activity_service.finalize_created_activity(aid)

    db.reset_database()

    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_project_assignment").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_clipboard_event").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM project_session_note").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_project_rule").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_rule_index_state").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_rule_file_index").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM project_rule").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_resource").fetchone()["c"] == 0
        # Default projects are rebuilt.
        uncategorized = conn.execute(
            "SELECT * FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)
        ).fetchone()
        excluded = conn.execute(
            "SELECT * FROM project WHERE name = ?", (EXCLUDED_PROJECT,)
        ).fetchone()
        # Default settings are rebuilt.
        keys = {
            row["key"]
            for row in conn.execute("SELECT key FROM settings").fetchall()
        }

    assert uncategorized is not None
    assert excluded is not None
    assert EXPECTED_DEFAULT_SETTINGS.issubset(keys)
