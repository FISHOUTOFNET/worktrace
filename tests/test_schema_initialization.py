from worktrace import db
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.db import now_str
import sqlite3
import pytest

pytestmark = [pytest.mark.db, pytest.mark.contract]


def test_new_database_has_current_schema_and_defaults(temp_db):
    with db.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        activity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        project_columns = {row["name"] for row in conn.execute("PRAGMA table_info(project)").fetchall()}
        assignment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(activity_project_assignment)").fetchall()
        }
        setting = conn.execute("SELECT value FROM settings WHERE key = 'context_carry_minutes'").fetchone()
        idle_threshold = conn.execute("SELECT value FROM settings WHERE key = 'idle_threshold_seconds'").fetchone()
        ui_refresh = conn.execute("SELECT value FROM settings WHERE key = 'ui_refresh_seconds'").fetchone()
        clipboard_capture = conn.execute("SELECT value FROM settings WHERE key = 'clipboard_capture_enabled'").fetchone()
        removed_setting = conn.execute("SELECT value FROM settings WHERE key = 'default_billable'").fetchone()
        min_history = conn.execute("SELECT value FROM settings WHERE key = 'min_history_seconds'").fetchone()
        min_idle = conn.execute("SELECT value FROM settings WHERE key = 'min_idle_segment_seconds'").fetchone()
        min_activity = conn.execute("SELECT value FROM settings WHERE key = 'min_activity_seconds'").fetchone()
        uncategorized = conn.execute("SELECT * FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()
        excluded = conn.execute("SELECT * FROM project WHERE name = ?", (EXCLUDED_PROJECT,)).fetchone()
        exclude_rule_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM project_rule pr
            JOIN project p ON p.id = pr.project_id
            WHERE p.name = ?
            """,
            (EXCLUDED_PROJECT,),
        ).fetchone()
        assignment_schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'activity_project_assignment'"
        ).fetchone()["sql"]

    assert "resource_id" not in activity_columns
    assert "file_path_hint" in activity_columns
    assert "is_billable" not in activity_columns
    assert "is_confirmed" not in activity_columns
    assert "created_by" in project_columns
    assert "enabled" in project_columns
    assert "language" in project_columns
    assert "default_billable" not in project_columns
    assert "suggested_project_name" in assignment_columns
    assert "source_rule_type" in assignment_columns
    assert "source_rule_id" in assignment_columns
    assert "resource" not in tables
    assert "project_rule" in tables
    assert "folder_project_rule" in tables
    assert "folder_rule_index_state" in tables
    assert "folder_rule_file_index" in tables
    assert "activity_project_assignment" in tables
    assert "activity_clipboard_event" in tables
    assert "project_session_override" not in tables
    assert "project_session_override_member" not in tables
    assert "report_session_operation" in tables
    assert "report_session_operation_member" in tables
    assert "manual_project_session" not in tables
    assert "manual_project_session_activity" not in tables
    assert setting["value"] == "15"
    assert idle_threshold["value"] == "300"
    assert ui_refresh["value"] == "10"
    assert clipboard_capture["value"] == "false"
    assert removed_setting is None
    assert min_history is None
    assert min_idle is None
    assert min_activity is None
    assert uncategorized is not None
    assert uncategorized["created_by"] == "system"
    assert uncategorized["language"] == "中文"
    assert excluded is not None
    assert excluded["created_by"] == "system"
    assert excluded["language"] == "中文"
    assert excluded["enabled"] == 0
    assert excluded["description"] == "命中后匿名记录"
    assert exclude_rule_count["c"] == 0
    assert "midnight_anchor" in assignment_schema
    assert "keyword_rule" in assignment_schema
    assert "clipboard_transition_context" not in assignment_schema
    assert "anchor_context" not in assignment_schema
    assert "same_project_context" not in assignment_schema
    assert "source_rule_type" in assignment_schema
    assert "anchor_keyword" not in assignment_schema
    assert "anchor_resource_default" not in assignment_schema
    assert "rule" not in tables


def test_report_session_operation_has_user_command_columns(temp_db):
    with db.get_connection() as conn:
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(report_session_operation)").fetchall()}
        member_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(report_session_operation_member)").fetchall()}
        assert "operation_type" in columns
        assert "source_instance_key" in columns
        assert "sequence" in columns
        assert "payload_json" in columns
        assert "match_state" not in columns
        assert "undo_of_operation_id" in columns
        assert "slice_start_time" in member_columns


def test_same_version_schema_drift_fails_closed_before_seeding(tmp_path):
    path = tmp_path / "drift.db"
    db.configure_database(path)
    with db.get_connection() as conn:
        conn.execute("CREATE TABLE project(id INTEGER PRIMARY KEY)")
        conn.execute(f"PRAGMA user_version = {db.CURRENT_SCHEMA_VERSION}")

    with pytest.raises(ValueError, match="database_schema_incompatible"):
        db.initialize_database(path)

    with sqlite3.connect(path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert tables == {"project"}


def test_operation_and_receipt_json_and_cardinality_constraints(temp_db):
    timestamp = now_str()
    with db.get_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO report_session_operation(
                    report_date, sequence, operation_type, source_instance_key,
                    source_expected_revision, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("2026-07-01", 1, "hide_session", "base:a", "revision", "not-json", timestamp),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO report_session_operation(
                    report_date, sequence, operation_type, source_instance_key,
                    source_expected_revision, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("2026-07-01", 1, "merge_sessions", "base:a", "revision", '{"payload_version":4}', timestamp),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO report_mutation_request(
                    request_id, input_signature, outcome_type, operation_id,
                    result_json, created_at, committed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("request", "signature", "no_op", 1, "{}", timestamp, timestamp),
            )


def test_reset_database_clears_current_schema_tables(temp_db):
    from tests.support import activity_factory as activity_service

    aid = activity_service.create_activity("Edge", "msedge.exe", "Search", start_time="2026-06-18 09:00:00")
    activity_service.finalize_created_activity(aid)

    db.reset_database()

    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM activity_clipboard_event").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM report_session_operation").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM report_session_operation_member").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_project_rule").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_rule_index_state").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM folder_rule_file_index").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM project_rule").fetchone()["c"] == 0
        activity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
        project_columns = {row["name"] for row in conn.execute("PRAGMA table_info(project)").fetchall()}
        assignment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(activity_project_assignment)").fetchall()
        }
        assert "file_path_hint" in activity_columns
        assert "is_billable" not in activity_columns
        assert "is_confirmed" not in activity_columns
        assert "created_by" in project_columns
        assert "enabled" in project_columns
        assert "language" in project_columns
        assert "default_billable" not in project_columns
        assert "suggested_project_name" in assignment_columns
        assert "source_rule_type" in assignment_columns
        assert "source_rule_id" in assignment_columns
        assert conn.execute("SELECT value FROM settings WHERE key = 'context_carry_minutes'").fetchone()["value"] == "15"
        assert conn.execute("SELECT value FROM settings WHERE key = 'idle_threshold_seconds'").fetchone()["value"] == "300"
        assert conn.execute("SELECT value FROM settings WHERE key = 'ui_refresh_seconds'").fetchone()["value"] == "10"
        assert conn.execute("SELECT value FROM settings WHERE key = 'clipboard_capture_enabled'").fetchone()["value"] == "false"
        assert conn.execute("SELECT value FROM settings WHERE key = 'default_billable'").fetchone() is None
        assert conn.execute("SELECT value FROM settings WHERE key = 'min_history_seconds'").fetchone() is None
        assert conn.execute("SELECT value FROM settings WHERE key = 'min_idle_segment_seconds'").fetchone() is None
        assert conn.execute("SELECT value FROM settings WHERE key = 'min_activity_seconds'").fetchone() is None
        assert conn.execute("SELECT language FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()["language"] == "中文"
        assert conn.execute("SELECT language FROM project WHERE name = ?", (EXCLUDED_PROJECT,)).fetchone()["language"] == "中文"
