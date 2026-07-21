from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection, now_str
from worktrace.services import (
    database_maintenance_service,
    history_mutation_job_service,
    privacy_gate_service,
    project_service,
    rule_catalog_command_service,
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
    rule_id = rule_catalog_command_service.create_keyword_rule(
        "worker-progress",
        project_id,
    )
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "worker-progress document",
        start_time="2026-07-18 13:00:00",
    )
    activity_service.close_activity_row(activity_id, "2026-07-18 13:05:00")
    history_mutation_job_service.submit_rule_job(
        "keyword",
        rule_id,
        kind="rule_backfill",
        synchronous_scan_limit=0,
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


def test_clear_all_advances_replacement_and_restored_settings_once(temp_db):
    privacy_gate_service.accept_privacy_notice()
    project_service.create_project("Replacement Source")
    before = _generations()

    database_maintenance_service.clear_all_live_data()

    after = _generations()
    assert after[DataGenerationNamespace.DATABASE_REPLACEMENT] == (
        before[DataGenerationNamespace.DATABASE_REPLACEMENT] + 1
    )
    assert after[DataGenerationNamespace.SETTINGS] == (
        before[DataGenerationNamespace.SETTINGS] + 1
    )
    for namespace in DataGenerationNamespace:
        if namespace in {
            DataGenerationNamespace.DATABASE_REPLACEMENT,
            DataGenerationNamespace.SETTINGS,
        }:
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
    rule_catalog_command_service.create_or_update_excluded_folder_rule(
        "D:\\ReplacementPrivacy",
        recursive=True,
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


def test_replacement_generation_failure_rolls_back_data_and_replacement_epoch(
    temp_db,
    monkeypatch,
):
    """Replacement generation failure rolls back data without fail-closing.

    Per the architecture contract (Problem 1): when ``bump_replacement``
    raises after the generation write but before commit, the
    ``DatabaseReplacementUnitOfWork`` rolls back the live transaction. The
    operation did not complete. Because the runtime restoration can be
    verified (operational control, durable settings restored), the coordinator
    MUST NOT enter durable fail-closed. Only when restoration cannot be
    verified does fail-closed become mandatory.
    """
    privacy_gate_service.accept_privacy_notice()
    project_id = project_service.create_project("Must Survive")
    before = _generations()
    original_bump_replacement = DataGenerationRepository.bump_replacement

    def fail_after_generation_write(conn, *, minimum_value=None):
        original_bump_replacement(conn, minimum_value=minimum_value)
        raise RuntimeError("generation_publish_failed")

    monkeypatch.setattr(
        DataGenerationRepository,
        "bump_replacement",
        staticmethod(fail_after_generation_write),
    )

    with pytest.raises(RuntimeError, match="generation_publish_failed"):
        database_maintenance_service.clear_all_live_data()

    after = _generations()
    for namespace in DataGenerationNamespace:
        if namespace is DataGenerationNamespace.SETTINGS:
            assert after[namespace] == before[namespace] + 1
        else:
            assert after[namespace] == before[namespace]
    assert (
        database_maintenance_service.MAINTENANCE_COORDINATOR.recovery_blocked()
        is False
    )
    assert (
        database_maintenance_service.MAINTENANCE_COORDINATOR.phase
        is database_maintenance_service.MaintenancePhase.IDLE
    )
    assert project_service.get_project(project_id) is not None
    assert privacy_gate_service.is_privacy_notice_accepted() is True


def test_replacement_generation_failure_when_restoration_fails_must_fail_closed(
    temp_db,
    monkeypatch,
):
    """Replacement generation failure with unverifiable restoration MUST fail-close.

    Per the architecture contract (Problem 1): if ``bump_replacement`` raises
    AND the collector restoration cannot be verified
    (``restore_after_maintenance`` raises), the coordinator MUST enter durable
    fail-closed because the runtime state is unverifiable.
    """
    privacy_gate_service.accept_privacy_notice()
    project_service.create_project("Must Survive")

    from tests.support.application import TestRuntimeMaintenanceControl

    class _OperationalHoldState:
        value = "operational"

    class _OperationalCollectorControl:
        hold_state = _OperationalHoldState()

        def query_command(self, command_id: str):
            return None

    class _RestorationFailingControl(TestRuntimeMaintenanceControl):
        def __init__(self) -> None:
            super().__init__()
            self.collector_control = _OperationalCollectorControl()

        @staticmethod
        def _ack(command_kind: str, terminal_state: str) -> dict[str, object]:
            return {
                "ok": True,
                "command_id": f"test-{command_kind}",
                "command_kind": command_kind,
                "command_state": "completed",
                "command_state_unknown": False,
                "terminal_state": terminal_state,
            }

        def is_collection_running_for_maintenance(self) -> bool:
            return True

        def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
            return self._ack("maintenance_hold", "held")

        def restore_after_maintenance(self, state, timeout_seconds=5.0):
            raise RuntimeError("restoration failed")

    failing_control = _RestorationFailingControl()
    database_maintenance_service.MAINTENANCE_COORDINATOR.register_runtime_control(
        failing_control
    )

    original_bump_replacement = DataGenerationRepository.bump_replacement

    def fail_after_generation_write(conn, *, minimum_value=None):
        original_bump_replacement(conn, minimum_value=minimum_value)
        raise RuntimeError("generation_publish_failed")

    monkeypatch.setattr(
        DataGenerationRepository,
        "bump_replacement",
        staticmethod(fail_after_generation_write),
    )

    try:
        with pytest.raises(RuntimeError, match="generation_publish_failed"):
            database_maintenance_service.clear_all_live_data()

        assert (
            database_maintenance_service.MAINTENANCE_COORDINATOR.recovery_blocked()
            is True
        )
        assert (
            database_maintenance_service.MAINTENANCE_COORDINATOR.phase
            is database_maintenance_service.MaintenancePhase.FAILED_CLOSED
        )
    finally:
        database_maintenance_service.MAINTENANCE_COORDINATOR.clear_runtime_control(
            failing_control
        )
        database_maintenance_service.MAINTENANCE_COORDINATOR._set_phase(
            database_maintenance_service.MaintenancePhase.IDLE
        )
