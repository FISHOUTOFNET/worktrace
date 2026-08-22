"""Late-bound FD Work interaction boundary for renderer-free startup."""

from __future__ import annotations

import threading
from typing import Any, Callable, Mapping, Protocol

from .contracts import FDWorkEntryDraft


class FDWorkInteraction(Protocol):
    def bind_status_callback(
        self,
        callback: Callable[[Mapping[str, Any]], None],
    ) -> None: ...

    def bind_picker_result_callback(
        self,
        callback: Callable[[Mapping[str, Any]], None],
    ) -> None: ...

    def get_status(self) -> Mapping[str, Any]: ...

    def prepare_session(
        self,
        show_login_if_required: bool = True,
    ) -> Mapping[str, Any]: ...

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


_WINDOW_UNAVAILABLE = {"ok": False, "error": "window_unavailable"}


class DeferredFDWorkInteractionCoordinator:
    """Keep one service dependency while deferring all WebView ownership."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._delegate: FDWorkInteraction | None = None
        self._status_callback: Callable[[Mapping[str, Any]], None] = lambda _status: None
        self._picker_result_callback: Callable[[Mapping[str, Any]], None] = (
            lambda _result: None
        )
        self._enabled = True
        self._shutdown = False

    def bind(self, coordinator: FDWorkInteraction) -> bool:
        if coordinator is None:
            raise TypeError("coordinator is required")
        with self._lock:
            if self._shutdown:
                raise RuntimeError("deferred_interaction_shutdown")
            if self._delegate is coordinator:
                return False
            if self._delegate is not None:
                raise RuntimeError("deferred_interaction_already_bound")
            coordinator.bind_status_callback(self._status_callback)
            coordinator.bind_picker_result_callback(self._picker_result_callback)
            if self._enabled:
                coordinator.enable()
            else:
                coordinator.disable()
            self._delegate = coordinator
        return True

    def bind_status_callback(
        self,
        callback: Callable[[Mapping[str, Any]], None],
    ) -> None:
        if not callable(callback):
            raise TypeError("status callback must be callable")
        with self._lock:
            self._status_callback = callback
            delegate = self._delegate
        if delegate is not None:
            delegate.bind_status_callback(callback)

    def bind_picker_result_callback(
        self,
        callback: Callable[[Mapping[str, Any]], None],
    ) -> None:
        if not callable(callback):
            raise TypeError("picker result callback must be callable")
        with self._lock:
            self._picker_result_callback = callback
            delegate = self._delegate
        if delegate is not None:
            delegate.bind_picker_result_callback(callback)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            if self._shutdown:
                return self._unavailable_status(session_state="shutdown")
            delegate = self._delegate
            enabled = self._enabled
        if delegate is not None:
            return dict(delegate.get_status())
        return self._unavailable_status(
            session_state="idle" if enabled else "disabled",
        )

    def prepare_session(
        self,
        show_login_if_required: bool = True,
    ) -> dict[str, Any]:
        delegate = self._available_delegate()
        if delegate is None:
            return dict(_WINDOW_UNAVAILABLE)
        return dict(delegate.prepare_session(show_login_if_required))

    def prepare_window_before_start(
        self,
        show_login_if_required: bool = True,
    ) -> dict[str, Any]:
        delegate = self._available_delegate()
        if delegate is None:
            return dict(_WINDOW_UNAVAILABLE)
        return dict(delegate.prepare_window_before_start(show_login_if_required))

    def on_renderer_initialized(self, renderer: str) -> None:
        delegate = self._available_delegate()
        if delegate is not None:
            delegate.on_renderer_initialized(renderer)

    def open_case_picker(self, request_id: str) -> dict[str, Any]:
        delegate = self._available_delegate()
        if delegate is None:
            return dict(_WINDOW_UNAVAILABLE)
        return dict(delegate.open_case_picker(request_id))

    def cancel_case_picker(self, request_id: str) -> dict[str, Any]:
        delegate = self._available_delegate()
        if delegate is None:
            return dict(_WINDOW_UNAVAILABLE)
        action = getattr(delegate, "cancel_case_picker", None)
        if not callable(action):
            return dict(_WINDOW_UNAVAILABLE)
        return dict(action(request_id))

    def open_entry(self, draft: FDWorkEntryDraft) -> dict[str, Any]:
        delegate = self._available_delegate()
        if delegate is None:
            return dict(_WINDOW_UNAVAILABLE)
        return dict(delegate.open_entry(draft))

    def enable(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._enabled = True
            delegate = self._delegate
        if delegate is not None:
            delegate.enable()

    def disable(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._enabled = False
            delegate = self._delegate
        if delegate is not None:
            delegate.disable()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            delegate = self._delegate
        if delegate is not None:
            delegate.shutdown()

    def _available_delegate(self) -> FDWorkInteraction | None:
        with self._lock:
            if self._shutdown or not self._enabled:
                return None
            return self._delegate

    @staticmethod
    def _unavailable_status(*, session_state: str) -> dict[str, Any]:
        return {
            "session_state": session_state,
            "page_phase": "none",
            "operation": "none",
            "interaction_owner": "none",
            "ready": False,
            "login_required": False,
            "error_code": "window_unavailable",
            "navigation_generation": 0,
        }


__all__ = ["DeferredFDWorkInteractionCoordinator", "FDWorkInteraction"]
