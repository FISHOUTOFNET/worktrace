"""Public FD Work capability with request-scoped picker cancellation."""

from __future__ import annotations

from typing import Any

from ._integration_service_core import (
    FDWorkIntegrationService as _CoreIntegrationService,
    FD_WORK_CASE_LABEL_MAX_LENGTH,
    FD_WORK_ENABLED_SETTING,
    FD_WORK_SELECTION_CAPACITY,
    FD_WORK_SELECTION_TOKEN_MAX_LENGTH,
    FD_WORK_SELECTION_TTL_SECONDS,
    SelectionClaim,
    normalize_case_label,
)
from .error_codes import public_fd_work_error


class FDWorkIntegrationService\
(_CoreIntegrationService):
    """Expose request-safe picker lifecycle without leaking coordinator nonces."""

    # Keep these use-case methods visible on the public class itself. Architecture
    # contracts intentionally inspect this boundary rather than implementation
    # inheritance details.
    def create_bound_project(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return super().create_bound_project(*args, **kwargs)

    def rebind_project(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return super().rebind_project(*args, **kwargs)

    def list_bound_project_ids(self) -> set[int]:
        return super().list_bound_project_ids()

    def clear_project_identity(self, project_id: int) -> dict[str, Any]:
        return super().clear_project_identity(project_id)

    def open_case_picker(self, request_id: str) -> dict[str, Any]:
        if type(request_id) is not str or not request_id or len(request_id) > 128:
            return self._failure("invalid_input", str(request_id or ""))
        with self._lock:
            if not self._enabled_locked():
                return self._failure_locked("fd_work_disabled", request_id)
            if not self._privacy_authorized:
                return self._failure_locked("deferred_by_privacy", request_id)
            if self._active_picker_request_id is not None:
                return self._failure_locked("fd_work_busy", request_id)
            controller = self._require_enabled_controller_locked()
            if controller is None:
                return self._failure_locked("fd_work_disabled", request_id)
            # Reserve before foregrounding the helper. The coordinator can publish
            # a very fast terminal result before open_case_picker returns; that
            # result must already have an authoritative request owner.
            self._active_picker_request_id = request_id
        try:
            result = dict(controller.open_case_picker(request_id))
        except Exception:
            result = {"ok": False, "error": "window_unavailable"}
        if result.get("ok") is not True:
            with self._lock:
                if self._active_picker_request_id == request_id:
                    self._active_picker_request_id = None
            return self._failure(
                public_fd_work_error(result.get("error") or "window_unavailable"),
                request_id,
            )
        # Do not assign the active id here: a synchronous terminal callback may
        # already have consumed the reservation and issued the selection proof.
        result["request_id"] = request_id
        return self._with_capability_status(result)

    def cancel_case_picker(self, request_id: str) -> dict[str, Any]:
        if type(request_id) is not str or not request_id or len(request_id) > 128:
            return self._failure("invalid_input", str(request_id or ""))
        with self._lock:
            if not self._enabled_locked():
                return self._failure_locked("fd_work_disabled", request_id)
            if not self._privacy_authorized:
                return self._failure_locked("deferred_by_privacy", request_id)
            if request_id != self._active_picker_request_id:
                return self._with_capability_status({"ok": True, "accepted": False})
            coordinator = self._require_enabled_controller_locked()
        action = getattr(coordinator, "cancel_case_picker", None)
        if not callable(action):
            return self._with_capability_status({"ok": False, "error": "window_unavailable"})
        try:
            result = dict(action(request_id))
        except Exception:
            result = {"ok": False, "error": "window_unavailable"}
        if result.get("ok") is not True:
            result["error"] = public_fd_work_error(result.get("error") or "window_unavailable")
        return self._with_capability_status(result)


__all__ = [
    "FDWorkIntegrationService",
    "SelectionClaim",
    "FD_WORK_CASE_LABEL_MAX_LENGTH",
    "FD_WORK_ENABLED_SETTING",
    "FD_WORK_SELECTION_CAPACITY",
    "FD_WORK_SELECTION_TOKEN_MAX_LENGTH",
    "FD_WORK_SELECTION_TTL_SECONDS",
    "normalize_case_label",
]
