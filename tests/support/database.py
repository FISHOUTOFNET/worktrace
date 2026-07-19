from __future__ import annotations

import sqlite3

from worktrace import db
from worktrace.report_generation_classifier import report_structure_classifier_scope


def drop_all_tables(conn: sqlite3.Connection) -> None:
    """Destroy the test database schema without exposing a production entrypoint."""

    conn.executescript(
        """
        DROP TABLE IF EXISTS activity_resource;
        DROP TABLE IF EXISTS folder_rule_file_index;
        DROP TABLE IF EXISTS folder_rule_index_state;
        DROP TABLE IF EXISTS history_mutation_job_rule;
        DROP TABLE IF EXISTS history_mutation_job;
        DROP TABLE IF EXISTS startup_recovery_job;
        DROP TABLE IF EXISTS activity_inference_job;
        DROP TABLE IF EXISTS report_session_operation_member;
        DROP TABLE IF EXISTS report_mutation_request;
        DROP TABLE IF EXISTS report_session_operation;
        DROP TABLE IF EXISTS activity_clipboard_event;
        DROP TABLE IF EXISTS activity_project_assignment;
        DROP TABLE IF EXISTS activity_log;
        DROP TABLE IF EXISTS session_boundary;
        DROP TABLE IF EXISTS folder_project_rule;
        DROP TABLE IF EXISTS project_rule;
        DROP TABLE IF EXISTS project;
        DROP TABLE IF EXISTS settings;
        DROP TABLE IF EXISTS report_structure_revision_state;
        DROP TABLE IF EXISTS data_generation_state;
        DROP TABLE IF EXISTS activity_resource_repair_job;
        """
    )


def reset_database() -> None:
    """Rebuild the configured test database using the current-only schema."""

    with db.get_connection() as conn:
        db.ensure_wal(conn)
        with report_structure_classifier_scope():
            drop_all_tables(conn)
            db.apply_current_schema(conn)
