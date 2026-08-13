from __future__ import annotations

import pytest

from worktrace.integrations.fd_work.integration_service import FDWorkIntegrationService
from worktrace.integrations.fd_work.interaction_coordinator import FDWorkInteractionCoordinator

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _Controller:
    def __init__(self, *, ready=True):
        self.status = {"session_state": "ready" if ready else "login_required", "page_phase": "work_shell" if ready else "login_credentials", "ready": ready, "login_required": not ready, "error_code": None, "navigation_generation": 4}
        self.status_callback = None; self.close_callback = None; self.scheduled = []; self.window = object(); self.hide_calls = 0
    def bind_status_callback(self, callback): self.status_callback = callback
    def bind_close_callback(self, callback): self.close_callback = callback
    def get_status(self): return dict(self.status)
    def prepare_session(self, show_login_if_required=True): return {"ok": True, "status": self.get_status()}
    def prepare_window_before_start(self, show_login_if_required=False): return self.prepare_session(show_login_if_required)
    def on_renderer_initialized(self, renderer): pass
    def foreground(self, owner, operation_generation, guard): assert guard(); return {"ok": True, "window": self.window, "navigation_generation": 4}
    def hide_and_restore_main(self, navigation_generation, operation_generation, guard):
        if guard(): self.hide_calls += 1
    def schedule_callback(self, callback): self.scheduled.append(callback); return True
    def run_scheduled(self): self.scheduled.pop(0)()
    def disable(self): pass
    def shutdown(self): pass


class _Adapter:
    def __init__(self): self.leave_calls = 0
    def await_stable_work_page(self, window, contract): return {"ok": True}
    def ensure_entry_editor(self, window, contract): return {"ok": True}
    def await_stable_entry_editor(self, window, contract): return {"ok": True}
    def enter_case_picker(self, window, contract): return {"ok": True, "status": "picker_ready"}
    def leave_case_picker(self, window, contract): self.leave_calls += 1; return {"ok": True}


def test_main_window_cancel_is_request_scoped_and_releases_ready_picker():
    controller = _Controller(ready=True); adapter = _Adapter(); results = []
    coordinator = FDWorkInteractionCoordinator(window_controller=controller, page_adapter=adapter, nonce_factory=lambda: "picker-nonce", picker_result_callback=results.append)
    assert coordinator.open_case_picker("drawer-1")["ok"] is True
    assert coordinator.cancel_case_picker("drawer-stale") == {"ok": True, "accepted": False}
    assert coordinator.cancel_case_picker("drawer-1") == {"ok": True, "accepted": True}
    controller.run_scheduled()
    assert coordinator.get_status()["interaction_owner"] == "none"
    assert adapter.leave_calls == 1
    assert results[-1]["request_id"] == "drawer-1" and results[-1]["error"] == "picker_canceled"


def test_main_window_cancel_also_releases_picker_waiting_for_login():
    controller = _Controller(ready=False); adapter = _Adapter(); results = []
    coordinator = FDWorkInteractionCoordinator(window_controller=controller, page_adapter=adapter, nonce_factory=lambda: "auth-nonce", picker_result_callback=results.append)
    opened = coordinator.open_case_picker("drawer-auth")
    assert opened["operation_status"] == "authentication_required"
    assert coordinator.cancel_case_picker("drawer-auth") == {"ok": True, "accepted": True}
    controller.run_scheduled()
    assert coordinator.get_status()["interaction_owner"] == "none"
    assert adapter.leave_calls == 0 and results[-1]["error"] == "picker_canceled"


class _ServiceCoordinator:
    def __init__(self): self.status_callback = None; self.picker_callback = None; self.cancel_calls = []
    def bind_status_callback(self, callback): self.status_callback = callback
    def bind_picker_result_callback(self, callback): self.picker_callback = callback
    def get_status(self): return {"session_state":"ready","page_phase":"work_shell","operation":"none","interaction_owner":"none","ready":True,"login_required":False,"error_code":None,"navigation_generation":4}
    def open_case_picker(self, request_id): return {"ok": True, "request_id": request_id, "operation_nonce": "nonce", "operation_status": "picker_ready"}
    def cancel_case_picker(self, request_id): self.cancel_calls.append(request_id); return {"ok": True, "accepted": True}
    def enable(self): pass
    def disable(self): pass
    def shutdown(self): pass
    def on_renderer_initialized(self, renderer): pass


def test_integration_service_only_forwards_cancel_for_its_active_request():
    coordinator = _ServiceCoordinator()
    service = FDWorkIntegrationService(interaction_coordinator=coordinator, enabled_reader=lambda: True, enabled_writer=lambda enabled: None)
    service.set_privacy_authorized(True)
    assert service.open_case_picker("drawer-1")["ok"] is True
    stale = service.cancel_case_picker("drawer-old")
    assert stale["ok"] is True and stale["accepted"] is False and coordinator.cancel_calls == []
    current = service.cancel_case_picker("drawer-1")
    assert current["ok"] is True and current["accepted"] is True
    assert coordinator.cancel_calls == ["drawer-1"]
