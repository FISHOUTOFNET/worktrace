from __future__ import annotations

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
from worktrace.integrations.fd_work.interaction_coordinator import FDWorkInteractionCoordinator


pytestmark = [pytest.mark.unit, pytest.mark.integration, pytest.mark.contract, pytest.mark.parallel_safe]


class _Controller:
    def __init__(self) -> None:
        self.window = object()
        self.navigation_generation = 7
        self.hide_calls: list[tuple[int, int]] = []
        self.visible = False
        self._status_callback = None
        self._close_callback = None

    def bind_status_callback(self, callback):
        self._status_callback = callback

    def bind_close_callback(self, callback):
        self._close_callback = callback

    def schedule_callback(self, callback):
        callback()
        return True

    def get_status(self):
        return {
            "session_state": "ready",
            "page_phase": "work_shell",
            "ready": True,
            "login_required": False,
            "error_code": None,
            "navigation_generation": self.navigation_generation,
        }

    def prepare_session(self, show_login_if_required=True):
        return {"ok": True, "status": self.get_status()}

    def prepare_window_before_start(self, show_login_if_required=False):
        return self.prepare_session(show_login_if_required)

    def on_renderer_initialized(self, renderer):
        del renderer

    def foreground(self, owner, operation_generation, guard):
        assert owner == "automation_fill"
        assert guard()
        self.visible = True
        return {
            "ok": True,
            "window": self.window,
            "navigation_generation": self.navigation_generation,
        }

    def hide_and_restore_main(self, navigation_generation, operation_generation, guard):
        assert guard()
        self.hide_calls.append((navigation_generation, operation_generation))
        self.visible = False

    def disable(self):
        pass

    def shutdown(self):
        pass


class _Adapter:
    def __init__(self, *, fill_result=None, clock=None) -> None:
        self.work_page_calls = []
        self.ensure_editor_calls = []
        self.stable_calls = []
        self.fill_calls = []
        self.fill_result = fill_result or {
            "ok": True,
            "status": "saved",
            "stage": "save_completed",
        }
        self.clock = clock

    def await_stable_work_page(self, window, contract):
        self.work_page_calls.append((window, dict(contract)))
        if self.clock is not None:
            self.clock[0] += 5.0
        return {"ok": True, "status": "work_page_ready"}

    def ensure_entry_editor(self, window, contract):
        self.ensure_editor_calls.append((window, dict(contract)))
        return {"ok": True, "status": "entry_editor_ready"}

    def await_stable_entry_editor(self, window, contract):
        self.stable_calls.append((window, dict(contract)))
        return {"ok": True, "status": "entry_editor_ready"}

    def fill_entry(self, window, draft, *, contract):
        self.fill_calls.append((window, draft, dict(contract)))
        return dict(self.fill_result)


def _draft() -> FDWorkEntryDraft:
    return FDWorkEntryDraft(
        "2026-08-03",
        "#26IP0165 IPDD_Miragene",
        "26IP0165",
        "1.5",
        "Narrative",
    )


def test_fill_coordinator_leaves_target_date_editor_preparation_to_adapter_transaction():
    controller = _Controller()
    adapter = _Adapter()
    coordinator = FDWorkInteractionCoordinator(
        window_controller=controller,
        page_adapter=adapter,
        nonce_factory=lambda: "fill-nonce",
    )

    result = coordinator.open_entry(_draft())

    assert result == {"ok": True, "operation_status": "save_completed"}
    assert len(adapter.work_page_calls) == 1
    assert adapter.ensure_editor_calls == []
    assert adapter.stable_calls == []
    assert len(adapter.fill_calls) == 1
    assert len(controller.hide_calls) == 1


def test_non_cancellation_fill_failure_restores_main_before_terminalizing():
    controller = _Controller()
    adapter = _Adapter(fill_result={
        "ok": False,
        "error": "entry_editor_not_rendered",
        "stage": "entry_editor_ready",
    })
    statuses = []
    coordinator = FDWorkInteractionCoordinator(
        window_controller=controller,
        page_adapter=adapter,
        nonce_factory=lambda: "fill-nonce",
        status_callback=statuses.append,
    )

    result = coordinator.open_entry(_draft())

    assert result == {"ok": False, "error": "entry_editor_not_rendered"}
    assert len(controller.hide_calls) == 1
    assert controller.visible is False
    assert statuses[-1]["operation_status"] == "failed"
    assert statuses[-1]["operation_result_owner"] == "automation_fill"
    assert statuses[-1]["error_code"] == "entry_editor_not_rendered"


def test_save_completion_failure_after_click_becomes_unknown_and_keeps_helper_visible():
    controller = _Controller()
    adapter = _Adapter(fill_result={
        "ok": False,
        "error": "save_completion_failed",
        "stage": "save_completed",
    })
    statuses = []
    coordinator = FDWorkInteractionCoordinator(
        window_controller=controller,
        page_adapter=adapter,
        nonce_factory=lambda: "fill-nonce",
        status_callback=statuses.append,
    )

    result = coordinator.open_entry(_draft())

    assert result == {"ok": False, "error": "save_outcome_unknown"}
    assert controller.hide_calls == []
    assert controller.visible is True
    assert statuses[-1]["operation_status"] == "failed"
    assert statuses[-1]["operation_result_owner"] == "automation_fill"
    assert statuses[-1]["error_code"] == "save_outcome_unknown"


def test_fill_deadline_is_refreshed_and_save_has_separate_budget(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(
        "worktrace.integrations.fd_work.interaction_coordinator.time.time",
        lambda: clock[0],
    )
    controller = _Controller()
    adapter = _Adapter(clock=clock)
    coordinator = FDWorkInteractionCoordinator(
        window_controller=controller,
        page_adapter=adapter,
        nonce_factory=lambda: "fill-nonce",
        fill_timeout_seconds=15.0,
        save_timeout_seconds=5.0,
    )

    result = coordinator.open_entry(_draft())

    assert result["ok"] is True
    preflight_deadline = adapter.work_page_calls[0][1]["operation_deadline_ms"]
    fill_contract = adapter.fill_calls[0][2]
    assert fill_contract["fill_deadline_ms"] - preflight_deadline == 5000
    assert fill_contract["operation_deadline_ms"] - fill_contract["fill_deadline_ms"] == 5000
    assert fill_contract["save_timeout_ms"] == 5000
