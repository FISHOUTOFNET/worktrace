"""Public FD Work interaction coordinator with request-scoped picker cancellation."""

from __future__ import annotations

from typing import Any

from . import _interaction_coordinator_core as _core_module
from ._interaction_coordinator_core import FDWorkInteractionCoordinator as _CoreCoordinator

# Preserve the public module's historical monkeypatch seam. Both names point to
# the same stdlib module object, so patching interaction_coordinator.time.time
# also affects the unchanged core implementation.
time = _core_module.time


class FDWorkInteractionCoordinator(_CoreCoordinator):
    """Add recoverable picker lifecycle boundaries to the core coordinator."""

    def cancel_case_picker(self, request_id: str) -> dict[str, Any]:
        if type(request_id) is not str or not request_id or len(request_id) > 128:
            return {"ok": False, "error": "invalid_input"}
        with self._lock:
            if self._shutdown or self._disabled:
                return {"ok": False, "error": "fd_work_disabled"}
            current_request = self._active_request_id or self._pending_picker_request_id
            if (
                current_request != request_id
                or self._interaction_owner not in {"user_auth", "user_picker"}
            ):
                return {"ok": True, "accepted": False}
            if self._pending_picker_command is not None:
                return {"ok": True, "accepted": False}
            generation = self._operation_generation

        def complete() -> None:
            with self._lock:
                current = self._active_request_id or self._pending_picker_request_id
                if (
                    current != request_id
                    or self._operation_generation != generation
                    or self._interaction_owner not in {"user_auth", "user_picker"}
                ):
                    return
            self._cancel_current_picker("picker_canceled", restore_main=True)

        if not self._controller.schedule_callback(complete):
            return {"ok": False, "error": "executor_rejected"}
        return {"ok": True, "accepted": True}

    def _reset_picker_preflight(
        self,
        window: Any,
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        reset = getattr(self._page_adapter, "reset_case_picker", None)
        if not callable(reset):
            # Keep third-party/test adapters compatible; shipping FDWorkPageAdapter
            # owns this boundary.
            return {"ok": True}
        last: dict[str, Any] = {"ok": False, "error": "javascript_exception"}
        for _attempt in range(2):
            try:
                last = dict(reset(window, contract))
            except Exception:
                last = {"ok": False, "error": "javascript_exception"}
            if last.get("ok") is True:
                return last
        return last

    def _activate_picker(self) -> dict[str, Any]:
        with self._lock:
            if self._interaction_owner != "user_picker" or not self._operation_nonce:
                return {"ok": False, "error": "picker_superseded"}
            nonce = self._operation_nonce
            request_id = self._active_request_id
            operation_generation = self._operation_generation
        context = dict(
            self._controller.foreground(
                "user_picker",
                operation_generation,
                lambda: self._operation_is_current(
                    "user_picker", nonce, operation_generation
                ),
            )
        )
        if context.get("ok") is not True:
            self._cancel_current_picker(
                str(context.get("error") or "window_unavailable"),
                restore_main=False,
            )
            return context
        window = context.get("window")
        navigation_generation = context.get("navigation_generation")
        if window is None or type(navigation_generation) is not int:
            self._cancel_current_picker("window_unavailable", restore_main=False)
            return {"ok": False, "error": "window_unavailable"}
        with self._lock:
            if not self._operation_is_current_locked(
                "user_picker", nonce, operation_generation
            ) or self._navigation_generation_locked() != navigation_generation:
                current = False
            else:
                current = True
        if not current:
            self._cancel_current_picker("picker_superseded", restore_main=False)
            return {"ok": False, "error": "picker_superseded"}
        with self._lock:
            self._current_window = window
            self._operation_navigation_generation = navigation_generation
            contract = self._operation_contract_locked(self._picker_timeout_seconds)
        try:
            # The helper window is intentionally reused. Always clean WorkTrace's
            # previous picker/fill artifacts before asking whether the existing
            # FD Work editor is interactive; otherwise a stale disabled input can
            # poison every later "更换案件" attempt until timeout.
            reset = self._reset_picker_preflight(window, contract)
            if reset.get("ok") is not True:
                self._cancel_current_picker(
                    str(reset.get("error") or "fd_work_page_unavailable"),
                    restore_main=True,
                )
                return reset
            page_ready = dict(
                self._page_adapter.await_stable_work_page(window, contract)
            )
            if page_ready.get("ok") is not True:
                self._cancel_current_picker(
                    str(page_ready.get("error") or "work_page_not_ready"),
                    restore_main=True,
                )
                return page_ready
            editor = dict(self._page_adapter.ensure_entry_editor(window, contract))
            if editor.get("ok") is not True:
                self._cancel_current_picker(
                    str(editor.get("error") or "entry_editor_not_rendered"),
                    restore_main=True,
                )
                return editor
            stable = dict(
                self._page_adapter.await_stable_entry_editor(window, contract)
            )
            if stable.get("ok") is not True:
                self._cancel_current_picker(
                    str(stable.get("error") or "entry_editor_not_rendered"),
                    restore_main=True,
                )
                return stable
            if not self._operation_is_current(
                "user_picker", nonce, operation_generation
            ):
                return {"ok": False, "error": "picker_superseded"}
            entered = dict(self._page_adapter.enter_case_picker(window, contract))
        except Exception:
            entered = {"ok": False, "error": "javascript_exception"}
        if entered.get("ok") is not True:
            self._cancel_current_picker(
                str(entered.get("error") or "dom_contract_changed"),
                restore_main=True,
            )
            return entered
        with self._lock:
            if not self._operation_is_current_locked(
                "user_picker", nonce, operation_generation
            ):
                return {"ok": False, "error": "picker_superseded"}
        return {
            "ok": True,
            "request_id": request_id,
            "operation_nonce": nonce,
            "operation_status": "picker_ready",
        }


__all__ = ["FDWorkInteractionCoordinator"]
