from __future__ import annotations

import pytest

from worktrace.integrations.fd_work.integration_service import FDWorkIntegrationService


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _Coordinator:
    def __init__(self) -> None:
        self._status_callback = None
        self._picker_result_callback = None
        self.fail_next = False
        self.status = {
            "session_state": "ready",
            "page_phase": "work_shell",
            "operation": "none",
            "interaction_owner": "none",
            "ready": True,
            "login_required": False,
            "error_code": None,
            "navigation_generation": 3,
        }

    def bind_status_callback(self, callback): self._status_callback = callback
    def bind_picker_result_callback(self, callback): self._picker_result_callback = callback
    def get_status(self): return dict(self.status)
    def open_case_picker(self, request_id):
        if self.fail_next:
            self.fail_next = False
            return {"ok": False, "error": "window_unavailable"}
        assert self._picker_result_callback is not None
        self._picker_result_callback({
            "ok": True,
            "request_id": request_id,
            "operation_nonce": "nonce",
            "navigation_generation": 3,
            "label": "CASE A",
        })
        return {"ok": True, "operation_nonce": "nonce", "operation_status": "picker_ready"}
    def prepare_session(self, show_login_if_required=True): return {"ok": True, "status": self.get_status()}
    def prepare_window_before_start(self, show_login_if_required=False): return {"ok": True, "status": self.get_status()}
    def on_renderer_initialized(self, renderer): pass
    def open_entry(self, draft): return {"ok": True}
    def enable(self): pass
    def disable(self): pass
    def shutdown(self): pass


def _service(coordinator, delivered):
    service = FDWorkIntegrationService(
        interaction_coordinator=coordinator,
        enabled_reader=lambda: True,
        enabled_writer=lambda value: None,
        token_factory=lambda: "selection-token",
        picker_result_callback=delivered.append,
    )
    service.set_privacy_authorized(True)
    return service


def test_active_picker_request_is_reserved_before_fast_terminal_callback() -> None:
    coordinator = _Coordinator()
    delivered = []
    service = _service(coordinator, delivered)

    opened = service.open_case_picker("drawer-fast")

    assert opened["ok"] is True
    assert delivered == [{
        "ok": True,
        "request_id": "drawer-fast",
        "selected_label": "CASE A",
        "selection_token": "selection-token",
    }]
    assert service.validate_case_selection("selection-token", "CASE A") == "CASE A"


def test_failed_open_rolls_back_request_reservation_for_immediate_retry() -> None:
    coordinator = _Coordinator()
    coordinator.fail_next = True
    delivered = []
    service = _service(coordinator, delivered)

    failed = service.open_case_picker("drawer-first")
    retried = service.open_case_picker("drawer-second")

    assert failed["ok"] is False
    assert retried["ok"] is True
    assert delivered[-1]["request_id"] == "drawer-second"
