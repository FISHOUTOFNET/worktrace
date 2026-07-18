"""Tests for the encrypted local backup export/import service.

Includes import guard, DB safety, and logging hygiene tests.
"""

from __future__ import annotations
from tests.support import runtime_state_fixture

import json
import logging
import sqlite3
from pathlib import Path

import pytest

pytestmark = [pytest.mark.security_privacy, pytest.mark.integration, pytest.mark.db]

from worktrace.api import backup_api
from worktrace.db import get_connection, now_str
from worktrace.services import secure_backup_service
from worktrace.services.secure_backup_service import (
    BackupCorruptedError,
    BackupDecryptionError,
    BackupImportInProgressError,
    BackupVersionNotSupportedError,
    SecureBackupError,
)
from worktrace.services.settings_service import (
    get_bool_setting,
    get_setting,
    set_setting,
)
from worktrace.security.backup_format import (
    MAGIC,
    create_encrypted_backup,
    decrypt_encrypted_backup,
)


# Distinctive test markers used for plaintext-leak checks.
TEST_PROJECT_NAME = "TestProject-Alpha-7Q2"
TEST_WINDOW_TITLE = "TestWindow-Beta-Title-9XK"
TEST_FILE_PATH = "C:\\TestPath-Gamma-5M8\\secret-file.docx"
TEST_NOTE = "TestNote-Delta-Secret-3RJ"
TEST_COPIED_TEXT = "TestClipboard-Epsilon-Secret-1W4"
TEST_FOLDER_PATH = "D:\\TestFolder-Zeta-6P0"


