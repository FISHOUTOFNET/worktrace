"""Tests for the encrypted local backup export/import service.

Includes import guard, DB safety, and logging hygiene tests.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

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


# =========================================================================
# Encrypted Import Safety Hardening tests
# =========================================================================
#
# These tests verify the secure import guard, DB safety on failure,
# collector write-path protection, and logging hygiene introduced in
# See docs/v0.2-local-security-design.md.


# --- helpers -------------------------------------------------------------


def _reset_guard_and_pause_state() -> None:
    """Clear the import guard and pause/status settings to a clean baseline."""
    set_setting("secure_import_in_progress", "false")
    set_setting("user_paused", "false")
    set_setting("collector_status", "stopped")
    set_setting("current_activity_snapshot", "")


def _make_backup(tmp_path: Path, passphrase: str = "correct-passphrase") -> Path:
    """Create a valid encrypted backup from the current DB."""
    _seed_test_data()
    out = tmp_path / "guard-test.wtbackup"
    secure_backup_service.export_encrypted_backup(out, passphrase)
    return out


def _corrupt_backup(out: Path) -> None:
    """Flip a byte in the ciphertext region of a backup file."""
    blob = bytearray(out.read_bytes())
    blob[-5] = blob[-5] ^ 0xFF
    out.write_bytes(bytes(blob))


# --- import guard service tests ------------------------------------------


def test_import_sets_secure_import_in_progress_during_replacement(temp_db, tmp_path, monkeypatch):
    """While the DB replacement is running, the guard flag must be true."""
    out = _make_backup(tmp_path)
    _reset_guard_and_pause_state()

    captured = {}

    original_replace = secure_backup_service._replace_import

    def spy_replace(data):
        captured["guard_during_replace"] = get_bool_setting("secure_import_in_progress", False)
        captured["user_paused_during_replace"] = get_bool_setting("user_paused", False)
        captured["collector_status_during_replace"] = get_setting("collector_status", "")
        captured["snapshot_during_replace"] = get_setting("current_activity_snapshot", "")
        return original_replace(data)

    monkeypatch.setattr(secure_backup_service, "_replace_import", spy_replace)

    secure_backup_service.import_encrypted_backup(out, "correct-passphrase", mode="replace")

    assert captured["guard_during_replace"] is True
    assert captured["user_paused_during_replace"] is True
    assert captured["collector_status_during_replace"] == "paused"
    assert captured["snapshot_during_replace"] == ""


def test_import_clears_secure_import_in_progress_after_success(temp_db, tmp_path):
    out = _make_backup(tmp_path)
    _reset_guard_and_pause_state()

    secure_backup_service.import_encrypted_backup(out, "correct-passphrase", mode="replace")

    assert get_bool_setting("secure_import_in_progress", False) is False


def test_import_clears_secure_import_in_progress_after_failure(temp_db, tmp_path):
    out = _make_backup(tmp_path)
    _reset_guard_and_pause_state()

    with pytest.raises(BackupDecryptionError):
        secure_backup_service.import_encrypted_backup(out, "wrong-passphrase")

    assert get_bool_setting("secure_import_in_progress", False) is False


def test_import_success_leaves_user_paused_and_collector_status_paused(temp_db, tmp_path):
    out = _make_backup(tmp_path)
    _reset_guard_and_pause_state()

    secure_backup_service.import_encrypted_backup(out, "correct-passphrase", mode="replace")

    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status", "") == "paused"


def test_wrong_passphrase_restores_prior_pause_status(temp_db, tmp_path):
    out = _make_backup(tmp_path)
    # Set a distinctive prior state.
    set_setting("secure_import_in_progress", "false")
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    set_setting("current_activity_snapshot", '{"app":"prior-snapshot-marker"}')

    with pytest.raises(BackupDecryptionError):
        secure_backup_service.import_encrypted_backup(out, "wrong-passphrase")

    assert get_bool_setting("secure_import_in_progress", False) is False
    assert get_bool_setting("user_paused", False) is False
    assert get_setting("collector_status", "") == "running"
    assert get_setting("current_activity_snapshot", "") == '{"app":"prior-snapshot-marker"}'


def test_corrupted_backup_restores_prior_pause_status(temp_db, tmp_path):
    out = _make_backup(tmp_path)
    _corrupt_backup(out)
    set_setting("secure_import_in_progress", "false")
    set_setting("user_paused", "true")
    set_setting("collector_status", "stopped")
    set_setting("current_activity_snapshot", '{"app":"corrupt-prior-marker"}')

    with pytest.raises((BackupCorruptedError, BackupDecryptionError)):
        secure_backup_service.import_encrypted_backup(out, "correct-passphrase")

    assert get_bool_setting("secure_import_in_progress", False) is False
    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status", "") == "stopped"
    assert get_setting("current_activity_snapshot", "") == '{"app":"corrupt-prior-marker"}'


def test_existing_secure_import_in_progress_rejects_new_import(temp_db, tmp_path):
    out = _make_backup(tmp_path)
    set_setting("secure_import_in_progress", "true")

    with pytest.raises(BackupImportInProgressError):
        secure_backup_service.import_encrypted_backup(out, "correct-passphrase")

    # The guard should still be true (the rejected call did not clear it).
    assert get_bool_setting("secure_import_in_progress", False) is True


def test_current_activity_snapshot_cleared_during_import(temp_db, tmp_path, monkeypatch):
    out = _make_backup(tmp_path)
    _reset_guard_and_pause_state()
    set_setting("current_activity_snapshot", '{"app":"snapshot-before-import"}')

    captured = {}
    original_replace = secure_backup_service._replace_import

    def spy_replace(data):
        captured["snapshot_during"] = get_setting("current_activity_snapshot", "")
        return original_replace(data)

    monkeypatch.setattr(secure_backup_service, "_replace_import", spy_replace)

    secure_backup_service.import_encrypted_backup(out, "correct-passphrase", mode="replace")

    assert captured["snapshot_during"] == ""


# --- DB safety tests -----------------------------------------------------


def test_wrong_passphrase_does_not_alter_row_counts(temp_db, tmp_path):
    out = _make_backup(tmp_path)
    counts_before = _row_counts()

    with pytest.raises(BackupDecryptionError):
        secure_backup_service.import_encrypted_backup(out, "wrong-passphrase")

    assert _row_counts() == counts_before


def test_corrupted_backup_does_not_alter_row_counts(temp_db, tmp_path):
    out = _make_backup(tmp_path)
    _corrupt_backup(out)
    counts_before = _row_counts()

    with pytest.raises((BackupCorruptedError, BackupDecryptionError)):
        secure_backup_service.import_encrypted_backup(out, "correct-passphrase")

    assert _row_counts() == counts_before


def test_simulated_db_failure_during_replace_rolls_back(temp_db, tmp_path, monkeypatch):
    out = _make_backup(tmp_path)
    counts_before = _row_counts()

    def failing_replace(data):
        raise sqlite3.OperationalError("simulated DB failure during replace")

    monkeypatch.setattr(secure_backup_service, "_replace_import", failing_replace)

    with pytest.raises(sqlite3.OperationalError):
        secure_backup_service.import_encrypted_backup(out, "correct-passphrase")

    assert _row_counts() == counts_before


def test_after_rollback_import_guard_cleared(temp_db, tmp_path, monkeypatch):
    out = _make_backup(tmp_path)

    def failing_replace(data):
        raise sqlite3.OperationalError("simulated DB failure during replace")

    monkeypatch.setattr(secure_backup_service, "_replace_import", failing_replace)

    with pytest.raises(sqlite3.OperationalError):
        secure_backup_service.import_encrypted_backup(out, "correct-passphrase")

    assert get_bool_setting("secure_import_in_progress", False) is False


def test_after_rollback_previous_pause_status_restored(temp_db, tmp_path, monkeypatch):
    out = _make_backup(tmp_path)
    set_setting("secure_import_in_progress", "false")
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    set_setting("current_activity_snapshot", '{"app":"rollback-prior-marker"}')

    def failing_replace(data):
        raise sqlite3.OperationalError("simulated DB failure during replace")

    monkeypatch.setattr(secure_backup_service, "_replace_import", failing_replace)

    with pytest.raises(sqlite3.OperationalError):
        secure_backup_service.import_encrypted_backup(out, "correct-passphrase")

    assert get_bool_setting("user_paused", False) is False
    assert get_setting("collector_status", "") == "running"
    assert get_setting("current_activity_snapshot", "") == '{"app":"rollback-prior-marker"}'


# --- logging hygiene tests ------------------------------------------------


def test_export_success_log_does_not_contain_output_path(temp_db, tmp_path, caplog):
    _seed_test_data()
    out = tmp_path / "log-export-path.wtbackup"

    with caplog.at_level(logging.INFO):
        secure_backup_service.export_encrypted_backup(out, "passphrase")

    full_log = "\n".join(record.getMessage() for record in caplog.records)
    assert str(out) not in full_log
    assert out.name not in full_log


def test_import_success_log_does_not_contain_input_path(temp_db, tmp_path, caplog):
    out = _make_backup(tmp_path)
    _reset_guard_and_pause_state()

    with caplog.at_level(logging.INFO):
        secure_backup_service.import_encrypted_backup(out, "correct-passphrase", mode="replace")

    full_log = "\n".join(record.getMessage() for record in caplog.records)
    assert str(out) not in full_log
    assert out.name not in full_log


def test_failure_log_does_not_contain_passphrase(temp_db, tmp_path, caplog):
    out = _make_backup(tmp_path)
    secret_passphrase = "SecretPassphrase-Log-Leak-Test-9Z"

    with caplog.at_level(logging.WARNING):
        with pytest.raises(BackupDecryptionError):
            secure_backup_service.import_encrypted_backup(out, secret_passphrase)

    full_log = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_passphrase not in full_log


def test_failure_log_does_not_contain_sensitive_markers(temp_db, tmp_path, caplog):
    _seed_test_data()
    out = tmp_path / "log-markers.wtbackup"
    secure_backup_service.export_encrypted_backup(out, "passphrase")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(BackupDecryptionError):
            secure_backup_service.import_encrypted_backup(out, "wrong")

    full_log = "\n".join(record.getMessage() for record in caplog.records)
    for marker in [TEST_PROJECT_NAME, TEST_WINDOW_TITLE, TEST_FILE_PATH, TEST_NOTE, TEST_COPIED_TEXT]:
        assert marker not in full_log, f"sensitive marker {marker!r} leaked into log"


def test_logs_contain_only_safe_counts(temp_db, tmp_path, caplog):
    out = _make_backup(tmp_path)
    _reset_guard_and_pause_state()

    with caplog.at_level(logging.INFO):
        secure_backup_service.import_encrypted_backup(out, "correct-passphrase", mode="replace")

    # The success log should mention operation name, mode, and table count.
    import_logs = [
        record.getMessage()
        for record in caplog.records
        if "encrypted backup import" in record.getMessage()
    ]
    assert any("success" in msg for msg in import_logs), "expected a success log entry"
    assert any("mode=replace" in msg for msg in import_logs), "expected mode in log"
    assert any("tables=" in msg for msg in import_logs), "expected table count in log"
