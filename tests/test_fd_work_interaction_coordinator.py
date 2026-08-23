from __future__ import annotations

from dataclasses import dataclass
import re
import threading

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
from worktrace.integrations.fd_work.interaction_coordinator import (
    FDWorkInteractionCoordinator,
)
from worktrace.integrations.fd_work.helper_bridge import FDWorkHelperBridge
from worktrace.integrations.fd_work.page_adapter import FDWorkPageAdapter


pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.parallel_safe,
]


@dataclass
class _WindowContext:
    window: object
    navigation_generation: int


class _Controller:
    def __init__(self) -> None:
        self.window = object()
        self.navigation_generation = 4
        self.foreground_calls: list[tuple[str, int]] = []
        self.hide_calls: list[tuple[int, int]] = []
        self.main_focus_calls = 0
        self.prepare_calls: list[bool] = []
        self._status_callback = None
        self._close_callback = None
        self.disable_calls = 0
        self.shutdown_calls = 0
        self.scheduled = []
        self.visible = False
        self.window_actions = []
        self.status = {
            "session_state": "ready",
            "page_phase": "work_shell",
            "ready": True,
            "login_required": False,
            "error_code": None,
            "navigation_generation": self.navigation_generation,
        }

    def bind_status_callback(self, callback):
        self._status_callback = callback

    def bind_close_callback(self, callback):
        self._close_callback = callback

    def schedule_callback(self, callback):
        self.scheduled.append(callback)
        return True

    def run_scheduled(self):
        self.scheduled.pop(0)()

    def get_status(self):
        return dict(self.status)

    def prepare_session(self, show_login_if_required=True):
        self.prepare_calls.append(show_login_if_required)
        if show_login_if_required and not self.visible:
            self.visible = True
            self.window_actions.extend(["show", "restore", "focus"])
        return {"ok": True, "status": self.get_status()}

    def prepare_window_before_start(self, show_login_if_required=False):
        return self.prepare_session(show_login_if_required)

    def foreground(self, owner, operation_generation, guard):
        assert guard()
        self.foreground_calls.append((owner, operation_generation))
        if not self.visible:
            self.visible = True
            self.window_actions.extend(["show", "restore", "focus"])
        assert guard()
        return {
            "ok": True,
            "window": self.window,
            "navigation_generation": self.navigation_generation,
        }

    def hide_and_restore_main(self, navigation_generation, operation_generation, guard):
        assert guard()
        self.hide_calls.append((navigation_generation, operation_generation))
        self.main_focus_calls += 1
        self.visible = False
        self.window_actions.extend(["hide", "main"])
        assert guard()

    def close_helper(self):
        if self._close_callback:
            self._close_callback(self.navigation_generation)

    def disable(self):
        self.disable_calls += 1

    def shutdown(self):
        self.shutdown_calls += 1

    def publish(self, **changes):
        self.status.update(changes)
        if "navigation_generation" in changes:
            self.navigation_generation = changes["navigation_generation"]
        if self._status_callback:
            self._status_callback(dict(self.status))


class _Adapter:
    def __init__(self) -> None:
        self.enter_picker_calls = []
        self.read_calls = []
        self.leave_calls = []
        self.work_page_calls = []
        self.ensure_editor_calls = []
        self.stable_calls = []
        self.fill_calls = []
        self.read_result = {"ok": True, "label": "CASE A"}
        self.fill_started = threading.Event()
        self.fill_release = threading.Event()
        self.block_fill = False
        self.fill_result = {"ok": True, "status": "saved", "stage": "save_completed"}

    def enter_case_picker(self, window, contract):
        self.enter_picker_calls.append((window, dict(contract)))
        return {"ok": True, "status": "picker_ready"}

    def read_selected_case(self, window, contract):
        self.read_calls.append((window, dict(contract)))
        return dict(self.read_result)

    def leave_case_picker(self, window, contract):
        self.leave_calls.append((window, dict(contract)))
        return {"ok": True}

    def await_stable_work_page(self, window, contract):
        self.work_page_calls.append((window, dict(contract)))
        return {"ok": True, "status": "work_page_ready"}

    def ensure_entry_editor(self, window, contract):
        self.ensure_editor_calls.append((window, dict(contract)))
        return {"ok": True, "status": "entry_editor_ready"}

    def await_stable_entry_editor(self, window, contract):
        self.stable_calls.append((window, dict(contract)))
        return {"ok": True, "status": "entry_editor_ready"}

    def await_stable_work_shell(self, window, contract):
        self.stable_calls.append((window, dict(contract)))
        return {"ok": True, "status": "stable"}

    def fill_entry(self, window, draft, *, contract):
        self.fill_calls.append((window, draft, dict(contract)))
        self.fill_started.set()
        if self.block_fill:
            assert self.fill_release.wait(timeout=2)
        return dict(self.fill_result)


