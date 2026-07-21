from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection, now_str
from worktrace.generation_clock import generation
from worktrace.platforms.base import ActiveWindow
from worktrace.services import (
    activity_lifecycle_service,
    folder_rule_service,
    privacy_service,
    project_inference_service,
    project_service,
    rule_catalog_command_service,
    rule_service,
    secure_backup_service,
)
from worktrace.services import database_maintenance_service
from worktrace.services.secure_backup_service import (
    BackupCorruptedError,
    BackupImportInProgressError,
    BackupReplacementError,
)
from worktrace.services.secure_backup_validation import BackupValidationError
from worktrace.services.settings_service import get_setting, set_setting

pytestmark = [pytest.mark.security_privacy, pytest.mark.integration, pytest.mark.db]


def _make_backup(tmp_path):
    output = tmp_path / "generation-protocol.wtbackup"
    secure_backup_service.export_encrypted_backup(output, "correct-passphrase")
    return output


def _assert_process_and_durable_generations_match() -> None:
    with get_connection() as conn:
        durable = {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in DataGenerationNamespace
        }
    assert {
        namespace: generation(namespace)
        for namespace in DataGenerationNamespace
    } == durable


def _insert_sentinel(name: str) -> None:
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO project(
                name, description, is_archived, enabled, created_by,
                created_at, updated_at
            ) VALUES (?, '', 0, 1, 'user', ?, ?)
            """,
            (name, timestamp, timestamp),
        )


def _assert_sentinel_exists(name: str) -> None:
    with get_connection() as conn:
        assert conn.execute(
            "SELECT id FROM project WHERE name = ?",
            (name,),
        ).fetchone() is not None


def _is_excluded(window: ActiveWindow) -> bool:
    return privacy_service.evaluate_exclusion(window).excluded


def _record_staging_paths(monkeypatch) -> list[str]:
    paths: list[str] = []
    original = secure_backup_service._build_and_validate_staging

    def recording_build(staging_path: str, data: dict):
        paths.append(staging_path)
        return original(staging_path, data)

    monkeypatch.setattr(
        secure_backup_service,
        "_build_and_validate_staging",
        recording_build,
    )
    return paths


def _assert_paths_removed(paths: list[str]) -> None:
    assert paths
    assert all(not os.path.exists(path) for path in paths)


def _assert_maintenance_unblocked() -> None:
    status = database_maintenance_service.maintenance_status()
    assert status.recovery_blocked is False
    assert status.maintenance_in_progress is False


def test_import_publishes_exact_committed_replacement_generations(temp_db, tmp_path):
    output = _make_backup(tmp_path)
    for namespace in DataGenerationNamespace:
        generation(namespace)

    secure_backup_service.import_encrypted_backup(
        output,
        "correct-passphrase",
        mode="replace",
    )

    _assert_process_and_durable_generations_match()


def test_successful_import_removes_decrypted_staging_file(
    temp_db,
    tmp_path,
    monkeypatch,
):
    output = _make_backup(tmp_path)
    paths = _record_staging_paths(monkeypatch)

    secure_backup_service.import_encrypted_backup(
        output,
        "correct-passphrase",
        mode="replace",
    )

    _assert_paths_removed(paths)
    _assert_process_and_durable_generations_match()
    _assert_maintenance_unblocked()


def test_import_staging_validation_failure_does_not_fail_closed(
    temp_db,
    tmp_path,
    monkeypatch,
):
    """Staging corruption is cleaned before maintenance and never fail-closes."""

    output = _make_backup(tmp_path)
    _insert_sentinel("Import Failure Sentinel")
    paths = _record_staging_paths(monkeypatch)

    def fail_validation(_conn):
        raise BackupValidationError("staging validation failed")

    monkeypatch.setattr(
        secure_backup_service,
        "validate_staging_database",
        fail_validation,
    )

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    _assert_paths_removed(paths)
    _assert_sentinel_exists("Import Failure Sentinel")
    _assert_process_and_durable_generations_match()
    _assert_maintenance_unblocked()


def test_import_staging_insert_failure_removes_staging_and_preserves_live_db(
    temp_db,
    tmp_path,
    monkeypatch,
):
    output = _make_backup(tmp_path)
    _insert_sentinel("Staging Insert Failure Sentinel")
    paths = _record_staging_paths(monkeypatch)

    def fail_insert(_conn, _tables):
        raise sqlite3.OperationalError("staging insert failed")

    monkeypatch.setattr(secure_backup_service, "_load_import_tables", fail_insert)

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    _assert_paths_removed(paths)
    _assert_sentinel_exists("Staging Insert Failure Sentinel")
    _assert_process_and_durable_generations_match()
    _assert_maintenance_unblocked()


def test_import_staging_commit_failure_removes_staging_and_preserves_live_db(
    temp_db,
    tmp_path,
    monkeypatch,
):
    output = _make_backup(tmp_path)
    _insert_sentinel("Staging Commit Failure Sentinel")
    paths = _record_staging_paths(monkeypatch)
    original_connect = secure_backup_service.sqlite3.connect

    class CommitFailingConnection:
        def __init__(self, connection):
            object.__setattr__(self, "_connection", connection)

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def __setattr__(self, name, value):
            if name == "_connection":
                object.__setattr__(self, name, value)
            else:
                setattr(self._connection, name, value)

        def commit(self):
            raise sqlite3.OperationalError("staging commit failed")

    def connect_with_staging_commit_failure(path, *args, **kwargs):
        connection = original_connect(path, *args, **kwargs)
        if "worktrace-import-" in str(path):
            return CommitFailingConnection(connection)
        return connection

    monkeypatch.setattr(
        secure_backup_service.sqlite3,
        "connect",
        connect_with_staging_commit_failure,
    )

    with pytest.raises(BackupCorruptedError):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    _assert_paths_removed(paths)
    _assert_sentinel_exists("Staging Commit Failure Sentinel")
    _assert_process_and_durable_generations_match()
    _assert_maintenance_unblocked()


def test_import_maintenance_busy_removes_validated_staging(
    temp_db,
    tmp_path,
    monkeypatch,
):
    output = _make_backup(tmp_path)
    paths = _record_staging_paths(monkeypatch)

    @contextmanager
    def busy_replacement(*_args, **_kwargs):
        raise database_maintenance_service.MaintenanceInProgressError(
            "database_maintenance_in_progress"
        )
        yield

    monkeypatch.setattr(
        database_maintenance_service,
        "database_replacement",
        busy_replacement,
    )

    with pytest.raises(BackupImportInProgressError):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    _assert_paths_removed(paths)
    _assert_process_and_durable_generations_match()
    _assert_maintenance_unblocked()


def test_import_live_apply_failure_removes_staging_and_uses_replacement_error(
    temp_db,
    tmp_path,
    monkeypatch,
):
    output = _make_backup(tmp_path)
    _insert_sentinel("Live Apply Failure Sentinel")
    paths = _record_staging_paths(monkeypatch)

    def fail_live_delete(_conn):
        raise sqlite3.OperationalError("live delete failed")

    monkeypatch.setattr(secure_backup_service, "_delete_all_rows", fail_live_delete)

    with pytest.raises(BackupReplacementError):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    _assert_paths_removed(paths)
    _assert_sentinel_exists("Live Apply Failure Sentinel")
    _assert_process_and_durable_generations_match()
    _assert_maintenance_unblocked()


def test_staging_cleanup_failure_does_not_replace_original_error(
    temp_db,
    tmp_path,
    monkeypatch,
):
    output = _make_backup(tmp_path)
    paths: list[str] = []
    real_unlink = os.unlink

    def fail_build(staging_path: str, _data: dict):
        paths.append(staging_path)
        raise BackupCorruptedError("original_staging_error")

    def fail_cleanup(_path: str):
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(
        secure_backup_service,
        "_build_and_validate_staging",
        fail_build,
    )
    monkeypatch.setattr(secure_backup_service.os, "unlink", fail_cleanup)

    with pytest.raises(BackupCorruptedError, match="original_staging_error"):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    assert paths
    for path in paths:
        if Path(path).exists():
            real_unlink(path)
    _assert_maintenance_unblocked()


def test_import_live_generation_failure_preserves_live_database_and_clock(
    temp_db,
    tmp_path,
    monkeypatch,
):
    """A live generation failure is a replacement failure, never corruption."""

    output = _make_backup(tmp_path)
    _insert_sentinel("Import Failure Sentinel")

    original_bump_replacement = DataGenerationRepository.bump_replacement

    def fail_generation(conn, *, minimum_value=None):
        original_bump_replacement(conn, minimum_value=minimum_value)
        raise RuntimeError("generation write failed")

    monkeypatch.setattr(
        DataGenerationRepository,
        "bump_replacement",
        staticmethod(fail_generation),
    )

    with pytest.raises(BackupReplacementError):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    _assert_sentinel_exists("Import Failure Sentinel")
    _assert_process_and_durable_generations_match()
    _assert_maintenance_unblocked()


def test_import_commit_failure_rolls_back_replacement(temp_db, tmp_path, monkeypatch):
    output = _make_backup(tmp_path)
    _insert_sentinel("Commit Failure Sentinel")
    from worktrace import database_replacement_unit_of_work

    original_get_connection = database_replacement_unit_of_work.get_connection

    class CommitFailingConnection:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def commit(self):
            raise sqlite3.OperationalError("commit failed")

    def failing_get_connection():
        return CommitFailingConnection(original_get_connection())

    monkeypatch.setattr(
        database_replacement_unit_of_work,
        "get_connection",
        failing_get_connection,
    )
    with pytest.raises(BackupReplacementError):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    _assert_sentinel_exists("Commit Failure Sentinel")
    _assert_process_and_durable_generations_match()


def test_import_process_publish_failure_recovers_by_durable_reload(
    temp_db,
    tmp_path,
    monkeypatch,
):
    output = _make_backup(tmp_path)
    from worktrace import database_replacement_unit_of_work

    def fail_publish(_database_key, _values):
        raise RuntimeError("process publish failed")

    monkeypatch.setattr(
        database_replacement_unit_of_work,
        "publish_replacement_committed",
        fail_publish,
    )

    result = secure_backup_service.import_encrypted_backup(
        output,
        "correct-passphrase",
        mode="replace",
    )

    assert result.mode == "replace"
    _assert_process_and_durable_generations_match()


def test_first_domain_mutations_after_import_invalidate_hot_caches(
    temp_db,
    tmp_path,
):
    output = _make_backup(tmp_path)
    get_setting("ui_refresh_seconds")
    folder_rule_service._enabled_folder_rules()
    project_inference_service._enabled_keyword_rules()
    _is_excluded(ActiveWindow("App", "app.exe", "Public"))

    secure_backup_service.import_encrypted_backup(
        output,
        "correct-passphrase",
        mode="replace",
    )

    settings_before = generation(DataGenerationNamespace.SETTINGS)
    set_setting("ui_refresh_seconds", "19")
    assert get_setting("ui_refresh_seconds") == "19"
    assert generation(DataGenerationNamespace.SETTINGS) == settings_before + 1

    project_id = project_service.create_project("Post Import Rules")
    keyword_before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    keyword_id = rule_service.create_rule("post-import-keyword", project_id)
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == keyword_before + 1
    assert any(
        int(row["id"]) == keyword_id
        for row in project_inference_service._enabled_keyword_rules()
    )

    folder_before = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    folder_id = folder_rule_service.create_or_update_folder_rule(
        "D:\\PostImportFolder",
        project_id,
        True,
    )
    assert generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) == folder_before + 1
    assert folder_rule_service.find_matching_folder_rule(
        "D:\\PostImportFolder\\brief.docx"
    )["id"] == folder_id

    project_service.set_excluded_project_enabled(True)
    _is_excluded(ActiveWindow("App", "app.exe", "Public"))
    privacy_before = generation(DataGenerationNamespace.PRIVACY_CATALOG)
    rule_catalog_command_service.create_or_update_excluded_folder_rule(
        "D:\\PostImportPrivate",
        recursive=True,
    )
    assert generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before + 1
    assert _is_excluded(
        ActiveWindow(
            "App",
            "app.exe",
            "Private",
            file_path_hint="D:\\PostImportPrivate\\secret.docx",
        )
    ) is True

    report_before = generation(DataGenerationNamespace.REPORT_STRUCTURE)
    activity_lifecycle_service.persist_open_activity(
        start_time="2026-06-25 11:00:00",
        source="auto",
        payload={
            "app_name": "App",
            "process_name": "app.exe",
            "window_title": "Post import report",
            "status": "normal",
        },
    )
    assert generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before + 1
