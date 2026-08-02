"""Lifecycle and serialized DOM-operation owner for one FD Work window."""

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
    """Own one persistent helper window and serialize its remote form access."""

    def __init__(
        self,
        webview: Any,
        *,
        page_adapter: FDWorkPageAdapter | None = None,
        schedule: Callable[[Callable[[], None]], None] = _run_now,
        schedule_after: Callable[[float, Callable[[], None]], None] = _run_after,
        status_callback: Callable[[Mapping[str, Any]], None] | None = None,
        login_readiness_attempts: int = 5,
        login_readiness_interval_seconds: float = 0.5,
        login_readiness_timeout_seconds: float = 3.0,
        operation_timeout_seconds: float = 20.0,
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
        self._login_readiness_timeout_seconds = max(
            0.1,
            float(login_readiness_timeout_seconds),
        )
        self._operation_timeout_seconds = max(1.0, float(operation_timeout_seconds))
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._window: Any | None = None
        self._creating_window = False
        self._pending_draft: FDWorkEntryDraft | None = None
        self._review_visible = False
        self._shutdown = False
        self._renderer_available = True
        self._navigation_generation = 0
        self._operation_generation = 0
        self._session_state = "idle"
        self._operation = "none"
        self._error_code: str | None = None
        self._show_login_if_required = True
        self._session_reload_used = False

    def bind_status_callback(
        self,
        callback: Callable[[Mapping[str, Any]], None],
    ) -> None:
        with self._lock:
            self._status_callback = callback

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def prepare_session(
        self,
        show_login_if_required: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if self._shutdown:
                return self._failure_locked("window_unavailable")
            if not self._renderer_available:
                return self._failure_locked("renderer_unavailable")
            self._show_login_if_required = bool(show_login_if_required)
            window = self._window
            generation = self._navigation_generation
            show_existing = bool(
                window is not None
                and self._session_state == "login_required"
                and show_login_if_required
            )
            process_existing = bool(
                window is not None and self._session_state in {"idle", "error"}
            )
            if window is None and not self._creating_window:
                self._creating_window = True
                self._session_reload_used = False
                self._session_state = "starting"
                self._operation = "none"
                self._error_code = None
                create = True
            else:
                create = False
            status = self._status_locked()
        self._emit(status)

        if create:
            return self._create_window()
        if show_existing and window is not None:
            self._show_window_if_current(window, generation, focus=True)
        elif process_existing and window is not None:
            self._on_loaded(window)
        return {"ok": True, "status": self.get_status()}

    def search_cases(self, query: str) -> Mapping[str, Any]:
        with self._lock:
            window = self._window
            if self._shutdown or window is None:
                return self._failure_locked("window_unavailable")
            if not self._renderer_available:
                return self._failure_locked("renderer_unavailable")
            if self._session_state == "login_required":
                return self._failure_locked("login_required")
            if self._session_state != "ready":
                return self._failure_locked("fd_work_not_ready")
            if (
                self._review_visible
                or self._pending_draft is not None
                or self._operation != "none"
            ):
                return self._failure_locked("fd_work_busy")
            self._operation_generation += 1
            operation_generation = self._operation_generation
            navigation_generation = self._navigation_generation
            self._operation = "searching"
            self._error_code = None
            status = self._status_locked()
        self._emit(status)

        acquired = self._operation_lock.acquire(
            timeout=self._operation_timeout_seconds
        )
        if not acquired:
            return self._finish_search_failure(
                window,
                navigation_generation,
                operation_generation,
                "case_search_timeout",
            )
        try:
            try:
                result = dict(self._page_adapter.search_cases(window, query))
            except Exception:
                result = {"ok": False, "error": "page_contract_changed"}
        finally:
            self._operation_lock.release()

        with self._lock:
            if not self._operation_is_current_locked(
                window,
                navigation_generation,
                operation_generation,
                "searching",
            ):
                stale = True
            else:
                stale = False
                self._operation = "none"
                if result.get("ok") is True:
                    self._error_code = None
                else:
                    self._error_code = str(
                        result.get("error") or "page_contract_changed"
                    )
                status = self._status_locked()
        if stale:
            return {"ok": False, "error": "fd_work_busy"}
        self._emit(status)
        result["navigation_generation"] = navigation_generation
        return result

    def open_entry(self, draft: FDWorkEntryDraft) -> Mapping[str, Any]:
        with self._lock:
            if self._shutdown:
                return self._failure_locked("window_unavailable")
            if not self._renderer_available:
                return self._failure_locked("renderer_unavailable")
            self._pending_draft = draft
            self._review_visible = False
            self._operation_generation += 1
            window = self._window
            generation = self._navigation_generation
            login_required = self._session_state == "login_required"
            status = self._status_locked()
        self._emit(status)
        if window is None:
            prepared = self.prepare_session(show_login_if_required=True)
            if prepared.get("ok") is not True:
                return prepared
        elif login_required:
            self._show_window_if_current(window, generation, focus=True)
        else:
            self._schedule(lambda: self._process_current_page(window))
        return {"ok": True, "status": "opening"}

    def disable(self) -> None:
        with self._lock:
            self._navigation_generation += 1
            self._operation_generation += 1
            self._pending_draft = None
            self._review_visible = False
            self._creating_window = False
            self._session_reload_used = False
            self._session_state = "idle"
            self._operation = "none"
            self._error_code = None
            window = self._window
            self._window = None
            status = self._status_locked()
        self._destroy_window(window)
        self._emit(status)

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._navigation_generation += 1
            self._operation_generation += 1
            self._pending_draft = None
            self._review_visible = False
            self._creating_window = False
            self._session_reload_used = False
            self._session_state = "shutdown"
            self._operation = "none"
            self._error_code = None
            window = self._window
            self._window = None
            status = self._status_locked()
        self._destroy_window(window)
        self._emit(status)

    def mark_renderer_unavailable(self) -> None:
        with self._lock:
            if not self._renderer_available:
                return
            self._renderer_available = False
            self._navigation_generation += 1
            self._operation_generation += 1
            self._pending_draft = None
            self._review_visible = False
            self._creating_window = False
            self._session_reload_used = False
            self._session_state = "error"
            self._operation = "none"
            self._error_code = "renderer_unavailable"
            window = self._window
            self._window = None
            status = self._status_locked()
        self._destroy_window(window)
        self._emit(status)

    def _create_window(self) -> dict[str, Any]:
        window = None
        try:
            window = self._webview.create_window(
                "FD Work",
                self._page_adapter.business_url,
                width=980,
                height=760,
                resizable=True,
                js_api=None,
                hidden=True,
                focus=False,
            )
            window.events.loaded += (
                lambda *_args, _window=window: self._on_loaded(_window)
            )
            window.events.closing += (
                lambda *_args, _window=window: self._on_closing(_window)
            )
            window.events.closed += (
                lambda *_args, _window=window: self._on_closed(_window)
            )
        except Exception:
            with self._lock:
                self._creating_window = False
                self._session_state = "error"
                self._error_code = "session_start_failed"
                status = self._status_locked()
            self._destroy_window(window)
            self._emit(status)
            return {"ok": False, "error": "session_start_failed", "status": status}

        with self._lock:
            if self._shutdown or not self._renderer_available:
                keep = False
            elif self._window is None and self._creating_window:
                keep = True
                self._window = window
                self._creating_window = False
                self._navigation_generation += 1
                creation_generation = self._navigation_generation
                self._session_state = "starting"
                self._error_code = None
            else:
                keep = False
            status = self._status_locked()
        if not keep:
            self._destroy_window(window)
            return {"ok": False, "error": "window_unavailable", "status": status}
        self._emit(status)
        loaded_event = getattr(getattr(window, "events", None), "loaded", None)
        is_loaded = getattr(loaded_event, "is_set", None)
        if callable(is_loaded) and is_loaded():
            self._schedule(
                lambda: self._recover_completed_initial_load(
                    window,
                    creation_generation,
                )
            )
        return {"ok": True, "status": status}

    def _recover_completed_initial_load(
        self,
        window: Any,
        creation_generation: int,
    ) -> None:
        with self._lock:
            if (
                not self._navigation_is_current_locked(
                    window,
                    creation_generation,
                )
                or self._session_state != "starting"
            ):
                return
        self._on_loaded(window)

    def _on_loaded(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            self._navigation_generation += 1
            self._operation_generation += 1
            self._operation = "none"
            self._review_visible = False
            generation = self._navigation_generation
            self._session_state = "starting"
            self._error_code = None
            status = self._status_locked()
        self._emit(status)
        self._schedule(lambda: self._process_loaded_page(window, generation))

    def _process_current_page(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            generation = self._navigation_generation
        self._process_loaded_page(window, generation)

    def _process_loaded_page(
        self,
        window: Any,
        generation: int,
        work_readiness_attempt: int = 1,
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
        try:
            url = window.get_current_url()
        except Exception:
            self._set_page_error_if_current(
                window,
                generation,
                "page_contract_changed",
            )
            return
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
        if not self._page_adapter.navigation_allowed(url):
            self._set_page_error_if_current(window, generation, "navigation_blocked")
            try:
                window.load_url(self._page_adapter.business_url)
            except Exception:
                pass
            return

        page_type = self._page_adapter.detect_page(url)
        if page_type is FDWorkPageType.LOGIN:
            self._accept_login_page(window, generation)
            return
        if page_type is not FDWorkPageType.WORK_HOUR_LIST:
            self._set_page_error_if_current(
                window,
                generation,
                "page_contract_changed",
            )
            return

        self._check_work_page_readiness(
            window,
            generation,
            work_readiness_attempt,
        )

    def _check_work_page_readiness(
        self,
        window: Any,
        generation: int,
        attempt: int,
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return

        settled_lock = threading.Lock()
        settled = False

        def accept_readiness(result: Any) -> None:
            nonlocal settled
            with settled_lock:
                if settled:
                    return
                settled = True
            with self._lock:
                if not self._navigation_is_current_locked(window, generation):
                    return
            if isinstance(result, Mapping) and result.get("ready") is True:
                self._accept_ready_work_page(window, generation)
                return
            if isinstance(result, Mapping) and (
                result.get("login_ready") is True
                or result.get("login_navigation") is True
            ):
                self._accept_login_page(window, generation)
                return
            if attempt >= self._login_readiness_attempts:
                if not self._reload_business_page_once_if_current(
                    window,
                    generation,
                ):
                    self._set_page_error_if_current(
                        window,
                        generation,
                        "page_contract_changed",
                    )
                return
            self._schedule_after(
                self._login_readiness_interval_seconds,
                lambda: self._process_loaded_page(
                    window,
                    generation,
                    attempt + 1,
                ),
            )

        self._schedule_after(
            self._login_readiness_timeout_seconds,
            lambda: accept_readiness({"ready": False}),
        )
        try:
            self._page_adapter.check_work_hour_page_ready(
                window,
                accept_readiness,
            )
        except Exception:
            accept_readiness({"ready": False})

    def _reload_business_page_once_if_current(
        self,
        window: Any,
        generation: int,
    ) -> bool:
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or self._session_reload_used
            ):
                return False
            self._session_reload_used = True
            self._navigation_generation += 1
            self._operation_generation += 1
            reload_generation = self._navigation_generation
            self._session_state = "starting"
            self._operation = "none"
            self._error_code = None
            status = self._status_locked()
        self._emit(status)
        try:
            window.load_url(self._page_adapter.business_url)
        except Exception:
            self._set_page_error_if_current(
                window,
                reload_generation,
                "session_start_failed",
            )
        return True

    def _accept_login_page(
        self,
        window: Any,
        generation: int,
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
            self._session_state = "login_required"
            self._session_reload_used = False
            self._operation = "none"
            self._error_code = "login_required"
            show = bool(
                self._show_login_if_required or self._pending_draft is not None
            )
            status = self._status_locked()
        self._emit(status)
        if show:
            self._show_window_if_current(window, generation, focus=True)
        self._check_login_readiness(window, generation, 1)

    def _accept_ready_work_page(
        self,
        window: Any,
        generation: int,
    ) -> None:

        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
            draft = self._pending_draft
            if draft is None:
                self._session_reload_used = False
                self._session_state = "ready"
                self._operation = "none"
                self._error_code = None
                status = self._status_locked()
                hide = True
            else:
                self._operation_generation += 1
                operation_generation = self._operation_generation
                self._session_state = "ready"
                self._operation = "filling"
                self._error_code = None
                status = self._status_locked()
                hide = False
        self._emit(status)
        if hide:
            self._hide_window_if_current(window, generation)
            return
        self._run_fill(
            window,
            generation,
            operation_generation,
            draft,
        )

    def _run_fill(
        self,
        window: Any,
        navigation_generation: int,
        operation_generation: int,
        draft: FDWorkEntryDraft,
    ) -> None:
        acquired = self._operation_lock.acquire(
            timeout=self._operation_timeout_seconds
        )
        if not acquired:
            self._finish_fill(
                window,
                navigation_generation,
                operation_generation,
                draft,
                {"ok": False, "error": "page_operation_timeout"},
            )
            return
        try:
            try:
                result = dict(self._page_adapter.fill_entry(window, draft))
            except Exception:
                result = {"ok": False, "error": "page_contract_changed"}
        finally:
            self._operation_lock.release()
        self._finish_fill(
            window,
            navigation_generation,
            operation_generation,
            draft,
            result,
        )

    def _finish_fill(
        self,
        window: Any,
        navigation_generation: int,
        operation_generation: int,
        draft: FDWorkEntryDraft,
        result: Mapping[str, Any],
    ) -> None:
        with self._lock:
            if not self._operation_is_current_locked(
                window,
                navigation_generation,
                operation_generation,
                "filling",
            ):
                return
            self._operation = "none"
            if result.get("ok") is True:
                if self._pending_draft is draft:
                    self._pending_draft = None
                self._review_visible = True
                self._session_state = "ready"
                self._error_code = None
            else:
                self._session_state = "error"
                self._error_code = str(
                    result.get("error") or "page_contract_changed"
                )
            status = self._status_locked()
        self._emit(status)
        self._show_window_if_current(
            window,
            navigation_generation,
            focus=True,
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

        settled_lock = threading.Lock()
        settled = False

        def accept_readiness(result: Any) -> None:
            nonlocal settled
            with settled_lock:
                if settled:
                    return
                settled = True
            with self._lock:
                if not self._navigation_is_current_locked(window, generation):
                    return
                if isinstance(result, Mapping) and result.get("ready") is True:
                    self._session_state = "login_required"
                    self._operation = "none"
                    self._error_code = "login_required"
                    show = False
                    status = self._status_locked()
                    retry = False
                elif (
                    attempt >= self._login_readiness_attempts
                    and isinstance(result, Mapping)
                    and result.get("timed_out") is True
                ):
                    self._session_state = "login_required"
                    self._operation = "none"
                    self._error_code = "login_required"
                    show = False
                    status = self._status_locked()
                    retry = False
                elif attempt >= self._login_readiness_attempts:
                    self._session_state = "error"
                    self._operation = "none"
                    self._error_code = "session_start_failed"
                    show = True
                    status = self._status_locked()
                    retry = False
                else:
                    show = False
                    status = None
                    retry = True
            if retry:
                self._schedule_after(
                    self._login_readiness_interval_seconds,
                    lambda: self._check_login_readiness(
                        window,
                        generation,
                        attempt + 1,
                    ),
                )
                return
            if status is not None:
                self._emit(status)
            if show:
                self._show_window_if_current(window, generation, focus=True)

        self._schedule_after(
            self._login_readiness_timeout_seconds,
            lambda: accept_readiness({"ready": False, "timed_out": True}),
        )
        try:
            self._page_adapter.check_login_page_ready(window, accept_readiness)
        except Exception:
            accept_readiness({"ready": False})

    def _on_closing(self, window: Any) -> bool:
        with self._lock:
            if self._shutdown or self._window is not window:
                return True
            self._navigation_generation += 1
            self._operation_generation += 1
            self._review_visible = False
            if self._session_state != "login_required":
                self._operation = "none"
            generation = self._navigation_generation
            status = self._status_locked()
        self._emit(status)
        self._schedule(lambda: self._hide_window_if_current(window, generation))
        return False

    def _on_closed(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            self._navigation_generation += 1
            self._operation_generation += 1
            self._window = None
            self._pending_draft = None
            self._review_visible = False
            self._session_state = "idle"
            self._operation = "none"
            self._error_code = None
            status = self._status_locked()
        self._emit(status)

    def _finish_search_failure(
        self,
        window: Any,
        navigation_generation: int,
        operation_generation: int,
        error: str,
    ) -> Mapping[str, Any]:
        with self._lock:
            if self._operation_is_current_locked(
                window,
                navigation_generation,
                operation_generation,
                "searching",
            ):
                self._operation = "none"
                self._error_code = error
                status = self._status_locked()
            else:
                status = None
        if status is not None:
            self._emit(status)
        return {"ok": False, "error": error}

    def _set_page_error_if_current(
        self,
        window: Any,
        generation: int,
        error: str,
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
            self._session_state = "error"
            self._operation = "none"
            self._error_code = error
            status = self._status_locked()
        self._emit(status)

    def _hide_window_if_current(self, window: Any, generation: int) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
        try:
            window.hide()
        except Exception:
            pass
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return

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

    def _operation_is_current_locked(
        self,
        window: Any,
        navigation_generation: int,
        operation_generation: int,
        operation: str,
    ) -> bool:
        return bool(
            self._navigation_is_current_locked(window, navigation_generation)
            and self._operation_generation == operation_generation
            and self._operation == operation
        )

    def _status_locked(self) -> dict[str, Any]:
        state = "shutdown" if self._shutdown else self._session_state
        return {
            "session_state": state,
            "operation": self._operation,
            "ready": state == "ready",
            "login_required": state == "login_required",
            "error_code": self._error_code,
            "navigation_generation": self._navigation_generation,
        }

    def _failure_locked(self, error: str) -> dict[str, Any]:
        return {"ok": False, "error": error, "status": self._status_locked()}

    def _show_window_if_current(
        self,
        window: Any,
        generation: int,
        *,
        focus: bool,
    ) -> None:
        for action in ("show", "restore"):
            with self._lock:
                if not self._navigation_is_current_locked(window, generation):
                    return
            callback = getattr(window, action, None)
            if callable(callback):
                try:
                    callback()
                except Exception:
                    pass
        if focus:
            with self._lock:
                if not self._navigation_is_current_locked(window, generation):
                    return
            callback = getattr(window, "focus", None)
            if callable(callback):
                try:
                    callback()
                except Exception:
                    pass
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return

    @staticmethod
    def _destroy_window(window: Any | None) -> None:
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            pass

    def _emit(self, status: Mapping[str, Any]) -> None:
        try:
            self._status_callback(dict(status))
        except Exception:
            pass


__all__ = ["FDWorkWindowController"]
