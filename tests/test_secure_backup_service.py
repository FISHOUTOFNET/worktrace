"""Direct contracts for current-format encrypted backup and replace import."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from worktrace import db
from worktrace.security.backup_format import (
    MAGIC,
    create_encrypted_backup,
    decrypt_encrypted_backup,
)
from worktrace.services import (
    database_maintenance_service,
    history_mutation_job_service,
    rule_service,
    secure_backup_service,
)
from worktrace.services.secure_backup_service import (
    BackupCorruptedError,
    BackupDecryptionError,
    BackupImportInProgressError,
    BackupVersionNotSupportedError,
    SecureBackupError,
)
from worktrace.services.settings_service import get_bool_setting, get_setting, set_setting

pytestmark = [
    pytest.mark.security_privacy,
    pytest.mark.integration,
    pytest.mark.db,
    pytest.mark.contract,
]

PASSPHRASE = "current-format-passphrase"
PROJECT_NAME = "Backup Current Project"
_WORKER_PROGRESS_TABLES = (
    "history_mutation_job_rule",
    "history_mutation_job",
    "activity_inference_job",
    "activity_resource_repair_job",
    "startup_recovery_job",
)


def _seed_current_data() -> tuple[int, int]:
    timestamp = db.now_str()
    with db.get_connection() as conn:
        project_id = int(
            conn.execute(
                """
                INSERT INTO project(
                    name, description, language, is_archived, is_deleted,
                    enabled, created_by, created_at, updated_at
                ) VALUES (?, '', '中文', 0, 0, 1, 'user', ?, ?)
                """,
                (PROJECT_NAME, timestamp, timestamp),
            ).lastrowid
        )
        activity_ids: list[int] = []
        for index in range(2):
            activity_id = int(
                conn.execute(
                    """
                    INSERT INTO activity_log(
                        start_time, end_time, duration_seconds, app_name,
                        process_name, window_title, file_path_hint, status,
                        source, is_deleted, is_hidden, created_at, updated_at
                    ) VALUES (?, ?, 60, 'Word', 'winword.exe', ?, ?, 'normal',
                              'auto', 0, 0, ?, ?)
                    """,
                    (
                        f"2026-07-18 10:0{index}:00",
                        f"2026-07-18 10:0{index + 1}:00",
                        f"Matter {index}.docx",
                        f"C:\\Matter\\Matter {index}.docx",
                        timestamp,
                        timestamp,
                    ),
                ).lastrowid
            )
            activity_ids.append(activity_id)
            conn.execute(
                """
                INSERT INTO activity_resource(
                    activity_id, resource_kind, resource_subtype, display_name,
                    identity_key, is_anchor, confidence, source, app_name,
                    process_name, window_title, path_hint, uri_scheme, uri_host,
                    uri_hint, metadata_json, created_at, updated_at
                ) VALUES (?, 'office_document', 'word', ?, ?, 1, 100,
                          'detector', 'Word', 'winword.exe', ?, ?, NULL, NULL,
                          NULL, '{}', ?, ?)
                """,
                (
                    activity_id,
                    f"Matter {index}.docx",
                    f"office_file:c:/matter/matter {index}.docx",
                    f"Matter {index}.docx",
                    f"C:\\Matter\\Matter {index}.docx",
                    timestamp,
                    timestamp,
                ),
            )
        conn.execute(
            """
            INSERT INTO activity_inference_job(
                activity_id, reason, status, attempt_count, next_attempt_at,
                last_error_code, created_at, updated_at
            ) VALUES (?, 'closed_activity', 'pending', 0, NULL, NULL, ?, ?)
            """,
            (activity_ids[0], timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO activity_inference_job(
                activity_id, reason, status, attempt_count, next_attempt_at,
                last_error_code, created_at, updated_at
            ) VALUES (?, 'closed_activity', 'failed', 3, ?,
                      'database_busy', ?, ?)
            """,
            (
                activity_ids[1],
                "2026-07-18 11:00:00",
                timestamp,
                timestamp,
            ),
        )
    return activity_ids[0], activity_ids[1]


