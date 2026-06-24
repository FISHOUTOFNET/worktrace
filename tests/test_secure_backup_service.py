"""Tests for the Phase 1B encrypted local backup export/import service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worktrace.api import backup_api
from worktrace.db import get_connection, now_str
from worktrace.services import secure_backup_service
from worktrace.services.secure_backup_service import (
    BackupCorruptedError,
    BackupDecryptionError,
    BackupVersionNotSupportedError,
    SecureBackupError,
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
                window_title, file_path_hint, status, source, project_id, note, created_at, updated_at
            )
            VALUES (?, ?, 60, 'TestApp', 'test.exe', ?, ?, 'normal', 'auto', ?, ?, ?, ?)
            """,
            ("2026-06-25 10:00:00", "2026-06-25 10:01:00", TEST_WINDOW_TITLE, TEST_FILE_PATH, project_id, TEST_NOTE, ts, ts),
        )
        activity_id = conn.execute(
            "SELECT id FROM activity_log WHERE window_title = ?", (TEST_WINDOW_TITLE,)
        ).fetchone()["id"]

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

        # A project session note.
        conn.execute(
            """
            INSERT INTO project_session_note(report_date, first_activity_id, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-06-25", activity_id, TEST_NOTE, ts, ts),
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
            INSERT INTO project_rule(project_id, rule_type, pattern, enabled, created_by, created_at, updated_at)
            VALUES (?, 'keyword', 'alpha-keyword', 1, 'user', ?, ?)
            """,
            (project_id, ts, ts),
        )

        # An activity project assignment.
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual, created_at, updated_at
            )
            VALUES (?, ?, 100, 'manual', 1, ?, ?)
            """,
            (activity_id, project_id, ts, ts),
        )

        # A session boundary.
        conn.execute(
            """
            INSERT INTO session_boundary(occurred_at, reason, created_at)
            VALUES (?, 'manual', ?)
            """,
            ("2026-06-25 10:00:00", ts),
        )


def _row_counts() -> dict[str, int]:
    tables = [
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
    ]
    counts: dict[str, int] = {}
    with get_connection() as conn:
        for table in tables:
            counts[table] = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    return counts


# --- payload export tests ------------------------------------------------


def test_export_payload_contains_required_tables(temp_db, tmp_path):
    _seed_test_data()
    payload = secure_backup_service._build_export_payload()
    data = json.loads(payload.decode("utf-8"))

    assert data["format"] == "worktrace-local-data"
    assert data["version"] == 1
    tables = data["tables"]
    for required in [
        "project",
        "activity_log",
        "settings",
        "session_boundary",
        "folder_project_rule",
        "folder_rule_index_state",
        "project_rule",
        "activity_project_assignment",
        "activity_clipboard_event",
        "project_session_note",
        "activity_resource",
    ]:
        assert required in tables, f"missing table {required} in payload"


def test_export_payload_excludes_folder_rule_file_index(temp_db):
    _seed_test_data()
    payload = secure_backup_service._build_export_payload()
    data = json.loads(payload.decode("utf-8"))

    assert "folder_rule_file_index" not in data["tables"]


def test_export_payload_excludes_keyring(temp_db):
    _seed_test_data()
    payload = secure_backup_service._build_export_payload()
    data = json.loads(payload.decode("utf-8"))

    assert "keyring" not in data["tables"]


def test_export_payload_excludes_runtime_state_settings(temp_db):
    from worktrace.services.settings_service import set_setting

    set_setting("current_activity_snapshot", '{"app":"runtime-state-marker"}')
    set_setting("collector_status", "running")

    payload = secure_backup_service._build_export_payload()
    data = json.loads(payload.decode("utf-8"))

    settings_rows = {row["key"] for row in data["tables"]["settings"]}
    assert "current_activity_snapshot" not in settings_rows
    assert "collector_status" not in settings_rows
    assert "last_collector_heartbeat" not in settings_rows
    assert "user_paused" not in settings_rows


def test_export_payload_is_valid_utf8_json(temp_db):
    _seed_test_data()
    payload = secure_backup_service._build_export_payload()

    # Should not raise.
    text = payload.decode("utf-8")
    json.loads(text)


# --- encrypted backup export tests ---------------------------------------


def test_encrypted_export_creates_wtbackup_file(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "test-export.wtbackup"

    result = secure_backup_service.export_encrypted_backup(out, "correct-passphrase")

    assert result == out
    assert out.exists()
    blob = out.read_bytes()
    assert blob.startswith(MAGIC + b"\n")


def test_wtbackup_does_not_contain_plaintext_project_name(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "leak-test.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    blob = out.read_bytes()
    assert TEST_PROJECT_NAME.encode("utf-8") not in blob


def test_wtbackup_does_not_contain_plaintext_window_title(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "leak-test.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    blob = out.read_bytes()
    assert TEST_WINDOW_TITLE.encode("utf-8") not in blob


def test_wtbackup_does_not_contain_plaintext_file_path(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "leak-test.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    blob = out.read_bytes()
    assert TEST_FILE_PATH.encode("utf-8") not in blob


def test_wtbackup_does_not_contain_plaintext_note(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "leak-test.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    blob = out.read_bytes()
    assert TEST_NOTE.encode("utf-8") not in blob


def test_wtbackup_does_not_contain_plaintext_copied_text(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "leak-test.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    blob = out.read_bytes()
    assert TEST_COPIED_TEXT.encode("utf-8") not in blob


def test_wtbackup_does_not_contain_folder_rule_file_index_data(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "leak-test.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    # Decrypt and verify the payload doesn't include folder_rule_file_index.
    blob = out.read_bytes()
    payload = decrypt_encrypted_backup(blob, "passphrase")
    data = json.loads(payload.decode("utf-8"))
    assert "folder_rule_file_index" not in data["tables"]


# --- encrypted backup import tests ---------------------------------------


def test_correct_passphrase_imports(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "round-trip.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "correct-passphrase")

    # Reset the DB so import is into a fresh profile, then verify restore.
    from worktrace.db import reset_database

    reset_database()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM project WHERE name = ?", (TEST_PROJECT_NAME,)
        ).fetchone()
    assert row is None

    result = secure_backup_service.import_encrypted_backup(out, "correct-passphrase", mode="replace")

    assert result.mode == "replace"
    assert result.folder_index_reset is True
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM project WHERE name = ?", (TEST_PROJECT_NAME,)
        ).fetchone()
    assert row is not None


def test_wrong_passphrase_fails(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "wrong-pass.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "correct-passphrase")

    with pytest.raises(BackupDecryptionError):
        secure_backup_service.import_encrypted_backup(out, "wrong-passphrase")


def test_corrupted_backup_fails(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "corrupt.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    blob = bytearray(out.read_bytes())
    # Flip a byte in the encrypted payload region (after the manifest).
    blob[-5] = blob[-5] ^ 0xFF
    out.write_bytes(bytes(blob))

    with pytest.raises((BackupCorruptedError, BackupDecryptionError)):
        secure_backup_service.import_encrypted_backup(out, "passphrase")


def test_unsupported_version_fails(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "bad-version.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    # Rewrite the manifest with an unsupported version.
    blob = out.read_bytes()
    first_nl = blob.find(b"\n")
    second_nl = blob.find(b"\n", first_nl + 1)
    manifest_len = int(blob[first_nl + 1 : second_nl].decode("ascii"))
    manifest_start = second_nl + 1
    manifest_end = manifest_start + manifest_len
    manifest_json = blob[manifest_start:manifest_end]
    encrypted_payload = blob[manifest_end:]

    manifest_data = json.loads(manifest_json.decode("utf-8"))
    manifest_data["version"] = 999
    new_manifest_json = json.dumps(
        manifest_data, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    new_blob = (
        MAGIC
        + b"\n"
        + str(len(new_manifest_json)).encode("ascii")
        + b"\n"
        + new_manifest_json
        + encrypted_payload
    )
    out.write_bytes(new_blob)

    with pytest.raises(BackupVersionNotSupportedError):
        secure_backup_service.import_encrypted_backup(out, "passphrase")


def test_import_failure_does_not_change_current_database(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "safe.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "correct-passphrase")

    counts_before = _row_counts()

    with pytest.raises(BackupDecryptionError):
        secure_backup_service.import_encrypted_backup(out, "wrong-passphrase")

    counts_after = _row_counts()
    assert counts_after == counts_before


def test_replace_import_restores_all_tables(temp_db, tmp_path):
    _seed_test_data()
    counts_before = _row_counts()
    out = tmp_path / "full-restore.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    # Wipe the DB so import is into an empty-ish profile.
    from worktrace.db import reset_database

    reset_database()
    counts_after_reset = _row_counts()
    # After reset, folder_rule_file_index is empty and user data is gone.
    assert counts_after_reset["activity_log"] == 0
    assert counts_after_reset["folder_rule_file_index"] == 0

    secure_backup_service.import_encrypted_backup(out, "passphrase", mode="replace")
    counts_after = _row_counts()

    # All user-data tables should match the original counts.
    for table in [
        "project",
        "activity_log",
        "session_boundary",
        "folder_project_rule",
        "project_rule",
        "activity_project_assignment",
        "activity_clipboard_event",
        "project_session_note",
        "activity_resource",
    ]:
        assert counts_after[table] == counts_before[table], f"row count mismatch for {table}"


def test_replace_import_restores_distinctive_data(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "data-restore.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    from worktrace.db import reset_database

    reset_database()
    secure_backup_service.import_encrypted_backup(out, "passphrase", mode="replace")

    with get_connection() as conn:
        project = conn.execute(
            "SELECT id FROM project WHERE name = ?", (TEST_PROJECT_NAME,)
        ).fetchone()
        assert project is not None

        activity = conn.execute(
            "SELECT id, window_title, file_path_hint, note FROM activity_log WHERE window_title = ?",
            (TEST_WINDOW_TITLE,),
        ).fetchone()
        assert activity is not None
        assert activity["file_path_hint"] == TEST_FILE_PATH
        assert activity["note"] == TEST_NOTE

        resource = conn.execute(
            "SELECT id FROM activity_resource WHERE activity_id = ?", (activity["id"],)
        ).fetchone()
        assert resource is not None

        clipboard = conn.execute(
            "SELECT copied_text FROM activity_clipboard_event WHERE activity_id = ?",
            (activity["id"],),
        ).fetchone()
        assert clipboard is not None
        assert clipboard["copied_text"] == TEST_COPIED_TEXT

        note = conn.execute(
            "SELECT note FROM project_session_note WHERE first_activity_id = ?",
            (activity["id"],),
        ).fetchone()
        assert note is not None
        assert note["note"] == TEST_NOTE


def test_folder_rule_file_index_not_imported_and_left_rebuildable(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "folder-index.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    secure_backup_service.import_encrypted_backup(out, "passphrase", mode="replace")

    with get_connection() as conn:
        file_index_count = conn.execute(
            "SELECT COUNT(*) AS c FROM folder_rule_file_index"
        ).fetchone()["c"]
        assert file_index_count == 0

        states = conn.execute(
            "SELECT status, refresh_requested FROM folder_rule_index_state"
        ).fetchall()
        assert len(states) > 0
        for state in states:
            assert state["status"] == "pending"
            assert state["refresh_requested"] == 1


def test_import_re_seeds_defaults(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "defaults.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    from worktrace.db import reset_database

    reset_database()
    secure_backup_service.import_encrypted_backup(out, "passphrase", mode="replace")

    with get_connection() as conn:
        for name in ("未归类", "排除规则"):
            row = conn.execute(
                "SELECT id FROM project WHERE name = ?", (name,)
            ).fetchone()
            assert row is not None, f"system project {name} missing after import"

        # Runtime-state settings should be re-seeded with defaults.
        for key in ("collector_status", "user_paused", "current_activity_snapshot"):
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            assert row is not None, f"runtime setting {key} missing after import"


# --- API boundary tests --------------------------------------------------


def test_api_export_returns_path_string(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "api-export.wtbackup"

    result = backup_api.export_encrypted_backup(str(out), "passphrase")

    assert isinstance(result, str)
    assert Path(result).exists()


def test_api_import_returns_import_result(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "api-import.wtbackup"
    backup_api.export_encrypted_backup(str(out), "passphrase")

    result = backup_api.import_encrypted_backup(str(out), "passphrase", mode="replace")

    assert result.mode == "replace"
    assert result.folder_index_reset is True


def test_api_parse_manifest_does_not_require_passphrase(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "manifest.wtbackup"
    backup_api.export_encrypted_backup(str(out), "passphrase")

    info = backup_api.parse_encrypted_backup_manifest(str(out))

    assert info.version == 1
    assert info.payload_format == "wtenc1"


def test_api_exposes_typed_errors(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "errors.wtbackup"
    backup_api.export_encrypted_backup(str(out), "correct")

    with pytest.raises(backup_api.BackupDecryptionError):
        backup_api.import_encrypted_backup(str(out), "wrong")


def test_empty_passphrase_raises(temp_db, tmp_path):
    with pytest.raises(SecureBackupError):
        secure_backup_service.export_encrypted_backup(tmp_path / "x.wtbackup", "")


def test_unsupported_mode_raises(temp_db, tmp_path):
    out = tmp_path / "mode.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    with pytest.raises(SecureBackupError):
        secure_backup_service.import_encrypted_backup(out, "passphrase", mode="merge")


# --- atomic write test ---------------------------------------------------


def test_export_uses_atomic_write(temp_db, tmp_path):
    _seed_test_data()
    out = tmp_path / "atomic.wtbackup"

    secure_backup_service.export_encrypted_backup(out, "passphrase")

    # The temp file should not linger after a successful write.
    tmp = out.with_suffix(out.suffix + ".tmp")
    assert not tmp.exists()
    assert out.exists()
