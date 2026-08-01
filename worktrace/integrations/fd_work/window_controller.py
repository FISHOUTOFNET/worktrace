"""Narrow lifecycle controller for the single lazy FD Work window."""

from __future__ import annotations

import threading
from typing import Any, Callable, Mapping

from .contracts import FDWorkEntryDraft
from .page_adapter import FDWorkPageAdapter, FDWorkPageType


def _run_now(callback: Callable[[], None]) -> None:
    callback()


def _run_after(delay_seconds: float, callback: Callable[[], None]) -> None:
    timer = threading.Timer(delay_seconds, callback)
    timer.daemon = True
    timer.start()


class FDWorkWindowController:
    """Own one auxiliary remote window without joining main shell visibility."""

    def __init__(
        self,
        webview: Any,
        *,
        page_adapter: FDWorkPageAdapter | None = None,
        schedule: Callable[[Callable[[], None]], None] = _run_now,
        schedule_after: Callable[[float, Callable[[], None]], None] = _run_after,
        status_callback: Callable[[str], None] | None = None,
        login_readiness_attempts: int = 5,
        login_readiness_interval_seconds: float = 0.5,
    ) -> None:
        self._webview = webview
        self._page_adapter = page_adapter or FDWorkPageAdapter()
        self._schedule = schedule
        self._schedule_after = schedule_after
        self._status_callback = status_callback or (lambda _status: None)
        self._login_readiness_attempts = max(1, int(login_readiness_attempts))
        self._login_readiness_interval_seconds = max(
            0.0,
            float(login_readiness_interval_seconds),
        )
        self._lock = threading.RLock()
        self._window: Any | None = None
        self._pending_draft: FDWorkEntryDraft | None = None
        self._shutdown = False
        self._renderer_available = True
        self._navigation_generation = 0

    def open_entry(self, draft: FDWorkEntryDraft) -> Mapping[str, Any]:
        process_existing_page = False
        with self._lock:
            if self._shutdown:
                return {"ok": False, "error": "window_unavailable"}
            if not self._renderer_available:
                return {"ok": False, "error": "renderer_unavailable"}
            self._pending_draft = draft
            window = self._window
            if window is None:
                window = self._webview.create_window(
                    "FD Work",
                    self._page_adapter.login_url,
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
                process_existing_page = True
        self._emit("opening")
        if process_existing_page:
            self._on_loaded(window)
        return {"ok": True, "status": "opening"}

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._navigation_generation += 1
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
            self._navigation_generation += 1
            self._pending_draft = None
            window = self._window
            self._window = None
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

    def mark_renderer_unavailable(self) -> None:
        with self._lock:
            if not self._renderer_available:
                return
            self._renderer_available = False
            self._navigation_generation += 1
            self._pending_draft = None
            window = self._window
            self._window = None
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass
        self._emit("renderer_unavailable")

    def _on_loaded(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            self._navigation_generation += 1
            generation = self._navigation_generation
        self._schedule(
            lambda: self._process_loaded_page(window, generation)
        )

    def _process_loaded_page(self, window: Any, generation: int) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
            draft = self._pending_draft
        try:
            url = window.get_current_url()
        except Exception:
            self._emit_if_current(window, generation, "page_contract_changed")
            return
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
        if not self._page_adapter.navigation_allowed(url):
            self._emit_if_current(window, generation, "navigation_blocked")
            try:
                window.load_url(self._page_adapter.login_url)
            except Exception:
                pass
            return

        page_type = self._page_adapter.detect_page(url)
        if page_type is FDWorkPageType.LOGIN:
            self._check_login_readiness(window, generation, 1)
            return
        if page_type is not FDWorkPageType.WORK_HOUR_LIST or draft is None:
            self._emit_if_current(
                window,
                generation,
                "unauthorized"
                if page_type is FDWorkPageType.UNAUTHORIZED
                else "page_contract_changed"
            )
            return

        self._emit_if_current(window, generation, "matching_case")
        try:
            result = self._page_adapter.fill_entry(window, draft)
        except Exception:
            self._emit_if_current(window, generation, "page_contract_changed")
            return
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
        if result.get("ok"):
            with self._lock:
                if self._pending_draft is draft:
                    self._pending_draft = None
            self._emit_if_current(window, generation, "filled")
        else:
            self._emit_if_current(
                window,
                generation,
                str(result.get("error") or "page_contract_changed"),
            )

    def _check_login_readiness(
        self,
        window: Any,
        generation: int,
        attempt: int,
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return

        def accept_readiness(result: Any) -> None:
            with self._lock:
                if not self._navigation_is_current_locked(window, generation):
                    return
            if isinstance(result, Mapping) and result.get("ready") is True:
                self._emit_if_current(window, generation, "login_required")
                return
            if attempt >= self._login_readiness_attempts:
                self._emit_if_current(
                    window,
                    generation,
                    "login_page_load_failed",
                )
                return
            self._schedule_after(
                self._login_readiness_interval_seconds,
                lambda: self._check_login_readiness(
                    window,
                    generation,
                    attempt + 1,
                ),
            )

        try:
            self._page_adapter.check_login_page_ready(window, accept_readiness)
        except Exception:
            accept_readiness({"ready": False})

    def _on_closing(self, window: Any) -> bool:
        with self._lock:
            if self._shutdown:
                return True
            if self._window is not window:
                return True
            self._navigation_generation += 1
            close_generation = self._navigation_generation

        def hide_after_state_check() -> None:
            with self._lock:
                if (
                    self._shutdown
                    or self._window is not window
                    or self._navigation_generation != close_generation
                ):
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
                self._navigation_generation += 1
                self._window = None

    def _navigation_is_current_locked(
        self,
        window: Any,
        generation: int,
    ) -> bool:
        return bool(
            not self._shutdown
            and self._renderer_available
            and self._window is window
            and self._navigation_generation == generation
        )

    def _emit_if_current(
        self,
        window: Any,
        generation: int,
        status: str,
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
        self._emit(status)

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
