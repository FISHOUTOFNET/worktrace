from __future__ import annotations

import sqlite3

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
from worktrace.services.secure_backup_service import BackupCorruptedError
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


def test_import_staging_validation_failure_does_not_fail_closed(
    temp_db,
    tmp_path,
    monkeypatch,
):
    """Staging validation failure raises BackupCorruptedError without fail-closing.

    Staging is built and validated BEFORE entering the maintenance scope. A
    staging failure must never trigger durable fail-closed because the live
    database has not been touched and no maintenance hold was acquired.
    """

    output = _make_backup(tmp_path)
    _insert_sentinel("Import Failure Sentinel")

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

    _assert_sentinel_exists("Import Failure Sentinel")
    _assert_process_and_durable_generations_match()
    status = database_maintenance_service.maintenance_status()
    assert status.recovery_blocked is False
    assert status.maintenance_in_progress is False


def test_import_live_generation_failure_preserves_live_database_and_clock(
    temp_db,
    tmp_path,
    monkeypatch,
):
    """Live replacement failure during generation bump preserves the live DB.

    The staging succeeds before the maintenance scope; the failure is injected
    into the live replacement step via bump_replacement. The live transaction
    is rolled back by DatabaseReplacementUnitOfWork. Because the runtime
    control is operational and restoration succeeds, the coordinator does NOT
    durably fail-close. The process and durable generations remain aligned.
    """

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

    with pytest.raises(RuntimeError, match="failed"):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    _assert_sentinel_exists("Import Failure Sentinel")
    _assert_process_and_durable_generations_match()
    status = database_maintenance_service.maintenance_status()
    assert status.recovery_blocked is False
    assert status.maintenance_in_progress is False


def test_import_commit_failure_rolls_back_replacement(temp_db, tmp_path, monkeypatch):
    output = _make_backup(tmp_path)
    _insert_sentinel("Commit Failure Sentinel")
    from worktrace import database_replacement_unit_of_work
    from worktrace.services.secure_backup_service import BackupReplacementError

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