def _coordinator(*, controller=None, adapter=None, results=None, nonces=None):
    controller = controller or _Controller()
    adapter = adapter or _Adapter()
    nonce_values = iter(nonces or ["picker-nonce", "fill-nonce", "next-nonce"])
    coordinator = FDWorkInteractionCoordinator(
        window_controller=controller,
        page_adapter=adapter,
        nonce_factory=lambda: next(nonce_values),
        picker_result_callback=(results.append if results is not None else None),
    )
    return coordinator, controller, adapter


def _draft():
    return FDWorkEntryDraft(
        "2026-08-03", "CASE A", "CASE A", "1.5", "Narrative"
    )


def test_explicit_picker_foregrounds_once_and_enters_user_owned_mode():
    coordinator, controller, adapter = _coordinator()

    result = coordinator.open_case_picker("drawer-1")

    assert result["ok"] is True
    assert result["operation_nonce"] == "picker-nonce"
    assert controller.foreground_calls == [("user_picker", 1)]
    assert len(adapter.stable_calls) == 1
    assert len(adapter.enter_picker_calls) == 1
    assert coordinator.get_status()["interaction_owner"] == "user_picker"


def test_picker_and_fill_are_mutually_exclusive():
    coordinator, controller, adapter = _coordinator()
    coordinator.open_case_picker("drawer-1")

    assert coordinator.open_entry(_draft())["error"] == "fd_work_busy"

    coordinator.submit_case_picker_cancellation("picker-nonce")
    controller.run_scheduled()
    adapter.block_fill = True
    outcome = {}
    worker = threading.Thread(
        target=lambda: outcome.setdefault("result", coordinator.open_entry(_draft()))
    )
    worker.start()
    assert adapter.fill_started.wait(timeout=2)
    assert coordinator.open_case_picker("drawer-2")["error"] == "fd_work_busy"
    adapter.fill_release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert outcome["result"]["ok"] is True
    assert coordinator.get_status()["interaction_owner"] == "none"


def test_fill_failure_releases_owner_and_does_not_poison_next_picker():
    coordinator, controller, adapter = _coordinator(
        nonces=["fill-nonce", "picker-nonce"]
    )
    adapter.fill_result = {
        "ok": False,
        "error": "duration_verification_failed",
        "stage": "duration_verified",
    }

    failed = coordinator.open_entry(_draft())

    assert failed == {"ok": False, "error": "duration_verification_failed"}
    assert coordinator.get_status()["interaction_owner"] == "none"
    reopened = coordinator.open_case_picker("drawer-after-fill-failure")
    assert reopened["ok"] is True
    assert coordinator.get_status()["interaction_owner"] == "user_picker"
    assert controller.foreground_calls == [
        ("automation_fill", 1),
        ("user_picker", 3),
    ]


