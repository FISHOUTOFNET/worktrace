"""Public FD Work interaction coordinator with request-scoped picker cancellation."""

from __future__ import annotations

from typing import Any

from ._interaction_coordinator_core import FDWorkInteractionCoordinator as _CoreCoordinator


class FDWorkInteractionCoordinator(_CoreCoordinator):
    """Add an idempotent main-window cancellation boundary to the core coordinator."""

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


__all__ = ["FDWorkInteractionCoordinator"]
