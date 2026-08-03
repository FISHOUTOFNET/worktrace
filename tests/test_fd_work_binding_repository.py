from __future__ import annotations

import sqlite3

import pytest

from worktrace.db import CURRENT_SCHEMA_VERSION
from worktrace.integrations.fd_work.binding_repository import (
    FD_WORK_STATE_SCHEMA_VERSION,
    FDWorkBindingRepository,
    FDWorkBindingStoreError,
)
from worktrace.integrations.fd_work import binding_repository as binding_repository_module
from worktrace.integrations.fd_work.binding_service import FDWorkBindingService
from worktrace.integrations.fd_work.case_identity import case_label_hash


pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.security_privacy]


def _project(project_id=7, name=" CASE A ", created_at="2026-08-02 10:00:00"):
    return {
        "id": project_id,
        "name": name,
        "created_at": created_at,
        "is_deleted": 0,
    }


def test_sidecar_is_lazy_versioned_and_keeps_main_schema_unchanged(tmp_path):
    path = tmp_path / "plugins" / "fd_work" / "state.db"
    repository = FDWorkBindingRepository(path)

    assert not path.exists()
    assert repository.list_bindings() == []
    assert not path.exists()

    repository.bind_project(7, "2026-08-02 10:00:00", case_label_hash("CASE A"), 3)

    assert path.exists()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == FD_WORK_STATE_SCHEMA_VERSION
        columns = [row[1] for row in connection.execute("PRAGMA table_info(project_binding)")]
    assert columns == [
        "project_id",
        "project_created_at",
        "bound_name_hash",
        "adapter_contract_version",
        "bound_at",
        "updated_at",
    ]
    assert CURRENT_SCHEMA_VERSION == 13


def test_bind_get_rebind_and_clear_use_short_lived_connections(tmp_path):
    path = tmp_path / "state.db"
    repository = FDWorkBindingRepository(path)
    first_hash = case_label_hash("CASE A")
    second_hash = case_label_hash("CASE B")

    repository.bind_project(7, "created", first_hash, 3)
    first = repository.get_binding(7)
    repository.bind_project(7, "created", first_hash, 3)
    repository.bind_project(7, "created", second_hash, 3)
    second = repository.get_binding(7)
    repository.clear_binding(7)

    assert first is not None and first.bound_name_hash == first_hash
    assert second is not None and second.bound_name_hash == second_hash
    assert repository.get_binding(7) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000


def test_binding_service_validates_hash_created_at_and_reconciles_orphans(tmp_path):
    projects = {7: _project(), 8: _project(8, "CASE B", "created-b")}
    repository = FDWorkBindingRepository(tmp_path / "state.db")
    service = FDWorkBindingService(
        repository,
        project_reader=lambda project_id: projects.get(project_id),
        project_list_reader=lambda: list(projects.values()),
    )

    service.bind_project(7, "CASE A", adapter_contract_version=3)
    assert service.is_project_bound(7, "CASE A", "2026-08-02 10:00:00") is True
    assert service.is_project_bound(7, "CASE A renamed", "2026-08-02 10:00:00") is False
    assert service.is_project_bound(7, "CASE A", "different-created-at") is False

    repository.bind_project(99, None, case_label_hash("ORPHAN"), 3)
    assert service.reconcile_bindings() == {7}
    assert repository.get_binding(99) is None


def test_adapter_upgrade_does_not_invalidate_persistent_project_binding(tmp_path):
    project = _project()
    repository = FDWorkBindingRepository(tmp_path / "state.db")
    repository.bind_project(7, project["created_at"], case_label_hash("CASE A"), 3)
    upgraded = FDWorkBindingService(
        repository,
        project_reader=lambda _project_id: project,
        project_list_reader=lambda: [project],
        adapter_contract_version=4,
    )

    assert upgraded.is_project_bound(7, "CASE A", project["created_at"]) is True
    assert upgraded.reconcile_bindings() == {7}
    assert repository.get_binding(7).adapter_contract_version == 3


def test_corrupt_sidecar_and_write_failure_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    path.write_bytes(b"not sqlite")
    with pytest.raises(FDWorkBindingStoreError) as corrupted:
        FDWorkBindingRepository(path).list_bindings()
    assert corrupted.value.code == "binding_store_corrupted"
    service = FDWorkBindingService(
        FDWorkBindingRepository(path),
        project_reader=lambda _project_id: _project(),
        project_list_reader=lambda: [_project()],
    )
    assert service.is_project_bound(7, "CASE A", "2026-08-02 10:00:00") is False

    healthy = FDWorkBindingService(
        FDWorkBindingRepository(tmp_path / "healthy.db"),
        project_reader=lambda _project_id: _project(),
        project_list_reader=lambda: [_project()],
    )
    monkeypatch.setattr(healthy.repository, "bind_project", lambda *_args: (_ for _ in ()).throw(sqlite3.OperationalError("busy")))
    with pytest.raises(Exception) as raised:
        healthy.bind_project(7, "CASE A", adapter_contract_version=3)
    assert getattr(raised.value, "code", "") == "binding_store_busy"
    assert healthy.is_project_bound(7, "CASE A", "2026-08-02 10:00:00") is False


def test_locked_sidecar_returns_stable_busy_error(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    repository = FDWorkBindingRepository(path)
    repository.bind_project(7, "created", case_label_hash("CASE A"), 3)
    monkeypatch.setattr(binding_repository_module, "_BUSY_TIMEOUT_MS", 25)

    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(FDWorkBindingStoreError) as raised:
            repository.bind_project(8, "created", case_label_hash("CASE B"), 3)
    finally:
        blocker.rollback()
        blocker.close()

    assert raised.value.code == "binding_store_busy"