def test_confirmation_submission_is_async_and_uses_adapter_proof_without_reread():
    results = []
    coordinator, controller, adapter = _coordinator(results=results)
    coordinator.open_case_picker("drawer-1")

    assert coordinator.submit_case_picker_confirmation(
        "wrong", "CASE A", 1
    )["error"] == "picker_superseded"
    confirmed = coordinator.submit_case_picker_confirmation(
        "picker-nonce", "CASE A", 2
    )

    assert confirmed == {"ok": True, "accepted": True}
    assert results == []
    assert adapter.read_calls == []
    assert adapter.leave_calls == []
    assert controller.hide_calls == []

    controller.run_scheduled()

    assert results == [{
        "ok": True,
        "request_id": "drawer-1",
        "operation_nonce": "picker-nonce",
        "navigation_generation": 4,
        "selection_revision": 2,
        "label": "CASE A",
    }]
    assert adapter.read_calls == []
    assert len(adapter.leave_calls) == 1
    assert controller.hide_calls == [(4, 1)]
    assert controller.main_focus_calls == 1
    assert coordinator.get_status()["interaction_owner"] == "none"


def test_helper_bridge_return_path_has_no_same_window_javascript_reentry():
    diagnostics = []

    class ReentrantWindow:
        bridge_active = False
        bridge = None

        def evaluate_js(self, script, callback=None):
            if self.bridge_active:
                raise RuntimeError("same helper bridge stack re-entry")
            callback({"ok": True, "status": "dispatched"})
            nonce = re.search(r'"action_nonce":"([^"]+)"', script).group(1)
            action = re.search(r'"action":"([^"]+)"', script).group(1)
            status = "picker_ready" if action == "enterCasePicker" else "left"
            self.bridge.submit_adapter_action_result(
                nonce,
                action,
                {"ok": True, "status": status},
            )

    controller = _Controller()
    controller.window = ReentrantWindow()
    adapter = FDWorkPageAdapter(diagnostic_callback=diagnostics.append)
    coordinator, _controller, _adapter = _coordinator(
        controller=controller,
        adapter=adapter,
    )
    bridge = FDWorkHelperBridge(coordinator, action_result_sink=adapter)
    controller.window.bridge = bridge
    assert coordinator.open_case_picker("drawer-1")["ok"] is True
    before_submit = list(diagnostics)

    controller.window.bridge_active = True
    result = bridge.submit_case_picker_confirmation("picker-nonce", "CASE A", 1)

    assert result == {"ok": True, "accepted": True}
    assert diagnostics == before_submit
    assert len(controller.scheduled) == 1
    controller.window.bridge_active = False
    controller.run_scheduled()
    assert diagnostics[-1]["action"] == "leaveCasePicker"


def test_cancel_and_helper_close_complete_pending_picker_without_deadlock():
    results = []
    coordinator, controller, _adapter = _coordinator(
        results=results,
        nonces=["first", "second"],
    )
    coordinator.open_case_picker("drawer-1")
    assert coordinator.submit_case_picker_cancellation("first") == {
        "ok": True,
        "accepted": True,
    }
    assert results == []
    controller.run_scheduled()
    assert results[-1]["error"] == "picker_canceled"
    assert controller.main_focus_calls == 1

    coordinator.open_case_picker("drawer-2")
    worker = threading.Thread(target=controller.close_helper)
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert results[-1]["request_id"] == "drawer-2"
    assert results[-1]["error"] == "window_closed"


def test_navigation_disable_and_shutdown_supersede_stale_callbacks():
    results = []
    coordinator, controller, _adapter = _coordinator(
        results=results,
        nonces=["first", "second", "third"],
    )
    coordinator.open_case_picker("drawer-1")
    controller.publish(navigation_generation=5, session_state="probing", ready=False)
    assert coordinator.submit_case_picker_confirmation(
        "first", "CASE A", 1
    )["error"] == "picker_superseded"

    controller.publish(session_state="ready", ready=True, page_phase="work_shell")
    coordinator.open_case_picker("drawer-2")
    coordinator.disable()
    assert coordinator.submit_case_picker_confirmation(
        "second", "CASE A", 1
    )["error"] == "picker_superseded"

    coordinator.open_case_picker("drawer-3")
    coordinator.shutdown()
    assert coordinator.submit_case_picker_confirmation(
        "third", "CASE A", 1
    )["error"] == "picker_superseded"


