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
from .draft_builder import FDWorkEntryDraftBuilder
from .limits import (
    FD_WORK_CASE_LABEL_MAX_LENGTH,
    FD_WORK_QUERY_MAX_LENGTH,
    FD_WORK_QUERY_MIN_LENGTH,
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


class _WindowController(Protocol):
    def bind_status_callback(self, callback: Callable[[Mapping[str, Any]], None]) -> None: ...
    def get_status(self) -> Mapping[str, Any]: ...
    def prepare_session(self, show_login_if_required: bool = True) -> Mapping[str, Any]: ...
    def search_cases(self, query: str) -> Mapping[str, Any]: ...
    def open_entry(self, draft: FDWorkEntryDraft) -> Mapping[str, Any]: ...
    def disable(self) -> None: ...
    def shutdown(self) -> None: ...


@dataclass(frozen=True)
class _Selection:
    label: str
    navigation_generation: int
    expires_at: float


def normalize_case_label(value: object) -> str:
    text = str(value or "")
    for character in "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000":
        text = text.replace(character, " ")
    return text.strip()


class FDWorkIntegrationService:
    """Own plugin settings, session operations, and ephemeral case proofs."""

    def __init__(
        self,
        *,
        draft_builder: _DraftBuilder | None = None,
        window_controller: _WindowController | None = None,
        enabled_reader: Callable[[], bool] | None = None,
        enabled_writer: Callable[[bool], Any] | None = None,
        supported: bool = True,
        clock: Callable[[], float] | None = None,
        token_factory: Callable[[], str] | None = None,
        selection_ttl_seconds: float = FD_WORK_SELECTION_TTL_SECONDS,
        selection_capacity: int = FD_WORK_SELECTION_CAPACITY,
        status_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._draft_builder = draft_builder or FDWorkEntryDraftBuilder()
        self._window_controller = window_controller
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
        self._lock = threading.RLock()
        self._selections: OrderedDict[str, _Selection] = OrderedDict()
        self._controller_status = self._initial_controller_status()
        self._shutdown = False
        if window_controller is not None:
            window_controller.bind_status_callback(self._accept_controller_status)

    def bind_status_callback(
        self,
        callback: Callable[[dict[str, object]], None],
    ) -> None:
        with self._lock:
            self._status_callback = callback

    def get_settings_status(self) -> dict[str, object]:
        with self._lock:
            return self._status_locked()

    def prepare_session(
        self,
        show_login_if_required: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            controller = self._require_enabled_controller_locked()
            if controller is None:
                return {
                    "ok": False,
                    "error": "fd_work_disabled",
                    "status": self._status_locked(),
                }
        try:
            result = dict(
                controller.prepare_session(
                    show_login_if_required=show_login_if_required
                )
            )
        except Exception:
            result = {"ok": False, "error": "session_start_failed"}
        result["status"] = self.get_settings_status()
        return result

    def search_cases(self, query: str, request_id: str) -> dict[str, Any]:
        if not isinstance(query, str):
            return self._failure("invalid_input", request_id)
        normalized_query = normalize_case_label(query)
        if not (
            FD_WORK_QUERY_MIN_LENGTH
            <= len(normalized_query)
            <= FD_WORK_QUERY_MAX_LENGTH
        ):
            return self._failure("invalid_input", request_id)
        with self._lock:
            controller = self._require_enabled_controller_locked()
            if controller is None:
                return self._failure_locked("fd_work_disabled", request_id)
        try:
            result = dict(controller.search_cases(normalized_query))
        except Exception:
            return self._failure("page_contract_changed", request_id)
        if result.get("ok") is not True:
            return self._failure(
                str(result.get("error") or "page_contract_changed"),
                request_id,
            )
        labels = result.get("labels")
        generation = result.get("navigation_generation")
        if (
            not isinstance(labels, list)
            or len(labels) > 20
            or type(generation) is not int
        ):
            return self._failure("page_contract_changed", request_id)
        normalized_labels: list[str] = []
        for label in labels:
            if not isinstance(label, str):
                return self._failure("page_contract_changed", request_id)
            normalized = normalize_case_label(label)
            if not normalized or len(normalized) > FD_WORK_CASE_LABEL_MAX_LENGTH:
                return self._failure("page_contract_changed", request_id)
            normalized_labels.append(normalized)
        if len(set(normalized_labels)) != len(normalized_labels):
            return self._failure("duplicate_case_label", request_id)

        options: list[dict[str, str]] = []
        with self._lock:
            if self._shutdown or not self._enabled_locked():
                return self._failure_locked("fd_work_disabled", request_id)
            if generation != self._navigation_generation_locked():
                return self._failure_locked("case_selection_expired", request_id)
            self._cleanup_selections_locked()
            for label in normalized_labels:
                token = self._new_unique_token_locked()
                self._selections[token] = _Selection(
                    label=label,
                    navigation_generation=generation,
                    expires_at=self._clock() + self._selection_ttl_seconds,
                )
                options.append({"label": label, "selection_token": token})
            while len(self._selections) > self._selection_capacity:
                self._selections.popitem(last=False)
            return {
                "ok": True,
                "request_id": str(request_id),
                "options": options,
                "status": self._status_locked(),
            }

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
        return dict(controller.open_entry(draft))

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
            controller = self._window_controller
            if not enabled:
                self._selections.clear()
        if controller is not None and not enabled:
            controller.disable()
        elif controller is not None:
            try:
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
            controller = self._window_controller
        if controller is not None:
            controller.shutdown()
        self._emit_status(self.get_settings_status())

    def _initial_controller_status(self) -> dict[str, object]:
        if self._window_controller is None:
            return {
                "session_state": "idle",
                "operation": "none",
                "ready": False,
                "login_required": False,
                "error_code": None,
                "navigation_generation": 0,
            }
        return dict(self._window_controller.get_status())

    def _accept_controller_status(self, status: Mapping[str, Any]) -> None:
        with self._lock:
            previous_generation = self._navigation_generation_locked()
            self._controller_status = dict(status)
            if self._navigation_generation_locked() != previous_generation:
                self._selections.clear()
            public_status = self._status_locked()
        self._emit_status(public_status)

    def _status_locked(self) -> dict[str, object]:
        if self._shutdown:
            return {
                "supported": self._supported,
                "enabled": False,
                "session_state": "shutdown",
                "operation": "none",
                "ready": False,
                "login_required": False,
                "error_code": None,
            }
        if not self._enabled_locked():
            return {
                "supported": self._supported,
                "enabled": False,
                "session_state": "disabled",
                "operation": "none",
                "ready": False,
                "login_required": False,
                "error_code": None,
            }
        status = self._controller_status
        return {
            "supported": self._supported,
            "enabled": True,
            "session_state": str(status.get("session_state") or "idle"),
            "operation": str(status.get("operation") or "none"),
            "ready": status.get("ready") is True,
            "login_required": status.get("login_required") is True,
            "error_code": (
                str(status.get("error_code"))
                if status.get("error_code")
                else None
            ),
        }

    def _enabled_locked(self) -> bool:
        return bool(self._supported and not self._shutdown and self._enabled_reader())

    def _require_enabled_controller_locked(self) -> _WindowController | None:
        if not self._enabled_locked():
            return None
        if self._window_controller is None:
            raise FDWorkEntryError("window_unavailable")
        return self._window_controller

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
            "status": self._status_locked(),
        }

    def _emit_status(self, status: dict[str, object]) -> None:
        try:
            self._status_callback(status)
        except Exception:
            pass


__all__ = [
    "FDWorkIntegrationService",
    "FD_WORK_CASE_LABEL_MAX_LENGTH",
    "FD_WORK_ENABLED_SETTING",
    "FD_WORK_QUERY_MAX_LENGTH",
    "FD_WORK_QUERY_MIN_LENGTH",
    "FD_WORK_SELECTION_CAPACITY",
    "FD_WORK_SELECTION_TOKEN_MAX_LENGTH",
    "FD_WORK_SELECTION_TTL_SECONDS",
    "normalize_case_label",
]
