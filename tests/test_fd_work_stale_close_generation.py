from __future__ import annotations

from typing import Any, Callable, Mapping

from worktrace.integrations.fd_work.interaction_coordinator import (
    FDWorkInteractionCoordinator,
)


class _Controller:
    def __init__(self) -> None:
        self.status = {
            "ready": True,
            "navigation_generation": 2,
            "session_state": "ready",
            "page_phase": "work_shell",
        }
        self.status_callback: Callable[[Mapping[str, Any]], None] | None = None
        self.close_callback: Callable[[int], None] | None = None
        self.window = object()

    def bind_status_callback(self, callback):
        self.status_callback = callback

    def bind_close_callback(self, callback):
        self.close_callback = callback

    def schedule_callback(self, callback):
        callback()
        return True

    def get_status(self):
        return dict(self.status)

    def prepare_session(self, show_login_if_required=True):
        return {"ok": True}

    def prepare_window_before_start(self, show_login_if_required=False):
        return {"ok": True}

    def on_renderer_initialized(self, renderer):
        return None

    def foreground(self, owner, operation_generation, guard):
        assert guard()
        return {
            "ok": True,
            "window": self.window,
            "navigation_generation": self.status["navigation_generation"],
        }

    def hide_and_restore_main(
        self,
        navigation_generation,
        operation_generation,
        guard,
    ):
        return None

    def disable(self):
        return None

    def shutdown(self):
        return None


class _PageAdapter:
    def await_stable_work_page(self, window, contract):
        return {"ok": True}

    def ensure_entry_editor(self, window, contract):
        return {"ok": True}

    def await_stable_entry_editor(self, window, contract):
        return {"ok": True}

    def enter_case_picker(self, window, contract):
        return {"ok": True, "status": "picker_ready"}

    def leave_case_picker(self, window, contract):
        return {"ok": True}


def test_stale_helper_close_callback_cannot_cancel_new_generation_picker():
    controller = _Controller()
    coordinator = FDWorkInteractionCoordinator(
        window_controller=controller,
        page_adapter=_PageAdapter(),
        nonce_factory=lambda: "nonce",
    )

    opened = coordinator.open_case_picker("request-new-generation")
    assert opened["ok"] is True
    before = coordinator.get_status()
    assert before["interaction_owner"] == "user_picker"
    assert before["navigation_generation"] == 2
    operation_generation = before["operation_generation"]

    assert controller.close_callback is not None
    controller.close_callback(1)

    after_stale = coordinator.get_status()
    assert after_stale["interaction_owner"] == "user_picker"
    assert after_stale["operation_generation"] == operation_generation
    assert after_stale["operation_nonce"] == "nonce"

    controller.close_callback(2)

    after_current = coordinator.get_status()
    assert after_current["interaction_owner"] == "none"
    assert after_current["operation_generation"] > operation_generation
