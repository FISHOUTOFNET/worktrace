from __future__ import annotations

import sqlite3
import json

import pytest

from worktrace import db
from worktrace.services import database_maintenance_service, privacy_gate_service
from worktrace.services.installation_metadata_store import metadata_path
from worktrace.services.secure_backup_service import EXPORT_TABLES, MIGRATABLE_SETTINGS

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def test_v8_legacy_privacy_setting_migrates_once_outside_business_db(tmp_path):
    path = tmp_path / "worktrace.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(db.read_schema_sql())
        conn.executescript(db.read_schema_indexes_sql())
        conn.executescript(
            """
            CREATE TABLE data_generation_state (
                namespace TEXT PRIMARY KEY CHECK(length(trim(namespace)) > 0),
                generation INTEGER NOT NULL CHECK(generation >= 0)
            );
            INSERT INTO data_generation_state(namespace, generation) VALUES
                ('report_structure', 3),
                ('classification_catalog', 0),
                ('settings', 0),
                ('privacy_catalog', 0),
                ('database_replacement', 0);
            """
        )
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            ("first_run_notice_accepted", "true", "2026-07-18 09:00:00"),
        )
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            (
                "maintenance.activity_resource_repair.v1",
                json.dumps(
                    {
                        "policy_version": 1,
                        "status": "running",
                        "cursor_activity_id": 41,
                        "scanned_count": 40,
                        "repaired_count": 39,
                        "error_count": 1,
                        "last_error": "detector unavailable",
                    }
                ),
                "2026-07-18 09:00:00",
            ),
        )
        conn.execute("PRAGMA user_version = 8")
        conn.commit()
    finally:
        conn.close()

    db.initialize_database(path)

    assert privacy_gate_service.is_privacy_notice_accepted() is True
    assert metadata_path().exists()
    with db.get_connection() as business_conn:
        keys = business_conn.execute(
            "SELECT key FROM settings WHERE key IN (?, ?)",
            ("first_run_notice_accepted", "accepted_privacy_notice_version"),
        ).fetchall()
        job = business_conn.execute(
            "SELECT * FROM activity_resource_repair_job WHERE singleton_id = 1"
        ).fetchone()
        legacy_job = business_conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("maintenance.activity_resource_repair.v1",),
        ).fetchone()
    assert keys == []
    assert job["status"] == "running"
    assert job["cursor_activity_id"] == 41
    assert job["processed_count"] == 40
    assert job["repaired_count"] == 39
    assert job["failed_count"] == 1
    assert legacy_job is None


def test_clear_all_preserves_installation_consent_without_business_restore(temp_db):
    privacy_gate_service.accept_privacy_notice()

    database_maintenance_service.clear_all_live_data()

    assert privacy_gate_service.is_privacy_notice_accepted() is True
    with db.get_connection() as conn:
        keys = conn.execute(
            "SELECT key FROM settings WHERE key LIKE '%privacy_notice%'"
        ).fetchall()
    assert keys == []


def test_backup_contract_excludes_installation_and_repair_metadata():
    assert "installation_metadata" not in EXPORT_TABLES
    assert "activity_resource_repair_job" not in EXPORT_TABLES
    assert "first_run_notice_accepted" not in MIGRATABLE_SETTINGS
    assert "accepted_privacy_notice_version" not in MIGRATABLE_SETTINGS
