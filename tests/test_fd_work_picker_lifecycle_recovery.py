from __future__ import annotations

import threading

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
from worktrace.integrations.fd_work.interaction_coordinator import FDWorkInteractionCoordinator
from worktrace.integrations.fd_work.page_adapter import FDWorkPageAdapter


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _Controller:
    def __init__(self) -> None:
        self.window = object()
        self.navigation_generation = 4
        self._status_callback = None
        self._close_callback = None
        self.status = {
            "session_state": "ready",
            "page_phase": "work_shell",
            "ready": True,
            "login_required": False,
            "error_code": None,
            "navigation_generation": self.navigation_generation,
        }

    def bind_status_callback(self, callback): self._status_callback = callback
    def bind_close_callback(self, callback): self._close_callback = callback
    def schedule_callback(self, callback): callback(); return True
    def get_status(self): return dict(self.status)
    def prepare_session(self, show_login_if_required=True): return {"ok": True, "status": self.get_status()}
    def prepare_window_before_start(self, show_login_if_required=False): return {"ok": True, "status": self.get_status()}
    def on_renderer_initialized(self, renderer): pass
    def foreground(self, owner, operation_generation, guard):
        assert guard()
        return {"ok": True, "window": self.window, "navigation_generation": self.navigation_generation}
    def hide_and_restore_main(self, navigation_generation, operation_generation, guard): assert guard()
    def disable(self): pass
    def shutdown(self): pass


class _Adapter:
    def __init__(self, reset_results=None) -> None:
        self.calls = []
        self.reset_results = list(reset_results or [{"ok": True}])

    def reset_case_picker(self, window, contract):
        self.calls.append("reset")
        if len(self.reset_results) > 1:
            return self.reset_results.pop(0)
        return dict(self.reset_results[0])

    def await_stable_work_page(self, window, contract): self.calls.append("work"); return {"ok": True}
    def ensure_entry_editor(self, window, contract): self.calls.append("ensure"); return {"ok": True}
    def await_stable_entry_editor(self, window, contract): self.calls.append("stable"); return {"ok": True}
    def enter_case_picker(self, window, contract): self.calls.append("enter"); return {"ok": True, "status": "picker_ready"}
    def leave_case_picker(self, window, contract): self.calls.append("leave"); return {"ok": True}


def test_picker_preflight_resets_stale_artifacts_before_editor_readiness() -> None:
    adapter = _Adapter()
    coordinator = FDWorkInteractionCoordinator(
        window_controller=_Controller(),
        page_adapter=adapter,
        nonce_factory=lambda: "nonce",
    )

    result = coordinator.open_case_picker("drawer")

    assert result["ok"] is True
    assert adapter.calls == ["reset", "work", "ensure", "stable", "enter"]


def test_picker_preflight_retries_one_direct_cleanup_before_failing() -> None:
    adapter = _Adapter([{"ok": False, "error": "javascript_exception"}, {"ok": True}])
    coordinator = FDWorkInteractionCoordinator(
        window_controller=_Controller(),
        page_adapter=adapter,
        nonce_factory=lambda: "nonce",
    )

    result = coordinator.open_case_picker("drawer")

    assert result["ok"] is True
    assert adapter.calls[:3] == ["reset", "reset", "work"]


class _ResetWindow:
    def __init__(self) -> None:
        self.scripts = []

    def evaluate_js(self, script, *args, **kwargs):
        self.scripts.append(script)
        if "direct-picker-reset" in script:
            return {"ok": True}
        return {"ok": True}


def test_direct_picker_reset_removes_owned_artifacts_without_callback_round_trip() -> None:
    diagnostics = []
    adapter = FDWorkPageAdapter(diagnostic_callback=diagnostics.append)
    window = _ResetWindow()
    contract = {"operation_generation": 3, "navigation_generation": 4}

    result = adapter.reset_case_picker(window, contract)

    assert result == {"ok": True}
    assert len(window.scripts) == 1
    script = window.scripts[0]
    assert "leaveCasePicker" in script
    assert "worktrace-fdwork-picker-blocker" in script
    assert "worktrace-fdwork-fill-blocker" in script
    assert "#basic_caseId" in script
    assert diagnostics[-1]["action"] == "leaveCasePicker"


def test_fill_callback_timeout_is_fail_closed_as_unknown_save_outcome(monkeypatch) -> None:
    adapter = FDWorkPageAdapter()
    monkeypatch.setattr(
        adapter,
        "_run_action",
        lambda *args, **kwargs: {"ok": False, "error": "callback_timeout"},
    )
    draft = FDWorkEntryDraft("2026-08-03", "CASE A", "CASE A", "1.0", "Narrative")

    result = adapter.fill_entry(object(), draft, contract={"operation_generation": 1})

    assert result == {"ok": False, "error": "save_outcome_unknown"}