def test_login_completion_resumes_pending_picker_with_fresh_operation_nonce():
    controller = _Controller()
    controller.status.update({
        "session_state": "login_required",
        "page_phase": "login_credentials",
        "ready": False,
        "login_required": True,
    })
    coordinator, _controller, adapter = _coordinator(
        controller=controller,
        nonces=["auth-nonce", "picker-nonce"],
    )

    opening = coordinator.open_case_picker("drawer-1")
    assert opening["operation_status"] == "authentication_required"
    assert coordinator.get_status()["interaction_owner"] == "user_auth"
    assert adapter.enter_picker_calls == []

    controller.publish(
        session_state="ready",
        page_phase="work_shell",
        ready=True,
        login_required=False,
        navigation_generation=5,
    )

    assert coordinator.get_status()["interaction_owner"] == "user_picker"
    assert coordinator.get_status()["operation_nonce"] == "picker-nonce"
    assert len(adapter.enter_picker_calls) == 1


def test_visibility_sequence_passive_probe_stays_hidden():
    controller = _Controller()
    controller.status.update({"session_state": "probing", "ready": False})
    coordinator, _controller, _adapter = _coordinator(controller=controller)

    coordinator.prepare_window_before_start(False)
    controller.publish(session_state="ready", page_phase="work_shell", ready=True)

    assert controller.window_actions == []


def test_visibility_sequence_standalone_login_hides_once_and_restores_main():
    controller = _Controller()
    controller.status.update({
        "session_state": "login_required",
        "page_phase": "login_credentials",
        "ready": False,
    })
    coordinator, _controller, _adapter = _coordinator(controller=controller)

    coordinator.prepare_session(True)
    controller.publish(session_state="ready", page_phase="work_shell", ready=True)

    assert controller.window_actions == [
        "show", "restore", "focus", "hide", "main"
    ]


def test_visibility_sequence_login_to_picker_has_no_hide_show_round_trip():
    controller = _Controller()
    controller.status.update({
        "session_state": "login_required",
        "page_phase": "login_credentials",
        "ready": False,
    })
    coordinator, _controller, _adapter = _coordinator(
        controller=controller,
        nonces=["auth", "picker"],
    )

    coordinator.open_case_picker("drawer-1")
    controller.publish(session_state="ready", page_phase="work_shell", ready=True)

    assert controller.window_actions == ["show", "restore", "focus"]
    assert coordinator.get_status()["interaction_owner"] == "user_picker"


def test_visibility_sequence_ready_picker_foregrounds_and_hides_once_on_confirm():
    coordinator, controller, _adapter = _coordinator()
    coordinator.open_case_picker("drawer-1")

    accepted = coordinator.submit_case_picker_confirmation(
        "picker-nonce", "CASE A", 1
    )
    assert accepted == {"ok": True, "accepted": True}
    assert controller.window_actions == ["show", "restore", "focus"]
    controller.run_scheduled()

    assert controller.window_actions == [
        "show", "restore", "focus", "hide", "main"
    ]


def test_visibility_sequence_fill_saves_hides_and_restores_main():
    coordinator, controller, _adapter = _coordinator()

    result = coordinator.open_entry(_draft())

    assert result == {"ok": True, "operation_status": "save_completed"}
    assert controller.window_actions == [
        "show", "restore", "focus", "hide", "main"
    ]
    assert controller.hide_calls == [(4, 1)]
    assert controller.main_focus_calls == 1
    assert coordinator.get_status()["interaction_owner"] == "none"


def test_explicit_standalone_auth_owns_helper_until_ready_then_restores_main():
    controller = _Controller()
    controller.status.update({
        "session_state": "login_required",
        "page_phase": "login_credentials",
        "ready": False,
        "login_required": True,
    })
    coordinator, _controller, _adapter = _coordinator(
        controller=controller,
        nonces=["auth-nonce"],
    )

    opened = coordinator.prepare_session(show_login_if_required=True)

    assert opened["ok"] is True
    assert controller.prepare_calls == [True]
    assert coordinator.get_status()["interaction_owner"] == "user_auth"

    controller.publish(
        session_state="ready",
        page_phase="work_shell",
        ready=True,
        login_required=False,
        navigation_generation=5,
    )

    assert controller.hide_calls == [(5, 1)]
    assert controller.main_focus_calls == 1
    assert coordinator.get_status()["interaction_owner"] == "none"


