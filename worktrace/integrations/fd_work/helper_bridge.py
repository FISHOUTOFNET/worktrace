"""Minimal pywebview bridge exposed only to the FD Work helper window."""

from __future__ import annotations

import threading
from typing import Any, Protocol

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


class FDWorkHelperBridge:
    """Accept only picker completion/cancel; expose no application capability."""

    def __init__(self, coordinator: _Coordinator | None = None) -> None:
        self._lock = threading.Lock()
        self._coordinator = coordinator

    def bind_coordinator(self, coordinator: _Coordinator | None) -> None:
        with self._lock:
            self._coordinator = coordinator

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
