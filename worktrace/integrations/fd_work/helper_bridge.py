"""Minimal pywebview bridge exposed only to the FD Work helper window."""

from __future__ import annotations

import threading
from typing import Any, Mapping, Protocol

from .case_identity import normalize_case_label
from .limits import FD_WORK_CASE_LABEL_MAX_LENGTH, FD_WORK_SELECTION_TOKEN_MAX_LENGTH


class _Coordinator(Protocol):
    def submit_case_picker_confirmation(
        self,
        operation_nonce: str,
        selected_label: str,
        selection_revision: int,
    ) -> dict[str, Any]: ...
    def submit_case_picker_cancellation(
        self,
        operation_nonce: str,
    ) -> dict[str, Any]: ...


class _ActionResultSink(Protocol):
    def submit_adapter_action_result(
        self,
        action_nonce: str,
        action: str,
        result: Mapping[str, Any],
    ) -> bool: ...


_ADAPTER_ACTIONS = frozenset(
    {
        "awaitStableWorkPage",
        "ensureEntryEditor",
        "awaitStableEntryEditor",
        "awaitStableWorkShell",
        "enterCasePicker",
        "leaveCasePicker",
        "readSelectedCase",
        "fillEntry",
    }
)
_ADAPTER_RESULT_KEYS = frozenset(
    {
        "ok",
        "error",
        "status",
        "label",
        "document_visibility",
        "viewport_available",
        "input_exists",
        "input_interactive",
        "editor_exists",
        "stage",
        "internal_error_kind",
        "create_action_count",
        "create_click_count",
        "commit_method",
        "option_connected_before_action",
        "option_connected_after_action",
        "popup_replaced",
        "live_option_reacquired",
        "option_count",
        "date_step_count",
        "commit_attempt_count",
    }
)


class FDWorkHelperBridge:
    """Validate helper callbacks and signal their narrow in-process owners."""

    def __init__(
        self,
        coordinator: _Coordinator | None = None,
        *,
        action_result_sink: _ActionResultSink | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._coordinator = coordinator
        self._action_result_sink = action_result_sink

    def bind_coordinator(self, coordinator: _Coordinator | None) -> None:
        with self._lock:
            self._coordinator = coordinator

    def submit_adapter_action_result(
        self,
        action_nonce: object,
        action: object,
        result: object,
    ) -> dict[str, Any]:
        normalized = self._validated_adapter_result(action_nonce, action, result)
        if normalized is None:
            return {"ok": False, "error": "invalid_adapter_callback"}
        with self._lock:
            sink = self._action_result_sink
        if sink is None:
            return {"ok": True, "accepted": False}
        try:
            accepted = sink.submit_adapter_action_result(
                action_nonce,
                action,
                normalized,
            )
        except Exception:
            accepted = False
        return {"ok": True, "accepted": accepted is True}

    @staticmethod
    def _validated_adapter_result(
        action_nonce: object,
        action: object,
        result: object,
    ) -> dict[str, Any] | None:
        if (
            type(action_nonce) is not str
            or not action_nonce
            or len(action_nonce) > FD_WORK_SELECTION_TOKEN_MAX_LENGTH
            or type(action) is not str
            or action not in _ADAPTER_ACTIONS
            or not isinstance(result, Mapping)
            or set(result) - _ADAPTER_RESULT_KEYS
            or type(result.get("ok")) is not bool
        ):
            return None
        normalized = {"ok": result["ok"]}
        error = result.get("error")
        if error is not None:
            if type(error) is not str or len(error) > 64:
                return None
            normalized["error"] = error
        status = result.get("status")
        if status is not None:
            if type(status) is not str or len(status) > 64:
                return None
            normalized["status"] = status
        label = result.get("label")
        if label is not None:
            if type(label) is not str:
                return None
            canonical = normalize_case_label(label)
            if not canonical or len(canonical) > FD_WORK_CASE_LABEL_MAX_LENGTH:
                return None
            normalized["label"] = canonical
        visibility = result.get("document_visibility")
        if visibility is not None:
            if type(visibility) is not str or len(visibility) > 16:
                return None
            normalized["document_visibility"] = visibility
        for key in (
            "viewport_available", "input_exists", "input_interactive",
            "option_connected_before_action", "option_connected_after_action",
            "popup_replaced", "live_option_reacquired",
        ):
            value = result.get(key)
            if value is not None:
                if type(value) is not bool:
                    return None
                normalized[key] = value
        editor_exists = result.get("editor_exists")
        if editor_exists is not None:
            if type(editor_exists) is not bool:
                return None
            normalized["editor_exists"] = editor_exists
        for key in ("stage", "internal_error_kind"):
            value = result.get(key)
            if value is not None:
                if type(value) is not str or len(value) > 64:
                    return None
                normalized[key] = value
        commit_method = result.get("commit_method")
        if commit_method is not None:
            if commit_method not in {"none", "semantic_click", "semantic_click_event"}:
                return None
            normalized["commit_method"] = commit_method
        for key in (
            "create_action_count", "create_click_count", "option_count",
            "date_step_count", "commit_attempt_count",
        ):
            value = result.get(key)
            if value is not None:
                if type(value) is not int or value < 0 or value > 10_000:
                    return None
                normalized[key] = value
        return normalized

    def submit_case_picker_confirmation(
        self,
        operation_nonce: object,
        selected_label: object,
        selection_revision: object,
    ) -> dict[str, Any]:
        if (
            type(operation_nonce) is not str
            or not operation_nonce
            or len(operation_nonce) > FD_WORK_SELECTION_TOKEN_MAX_LENGTH
            or type(selected_label) is not str
            or type(selection_revision) is not int
            or selection_revision <= 0
            or selection_revision > 1_000_000
        ):
            return {"ok": False, "error": "invalid_picker_callback"}
        canonical = normalize_case_label(selected_label)
        if not canonical or len(canonical) > FD_WORK_CASE_LABEL_MAX_LENGTH:
            return {"ok": False, "error": "invalid_picker_callback"}
        with self._lock:
            coordinator = self._coordinator
        if coordinator is None:
            return {"ok": False, "error": "picker_superseded"}
        return dict(
            coordinator.submit_case_picker_confirmation(
                operation_nonce,
                canonical,
                selection_revision,
            )
        )

    def submit_case_picker_cancellation(
        self,
        operation_nonce: object,
    ) -> dict[str, Any]:
        if (
            type(operation_nonce) is not str
            or not operation_nonce
            or len(operation_nonce) > FD_WORK_SELECTION_TOKEN_MAX_LENGTH
        ):
            return {"ok": False, "error": "invalid_picker_callback"}
        with self._lock:
            coordinator = self._coordinator
        if coordinator is None:
            return {"ok": False, "error": "picker_superseded"}
        return dict(coordinator.submit_case_picker_cancellation(operation_nonce))


__all__ = ["FDWorkHelperBridge"]