def test_fill_uses_read_only_preflight_and_adapter_owned_dom_transaction():
    coordinator, controller, adapter = _coordinator(nonces=["fill-nonce"])

    result = coordinator.open_entry(_draft())

    assert result["ok"] is True
    assert controller.foreground_calls == [("automation_fill", 1)]
    assert len(adapter.work_page_calls) == 1
    assert adapter.ensure_editor_calls == []
    assert adapter.stable_calls == []
    assert len(adapter.fill_calls) == 1
    assert (
        adapter.fill_calls[0][2]["operation_deadline_ms"]
        >= adapter.work_page_calls[0][1]["operation_deadline_ms"]
    )
    assert not hasattr(adapter, "check_work_interactive")
    assert coordinator.get_status()["interaction_owner"] == "none"


def test_five_fill_save_transactions_reuse_ready_helper_without_busy_state():
    nonces = [f"fill-{index}" for index in range(5)]
    coordinator, controller, adapter = _coordinator(nonces=nonces)

    results = [coordinator.open_entry(_draft()) for _index in range(5)]

    assert results == [{"ok": True, "operation_status": "save_completed"}] * 5
    assert len(adapter.fill_calls) == 5
    assert controller.prepare_calls == []
    assert controller.hide_calls == [(4, generation) for generation in (1, 3, 5, 7, 9)]
    assert coordinator.get_status()["interaction_owner"] == "none"
    assert coordinator.get_status()["ready"] is True


def test_picker_owns_editor_preparation_while_fill_delegates_dom_transaction():
    picker, picker_controller, picker_adapter = _coordinator(
        nonces=["picker-nonce"]
    )

    assert picker.open_case_picker("drawer-1")["operation_status"] == "picker_ready"
    assert [
        len(picker_adapter.work_page_calls),
        len(picker_adapter.ensure_editor_calls),
        len(picker_adapter.stable_calls),
        len(picker_adapter.enter_picker_calls),
    ] == [1, 1, 1, 1]

    fill, fill_controller, fill_adapter = _coordinator(nonces=["fill-nonce"])
    assert fill.open_entry(_draft()) == {
        "ok": True,
        "operation_status": "save_completed",
    }
    assert [
        len(fill_adapter.work_page_calls),
        len(fill_adapter.ensure_editor_calls),
        len(fill_adapter.stable_calls),
        len(fill_adapter.fill_calls),
    ] == [1, 0, 0, 1]
    assert picker_controller.hide_calls == []
    assert fill_controller.hide_calls == [(4, 1)]


def test_missing_explicit_save_completed_stage_is_terminalized_as_unknown():
    statuses = []
    coordinator, controller, adapter = _coordinator(nonces=["fill-nonce"])
    coordinator.bind_status_callback(statuses.append)
    adapter.fill_result = {"ok": True, "status": "saved"}

    result = coordinator.open_entry(_draft())

    assert result == {"ok": False, "error": "save_outcome_unknown"}
    assert controller.hide_calls == []
    assert controller.visible is True
    assert statuses[-1]["operation_status"] == "failed"
    assert statuses[-1]["operation_result_owner"] == "automation_fill"
    assert statuses[-1]["error_code"] == "save_outcome_unknown"
    assert all(status.get("operation_status") != "save_completed" for status in statuses)


