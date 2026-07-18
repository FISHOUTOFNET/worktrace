from __future__ import annotations

import sqlite3
from contextlib import contextmanager

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
    rule_service,
    secure_backup_service,
)
from worktrace.services.secure_backup_service import BackupCorruptedError
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


@pytest.mark.parametrize("failure_point", ["validation", "generation"])
def test_import_precommit_failure_preserves_live_database_and_clock_alignment(
    temp_db,
    tmp_path,
    monkeypatch,
    failure_point,
):
    output = _make_backup(tmp_path)
    _insert_sentinel("Import Failure Sentinel")

    if failure_point == "validation":
        def fail_validation(_conn):
            raise RuntimeError("validation failed")

        monkeypatch.setattr(
            secure_backup_service,
            "_validate_staging_database",
            fail_validation,
        )
    else:
        original = secure_backup_service.publish_database_replacement

        def fail_generation(conn, **kwargs):
            original(conn, **kwargs)
            raise RuntimeError("generation write failed")

        monkeypatch.setattr(
            secure_backup_service,
            "publish_database_replacement",
            fail_generation,
        )

    with pytest.raises(RuntimeError, match="failed"):
        secure_backup_service.import_encrypted_backup(
            output,
            "correct-passphrase",
            mode="replace",
        )

    _assert_sentinel_exists("Import Failure Sentinel")
    _assert_process_and_durable_generations_match()


def test_import_commit_failure_rolls_back_replacement(temp_db, tmp_path, monkeypatch):
    output = _make_backup(tmp_path)
    _insert_sentinel("Commit Failure Sentinel")
    original_get_connection = secure_backup_service.get_connection

    class CommitFailingConnection:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def commit(self):
            raise sqlite3.OperationalError("commit failed")

    @contextmanager
    def failing_connection():
        conn = original_get_connection()
        try:
            yield CommitFailingConnection(conn)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(
        secure_backup_service,
        "get_connection",
        failing_connection,
    )
    with pytest.raises(BackupCorruptedError):
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

    def fail_publish(_database_key, _values):
        raise RuntimeError("process publish failed")

    monkeypatch.setattr(
        secure_backup_service,
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
    privacy_service.is_excluded(ActiveWindow("App", "app.exe", "Public"))

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

    excluded = project_service.get_project_by_name("排除规则")
    project_service.set_project_enabled(int(excluded["id"]), True)
    privacy_service.is_excluded(ActiveWindow("App", "app.exe", "Public"))
    privacy_before = generation(DataGenerationNamespace.PRIVACY_CATALOG)
    folder_rule_service.create_or_update_folder_rule(
        "D:\\PostImportPrivate",
        int(excluded["id"]),
        True,
    )
    assert generation(DataGenerationNamespace.PRIVACY_CATALOG) == privacy_before + 1
    assert privacy_service.is_excluded(
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
