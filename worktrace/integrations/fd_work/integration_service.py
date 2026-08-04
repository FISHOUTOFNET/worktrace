"""Application capability for the optional FD Work integration."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import secrets
import threading
import time
from typing import Any, Callable, Mapping, Protocol

from ...services.settings_service import get_bool_setting, set_setting
from .contracts import FDWorkEntryDraft, FDWorkEntryError
from .error_codes import public_fd_work_error
from .binding_service import FDWorkBindingService
from .case_identity import normalize_case_label
from .draft_builder import FDWorkEntryDraftBuilder
from .limits import (
    FD_WORK_ADAPTER_CONTRACT_VERSION,
    FD_WORK_CASE_LABEL_MAX_LENGTH,
    FD_WORK_SELECTION_TOKEN_MAX_LENGTH,
)

FD_WORK_ENABLED_SETTING = "fd_work_enabled"
FD_WORK_SELECTION_TTL_SECONDS = 300.0
FD_WORK_SELECTION_CAPACITY = 128


class _DraftBuilder(Protocol):
    def build(
        self,
        report_date: str,
        projection_instance_key: str,
        expected_projection_revision: str,
    ) -> FDWorkEntryDraft: ...


class _InteractionCoordinator(Protocol):
    def bind_status_callback(self, callback: Callable[[Mapping[str, Any]], None]) -> None: ...
    def bind_picker_result_callback(self, callback: Callable[[Mapping[str, Any]], None]) -> None: ...
    def get_status(self) -> Mapping[str, Any]: ...
    def prepare_session(self, show_login_if_required: bool = True) -> Mapping[str, Any]: ...
    def prepare_window_before_start(
        self,
        show_login_if_required: bool = True,
    ) -> Mapping[str, Any]: ...
    def on_renderer_initialized(self, renderer: str) -> None: ...
    def open_case_picker(self, request_id: str) -> Mapping[str, Any]: ...
    def open_entry(self, draft: FDWorkEntryDraft) -> Mapping[str, Any]: ...
    def enable(self) -> None: ...
    def disable(self) -> None: ...
    def shutdown(self) -> None: ...


@dataclass(frozen=True)
class _Selection:
    label: str
    navigation_generation: int
    request_id: str
    operation_nonce: str
    expires_at: float


class FDWorkIntegrationService:
    """Own plugin settings, session operations, and ephemeral case proofs."""

    def __init__(
        self,
        *,
        draft_builder: _DraftBuilder | None = None,
        binding_service: FDWorkBindingService | None = None,
        interaction_coordinator: _InteractionCoordinator | None = None,
        window_controller: _InteractionCoordinator | None = None,
        enabled_reader: Callable[[], bool] | None = None,
        enabled_writer: Callable[[bool], Any] | None = None,
        supported: bool = True,
        clock: Callable[[], float] | None = None,
        token_factory: Callable[[], str] | None = None,
        selection_ttl_seconds: float = FD_WORK_SELECTION_TTL_SECONDS,
        selection_capacity: int = FD_WORK_SELECTION_CAPACITY,
        status_callback: Callable[[dict[str, object]], None] | None = None,
        picker_result_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._draft_builder = draft_builder or FDWorkEntryDraftBuilder()
        self._binding_service = binding_service
        self._interaction_coordinator = interaction_coordinator or window_controller
        self._enabled_reader = enabled_reader or (
            lambda: get_bool_setting(FD_WORK_ENABLED_SETTING, False)
        )
        self._enabled_writer = enabled_writer or (
            lambda enabled: set_setting(
                FD_WORK_ENABLED_SETTING,
                "true" if enabled else "false",
            )
        )
        self._supported = bool(supported)
        self._clock = clock or time.monotonic
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._selection_ttl_seconds = max(1.0, float(selection_ttl_seconds))
        self._selection_capacity = max(1, int(selection_capacity))
        self._status_callback = status_callback or (lambda _status: None)
        self._picker_result_callback = picker_result_callback or (lambda _result: None)
        self._lock = threading.RLock()
        self._selections: OrderedDict[str, _Selection] = OrderedDict()
        self._controller_status = self._initial_controller_status()
        self._shutdown = False
        self._privacy_authorized = False
        self._active_picker_request_id: str | None = None
        if self._interaction_coordinator is not None:
            self._interaction_coordinator.bind_status_callback(self._accept_controller_status)
            binder = getattr(
                self._interaction_coordinator,
                "bind_picker_result_callback",
                None,
            )
            if callable(binder):
                binder(self._accept_picker_result)

    def bind_status_callback(
        self,
        callback: Callable[[dict[str, object]], None],
    ) -> None:
        with self._lock:
            self._status_callback = callback

    def bind_picker_result_callback(
        self,
        callback: Callable[[dict[str, object]], None],
    ) -> None:
        with self._lock:
            self._picker_result_callback = callback

    def get_settings_status(self) -> dict[str, object]:
        with self._lock:
            return self._status_locked()

    def prepare_session(
        self,
        show_login_if_required: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._enabled_locked():
                return {
                    "ok": False,
                    "error": "fd_work_disabled",
                    "capability_status": self._status_locked(),
                }
            if not self._privacy_authorized:
                return self._privacy_failure_locked()
            controller = self._require_enabled_controller_locked()
            if controller is None:
                return {
                    "ok": False,
                    "error": "fd_work_disabled",
                    "capability_status": self._status_locked(),
                }
        try:
            result = dict(
                controller.prepare_session(
                    show_login_if_required=show_login_if_required
                )
            )
        except Exception:
            result = {"ok": False, "error": "session_start_failed"}
        return self._with_capability_status(result)

    def prepare_window_before_start(
        self,
        show_login_if_required: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._enabled_locked():
                return {
                    "ok": False,
                    "error": "fd_work_disabled",
                    "capability_status": self._status_locked(),
                }
            if not self._privacy_authorized:
                return self._privacy_failure_locked()
            controller = self._require_enabled_controller_locked()
            if controller is None:
                return {
                    "ok": False,
                    "error": "fd_work_disabled",
                    "capability_status": self._status_locked(),
                }
        try:
            result = dict(
                controller.prepare_window_before_start(
                    show_login_if_required=show_login_if_required
                )
            )
        except Exception:
            result = {"ok": False, "error": "session_start_failed"}
        return self._with_capability_status(result)

    def on_renderer_initialized(self, renderer: str) -> None:
        with self._lock:
            if self._shutdown:
                return
            controller = self._interaction_coordinator
        if controller is not None:
            controller.on_renderer_initialized(renderer)

    def open_case_picker(self, request_id: str) -> dict[str, Any]:
        if type(request_id) is not str or not request_id or len(request_id) > 128:
            return self._failure("invalid_input", str(request_id or ""))
        with self._lock:
            if not self._enabled_locked():
                return self._failure_locked("fd_work_disabled", request_id)
            if not self._privacy_authorized:
                return self._failure_locked("deferred_by_privacy", request_id)
            controller = self._require_enabled_controller_locked()
            if controller is None:
                return self._failure_locked("fd_work_disabled", request_id)
        try:
            result = dict(controller.open_case_picker(request_id))
        except Exception:
            result = {"ok": False, "error": "window_unavailable"}
        if result.get("ok") is not True:
            return self._failure(
                public_fd_work_error(result.get("error") or "window_unavailable"),
                request_id,
            )
        with self._lock:
            self._active_picker_request_id = request_id
        result["request_id"] = request_id
        return self._with_capability_status(result)

    def validate_case_selection(
        self,
        selection_token: str | None,
        expected_label: str,
    ) -> str:
        if not isinstance(selection_token, str) or not selection_token:
            raise FDWorkEntryError("case_selection_required")
        if len(selection_token) > FD_WORK_SELECTION_TOKEN_MAX_LENGTH:
            raise FDWorkEntryError("case_selection_expired")
        normalized_expected = normalize_case_label(expected_label)
        with self._lock:
            self._cleanup_selections_locked()
            selection = self._selections.get(selection_token)
            if selection is None:
                raise FDWorkEntryError("case_selection_expired")
            if (
                selection.navigation_generation
                != self._navigation_generation_locked()
            ):
                self._selections.pop(selection_token, None)
                raise FDWorkEntryError("case_selection_expired")
            if selection.label != normalized_expected:
                raise FDWorkEntryError("case_selection_mismatch")
            self._selections.pop(selection_token, None)
            return selection.label

    def discard_case_selection(self, selection_token: str | None) -> None:
        if not isinstance(selection_token, str):
            return
        with self._lock:
            self._cleanup_selections_locked()
            self._selections.pop(selection_token, None)

    def open_entry(
        self,
        report_date: str,
        projection_instance_key: str,
        expected_projection_revision: str,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._enabled_locked():
                raise FDWorkEntryError("fd_work_disabled")
            if not self._privacy_authorized:
                raise FDWorkEntryError("deferred_by_privacy")
            controller = self._require_enabled_controller_locked()
            if controller is None:
                raise FDWorkEntryError("fd_work_disabled")
        draft = self._draft_builder.build(
            report_date,
            projection_instance_key,
            expected_projection_revision,
        )
        with self._lock:
            if controller is not self._require_enabled_controller_locked():
                raise FDWorkEntryError("window_unavailable")
        try:
            result = dict(controller.open_entry(draft))
        except FDWorkEntryError:
            raise
        except Exception:
            result = {"ok": False, "error": "window_unavailable"}
        return self._with_capability_status(result)

    def set_privacy_authorized(self, authorized: bool) -> None:
        if authorized is not True and authorized is not False:
            raise ValueError("invalid_privacy_authorization")
        with self._lock:
            if self._shutdown:
                return
            self._privacy_authorized = authorized
            if not authorized:
                self._selections.clear()
                self._active_picker_request_id = None
            coordinator = self._interaction_coordinator
            status = self._status_locked()
        if coordinator is not None:
            action = getattr(coordinator, "enable" if authorized else "disable", None)
            if callable(action):
                action()
        self._emit_status(status)

    def bind_project(self, project_id: int, project_name: str) -> None:
        service = self._require_binding_service()
        service.bind_project(
            project_id,
            project_name,
            adapter_contract_version=FD_WORK_ADAPTER_CONTRACT_VERSION,
        )

    def clear_project_binding(self, project_id: int) -> None:
        self._require_binding_service().clear_binding(project_id)

    def list_bound_project_ids(self) -> set[int]:
        return self._require_binding_service().list_bound_project_ids()

    def clear_all_bindings(self, *, delete_database: bool = False) -> None:
        self._require_binding_service().clear_all_bindings(
            delete_database=delete_database
        )

    def set_enabled(self, enabled: bool) -> dict[str, object]:
        if enabled is not True and enabled is not False:
            raise ValueError("invalid_fd_work_enabled")
        with self._lock:
            if self._shutdown:
                raise RuntimeError("fd_work_shutdown")
            if enabled and not self._supported:
                raise RuntimeError("fd_work_unsupported")
            self._enabled_writer(enabled)
            persisted = self._enabled_locked()
            if persisted is not enabled:
                raise RuntimeError("fd_work_setting_not_persisted")
            controller = self._interaction_coordinator
            if not enabled:
                self._selections.clear()
                self._active_picker_request_id = None
        if controller is not None and not enabled:
            controller.disable()
        elif controller is not None and self._privacy_authorized:
            try:
                enable_action = getattr(controller, "enable", None)
                if callable(enable_action):
                    enable_action()
                controller.prepare_session(show_login_if_required=True)
            except Exception:
                pass
        status = self.get_settings_status()
        self._emit_status(status)
        return status

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._selections.clear()
            controller = self._interaction_coordinator
        if controller is not None:
            controller.shutdown()
        if self._binding_service is not None:
            self._binding_service.cancel_pending_reconciliation(
                timeout_seconds=0.25
            )
        self._emit_status(self.get_settings_status())

    def _initial_controller_status(self) -> dict[str, object]:
        if self._interaction_coordinator is None:
            return {
                "session_state": "idle",
                "page_phase": "none",
                "operation": "none",
                "interaction_owner": "none",
                "ready": False,
                "login_required": False,
                "error_code": None,
                "navigation_generation": 0,
            }
        return dict(self._interaction_coordinator.get_status())

    def _accept_controller_status(self, status: Mapping[str, Any]) -> None:
        with self._lock:
            previous_generation = self._navigation_generation_locked()
            self._controller_status = dict(status)
            if self._navigation_generation_locked() != previous_generation:
                self._selections.clear()
            public_status = self._status_locked()
        self._emit_status(public_status)

    def _accept_picker_result(self, result: Mapping[str, Any]) -> None:
        request_id = result.get("request_id")
        operation_nonce = result.get("operation_nonce")
        with self._lock:
            if (
                self._shutdown
                or not self._enabled_locked()
                or not self._privacy_authorized
                or type(request_id) is not str
                or request_id != self._active_picker_request_id
                or type(operation_nonce) is not str
                or not operation_nonce
            ):
                return
            self._active_picker_request_id = None
            if result.get("ok") is not True:
                payload = {
                    "ok": False,
                    "request_id": request_id,
                    "error": public_fd_work_error(
                        result.get("error") or "picker_canceled"
                    ),
                }
            else:
                label = result.get("label")
                generation = result.get("navigation_generation")
                canonical = normalize_case_label(label)
                if (
                    type(label) is not str
                    or not canonical
                    or len(canonical) > FD_WORK_CASE_LABEL_MAX_LENGTH
                    or type(generation) is not int
                ):
                    payload = {
                        "ok": False,
                        "request_id": request_id,
                        "error": "fd_work_page_unavailable",
                    }
                else:
                    self._cleanup_selections_locked()
                    token = self._new_unique_token_locked()
                    self._selections[token] = _Selection(
                        label=canonical,
                        navigation_generation=generation,
                        request_id=request_id,
                        operation_nonce=operation_nonce,
                        expires_at=self._clock() + self._selection_ttl_seconds,
                    )
                    while len(self._selections) > self._selection_capacity:
                        self._selections.popitem(last=False)
                    payload = {
                        "ok": True,
                        "request_id": request_id,
                        "selected_label": canonical,
                        "selection_token": token,
                    }
        self._emit_picker_result(payload)

    def _status_locked(self) -> dict[str, object]:
        if self._shutdown:
            return {
                "supported": self._supported,
                "enabled": False,
                "session_state": "shutdown",
                "page_phase": "none",
                "operation": "none",
                "interaction_owner": "none",
                "ready": False,
                "login_required": False,
                "error_code": None,
                "navigation_generation": self._navigation_generation_locked(),
            }
        if not self._enabled_locked():
            return {
                "supported": self._supported,
                "enabled": False,
                "session_state": "disabled",
                "page_phase": "none",
                "operation": "none",
                "interaction_owner": "none",
                "ready": False,
                "login_required": False,
                "error_code": None,
                "navigation_generation": self._navigation_generation_locked(),
            }
        if not self._privacy_authorized:
            return {
                "supported": self._supported,
                "enabled": True,
                "session_state": "deferred_by_privacy",
                "page_phase": "none",
                "operation": "none",
                "interaction_owner": "none",
                "ready": False,
                "login_required": False,
                "error_code": None,
                "navigation_generation": self._navigation_generation_locked(),
            }
        status = self._controller_status
        return {
            "supported": self._supported,
            "enabled": True,
            "session_state": str(status.get("session_state") or "idle"),
            "page_phase": str(status.get("page_phase") or "none"),
            "operation": str(status.get("operation") or "none"),
            "interaction_owner": str(status.get("interaction_owner") or "none"),
            "ready": status.get("ready") is True,
            "login_required": status.get("login_required") is True,
            "error_code": (
                str(status.get("error_code"))
                if status.get("error_code")
                else None
            ),
            "navigation_generation": self._navigation_generation_locked(),
        }

    def _enabled_locked(self) -> bool:
        return bool(self._supported and not self._shutdown and self._enabled_reader())

    def _require_enabled_controller_locked(self) -> _InteractionCoordinator | None:
        if not self._enabled_locked():
            return None
        if self._interaction_coordinator is None:
            raise FDWorkEntryError("window_unavailable")
        return self._interaction_coordinator

    def _navigation_generation_locked(self) -> int:
        value = self._controller_status.get("navigation_generation")
        return int(value) if type(value) is int else 0

    def _cleanup_selections_locked(self) -> None:
        now = self._clock()
        expired = [
            token
            for token, selection in self._selections.items()
            if selection.expires_at <= now
        ]
        for token in expired:
            self._selections.pop(token, None)

    def _new_unique_token_locked(self) -> str:
        for _attempt in range(8):
            token = str(self._token_factory())
            if (
                token
                and len(token) <= FD_WORK_SELECTION_TOKEN_MAX_LENGTH
                and token not in self._selections
            ):
                return token
        raise RuntimeError("fd_work_selection_token_unavailable")

    def _failure(self, error: str, request_id: str) -> dict[str, Any]:
        with self._lock:
            return self._failure_locked(error, request_id)

    def _failure_locked(self, error: str, request_id: str) -> dict[str, Any]:
        return {
            "ok": False,
            "request_id": str(request_id),
            "error": error,
            "capability_status": self._status_locked(),
        }

    def _privacy_failure_locked(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "deferred_by_privacy",
            "capability_status": self._status_locked(),
        }

    def _with_capability_status(self, result: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(result)
        ambiguous_status = payload.pop("status", None)
        if isinstance(ambiguous_status, str):
            payload["operation_status"] = ambiguous_status
        if payload.get("ok") is not True:
            payload["error"] = public_fd_work_error(payload.get("error"))
        payload["capability_status"] = self.get_settings_status()
        return payload

    def _require_binding_service(self) -> FDWorkBindingService:
        if self._binding_service is None:
            raise FDWorkEntryError("binding_store_unavailable")
        return self._binding_service

    def _emit_status(self, status: dict[str, object]) -> None:
        try:
            self._status_callback(status)
        except Exception:
            pass

    def _emit_picker_result(self, result: dict[str, object]) -> None:
        try:
            self._picker_result_callback(result)
        except Exception:
            pass


__all__ = [
    "FDWorkIntegrationService",
    "FD_WORK_CASE_LABEL_MAX_LENGTH",
    "FD_WORK_ENABLED_SETTING",
    "FD_WORK_SELECTION_CAPACITY",
    "FD_WORK_SELECTION_TOKEN_MAX_LENGTH",
    "FD_WORK_SELECTION_TTL_SECONDS",
    "normalize_case_label",
]
