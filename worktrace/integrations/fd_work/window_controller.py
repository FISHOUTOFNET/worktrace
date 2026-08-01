"""Narrow lifecycle controller for the single lazy FD Work window."""

from __future__ import annotations

import threading
from typing import Any, Callable, Mapping

from .contracts import FDWorkEntryDraft
from .page_adapter import FDWorkPageAdapter, FDWorkPageType


def _run_now(callback: Callable[[], None]) -> None:
    callback()


class FDWorkWindowController:
    """Own one auxiliary remote window without joining main shell visibility."""

    def __init__(
        self,
        webview: Any,
        *,
        page_adapter: FDWorkPageAdapter | None = None,
        schedule: Callable[[Callable[[], None]], None] = _run_now,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._webview = webview
        self._page_adapter = page_adapter or FDWorkPageAdapter()
        self._schedule = schedule
        self._status_callback = status_callback or (lambda _status: None)
        self._lock = threading.RLock()
        self._window: Any | None = None
        self._pending_draft: FDWorkEntryDraft | None = None
        self._shutdown = False

    def open_entry(self, draft: FDWorkEntryDraft) -> Mapping[str, Any]:
        with self._lock:
            if self._shutdown:
                return {"ok": False, "error": "window_unavailable"}
            self._pending_draft = draft
            window = self._window
            if window is None:
                window = self._webview.create_window(
                    "FD Work",
                    self._page_adapter.business_url,
                    width=980,
                    height=760,
                    resizable=True,
                    js_api=None,
                )
                self._window = window
                window.events.loaded += lambda *_args, _window=window: self._on_loaded(_window)
                window.events.closing += lambda *_args, _window=window: self._on_closing(_window)
                window.events.closed += lambda *_args, _window=window: self._on_closed(_window)
            else:
                self._restore_window(window)
        self._emit("opening")
        return {"ok": True, "status": "opening"}

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._pending_draft = None
            window = self._window
            self._window = None
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

    def disable(self) -> None:
        with self._lock:
            self._pending_draft = None
            window = self._window
            self._window = None
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

    def _on_loaded(self, window: Any) -> None:
        self._schedule(lambda: self._process_loaded_page(window))

    def _process_loaded_page(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            draft = self._pending_draft
        try:
            url = window.get_current_url()
        except Exception:
            self._emit("page_contract_changed")
            return
        if not self._page_adapter.navigation_allowed(url):
            self._emit("navigation_blocked")
            try:
                window.load_url(self._page_adapter.business_url)
            except Exception:
                pass
            return

        page_type = self._page_adapter.detect_page(url)
        if page_type is FDWorkPageType.LOGIN:
            self._emit("login_required")
            return
        if page_type is not FDWorkPageType.WORK_HOUR_LIST or draft is None:
            self._emit(
                "unauthorized"
                if page_type is FDWorkPageType.UNAUTHORIZED
                else "page_contract_changed"
            )
            return

        self._emit("matching_case")
        try:
            result = self._page_adapter.fill_entry(window, draft)
        except Exception:
            self._emit("page_contract_changed")
            return
        if result.get("ok"):
            with self._lock:
                if self._pending_draft is draft:
                    self._pending_draft = None
            self._emit("filled")
        else:
            self._emit(str(result.get("error") or "page_contract_changed"))

    def _on_closing(self, window: Any) -> bool:
        with self._lock:
            if self._shutdown:
                return True
            if self._window is not window:
                return True

        def hide_after_state_check() -> None:
            with self._lock:
                if self._shutdown or self._window is not window:
                    return
            try:
                window.hide()
            except Exception:
                pass

        self._schedule(hide_after_state_check)
        return False

    def _on_closed(self, window: Any) -> None:
        with self._lock:
            if not self._shutdown and self._window is window:
                self._window = None

    @staticmethod
    def _restore_window(window: Any) -> None:
        for action in ("show", "restore", "focus"):
            callback = getattr(window, action, None)
            if callable(callback):
                try:
                    callback()
                except Exception:
                    pass

    def _emit(self, status: str) -> None:
        try:
            self._status_callback(status)
        except Exception:
            pass


__all__ = ["FDWorkWindowController"]
