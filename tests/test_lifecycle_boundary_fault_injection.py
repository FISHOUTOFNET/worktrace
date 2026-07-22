from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from worktrace import atomic_file, db
from worktrace.atomic_file import AtomicFileOutput
from worktrace.collector import single_instance
from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.security import key_manager
from worktrace.services import (
    activity_lifecycle_service,
    folder_index_service,
    folder_index_query_service,
    folder_rule_service,
    maintenance_recovery_latch_repository,
    project_service,
    settings_service,
)
from worktrace.services.database_maintenance_service import RuntimeMaintenanceCoordinator

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.collector_runtime,
    pytest.mark.security_privacy,
    pytest.mark.contract,
    pytest.mark.serial,
]


def _generation(namespace: DataGenerationNamespace) -> int:
    with get_connection() as conn:
        return DataGenerationRepository.get(conn, namespace)


def test_atomic_output_success_and_concurrent_owners_use_unique_paths(tmp_path):
    target = tmp_path / "report.csv"
    first = AtomicFileOutput(target, resource="test_export")
    second = AtomicFileOutput(target, resource="test_export")
    with first, second:
        assert first.temporary_path != second.temporary_path
        first.temporary_path.write_text("first", encoding="utf-8")
        second.temporary_path.write_text("second", encoding="utf-8")
        first.commit()
        second.commit()
    assert target.read_text(encoding="utf-8") == "second"
    assert list(tmp_path.glob(".report.csv.*.tmp")) == []


def test_atomic_replace_failure_preserves_existing_target_and_cleans_temp(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "report.csv"
    target.write_text("old", encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("injected_replace_failure")

    monkeypatch.setattr(atomic_file.os, "replace", fail_replace)
    with pytest.raises(atomic_file.AtomicReplaceError):
        with AtomicFileOutput(target, resource="test_export") as output:
            output.temporary_path.write_text("new", encoding="utf-8")
            output.commit()

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".report.csv.*.tmp")) == []