def _seed_test_data() -> None:
    """Insert distinctive test rows into the current database."""
    ts = now_str()
    with get_connection() as conn:
        # A user project (system projects already exist from seed_defaults).
        conn.execute(
            """
            INSERT INTO project(name, description, is_archived, enabled, created_by, created_at, updated_at)
            VALUES (?, 'test project', 0, 1, 'user', ?, ?)
            """,
            (TEST_PROJECT_NAME, ts, ts),
        )
        project_id = conn.execute(
            "SELECT id FROM project WHERE name = ?", (TEST_PROJECT_NAME,)
        ).fetchone()["id"]

        # An activity log with a distinctive window title and file path.
        conn.execute(
            """
            INSERT INTO activity_log(
                start_time, end_time, duration_seconds, app_name, process_name,
                window_title, file_path_hint, status, source, created_at, updated_at
            )
            VALUES (?, ?, 60, 'TestApp', 'test.exe', ?, ?, 'normal', 'auto', ?, ?)
            """,
            ("2026-06-25 10:00:00", "2026-06-25 10:01:00", TEST_WINDOW_TITLE, TEST_FILE_PATH, ts, ts),
        )
        activity_id = conn.execute(
            "SELECT id FROM activity_log WHERE window_title = ?", (TEST_WINDOW_TITLE,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual, created_at, updated_at
            )
            VALUES (?, ?, 100, 'manual', 1, ?, ?)
            """,
            (activity_id, project_id, ts, ts),
        )

        # An activity resource.
        conn.execute(
            """
            INSERT INTO activity_resource(
                activity_id, resource_kind, resource_subtype, display_name, identity_key,
                is_anchor, confidence, source, app_name, process_name, window_title,
                path_hint, created_at, updated_at
            )
            VALUES (?, 'office_document', 'word', 'secret-file.docx', 'identity-key-1',
                    1, 100, 'detector', 'TestApp', 'test.exe', ?, ?, ?, ?)
            """,
            (activity_id, TEST_WINDOW_TITLE, TEST_FILE_PATH, ts, ts),
        )

        # A clipboard event with distinctive copied text.
        conn.execute(
            """
            INSERT INTO activity_clipboard_event(
                activity_id, copied_at, app_name, process_name, window_title,
                file_path_hint, copied_text, text_hash, text_length, created_at, updated_at
            )
            VALUES (?, ?, 'TestApp', 'test.exe', ?, ?, ?, 'hash-1', 28, ?, ?)
            """,
            (activity_id, "2026-06-25 10:00:30", TEST_WINDOW_TITLE, TEST_FILE_PATH, TEST_COPIED_TEXT, ts, ts),
        )

        # A projected session edit command.
        cur = conn.execute(
            """
            INSERT INTO report_session_operation(
                report_date, operation_type, source_instance_key, source_expected_revision,
                target_instance_key, target_expected_revision, direction, sequence,
                payload_json, created_at
            )
            VALUES (?, 'edit_session', ?, ?, NULL, NULL, NULL, 1, ?, ?)
            """,
            (
                "2026-06-25",
                "base:" + "a" * 40,
                "b" * 40,
                json.dumps(
                    {
                        "payload_version": 4,
                        "project": {"mode": "set", "project_id": project_id},
                        "duration": {"mode": "set", "value": 60},
                        "note": {"mode": "set", "value": TEST_NOTE},
                    },
                    ensure_ascii=False,
                ),
                ts,
            ),
        )
        operation_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO report_session_operation_member(
                operation_id, role, activity_id, report_date, slice_start_time
            )
            VALUES (?, 'source', ?, ?, ?)
            """,
            (
                operation_id,
                activity_id,
                "2026-06-25",
                "2026-06-25 10:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO report_mutation_request(
                request_id, input_signature, outcome_type, operation_id, result_json, created_at, committed_at
            )
            VALUES ('backup-seed-edit', 'seed-signature', 'operation_committed', ?, ?, ?, ?)
            """,
            (
                operation_id,
                json.dumps(
                    {
                        "request_id": "backup-seed-edit",
                        "outcome_type": "operation_committed",
                        "operation_id": operation_id,
                        "report_date": "2026-06-25",
                        "selection_hint": None,
                        "snapshot_revision": "c" * 40,
                    },
                    ensure_ascii=False,
                ),
                ts,
                ts,
            ),
        )

        # A folder rule.
        conn.execute(
            """
            INSERT INTO folder_project_rule(
                folder_path, normalized_folder_key, project_id, recursive, enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, 1, 1, ?, ?)
            """,
            (TEST_FOLDER_PATH, TEST_FOLDER_PATH.lower(), project_id, ts, ts),
        )
        folder_rule_id = conn.execute(
            "SELECT id FROM folder_project_rule WHERE folder_path = ?", (TEST_FOLDER_PATH,)
        ).fetchone()["id"]

        # Folder rule index state (ready).
        conn.execute(
            """
            INSERT INTO folder_rule_index_state(
                folder_rule_id, status, valid_from, last_indexed_at, file_count,
                refresh_requested, created_at, updated_at
            )
            VALUES (?, 'ready', ?, ?, 5, 0, ?, ?)
            """,
            (folder_rule_id, ts, ts, ts, ts),
        )

        # Folder rule file index entry (derived cache — must NOT be exported).
        conn.execute(
            """
            INSERT INTO folder_rule_file_index(
                folder_rule_id, file_name, normalized_file_name, file_path,
                normalized_path_key, mtime, size, created_at, updated_at
            )
            VALUES (?, 'cache-file.txt', 'cache-file.txt', ?, ?, 1000.0, 100, ?, ?)
            """,
            (folder_rule_id, TEST_FOLDER_PATH + "\\cache-file.txt", (TEST_FOLDER_PATH + "\\cache-file.txt").lower(), ts, ts),
        )

        # A project rule.
        conn.execute(
            """
            INSERT INTO project_rule(
                rule_type, pattern, normalized_pattern, project_id,
                enabled, priority, created_by, created_at, updated_at
            )
            VALUES ('keyword', 'alpha', 'alpha', ?, 1, 10, 'user', ?, ?)
            """,
            (project_id, ts, ts),
        )


def _row_counts() -> dict[str, int]:
    with get_connection() as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            for table in (
                "project",
                "activity_log",
                "activity_project_assignment",
                "activity_resource",
                "activity_clipboard_event",
                "report_session_operation",
                "report_session_operation_member",
                "report_mutation_request",
                "folder_project_rule",
                "folder_rule_index_state",
                "folder_rule_file_index",
                "project_rule",
            )
        }


def test_export_creates_encrypted_file_without_plaintext(temp_db, tmp_path: Path):
    _seed_test_data()
    output = tmp_path / "backup.wtbackup"

    result = secure_backup_service.export_encrypted_backup(
        output, "correct horse battery staple"
    )

    assert result == output
    assert output.exists()
    raw = output.read_bytes()
    assert raw.startswith(MAGIC)
    for marker in (
        TEST_PROJECT_NAME,
        TEST_WINDOW_TITLE,
        TEST_FILE_PATH,
        TEST_NOTE,
        TEST_COPIED_TEXT,
        TEST_FOLDER_PATH,
    ):
        assert marker.encode("utf-8") not in raw


def test_export_payload_contains_required_tables(temp_db):
    _seed_test_data()

    payload = secure_backup_service._build_export_payload()
    data = json.loads(payload.decode("utf-8"))

    assert data["format"] == secure_backup_service.PAYLOAD_FORMAT
    assert data["version"] == 5
    assert data["schema_version"] == secure_backup_service.SCHEMA_VERSION
    assert set(data["tables"]) == set(secure_backup_service.EXPORT_TABLES)
    required = list(secure_backup_service.EXPORT_TABLES)
    for table in required:
        assert table in data["tables"]
    for table in secure_backup_service.EXCLUDED_TABLES:
        assert table not in data["tables"]


def test_backup_settings_are_allowlisted_and_exclude_runtime_state(temp_db):
    _seed_test_data()
    set_setting("ui_refresh_seconds", "17")
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    set_setting("last_collector_heartbeat", "2026-06-25 10:01:00")
    set_setting("collector_last_failure_kind", "RuntimeError")
    set_setting("current_activity_snapshot", '{"activity_id": 999}')

    payload = secure_backup_service._build_export_payload()
    data = json.loads(payload.decode("utf-8"))
    settings = {
        str(row["key"]): str(row["value"])
        for row in data["tables"]["settings"]
    }

    assert settings["ui_refresh_seconds"] == "17"
    assert set(settings) <= secure_backup_service.MIGRATABLE_SETTINGS
    assert "user_paused" not in settings
    assert "collector_status" not in settings
    assert "last_collector_heartbeat" not in settings
    assert "collector_last_failure_kind" not in settings
    assert "current_activity_snapshot" not in settings


def test_import_round_trip_restores_rows_and_excludes_cache(temp_db, tmp_path: Path):
    _seed_test_data()
    before = _row_counts()
    backup = tmp_path / "roundtrip.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase-123")

    # Disturb the live database.
    with get_connection() as conn:
        conn.execute("DELETE FROM activity_clipboard_event")
        conn.execute("DELETE FROM activity_project_assignment")
        conn.execute("DELETE FROM activity_resource")
        conn.execute("DELETE FROM report_session_operation_member")
        conn.execute("DELETE FROM report_mutation_request")
        conn.execute("DELETE FROM report_session_operation")
        conn.execute("DELETE FROM folder_rule_file_index")
        conn.execute("DELETE FROM activity_log")
        conn.execute("DELETE FROM project_rule")
        conn.execute("DELETE FROM folder_rule_index_state")
        conn.execute("DELETE FROM folder_project_rule")
        conn.execute("DELETE FROM project WHERE name = ?", (TEST_PROJECT_NAME,))

    result = secure_backup_service.import_encrypted_backup(
        backup, "passphrase-123"
    )

    assert result.mode == "replace"
    after = _row_counts()
    assert after["project"] == before["project"]
    assert after["activity_log"] == before["activity_log"]
    assert after["activity_project_assignment"] == before["activity_project_assignment"]
    assert after["activity_resource"] == before["activity_resource"]
    assert after["activity_clipboard_event"] == before["activity_clipboard_event"]
    assert after["report_session_operation"] == before["report_session_operation"]
    assert after["report_session_operation_member"] == before["report_session_operation_member"]
    assert after["report_mutation_request"] == before["report_mutation_request"]
    assert after["folder_project_rule"] == before["folder_project_rule"]
    assert after["folder_rule_index_state"] == before["folder_rule_index_state"]
    assert after["project_rule"] == before["project_rule"]
    # Derived file index is deliberately reset, not restored.
    assert after["folder_rule_file_index"] == 0
    with get_connection() as conn:
        state = conn.execute(
            "SELECT status, refresh_requested FROM folder_rule_index_state"
        ).fetchone()
        assert state["status"] == "pending"
        assert state["refresh_requested"] == 1


def test_import_wrong_passphrase_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    backup = tmp_path / "wrong-pass.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "right-pass")

    with pytest.raises(BackupDecryptionError):
        secure_backup_service.import_encrypted_backup(backup, "wrong-pass")


def test_import_tampered_ciphertext_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    backup = tmp_path / "tampered.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase")
    raw = bytearray(backup.read_bytes())
    raw[-1] ^= 0x01
    backup.write_bytes(bytes(raw))

    with pytest.raises(BackupDecryptionError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_random_file_raises(temp_db, tmp_path: Path):
    backup = tmp_path / "random.wtbackup"
    backup.write_bytes(b"not a backup file")

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_unsupported_version_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["version"] = 999
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "unsupported.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupVersionNotSupportedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_unsupported_schema_version_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["schema_version"] = "999"
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "unsupported-schema.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupVersionNotSupportedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_schema_fingerprint_mismatch_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["schema_fingerprint"] = "0" * 64
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "wrong-fingerprint.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_published_v8_backup_remains_importable(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["version"] = 4
    payload["schema_version"] = "8"
    payload["schema_fingerprint"] = (
        secure_backup_service._LEGACY_BACKUP_SCHEMA_FINGERPRINTS["8"]
    )
    payload["tables"].pop("activity_inference_job", None)
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "published-v8.wtbackup"
    backup.write_bytes(blob)

    result = secure_backup_service.import_encrypted_backup(backup, "passphrase")

    assert result.mode == "replace"
    with get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM activity_log"
        ).fetchone()["c"] == 1


def test_import_missing_table_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"].pop("project")
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "missing-table.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_extra_table_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["unexpected_table"] = []
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "extra-table.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_row_column_mismatch_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["project"][0]["unexpected_column"] = "bad"
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "column-mismatch.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_foreign_key_violation_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["activity_project_assignment"][0]["project_id"] = 999999
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "fk-violation.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_open_activity_is_closed_deterministically(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    activity = payload["tables"]["activity_log"][0]
    activity["end_time"] = None
    activity["duration_seconds"] = 120
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "open-activity.wtbackup"
    backup.write_bytes(blob)

    result = secure_backup_service.import_encrypted_backup(backup, "passphrase")

    assert result.mode == "replace"
    with get_connection() as conn:
        row = conn.execute(
            "SELECT start_time, end_time, duration_seconds FROM activity_log"
        ).fetchone()
    assert row["start_time"] == "2026-06-25 10:00:00"
    assert row["end_time"] == "2026-06-25 10:02:00"
    assert row["duration_seconds"] == 120


def test_import_negative_activity_duration_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["activity_log"][0]["duration_seconds"] = -1
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "negative-duration.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_closed_activity_missing_duration_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["activity_log"][0]["duration_seconds"] = None
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "missing-duration.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_activity_end_before_start_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    activity = payload["tables"]["activity_log"][0]
    activity["end_time"] = "2026-06-25 09:59:59"
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "backward-activity.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_activity_duration_shorter_than_interval_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    activity = payload["tables"]["activity_log"][0]
    activity["duration_seconds"] = 30
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "short-duration.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_activity_unknown_status_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["activity_log"][0]["status"] = "mystery"
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "unknown-status.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_invalid_operation_payload_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    operation = payload["tables"]["report_session_operation"][0]
    operation["payload_json"] = json.dumps(
        {"payload_version": 4, "unexpected": True}
    )
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "bad-operation-payload.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_operation_missing_source_member_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["report_session_operation_member"] = []
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "missing-operation-member.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_mutation_request_invalid_json_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["report_mutation_request"][0]["result_json"] = "not-json"
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "bad-request-json.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_duplicate_operation_sequence_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    operation = dict(payload["tables"]["report_session_operation"][0])
    operation["id"] = int(operation["id"]) + 100
    payload["tables"]["report_session_operation"].append(operation)
    member = dict(payload["tables"]["report_session_operation_member"][0])
    member["operation_id"] = operation["id"]
    payload["tables"]["report_session_operation_member"].append(member)
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "duplicate-operation-sequence.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_mutation_request_missing_operation_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["report_mutation_request"][0]["operation_id"] = 999999
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "missing-request-operation.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_replay_revision_conflict_raises(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["tables"]["report_session_operation"][0][
        "source_expected_revision"
    ] = "0" * 40
    blob = create_encrypted_backup(
        json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
    )
    backup = tmp_path / "replay-conflict.wtbackup"
    backup.write_bytes(blob)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(backup, "passphrase")


def test_import_preserves_activity_resource(temp_db, tmp_path: Path):
    _seed_test_data()
    backup = tmp_path / "resource-roundtrip.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase")

    secure_backup_service.import_encrypted_backup(backup, "passphrase")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT resource_kind, identity_key, path_hint FROM activity_resource"
        ).fetchone()
    assert row["resource_kind"] == "office_document"
    assert row["identity_key"] == "identity-key-1"
    assert row["path_hint"] == TEST_FILE_PATH


def test_import_preserves_clipboard_event(temp_db, tmp_path: Path):
    _seed_test_data()
    backup = tmp_path / "clipboard-roundtrip.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase")

    secure_backup_service.import_encrypted_backup(backup, "passphrase")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT copied_text, file_path_hint FROM activity_clipboard_event"
        ).fetchone()
    assert row["copied_text"] == TEST_COPIED_TEXT
    assert row["file_path_hint"] == TEST_FILE_PATH


def test_import_preserves_report_mutation_request(temp_db, tmp_path: Path):
    _seed_test_data()
    backup = tmp_path / "request-roundtrip.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase")

    secure_backup_service.import_encrypted_backup(backup, "passphrase")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT request_id, outcome_type, operation_id FROM report_mutation_request"
        ).fetchone()
    assert row["request_id"] == "backup-seed-edit"
    assert row["outcome_type"] == "operation_committed"
    assert row["operation_id"] is not None


def test_import_resets_folder_index(temp_db, tmp_path: Path):
    _seed_test_data()
    backup = tmp_path / "index-reset.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase")

    secure_backup_service.import_encrypted_backup(backup, "passphrase")

    with get_connection() as conn:
        state = conn.execute(
            "SELECT status, valid_from, last_indexed_at, file_count, refresh_requested "
            "FROM folder_rule_index_state"
        ).fetchone()
        cache_count = conn.execute(
            "SELECT COUNT(*) AS c FROM folder_rule_file_index"
        ).fetchone()["c"]
    assert state["status"] == "pending"
    assert state["valid_from"] is None
    assert state["last_indexed_at"] is None
    assert state["file_count"] == 0
    assert state["refresh_requested"] == 1
    assert cache_count == 0


def test_import_requires_replace_mode(temp_db, tmp_path: Path):
    backup = tmp_path / "mode.wtbackup"
    backup.write_bytes(b"x")

    with pytest.raises(SecureBackupError, match="unsupported import mode"):
        secure_backup_service.import_encrypted_backup(
            backup, "passphrase", mode="merge"
        )


def test_export_requires_passphrase(temp_db, tmp_path: Path):
    with pytest.raises(SecureBackupError, match="passphrase is required"):
        secure_backup_service.export_encrypted_backup(
            tmp_path / "empty.wtbackup", ""
        )


def test_import_requires_passphrase(temp_db, tmp_path: Path):
    with pytest.raises(SecureBackupError, match="passphrase is required"):
        secure_backup_service.import_encrypted_backup(
            tmp_path / "missing.wtbackup", ""
        )


def test_import_guard_rejects_concurrent_operation(temp_db):
    lock = secure_backup_service.SECURE_IMPORT_COORDINATOR._maintenance_lock
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(BackupImportInProgressError):
            with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire():
                pass
    finally:
        lock.release()


def test_import_guard_sets_and_clears_import_flag(temp_db):
    assert secure_backup_service.is_secure_import_in_progress() is False
    with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire() as guard:
        assert secure_backup_service.is_secure_import_in_progress() is True
        guard.mark_succeeded()
    assert secure_backup_service.is_secure_import_in_progress() is False


def test_import_guard_preserves_user_pause_state_on_failure(temp_db):
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")

    with pytest.raises(RuntimeError, match="boom"):
        with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire():
            raise RuntimeError("boom")

    assert get_bool_setting("user_paused", True) is False
    assert get_setting("collector_status") == "running"


def test_import_guard_leaves_paused_after_success(temp_db):
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")

    with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire() as guard:
        guard.mark_succeeded()

    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status") == "paused"


def test_import_guard_unknown_pause_state_fails_closed(temp_db):
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")

    def unknown_pause(**_kwargs):
        return {
            "ok": False,
            "pause_pending": False,
            "command_state_unknown": True,
        }

    secure_backup_service.register_collector_pause_handler(unknown_pause)
    try:
        with pytest.raises(
            SecureBackupError,
            match="collector_pause_not_acknowledged",
        ):
            with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire():
                pass
    finally:
        secure_backup_service.clear_collector_pause_handler(unknown_pause)

    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status") == "paused"


def test_import_guard_unknown_reset_state_fails_closed(temp_db):
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")

    def acknowledged_pause(**_kwargs):
        return {"ok": True, "pause_pending": False}

    def unknown_reset(**_kwargs):
        return {
            "ok": False,
            "reset_pending": False,
            "command_state_unknown": True,
        }

    secure_backup_service.register_collector_pause_handler(acknowledged_pause)
    secure_backup_service.register_collector_reset_handler(unknown_reset)
    try:
        with pytest.raises(
            SecureBackupError,
            match="collector_reset_not_acknowledged",
        ):
            with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire():
                pass
    finally:
        secure_backup_service.clear_collector_pause_handler(acknowledged_pause)
        secure_backup_service.clear_collector_reset_handler(unknown_reset)

    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status") == "paused"


def test_import_guard_calls_pause_and_reset_handlers(temp_db):
    calls: list[str] = []

    def pause_handler(**_kwargs):
        calls.append("pause")
        return {"ok": True, "pause_pending": False}

    def reset_handler(**_kwargs):
        calls.append("reset")
        return {"ok": True, "reset_pending": False}

    secure_backup_service.register_collector_pause_handler(pause_handler)
    secure_backup_service.register_collector_reset_handler(reset_handler)
    try:
        with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire() as guard:
            guard.mark_succeeded()
    finally:
        secure_backup_service.clear_collector_pause_handler(pause_handler)
        secure_backup_service.clear_collector_reset_handler(reset_handler)

    assert calls == ["pause", "reset"]


def test_import_guard_pause_failure_restores_state(temp_db):
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")

    def pause_handler(**_kwargs):
        return {"ok": False, "pause_pending": False}

    secure_backup_service.register_collector_pause_handler(pause_handler)
    try:
        with pytest.raises(
            SecureBackupError,
            match="collector_pause_not_acknowledged",
        ):
            with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire():
                pass
    finally:
        secure_backup_service.clear_collector_pause_handler(pause_handler)

    assert get_bool_setting("user_paused", True) is False
    assert get_setting("collector_status") == "running"


def test_import_guard_reset_failure_restores_state(temp_db):
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")

    def pause_handler(**_kwargs):
        return {"ok": True, "pause_pending": False}

    def reset_handler(**_kwargs):
        return {"ok": False, "reset_pending": False}

    secure_backup_service.register_collector_pause_handler(pause_handler)
    secure_backup_service.register_collector_reset_handler(reset_handler)
    try:
        with pytest.raises(
            SecureBackupError,
            match="collector_reset_not_acknowledged",
        ):
            with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire():
                pass
    finally:
        secure_backup_service.clear_collector_pause_handler(pause_handler)
        secure_backup_service.clear_collector_reset_handler(reset_handler)

    assert get_bool_setting("user_paused", True) is False
    assert get_setting("collector_status") == "running"


def test_import_guard_phase_transitions(temp_db):
    coordinator = secure_backup_service.SECURE_IMPORT_COORDINATOR
    assert coordinator.phase() is secure_backup_service.SecureImportPhase.IDLE
    with coordinator.acquire() as guard:
        assert coordinator.phase() is secure_backup_service.SecureImportPhase.EXCLUSIVE
        guard.mark_succeeded()
    assert coordinator.phase() is secure_backup_service.SecureImportPhase.IDLE


def test_import_guard_clears_runtime_activity_state(temp_db):
    runtime_state_fixture.publish_activity(321)
    with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire() as guard:
        assert runtime_state_fixture.read_activity() is None
        runtime_state_fixture.publish_activity(654)
        guard.mark_succeeded()
    assert runtime_state_fixture.read_activity() is None


def test_import_guard_does_not_write_raw_snapshot_setting(temp_db):
    set_setting("current_activity_snapshot", '{"activity_id": 999}')
    with secure_backup_service.SECURE_IMPORT_COORDINATOR.acquire() as guard:
        guard.mark_succeeded()
    assert get_setting("current_activity_snapshot") == '{"activity_id": 999}'


def test_import_success_disables_clipboard_capture(temp_db, tmp_path: Path):
    _seed_test_data()
    set_setting("clipboard_capture_enabled", "true")
    backup = tmp_path / "clipboard-disabled.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase")

    secure_backup_service.import_encrypted_backup(backup, "passphrase")

    assert get_bool_setting("clipboard_capture_enabled", True) is False


def test_import_failure_restores_prior_clipboard_capture_setting(temp_db, tmp_path: Path):
    set_setting("clipboard_capture_enabled", "true")
    bad = tmp_path / "bad.wtbackup"
    bad.write_bytes(b"not-a-backup")

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(bad, "passphrase")

    assert get_bool_setting("clipboard_capture_enabled", False) is True


def test_api_export_and_import_round_trip(temp_db, tmp_path: Path):
    _seed_test_data()
    backup = tmp_path / "api-roundtrip.wtbackup"

    exported = backup_api.export_encrypted_backup(str(backup), "passphrase")
    assert exported["ok"] is True
    assert exported["path"] == str(backup)

    imported = backup_api.import_encrypted_backup(str(backup), "passphrase")
    assert imported["ok"] is True
    assert imported["mode"] == "replace"
    assert imported["folder_index_reset"] is True


def test_api_import_wrong_passphrase_returns_safe_error(temp_db, tmp_path: Path):
    _seed_test_data()
    backup = tmp_path / "api-wrong-pass.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "right-pass")

    result = backup_api.import_encrypted_backup(str(backup), "wrong-pass")

    assert result["ok"] is False
    assert result["error"] == "backup_decryption_failed"
    assert "wrong-pass" not in str(result)


def test_api_import_corrupted_file_returns_safe_error(temp_db, tmp_path: Path):
    backup = tmp_path / "api-corrupted.wtbackup"
    backup.write_bytes(b"corrupt")

    result = backup_api.import_encrypted_backup(str(backup), "passphrase")

    assert result["ok"] is False
    assert result["error"] == "backup_corrupted"


def test_api_import_unsupported_version_returns_safe_error(temp_db, tmp_path: Path):
    _seed_test_data()
    payload = json.loads(
        secure_backup_service._build_export_payload().decode("utf-8")
    )
    payload["version"] = 999
    backup = tmp_path / "api-unsupported.wtbackup"
    backup.write_bytes(
        create_encrypted_backup(
            json.dumps(payload).encode("utf-8"), "passphrase", "0.1.0"
        )
    )

    result = backup_api.import_encrypted_backup(str(backup), "passphrase")

    assert result["ok"] is False
    assert result["error"] == "backup_version_unsupported"


def test_api_import_busy_returns_safe_error(temp_db, tmp_path: Path):
    backup = tmp_path / "busy.wtbackup"
    backup.write_bytes(b"x")
    lock = secure_backup_service.SECURE_IMPORT_COORDINATOR._maintenance_lock
    assert lock.acquire(blocking=False)
    try:
        result = backup_api.import_encrypted_backup(str(backup), "passphrase")
    finally:
        lock.release()

    assert result["ok"] is False
    assert result["error"] == "backup_import_in_progress"


def test_api_export_failure_does_not_leak_passphrase(temp_db, monkeypatch):
    secret = "super-secret-passphrase"

    def fail_export(_path, _passphrase):
        raise SecureBackupError(f"internal failure: {secret}")

    monkeypatch.setattr(backup_api, "export_backup", fail_export)
    result = backup_api.export_encrypted_backup("x.wtbackup", secret)

    assert result["ok"] is False
    assert result["error"] == "backup_export_failed"
    assert secret not in str(result)


def test_api_import_failure_does_not_leak_passphrase(temp_db, monkeypatch):
    secret = "super-secret-passphrase"

    def fail_import(_path, _passphrase, mode="replace"):
        raise SecureBackupError(f"internal failure: {secret}")

    monkeypatch.setattr(backup_api, "import_backup", fail_import)
    result = backup_api.import_encrypted_backup("x.wtbackup", secret)

    assert result["ok"] is False
    assert result["error"] == "backup_import_failed"
    assert secret not in str(result)


def test_service_logs_do_not_contain_passphrase_or_paths(temp_db, tmp_path: Path, caplog):
    _seed_test_data()
    backup = tmp_path / "hygiene.wtbackup"
    passphrase = "LogSecret-Passphrase-8H3"

    with caplog.at_level(logging.INFO):
        secure_backup_service.export_encrypted_backup(backup, passphrase)
        secure_backup_service.import_encrypted_backup(backup, passphrase)

    logs = caplog.text
    assert passphrase not in logs
    assert str(backup) not in logs
    assert TEST_PROJECT_NAME not in logs
    assert TEST_FILE_PATH not in logs
    assert TEST_COPIED_TEXT not in logs


def test_parse_manifest_returns_metadata_without_decrypting(temp_db, tmp_path: Path):
    _seed_test_data()
    backup = tmp_path / "manifest.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase")

    info = secure_backup_service.parse_encrypted_backup_manifest(backup)

    assert info.version == 4
    assert info.payload_format == "json"
    assert info.payload_alg == "AES-256-GCM"
    assert info.kdf_algorithm == "argon2id"
    assert info.app_version
    assert info.created_at.endswith("Z")


def test_decrypted_payload_contains_expected_markers(temp_db):
    _seed_test_data()
    payload = secure_backup_service._build_export_payload()
    blob = create_encrypted_backup(payload, "passphrase", "0.1.0")
    decrypted = decrypt_encrypted_backup(blob, "passphrase")
    text = decrypted.decode("utf-8")

    assert TEST_PROJECT_NAME in text
    assert TEST_WINDOW_TITLE in text
    assert TEST_FILE_PATH in text
    assert TEST_NOTE in text
    assert TEST_COPIED_TEXT in text
    assert TEST_FOLDER_PATH in text


def test_backup_file_size_limit(temp_db, tmp_path: Path):
    oversized = tmp_path / "oversized.wtbackup"
    oversized.write_bytes(b"x")

    class FakeStat:
        st_size = secure_backup_service.MAX_BACKUP_FILE_BYTES + 1

    original_stat = Path.stat

    def fake_stat(self):
        if self == oversized:
            return FakeStat()
        return original_stat(self)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "stat", fake_stat)
        with pytest.raises(BackupCorruptedError):
            secure_backup_service.import_encrypted_backup(
                oversized, "passphrase"
            )


def test_backup_payload_size_limit(temp_db, tmp_path: Path, monkeypatch):
    _seed_test_data()
    backup = tmp_path / "payload-too-large.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase")

    monkeypatch.setattr(
        secure_backup_service,
        "MAX_BACKUP_PAYLOAD_BYTES",
        10,
    )
    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(
            backup, "passphrase"
        )


def test_import_rolls_back_on_live_validation_failure(temp_db, tmp_path: Path, monkeypatch):
    _seed_test_data()
    backup = tmp_path / "rollback.wtbackup"
    secure_backup_service.export_encrypted_backup(backup, "passphrase")
    before = _row_counts()

    original_validate = secure_backup_service._validate_staging_database
    calls = {"count": 0}

    def fail_live_validation(conn):
        calls["count"] += 1
        if calls["count"] == 2:
            raise BackupCorruptedError("backup file is invalid or corrupted")
        return original_validate(conn)

    monkeypatch.setattr(
        secure_backup_service,
        "_validate_staging_database",
        fail_live_validation,
    )

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(
            backup, "passphrase"
        )

    assert _row_counts() == before


def test_import_does_not_log_exception_text(temp_db, tmp_path: Path, caplog):
    backup = tmp_path / "random.wtbackup"
    backup.write_bytes(b"not-a-backup")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(BackupCorruptedError):
            secure_backup_service.import_encrypted_backup(
                backup, "passphrase"
            )

    assert "not-a-backup" not in caplog.text
    assert str(backup) not in caplog.text