def _seed_all_worker_progress(source_activity_id: int) -> None:
    with db.get_connection() as conn:
        project_id = int(
            conn.execute(
                "SELECT id FROM project WHERE name = ?",
                (PROJECT_NAME,),
            ).fetchone()[0]
        )
    rule_id = rule_service.create_rule("Matter", project_id)
    history_mutation_job_service.submit_rule_job(
        "rule_backfill",
        "keyword",
        rule_id,
        synchronous_limit=0,
    )
    timestamp = db.now_str()
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO activity_resource_repair_job(
                singleton_id, policy_version, status, cursor_activity_id,
                processed_count, repaired_count, failed_count, unknown_count,
                last_error, started_at, completed_at, updated_at
            ) VALUES (1, 1, 'pending', 0, 0, 0, 0, 0, '', '', '', ?)
            """,
            (timestamp,),
        )
        conn.execute(
            """
            INSERT INTO startup_recovery_job(
                source_activity_id, cursor_time, end_time, source,
                activity_status, app_name, process_name, window_title,
                file_path_hint, project_id, status, attempt_count,
                next_attempt_at, last_error_code, created_at, updated_at
            ) VALUES (?, '2026-07-18 10:01:00', '2026-07-20 10:01:00',
                      'auto', 'normal', 'Word', 'winword.exe', 'Matter 0.docx',
                      'C:\\Matter\\Matter 0.docx', ?, 'pending', 0,
                      NULL, NULL, ?, ?)
            """,
            (source_activity_id, project_id, timestamp, timestamp),
        )


def _worker_progress_counts() -> dict[str, int]:
    with db.get_connection() as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in _WORKER_PROGRESS_TABLES
        }


def _write_payload(tmp_path: Path, data: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(
        create_encrypted_backup(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            ),
            PASSPHRASE,
            "test",
        )
    )
    return path


def _current_payload() -> bytes:
    with database_maintenance_service.consistent_snapshot("backup_test_payload"):
        return secure_backup_service._build_export_payload_under_snapshot()


def test_export_payload_is_exact_current_contract(temp_db):
    _seed_current_data()
    data = json.loads(_current_payload())
    assert data["format"] == "worktrace-local-data"
    assert data["version"] == 5
    assert data["schema_version"] == "11"
    assert data["schema_fingerprint"] == db.expected_schema_fingerprint()
    assert set(data["tables"]) == set(secure_backup_service.EXPORT_TABLES)
    for table in _WORKER_PROGRESS_TABLES:
        assert table not in data["tables"]
        assert table in secure_backup_service.EXCLUDED_TABLES
    assert "folder_rule_file_index" not in data["tables"]


def test_current_v5_round_trip_restores_business_data_and_clears_worker_progress(
    temp_db,
    tmp_path,
):
    first_activity_id, _second_activity_id = _seed_current_data()
    _seed_all_worker_progress(first_activity_id)
    assert all(count > 0 for count in _worker_progress_counts().values())
    out = tmp_path / "round-trip.wtbackup"
    secure_backup_service.export_encrypted_backup(out, PASSPHRASE)

    db.reset_database()
    secure_backup_service.import_encrypted_backup(out, PASSPHRASE)

    with db.get_connection() as conn:
        project = conn.execute(
            "SELECT 1 FROM project WHERE name = ?",
            (PROJECT_NAME,),
        ).fetchone()
        activity_count = conn.execute(
            "SELECT COUNT(*) FROM activity_log"
        ).fetchone()[0]
    assert project is not None
    assert activity_count == 2
    assert _worker_progress_counts() == {
        table: 0 for table in _WORKER_PROGRESS_TABLES
    }


def test_non_current_payload_version_is_explicitly_rejected(temp_db, tmp_path):
    data = json.loads(_current_payload())
    data["version"] = 4
    path = _write_payload(tmp_path, data, "payload-v4.wtbackup")
    with pytest.raises(BackupVersionNotSupportedError):
        secure_backup_service.import_encrypted_backup(path, PASSPHRASE)


def test_non_current_schema_version_is_explicitly_rejected(temp_db, tmp_path):
    data = json.loads(_current_payload())
    data["schema_version"] = "10"
    path = _write_payload(tmp_path, data, "schema-v10.wtbackup")
    with pytest.raises(BackupVersionNotSupportedError):
        secure_backup_service.import_encrypted_backup(path, PASSPHRASE)


def test_current_schema_wrong_fingerprint_is_corruption(temp_db, tmp_path):
    data = json.loads(_current_payload())
    data["schema_fingerprint"] = "0" * 64
    path = _write_payload(tmp_path, data, "bad-fingerprint.wtbackup")
    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(path, PASSPHRASE)


def test_encrypted_export_contains_no_plaintext_business_data(temp_db, tmp_path):
    _seed_current_data()
    out = tmp_path / "encrypted.wtbackup"
    secure_backup_service.export_encrypted_backup(out, PASSPHRASE)
    blob = out.read_bytes()
    assert blob.startswith(MAGIC + b"\n")
    assert PROJECT_NAME.encode("utf-8") not in blob
    payload = json.loads(decrypt_encrypted_backup(blob, PASSPHRASE))
    assert any(row["name"] == PROJECT_NAME for row in payload["tables"]["project"])


def test_wrong_passphrase_and_corruption_do_not_change_live_database(
    temp_db,
    tmp_path,
):
    _seed_current_data()
    out = tmp_path / "safe.wtbackup"
    secure_backup_service.export_encrypted_backup(out, PASSPHRASE)
    with db.get_connection() as conn:
        before = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]

    with pytest.raises(BackupDecryptionError):
        secure_backup_service.import_encrypted_backup(out, "wrong-passphrase")
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == before

    blob = bytearray(out.read_bytes())
    blob[-5] ^= 0xFF
    out.write_bytes(bytes(blob))
    with pytest.raises((BackupCorruptedError, BackupDecryptionError)):
        secure_backup_service.import_encrypted_backup(out, PASSPHRASE)
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == before


def test_replace_failure_rolls_back_and_fails_closed(
    temp_db,
    tmp_path,
    monkeypatch,
):
    _seed_current_data()
    out = tmp_path / "rollback.wtbackup"
    secure_backup_service.export_encrypted_backup(out, PASSPHRASE)
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    with db.get_connection() as conn:
        before = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]

    def fail(_data):
        raise sqlite3.OperationalError("simulated replace failure")

    monkeypatch.setattr(secure_backup_service, "_replace_import", fail)
    with pytest.raises(sqlite3.OperationalError):
        secure_backup_service.import_encrypted_backup(out, PASSPHRASE)

    assert secure_backup_service.is_secure_import_in_progress() is False
    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status") == "paused"
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == before


def test_secure_import_preserves_preexisting_user_pause(temp_db, tmp_path):
    _seed_current_data()
    out = tmp_path / "maintenance.wtbackup"
    secure_backup_service.export_encrypted_backup(out, PASSPHRASE)
    set_setting("user_paused", "true")
    set_setting("collector_status", "paused")

    secure_backup_service.import_encrypted_backup(out, PASSPHRASE)

    assert secure_backup_service.is_secure_import_in_progress() is False
    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status") == "paused"


def test_concurrent_maintenance_rejects_import(temp_db, tmp_path):
    _seed_current_data()
    out = tmp_path / "busy.wtbackup"
    secure_backup_service.export_encrypted_backup(out, PASSPHRASE)
    with database_maintenance_service.consistent_snapshot("test"):
        with pytest.raises(BackupImportInProgressError):
            secure_backup_service.import_encrypted_backup(out, PASSPHRASE)


def test_file_and_payload_size_limits_fail_closed(temp_db, tmp_path, monkeypatch):
    path = tmp_path / "oversize.wtbackup"
    path.write_bytes(b"x" * 10)
    monkeypatch.setattr(secure_backup_service, "MAX_BACKUP_FILE_BYTES", 5)
    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(path, PASSPHRASE)

    monkeypatch.setattr(secure_backup_service, "MAX_BACKUP_PAYLOAD_BYTES", 5)
    with pytest.raises(SecureBackupError):
        _current_payload()


def test_manifest_parse_requires_no_passphrase(temp_db, tmp_path):
    out = tmp_path / "manifest.wtbackup"
    secure_backup_service.export_encrypted_backup(out, PASSPHRASE)
    info = secure_backup_service.parse_encrypted_backup_manifest(out)
    assert info.payload_format == "wtenc1"
    assert info.app_version


def test_empty_passphrase_and_non_replace_mode_are_rejected(temp_db, tmp_path):
    with pytest.raises(SecureBackupError):
        secure_backup_service.export_encrypted_backup(tmp_path / "x.wtbackup", "")
    out = tmp_path / "mode.wtbackup"
    secure_backup_service.export_encrypted_backup(out, PASSPHRASE)
    with pytest.raises(SecureBackupError):
        secure_backup_service.import_encrypted_backup(out, PASSPHRASE, mode="merge")