def test_get_connection_closes_partial_resource_when_pragmas_fail(
    temp_db,
    monkeypatch,
):
    class FakeConnection:
        row_factory = None
        closed = False

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(db.sqlite3, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(
        db,
        "apply_connection_pragmas",
        lambda _conn: (_ for _ in ()).throw(RuntimeError("pragma_failed")),
    )

    with pytest.raises(RuntimeError, match="pragma_failed"):
        db.get_connection()
    assert connection.closed is True


def test_operational_only_pause_correction_publishes_no_business_generation(temp_db):
    settings_service.set_settings(
        {"user_paused": "true", "collector_status": "running"}
    )
    report_before = _generation(DataGenerationNamespace.REPORT_STRUCTURE)
    settings_before = _generation(DataGenerationNamespace.SETTINGS)

    assert activity_lifecycle_service.pause_collection(
        "2026-07-21 10:00:00"
    ) == []

    assert settings_service.get_setting("collector_status") == "paused"
    assert _generation(DataGenerationNamespace.REPORT_STRUCTURE) == report_before
    assert _generation(DataGenerationNamespace.SETTINGS) == settings_before


def test_folder_generation_gc_failure_keeps_new_active_generation(
    temp_db,
    tmp_path,
    monkeypatch,
    allow_sensitive_runtime,
):
    project_id = project_service.create_project("GC Boundary")
    folder = tmp_path / "GC"
    folder.mkdir()
    (folder / "one.txt").write_text("one", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(str(folder), project_id)
    assert folder_index_service.rebuild_folder_index(rule_id) is True
    with get_connection() as conn:
        first = int(
            conn.execute(
                "SELECT active_generation FROM folder_rule_index_state WHERE folder_rule_id = ?",
                (rule_id,),
            ).fetchone()["active_generation"]
        )

    (folder / "two.txt").write_text("two", encoding="utf-8")
    original_cleanup = folder_index_service._cleanup_old_generations
    monkeypatch.setattr(
        folder_index_service,
        "_cleanup_old_generations",
        lambda *_args: (_ for _ in ()).throw(OSError("gc_failed")),
    )
    assert folder_index_service.rebuild_folder_index(rule_id) is True

    with get_connection() as conn:
        state = conn.execute(
            """
            SELECT status, build_status, active_generation, file_count, last_error
            FROM folder_rule_index_state WHERE folder_rule_id = ?
            """,
            (rule_id,),
        ).fetchone()
        active = int(state["active_generation"])
        actual = int(
            conn.execute(
                """
                SELECT COUNT(*) AS value FROM folder_rule_file_index
                WHERE folder_rule_id = ? AND generation = ?
                """,
                (rule_id, active),
            ).fetchone()["value"]
        )
    assert active > first
    assert state["status"] == "ready"
    assert state["build_status"] == "ready"
    assert state["last_error"] == "folder_index_gc_pending"
    assert actual == int(state["file_count"]) == 2
    assert len(
        folder_index_query_service.lookup_indexed_paths_for_file_name(
            "two.txt", "2099-01-01 00:00:00"
        )
    ) == 1

    monkeypatch.setattr(
        folder_index_service,
        "_cleanup_old_generations",
        original_cleanup,
    )
    folder_index_service._retry_pending_gc()
    with get_connection() as conn:
        state = conn.execute(
            "SELECT last_error FROM folder_rule_index_state WHERE folder_rule_id = ?",
            (rule_id,),
        ).fetchone()
        generations = conn.execute(
            """
            SELECT DISTINCT generation FROM folder_rule_file_index
            WHERE folder_rule_id = ?
            """,
            (rule_id,),
        ).fetchall()
    assert state["last_error"] is None
    assert [int(row["generation"]) for row in generations] == [active]


def test_incomplete_subdirectory_scan_never_replaces_ready_generation(
    temp_db,
    tmp_path,
    monkeypatch,
    allow_sensitive_runtime,
):
    project_id = project_service.create_project("Incomplete Scan")
    folder = tmp_path / "Scan"
    child = folder / "Child"
    child.mkdir(parents=True)
    (folder / "root.txt").write_text("root", encoding="utf-8")
    (child / "child.txt").write_text("child", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        str(folder), project_id, True
    )
    assert folder_index_service.rebuild_folder_index(rule_id) is True
    with get_connection() as conn:
        previous = int(
            conn.execute(
                "SELECT active_generation FROM folder_rule_index_state WHERE folder_rule_id = ?",
                (rule_id,),
            ).fetchone()["active_generation"]
        )

    real_scandir = folder_index_service.os.scandir

    def injected_scandir(path):
        if Path(path) == child:
            raise PermissionError("injected_directory_unreadable")
        return real_scandir(path)

    monkeypatch.setattr(folder_index_service.os, "scandir", injected_scandir)
    assert folder_index_service.rebuild_folder_index(rule_id) is False

    with get_connection() as conn:
        state = conn.execute(
            """
            SELECT status, build_status, active_generation, last_error
            FROM folder_rule_index_state WHERE folder_rule_id = ?
            """,
            (rule_id,),
        ).fetchone()
    assert int(state["active_generation"]) == previous
    assert state["status"] == "ready"
    assert state["build_status"] == "error"
    assert state["last_error"] == "folder_index_directory_unreadable"


def test_recovery_sidecar_survives_database_mirror_failure(temp_db, monkeypatch):
    latch = maintenance_recovery_latch_repository.arm_recovery("replacement")
    monkeypatch.setattr(
        maintenance_recovery_latch_repository,
        "set_settings",
        lambda _values: (_ for _ in ()).throw(RuntimeError("db_unwritable")),
    )
    with pytest.raises(RuntimeError, match="db_unwritable"):
        maintenance_recovery_latch_repository.persist_fail_closed(
            "replacement_failed",
            expected_epoch=latch.epoch,
        )

    reloaded = maintenance_recovery_latch_repository.read_latch()
    assert reloaded.blocked is True
    assert reloaded.epoch == latch.epoch
    assert reloaded.reason == "replacement_failed"
    coordinator = RuntimeMaintenanceCoordinator()
    assert coordinator.hydrate_fail_closed_from_durable() is True


def test_stale_recovery_epoch_cannot_clear_newer_sidecar(temp_db):
    latch = maintenance_recovery_latch_repository.arm_recovery("replacement")
    with pytest.raises(
        maintenance_recovery_latch_repository.MaintenanceRecoverySealError,
        match="maintenance_recovery_epoch_mismatch",
    ):
        maintenance_recovery_latch_repository.clear_latch(
            expected_epoch="stale-epoch"
        )
    assert maintenance_recovery_latch_repository.read_latch().epoch == latch.epoch


def test_keyring_concurrent_first_create_returns_one_active_key(tmp_path):
    path = tmp_path / "keyring.json"
    wrapper = key_manager.FakeKeyWrapper()
    results: list[key_manager.LocalKey] = []
    errors: list[BaseException] = []

    def create() -> None:
        try:
            results.append(
                key_manager.create_or_load_local_key(path=path, wrapper=wrapper)
            )
        except BaseException as exc:  # pragma: no cover - assertion captures it.
            errors.append(exc)

    threads = [threading.Thread(target=create) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 4
    assert len({result.key_id for result in results}) == 1
    assert len({result.key for result in results}) == 1
    assert list(tmp_path.glob(".keyring.json.*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX partial-flock contract")
def test_single_instance_partial_acquisition_failure_releases_descriptor(
    tmp_path,
    monkeypatch,
):
    paths = type("Paths", (), {"base_dir": tmp_path})()
    monkeypatch.setattr(single_instance, "resolve_paths", lambda: paths)
    original_ftruncate = single_instance.os.ftruncate
    monkeypatch.setattr(
        single_instance.os,
        "ftruncate",
        lambda *_args: (_ for _ in ()).throw(OSError("truncate_failed")),
    )
    with pytest.raises(OSError, match="truncate_failed"):
        single_instance.acquire_single_instance()
    assert single_instance._lock_fd is None

    monkeypatch.setattr(single_instance.os, "ftruncate", original_ftruncate)
    assert single_instance.acquire_single_instance() is True
    single_instance.release_single_instance()
