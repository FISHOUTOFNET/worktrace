from __future__ import annotations

import sqlite3

import pytest

from worktrace.api import project_api
from worktrace.api.application_capabilities import RulesApplicationService
from worktrace.integrations.fd_work.binding_repository import FDWorkBindingRepository
from worktrace.integrations.fd_work.binding_service import FDWorkBindingService
from worktrace.integrations.fd_work.integration_service import FDWorkIntegrationService
from worktrace.services import project_service


pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.security_privacy]


class _Coordinator:
    def __init__(self) -> None:
        self._status_callback = lambda _status: None
        self._picker_callback = lambda _result: None
        self.status = {
            "session_state": "ready",
            "page_phase": "work_shell",
            "operation": "none",
            "interaction_owner": "none",
            "ready": True,
            "login_required": False,
            "error_code": None,
            "navigation_generation": 1,
        }
        self.shutdown_called = False

    def bind_status_callback(self, callback):
        self._status_callback = callback

    def bind_picker_result_callback(self, callback):
        self._picker_callback = callback

    def get_status(self):
        return dict(self.status)

    def open_case_picker(self, request_id):
        return {
            "ok": True,
            "request_id": request_id,
            "operation_status": "picker_ready",
        }

    def enable(self):
        return None

    def disable(self):
        return None

    def shutdown(self):
        self.shutdown_called = True

    def publish_picker(self, request_id, label):
        self._picker_callback(
            {
                "ok": True,
                "request_id": request_id,
                "operation_nonce": "operation-nonce",
                "navigation_generation": 1,
                "label": label,
            }
        )


def _binding_service(state_path):
    return FDWorkBindingService(
        FDWorkBindingRepository(state_path),
        project_reader=project_api.get_project,
        project_list_reader=project_service.list_user_project_identities,
    )


def _integration(state_path):
    coordinator = _Coordinator()
    delivered = []
    service = FDWorkIntegrationService(
        binding_service=_binding_service(state_path),
        interaction_coordinator=coordinator,
        enabled_reader=lambda: True,
        enabled_writer=lambda _enabled: None,
        picker_result_callback=delivered.append,
    )
    service.set_privacy_authorized(True)
    return service, coordinator, delivered


def _deliver_selection(service, coordinator, delivered, *, request_id, label):
    opened = service.open_case_picker(request_id)
    assert opened["ok"] is True
    coordinator.publish_picker(request_id, label)
    assert len(delivered) == 1
    assert delivered[0]["ok"] is True
    return delivered[0]["selection_token"]


def test_real_picker_to_project_binding_golden_path_survives_restart_and_deletes(
    temp_db, tmp_path
):
    state_path = tmp_path / "plugins" / "fd_work" / "state.db"
    integration, coordinator, delivered = _integration(state_path)
    token = _deliver_selection(
        integration,
        coordinator,
        delivered,
        request_id="drawer-golden",
        label="TEST MATTER A",
    )
    rules = RulesApplicationService(fd_work=integration)

    created = rules.create_project_for_rules(
        "TEST MATTER A", "test description", "中文", token
    )

    assert created["ok"] is True
    assert created["fd_work_binding"] == {"bound": True, "verified": True}
    project_id = created["project"]["id"]
    project = project_api.get_project(project_id)
    binding = integration._binding_service.repository.get_binding(project_id)
    assert project is not None
    assert project["name"] == "TEST MATTER A"
    assert binding is not None
    assert binding.project_id == project_id
    assert binding.project_created_at == project["created_at"]
    assert integration._binding_service.repository.list_pending_operations() == []

    listed = rules.list_project_bindings()
    readback = next(item for item in listed if item["id"] == project_id)
    assert readback["name"] == "TEST MATTER A"
    assert readback["fd_work_bound"] is True

    reused = rules.create_project_for_rules(
        "TEST MATTER A", "duplicate", "中文", token
    )
    assert reused == {"ok": False, "error": "case_selection_expired"}

    integration.shutdown()
    restarted_integration = FDWorkIntegrationService(
        binding_service=_binding_service(state_path),
        enabled_reader=lambda: True,
        enabled_writer=lambda _enabled: None,
    )
    restarted_rules = RulesApplicationService(fd_work=restarted_integration)
    restarted = restarted_rules.list_project_bindings()
    restart_readback = next(item for item in restarted if item["id"] == project_id)
    assert restart_readback["fd_work_bound"] is True

    deleted = restarted_rules.delete_project_for_rules(project_id)
    assert deleted["ok"] is True
    repository = restarted_integration._binding_service.repository
    assert repository.get_binding(project_id) is None
    assert repository.list_pending_operations() == []
    restarted_integration.shutdown()


def test_real_sidecar_binding_failure_never_returns_project_success(temp_db, tmp_path):
    state_path = tmp_path / "plugins" / "fd_work" / "state.db"
    integration, coordinator, delivered = _integration(state_path)
    token = _deliver_selection(
        integration,
        coordinator,
        delivered,
        request_id="drawer-failure",
        label="TEST MATTER B",
    )
    repository = integration._binding_service.repository
    repository.assert_writable()
    with sqlite3.connect(state_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_fd_work_binding
            BEFORE INSERT ON project_binding
            BEGIN
                SELECT RAISE(ABORT, 'binding rejected');
            END
            """
        )

    result = RulesApplicationService(fd_work=integration).create_project_for_rules(
        "TEST MATTER B", "", "中文", token
    )

    assert result == {"ok": False, "error": "fd_work_persistence_unconfirmed"}
    project = project_api.get_project_by_name("TEST MATTER B")
    assert project is not None
    assert repository.get_binding(project["id"]) is None
    pending = repository.list_pending_operations()
    assert len(pending) == 1
    assert pending[0].project_id == project["id"]
    assert pending[0].stage == "project_created"
    integration.shutdown()

    with sqlite3.connect(state_path) as connection:
        connection.execute("DROP TRIGGER reject_fd_work_binding")
    restarted_bindings = _binding_service(state_path)
    recovery = restarted_bindings.reconcile_pending_operations()
    assert len(recovery["completed"]) == 1
    assert recovery["errors"] == {}
    assert restarted_bindings.repository.get_binding(project["id"]) is not None
    assert restarted_bindings.repository.list_pending_operations() == []

    restarted_integration = FDWorkIntegrationService(
        binding_service=restarted_bindings,
        enabled_reader=lambda: True,
        enabled_writer=lambda _enabled: None,
    )
    deleted = RulesApplicationService(
        fd_work=restarted_integration
    ).delete_project_for_rules(project["id"])
    assert deleted["ok"] is True
    assert restarted_bindings.repository.get_binding(project["id"]) is None
    assert restarted_bindings.repository.list_pending_operations() == []
    restarted_integration.shutdown()
