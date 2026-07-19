from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.constants import EXCLUDED_PROJECT
from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection, now_str
from worktrace.services import (
    database_maintenance_service,
    folder_rule_service,
    history_mutation_job_service,
    privacy_gate_service,
    project_service,
    rule_service,
    settings_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]

_WORKER_PROGRESS_TABLES = (
    "history_mutation_job_rule",
    "history_mutation_job",
    "activity_inference_job",
    "activity_resource_repair_job",
    "startup_recovery_job",
)


def _generations() -> dict[DataGenerationNamespace, int]:
    with get_connection() as conn:
        return {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in DataGenerationNamespace
        }


def _worker_progress_counts() -> dict[str, int]:
    with get_connection() as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in _WORKER_PROGRESS_TABLES
        }


def _seed_all_worker_progress() -> None:
    project_id = project_service.create_project("Worker Progress Source")
    rule_id = rule_service.create_rule("worker-progress", project_id)
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "worker-progress document",
        start_time="2026-07-18 13:00:00",
    )
    activity_service.close_activity_row(activity_id, "2026-07-18 13:05:00")
    history_mutation_job_service.submit_rule_job(
        "rule_backfill",
        "keyword",
        rule_id,
        synchronous_limit=0,
    )
    timestamp = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO activity_inference_job(
                activity_id, reason, status, attempt_count, next_attempt_at,
                last_error_code, created_at, updated_at
            ) VALUES (?, 'closed_activity', 'pending', 0, NULL, NULL, ?, ?)
            """,
            (activity_id, timestamp, timestamp),
        )
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
            ) VALUES (?, '2026-07-18 13:05:00', '2026-07-20 13:05:00',
                      'auto', 'normal', 'Word', 'winword.exe',
                      'worker-progress document', NULL, ?, 'pending', 0,
                      NULL, NULL, ?, ?)
            """,
            (activity_id, project_id, timestamp, timestamp),
        )


def test_clear_all_advances_only_replacement_epoch_once(temp_db):
    privacy_gate_service.accept_privacy_notice()
    project_service.create_project("Replacement Source")
    before = _generations()

    database_maintenance_service.clear_all_live_data()

    after = _generations()
    assert after[DataGenerationNamespace.DATABASE_REPLACEMENT] == (
        before[DataGenerationNamespace.DATABASE_REPLACEMENT] + 1
    )
    for namespace in DataGenerationNamespace:
        if namespace is DataGenerationNamespace.DATABASE_REPLACEMENT:
            continue
        assert after[namespace] == before[namespace]
    assert privacy_gate_service.is_privacy_notice_accepted() is True


def test_clear_all_removes_every_durable_worker_progress(temp_db):
    _seed_all_worker_progress()
    assert all(count > 0 for count in _worker_progress_counts().values())

    database_maintenance_service.clear_all_live_data()

    assert _worker_progress_counts() == {
        table: 0 for table in _WORKER_PROGRESS_TABLES
    }


def test_ordinary_domain_writes_do_not_advance_replacement(temp_db):
    before = _generations()

    settings_service.set_setting("ui_refresh_seconds", "77")
    project_service.create_project("Ordinary Domain Write")
    excluded = project_service.get_project_by_name(EXCLUDED_PROJECT)
    assert excluded is not None
    project_service.set_project_enabled(int(excluded["id"]), True)
    folder_rule_service.create_or_update_folder_rule(
        "D:\\ReplacementPrivacy",
        int(excluded["id"]),
        True,
    )

    after = _generations()
    assert after[DataGenerationNamespace.DATABASE_REPLACEMENT] == before[
        DataGenerationNamespace.DATABASE_REPLACEMENT
    ]
    assert after[DataGenerationNamespace.SETTINGS] > before[
        DataGenerationNamespace.SETTINGS
    ]
    assert after[DataGenerationNamespace.CLASSIFICATION_CATALOG] > before[
        DataGenerationNamespace.CLASSIFICATION_CATALOG
    ]
    assert after[DataGenerationNamespace.PRIVACY_CATALOG] > before[
        DataGenerationNamespace.PRIVACY_CATALOG
    ]


def test_replacement_repository_advances_above_live_floor_and_rolls_back(temp_db):
    before = _generations()[DataGenerationNamespace.DATABASE_REPLACEMENT]
    with get_connection() as conn:
        conn.execute("BEGIN")
        values = DataGenerationRepository.bump_replacement(
            conn,
            minimum_value=before + 20,
        )
        assert values == {
            DataGenerationNamespace.DATABASE_REPLACEMENT: before + 21
        }
        conn.rollback()

    assert _generations()[DataGenerationNamespace.DATABASE_REPLACEMENT] == before


def test_clear_all_refreshes_generation_backed_settings_cache(temp_db):
    settings_service.set_setting("ui_refresh_seconds", "77")
    assert settings_service.get_setting("ui_refresh_seconds") == "77"

    database_maintenance_service.clear_all_live_data()

    assert settings_service.get_setting("ui_refresh_seconds") == "10"


def test_replacement_generation_failure_rolls_back_data_and_generations(
    temp_db,
    monkeypatch,
):
    privacy_gate_service.accept_privacy_notice()
    project_id = project_service.create_project("Must Survive")
    before = _generations()
    original = database_maintenance_service.publish_database_replacement

    def fail_after_generation_write(conn):
        original(conn)
        raise RuntimeError("generation_publish_failed")

    monkeypatch.setattr(
        database_maintenance_service,
        "publish_database_replacement",
        fail_after_generation_write,
    )

    with pytest.raises(RuntimeError, match="generation_publish_failed"):
        database_maintenance_service.clear_all_live_data()

    assert _generations() == before
    assert project_service.get_project(project_id) is not None
    assert privacy_gate_service.is_privacy_notice_accepted() is True
