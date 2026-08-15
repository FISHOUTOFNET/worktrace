from __future__ import annotations

import pytest

from worktrace.integrations.fd_work.page_adapter import FDWorkPageAdapter
from worktrace.integrations.fd_work.window_controller import FDWorkWindowController


pytestmark = [
    pytest.mark.unit,
    pytest.mark.collector_runtime,
    pytest.mark.contract,
    pytest.mark.parallel_safe,
]


def _operation() -> dict[str, object]:
    return {
        "operation_nonce": "hardening-test",
        "operation_generation": 2,
        "navigation_generation": 3,
        "timeout_seconds": 1.0,
        "operation_deadline_ms": 1893456000000,
    }


def test_page_phase_probe_prioritizes_top_level_login_and_requires_verified_shell() -> None:
    scripts: list[str] = []

    class Window:
        def evaluate_js(self, script, callback=None):
            assert callback is None
            scripts.append(script)
            return {"phase": "login_credentials"}

    values: list[object] = []
    FDWorkPageAdapter().probe_page_phase(Window(), values.append)

    assert values == [{"phase": "login_credentials"}]
    script = scripts[0]
    assert script.index('if (path === "/login")') < script.index(
        "var workCandidates = workTraceVerifiedWorkShellCandidates()"
    )
    assert 'candidate.document.querySelector(".loginPage")' in script
    assert ".workHourList, input[placeholder='请选择日期']" in script
    assert "work_shell_verified" in script
    assert "candidate.document.body" in script


def test_adapter_actions_fail_closed_without_verified_work_shell() -> None:
    class Window:
        def evaluate_js(self, script, callback=None):
            assert callback is None
            return {"ok": False}

    adapter = FDWorkPageAdapter()
    window = Window()

    assert adapter.install_adapter(window) == {
        "ok": False,
        "error": "adapter_injection_failed",
    }
    assert adapter.await_stable_work_page(window, _operation()) == {
        "ok": False,
        "error": "page_contract_changed",
    }


def test_before_load_immediately_invalidates_ready_navigation_state() -> None:
    class PageAdapter:
        business_url = "https://work.fangdalaw.com/Works/WorkHourList?picker=day"
        login_url = "https://work.fangdalaw.com/Login"

        def __init__(self) -> None:
            self.cancel_calls: list[str] = []

        def cancel_pending_actions(self, error_kind: str) -> None:
            self.cancel_calls.append(error_kind)

    adapter = PageAdapter()
    observed: list[dict[str, object]] = []
    controller = FDWorkWindowController(
        object(),
        page_adapter=adapter,
        schedule_after=lambda _delay, _callback: True,
        status_callback=observed.append,
    )
    window = object()
    try:
        with controller._lock:
            controller._window = window
            controller._navigation_generation = 7
            controller._operation_generation = 11
            controller._adapter_installed_generation = 7
            controller._session_state = "ready"
            controller._page_phase = "work_shell"
            controller._error_code = None
            controller._probe_generation = 7
            controller._probe_deadline = 123.0
            controller._login_watch_generation = 7
            controller._login_watch_deadline = 123.0

        controller._on_before_load(window)

        status = controller.get_status()
        assert status == {
            "session_state": "probing",
            "page_phase": "none",
            "operation": "none",
            "ready": False,
            "login_required": False,
            "error_code": None,
            "navigation_generation": 8,
        }
        assert observed[-1] == status
        assert adapter.cancel_calls == ["navigation_changed"]
        assert controller._navigation_is_current(window, 7) is False
        with controller._lock:
            assert controller._operation_generation == 12
            assert controller._adapter_installed_generation is None
            assert controller._probe_generation is None
            assert controller._probe_deadline is None
            assert controller._login_watch_generation is None
            assert controller._login_watch_deadline is None
    finally:
        controller.shutdown()
