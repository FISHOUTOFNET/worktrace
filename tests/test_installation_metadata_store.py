from __future__ import annotations

import sqlite3

import pytest

from worktrace import db
from worktrace.services import database_maintenance_service, privacy_gate_service
from worktrace.services.installation_metadata_store import metadata_path
from worktrace.services.secure_backup_service import EXPORT_TABLES, MIGRATABLE_SETTINGS

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def test_current_schema_initialization_does_not_read_or_migrate_legacy_privacy_settings(
    tmp_path,
):
    path = tmp_path / "worktrace.db"
    db.initialize_database(path)
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            ("first_run_notice_accepted", "true", "2026-07-18 09:00:00"),
        )
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            (
                "accepted_privacy_notice_version",
                "1",
                "2026-07-18 09:00:00",
            ),
        )

    db.initialize_database(path)

    assert privacy_gate_service.is_privacy_notice_accepted() is False
    with db.get_connection() as conn:
        values = {
            row["key"]: row["value"]
            for row in conn.execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?)",
                ("first_run_notice_accepted", "accepted_privacy_notice_version"),
            ).fetchall()
        }
    assert values == {
        "first_run_notice_accepted": "true",
        "accepted_privacy_notice_version": "1",
    }


def test_installation_consent_is_stored_outside_business_database(temp_db):
    privacy_gate_service.accept_privacy_notice()

    assert privacy_gate_service.is_privacy_notice_accepted() is True
    assert metadata_path().exists()
    with db.get_connection() as conn:
        keys = conn.execute(
            "SELECT key FROM settings WHERE key LIKE '%privacy_notice%'"
        ).fetchall()
    assert keys == []


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


def test_non_current_schema_is_rejected_without_modifying_original_database(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE preserved_user_data(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO preserved_user_data(id, value) VALUES (1, 'keep')")
        conn.execute("PRAGMA user_version = 8")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="database_schema_incompatible"):
        db.initialize_database(path)

    verify = sqlite3.connect(path)
    try:
        assert verify.execute(
            "SELECT value FROM preserved_user_data WHERE id = 1"
        ).fetchone()[0] == "keep"
        assert int(verify.execute("PRAGMA user_version").fetchone()[0]) == 8
    finally:
        verify.close()