def test_helper_close_terminalizes_blocked_fill_as_window_closed_and_next_fill_recovers():
    statuses = []
    coordinator, controller, adapter = _coordinator(
        nonces=["fill-1", "fill-2"]
    )
    coordinator.bind_status_callback(statuses.append)
    adapter.block_fill = True
    first_result = {}

    worker = threading.Thread(
        target=lambda: first_result.setdefault("value", coordinator.open_entry(_draft()))
    )
    worker.start()
    assert adapter.fill_started.wait(timeout=1)

    controller.publish(
        session_state="idle", page_phase="none", ready=False,
        navigation_generation=5,
    )
    assert coordinator.get_status()["operation"] == "automation_fill"
    controller.close_helper()
    adapter.fill_result = {"ok": False, "error": "window_closed"}
    adapter.fill_release.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert first_result["value"] == {"ok": False, "error": "window_closed"}
    assert coordinator.get_status()["operation"] == "none"
    assert statuses[-1]["operation_status"] == "operation_canceled"
    assert statuses[-1]["operation_result_owner"] == "automation_fill"
    assert statuses[-1]["error_code"] == "window_closed"

    adapter.block_fill = False
    adapter.fill_started.clear()
    adapter.fill_result = {"ok": True, "status": "saved", "stage": "save_completed"}
    controller.publish(
        session_state="ready", page_phase="work_shell", ready=True,
        navigation_generation=6,
    )
    assert coordinator.open_entry(_draft()) == {
        "ok": True,
        "operation_status": "save_completed",
    }


def test_non_ready_fill_requires_session_without_owning_or_preparing_auth():
    controller = _Controller()
    controller.status.update({
        "session_state": "login_required",
        "page_phase": "login_credentials",
        "ready": False,
        "login_required": True,
    })
    coordinator, _controller, adapter = _coordinator(
        controller=controller,
        nonces=["unused"],
    )

    result = coordinator.open_entry(_draft())

    assert result == {"ok": False, "error": "fd_work_not_ready"}
    assert controller.prepare_calls == []
    assert controller.scheduled == []
    assert adapter.fill_calls == []
    assert coordinator.get_status()["interaction_owner"] == "none"


def test_pending_picker_auth_error_releases_owner_and_emits_terminal_failure():
    results = []
    statuses = []
    controller = _Controller()
    controller.status.update({
        "session_state": "login_required",
        "page_phase": "login_credentials",
        "ready": False,
        "login_required": True,
    })
    coordinator, _controller, adapter = _coordinator(
        controller=controller,
        results=results,
        nonces=["auth-nonce", "next-picker"],
    )
    coordinator.bind_status_callback(statuses.append)

    opening = coordinator.open_case_picker("drawer-auth")
    assert opening["operation_status"] == "authentication_required"
    assert coordinator.get_status()["interaction_owner"] == "user_auth"

    controller.publish(
        session_state="error",
        page_phase="error",
        ready=False,
        login_required=False,
        error_code="page_error",
    )

    assert adapter.enter_picker_calls == []
    assert coordinator.get_status()["interaction_owner"] == "none"
    assert results[-1]["request_id"] == "drawer-auth"
    assert results[-1]["error"] == "page_error"
    assert statuses[-1]["operation_status"] == "failed"
    assert statuses[-1]["operation_result_owner"] == "user_picker"
    assert statuses[-1]["error_code"] == "page_error"


def test_standalone_auth_error_releases_owner_for_next_operation():
    statuses = []
    controller = _Controller()
    controller.status.update({
        "session_state": "login_required",
        "page_phase": "login_credentials",
        "ready": False,
        "login_required": True,
    })
    coordinator, _controller, _adapter = _coordinator(
        controller=controller,
        nonces=["auth-nonce", "picker-nonce"],
    )
    coordinator.bind_status_callback(statuses.append)

    assert coordinator.prepare_session(True)["ok"] is True
    assert coordinator.get_status()["interaction_owner"] == "user_auth"

    controller.publish(
        session_state="error",
        page_phase="error",
        ready=False,
        login_required=False,
        error_code="page_error",
    )

    assert coordinator.get_status()["interaction_owner"] == "none"
    assert statuses[-1]["operation_status"] == "failed"
    assert statuses[-1]["operation_result_owner"] == "user_auth"
    assert statuses[-1]["error_code"] == "page_error"
