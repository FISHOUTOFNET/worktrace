from __future__ import annotations

import threading

import pytest

from worktrace.integrations.fd_work.binding_repository import FDWorkBindingRepository
from worktrace.integrations.fd_work.binding_service import FDWorkBindingService
from worktrace.integrations.fd_work.case_identity import case_label_hash


pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.security_privacy]


def _project(project_id, name="TEST MATTER A", created_at="2026-08-04 10:00:01"):
    return {"id": project_id, "name": name, "created_at": created_at}


def _service(path, projects):
    by_id = {project["id"]: project for project in projects}
    return FDWorkBindingService(
        FDWorkBindingRepository(path),
        project_reader=by_id.get,
        project_list_reader=lambda: list(projects),
    )


def test_reconciliation_discards_pending_when_no_project_exists(tmp_path):
    service = _service(tmp_path / "state.db", [])
    service.repository.begin_pending_operation(
        "missing-project",
        "create",
        case_label_hash("TEST MATTER A"),
        started_at="2026-08-04T10:00:00+00:00",
    )

    result = service.reconcile_pending_operations()

    assert result["discarded"] == ("missing-project",)
    assert service.repository.list_pending_operations() == []


def test_reconciliation_completes_unique_hash_and_created_at_match(tmp_path):
    project = _project(9)
    service = _service(tmp_path / "state.db", [project])
    service.repository.begin_pending_operation(
        "recover-create",
        "create",
        case_label_hash(project["name"]),
        started_at="2026-08-04T10:00:00+00:00",
    )

    result = service.reconcile_pending_operations()

    assert result["completed"] == ("recover-create",)
    assert service.is_project_bound(9, project["name"], project["created_at"])
    assert service.repository.list_pending_operations() == []


def test_reconciliation_clears_pending_when_valid_binding_already_exists(tmp_path):
    project = _project(9)
    service = _service(tmp_path / "state.db", [project])
    name_hash = case_label_hash(project["name"])
    service.repository.bind_project(9, project["created_at"], name_hash, 5)
    service.repository.begin_pending_operation(
        "already-bound",
        "create",
        name_hash,
        started_at="2026-08-04T10:00:00+00:00",
    )
    service.repository.record_pending_project(
        "already-bound", 9, project["created_at"], "binding_written"
    )

    result = service.reconcile_pending_operations()

    assert result["completed"] == ("already-bound",)
    assert service.repository.get_pending_operation("already-bound") is None


def test_reconciliation_identity_mismatch_clears_binding_and_keeps_error(tmp_path):
    project = _project(9, "DIFFERENT MATTER")
    service = _service(tmp_path / "state.db", [project])
    intended_hash = case_label_hash("TEST MATTER A")
    service.repository.bind_project(9, project["created_at"], intended_hash, 5)
    service.repository.begin_pending_operation(
        "mismatch",
        "create",
        intended_hash,
        started_at="2026-08-04T10:00:00+00:00",
    )
    service.repository.record_pending_project(
        "mismatch", 9, project["created_at"], "project_created"
    )

    result = service.reconcile_pending_operations()

    assert result["errors"] == {"mismatch": "recovery_identity_mismatch"}
    assert service.repository.get_binding(9) is None
    pending = service.repository.get_pending_operation("mismatch")
    assert pending is not None and pending.stage == "recovery_identity_mismatch"


def test_reconciliation_ambiguous_candidates_fail_closed_and_is_bounded(tmp_path):
    projects = [_project(9), _project(10)]
    service = _service(tmp_path / "state.db", projects)
    intended_hash = case_label_hash("TEST MATTER A")
    for operation_id in ("ambiguous", "later"):
        service.repository.begin_pending_operation(
            operation_id,
            "create",
            intended_hash,
            started_at="2026-08-04T10:00:00+00:00",
        )

    result = service.reconcile_pending_operations(max_operations=1)

    assert len(result["errors"]) == 1
    assert set(result["errors"].values()) == {"recovery_ambiguous"}
    assert result["limit_reached"] is True
    assert service.repository.list_bindings() == []


@pytest.mark.parametrize(
    "stage",
    ["prepared", "project_created", "project_updated", "binding_written"],
)
def test_each_persisted_stage_recovers_after_service_restart(tmp_path, stage):
    project = _project(19)
    path = tmp_path / f"{stage}.db"
    first = _service(path, [project])
    name_hash = case_label_hash(project["name"])
    first.repository.begin_pending_operation(
        f"restart-{stage}",
        "rebind" if stage == "project_updated" else "create",
        name_hash,
        previous_name_hash=(
            case_label_hash("PREVIOUS MATTER") if stage == "project_updated" else None
        ),
        started_at="2026-08-04T10:00:00+00:00",
    )
    if stage != "prepared":
        first.repository.record_pending_project(
            f"restart-{stage}", project["id"], project["created_at"], stage
        )
    if stage == "binding_written":
        first.repository.bind_project(
            project["id"], project["created_at"], name_hash, 5
        )

    restarted = _service(path, [project])
    result = restarted.reconcile_pending_operations()

    assert result["completed"] == (f"restart-{stage}",)
    assert restarted.is_project_bound(
        project["id"], project["name"], project["created_at"]
    )
    assert restarted.repository.list_pending_operations() == []


def test_startup_reconciliation_never_blocks_on_a_slow_project_reader(tmp_path):
    repository = FDWorkBindingRepository(tmp_path / "state.db")
    repository.begin_pending_operation(
        "slow-reader",
        "create",
        case_label_hash("TEST MATTER A"),
        started_at="2026-08-04T10:00:00+00:00",
    )
    reader_entered = threading.Event()
    release_reader = threading.Event()
    caller_thread_id = threading.get_ident()

    def slow_reader():
        assert threading.get_ident() != caller_thread_id
        reader_entered.set()
        release_reader.wait(timeout=1)
        return []

    service = FDWorkBindingService(
        repository,
        project_reader=lambda _project_id: None,
        project_list_reader=slow_reader,
    )
    assert service.start_pending_reconciliation() is True

    assert reader_entered.wait(timeout=1)
    release_reader.set()
    assert service.wait_for_pending_reconciliation(timeout_seconds=1) is True
