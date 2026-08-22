from __future__ import annotations

from typing import Any, Callable, Mapping

import pytest

from worktrace.integrations.fd_work.deferred_interaction import (
    DeferredFDWorkInteractionCoordinator,
)


pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


class _Coordinator:
    def __init__(self) -> None:
        self.status_callback: Callable[[Mapping[str, Any]], None] = lambda _status: None
        self.picker_callback: Callable[[Mapping[str, Any]], None] = lambda _result: None
        self.calls: list[tuple[str, object]] = []
        self.shutdown_calls = 0

    def bind_status_callback(self, callback) -> None:
        self.status_callback = callback

    def bind_picker_result_callback(self, callback) -> None:
        self.picker_callback = callback

    def get_status(self):
        return {
            "session_state": "ready",
            "page_phase": "work_page_ready",
            "operation": "none",
            "interaction_owner": "none",
            "ready": True,
            "login_required": False,
            "error_code": None,
            "navigation_generation": 7,
        }

    def prepare_session(self, show_login_if_required=True):
        self.calls.append(("prepare_session", show_login_if_required))
        return {"ok": True}

    def prepare_window_before_start(self, show_login_if_required=True):
        self.calls.append(("prepare_window_before_start", show_login_if_required))
        return {"ok": True}

    def on_renderer_initialized(self, renderer: str) -> None:
        self.calls.append(("renderer", renderer))

    def open_case_picker(self, request_id: str):
        self.calls.append(("open_case_picker", request_id))
        return {"ok": True, "request_id": request_id}

    def cancel_case_picker(self, request_id: str):
        self.calls.append(("cancel_case_picker", request_id))
        return {"ok": True, "accepted": True}

    def open_entry(self, draft):
        self.calls.append(("open_entry", draft))
        return {"ok": True}

    def enable(self) -> None:
        self.calls.append(("enable", True))

    def disable(self) -> None:
        self.calls.append(("disable", False))

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def test_pre_bind_operations_are_stable_and_never_create_a_window() -> None:
    deferred = DeferredFDWorkInteractionCoordinator()

    status = deferred.get_status()
    assert status["ready"] is False
    assert status["error_code"] == "window_unavailable"
    assert deferred.prepare_session() == {"ok": False, "error": "window_unavailable"}
    assert deferred.prepare_window_before_start() == {
        "ok": False,
        "error": "window_unavailable",
    }
    assert deferred.open_case_picker("picker-1") == {
        "ok": False,
        "error": "window_unavailable",
    }
    assert deferred.cancel_case_picker("picker-1") == {
        "ok": False,
        "error": "window_unavailable",
    }
    assert deferred.open_entry(object()) == {
        "ok": False,
        "error": "window_unavailable",
    }
    deferred.on_renderer_initialized("edgechromium")


def test_bind_preserves_callbacks_state_and_delegates_every_interaction() -> None:
    deferred = DeferredFDWorkInteractionCoordinator()
    statuses: list[dict[str, Any]] = []
    picker_results: list[dict[str, Any]] = []
    deferred.bind_status_callback(lambda value: statuses.append(dict(value)))
    deferred.bind_picker_result_callback(lambda value: picker_results.append(dict(value)))
    deferred.disable()
    coordinator = _Coordinator()

    assert deferred.bind(coordinator) is True
    assert deferred.bind(coordinator) is False
    assert ("disable", False) in coordinator.calls

    coordinator.status_callback({"ready": True})
    coordinator.picker_callback({"ok": True, "request_id": "picker-1"})
    assert statuses == [{"ready": True}]
    assert picker_results == [{"ok": True, "request_id": "picker-1"}]

    deferred.enable()
    assert deferred.prepare_session(False) == {"ok": True}
    assert deferred.prepare_window_before_start(False) == {"ok": True}
    assert deferred.open_case_picker("picker-1")["ok"] is True
    assert deferred.cancel_case_picker("picker-1")["accepted"] is True
    draft = object()
    assert deferred.open_entry(draft)["ok"] is True
    deferred.on_renderer_initialized("edgechromium")
    assert deferred.get_status()["navigation_generation"] == 7

    assert ("enable", True) in coordinator.calls
    assert ("prepare_session", False) in coordinator.calls
    assert ("prepare_window_before_start", False) in coordinator.calls
    assert ("open_entry", draft) in coordinator.calls
    assert ("renderer", "edgechromium") in coordinator.calls


def test_shutdown_is_idempotent_and_forbids_late_reactivation() -> None:
    deferred = DeferredFDWorkInteractionCoordinator()
    coordinator = _Coordinator()
    deferred.bind(coordinator)

    deferred.shutdown()
    deferred.shutdown()

    assert coordinator.shutdown_calls == 1
    assert deferred.get_status()["session_state"] == "shutdown"
    assert deferred.prepare_session()["error"] == "window_unavailable"
    with pytest.raises(RuntimeError, match="shutdown"):
        deferred.bind(_Coordinator())


def test_bind_is_only_idempotent_for_the_same_real_coordinator() -> None:
    deferred = DeferredFDWorkInteractionCoordinator()
    first = _Coordinator()
    deferred.bind(first)

    with pytest.raises(RuntimeError, match="already_bound"):
        deferred.bind(_Coordinator())
