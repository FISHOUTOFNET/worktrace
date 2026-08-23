from __future__ import annotations

import re

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
from worktrace.integrations.fd_work.error_codes import public_fd_work_error
from worktrace.integrations.fd_work.interaction_coordinator import FDWorkInteractionCoordinator
from worktrace.integrations.fd_work.page_adapter import FDWorkPageAdapter
from worktrace.webview_ui.bridge_fd_work import fd_work_message


pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.parallel_safe,
]


class _Window:
    def __init__(self, adapter: FDWorkPageAdapter) -> None:
        self.adapter = adapter
        self.actions: list[str] = []

    def evaluate_js(self, script, callback=None):
        if callback is None:
            return {"ok": True, "version": 5}
        callback({"ok": True, "status": "dispatched"})
        nonce = re.search(r'"action_nonce":"([^"]+)"', script).group(1)
        action = re.search(r'"action":"([^"]+)"', script).group(1)
        self.actions.append(action)
        if action == "awaitStableWorkPage":
            value = {"ok": True, "status": "work_page_ready"}
        elif action == "fillEntry":
            value = {
                "ok": True,
                "status": "saved",
                "stage": "save_completed",
            }
        else:
            value = {"ok": False, "error": "dom_contract_changed"}
        self.adapter.submit_adapter_action_result(nonce, action, value)
        return None


class _Controller:
    def __init__(self, window: _Window) -> None:
        self.window = window
        self.navigation_generation = 4
        self.hide_calls = 0

    def bind_status_callback(self, callback):
        self.status_callback = callback

    def bind_close_callback(self, callback):
        self.close_callback = callback

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
        del show_login_if_required
        return {"ok": True, "status": self.get_status()}

    def prepare_window_before_start(self, show_login_if_required=False):
        return self.prepare_session(show_login_if_required)

    def on_renderer_initialized(self, renderer):
        del renderer

    def foreground(self, owner, operation_generation, guard):
        assert owner == "automation_fill"
        assert operation_generation > 0
        assert guard()
        return {
            "ok": True,
            "window": self.window,
            "navigation_generation": self.navigation_generation,
        }

    def hide_and_restore_main(self, navigation_generation, operation_generation, guard):
        assert navigation_generation == self.navigation_generation
        assert operation_generation > 0
        assert guard()
        self.hide_calls += 1

    def disable(self):
        pass

    def shutdown(self):
        pass


def _draft() -> FDWorkEntryDraft:
    return FDWorkEntryDraft(
        work_date="2026-08-03",
        case_label="#26IP0165 IPDD_Miragene",
        case_query="26IP0165",
        duration_hours="1.5",
        narrative="Narrative",
    )


def test_real_page_adapter_preserves_save_completed_for_coordinator():
    adapter = FDWorkPageAdapter(nonce_factory=iter(["page", "fill"]).__next__)
    window = _Window(adapter)
    controller = _Controller(window)
    statuses = []
    coordinator = FDWorkInteractionCoordinator(
        window_controller=controller,
        page_adapter=adapter,
        nonce_factory=lambda: "operation",
        status_callback=statuses.append,
    )

    result = coordinator.open_entry(_draft())

    assert result == {"ok": True, "operation_status": "save_completed"}
    assert window.actions == ["awaitStableWorkPage", "fillEntry"]
    assert controller.hide_calls == 1
    assert statuses[-1]["operation_status"] == "save_completed"
    assert statuses[-1]["operation_result_owner"] == "automation_fill"


def test_uncertain_save_outcome_survives_public_error_boundary():
    assert public_fd_work_error("save_outcome_unknown") == "save_outcome_unknown"
    message = fd_work_message("save_outcome_unknown")
    assert "结果未确认" in message
    assert "不要重复填入" in message
