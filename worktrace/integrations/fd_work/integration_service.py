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
    """Expose cancellation without leaking coordinator nonces to the main UI."""

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
