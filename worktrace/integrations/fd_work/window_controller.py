"""Lifecycle and serialized DOM-operation owner for one FD Work window."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Mapping

from .contracts import FDWorkEntryDraft
from .page_adapter import FDWorkPageAdapter, FDWorkPageType


def _run_now(callback: Callable[[], None]) -> None:
    callback()


def _run_after(delay_seconds: float, callback: Callable[[], None]) -> None:
    timer = threading.Timer(delay_seconds, callback)
    timer.daemon = True
    timer.start()


_DIAGNOSTIC_EVENTS = frozenset(
    {
        "fd_work_prepare_requested",
        "fd_work_create_reserved",
        "fd_work_create_begin",
        "fd_work_create_returned",
        "fd_work_handlers_bound",
        "fd_work_renderer_initialized",
        "fd_work_before_load",
        "fd_work_loaded",
        "fd_work_start_watchdog_armed",
        "fd_work_start_watchdog_probe",
        "fd_work_start_watchdog_visible",
        "fd_work_page_detected",
        "fd_work_login_required",
        "fd_work_login_watch_armed",
        "fd_work_login_watch_probe",
        "fd_work_ready",
        "fd_work_start_timeout",
        "fd_work_window_show",
        "fd_work_window_hide",
        "fd_work_window_destroy",
    }
)
_SAFE_RENDERERS = frozenset({"edgechromium", "cef", "qt", "gtk", "mshtml"})
_SAFE_PAGE_TYPES = frozenset({"none", "login", "work_hour_list", "unknown"})


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
        login_readiness_attempts: int = 35,
        login_readiness_interval_seconds: float = 1.0,
        login_readiness_timeout_seconds: float = 3.0,
        work_readiness_attempts: int = 35,
        work_readiness_interval_seconds: float = 1.0,
        login_transition_interval_seconds: float = 1.0,
        operation_timeout_seconds: float = 20.0,
        start_probe_delay_seconds: float = 5.0,
        start_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
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
        self._work_readiness_attempts = max(1, int(work_readiness_attempts))
        self._work_readiness_interval_seconds = max(
            0.1,
            float(work_readiness_interval_seconds),
        )
        self._login_transition_interval_seconds = max(
            0.1,
            float(login_transition_interval_seconds),
        )
        self._operation_timeout_seconds = max(1.0, float(operation_timeout_seconds))
        self._start_probe_delay_seconds = max(0.1, float(start_probe_delay_seconds))
        self._start_timeout_seconds = max(
            self._start_probe_delay_seconds,
            float(start_timeout_seconds),
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._window: Any | None = None
        self._creating_window = False
        self._pending_draft: FDWorkEntryDraft | None = None
        self._review_visible = False
        self._shutdown = False
        self._renderer_available = True
        self._renderer_initialized = False
        self._renderer_name = "unknown"
        self._navigation_generation = 0
        self._operation_generation = 0
        self._session_state = "idle"
        self._operation = "none"
        self._error_code: str | None = None
        self._show_login_if_required = True
        self._session_reload_used = False
        self._initial_load_observed = False
        self._initial_probe_started = False
        self._start_watch_generation: int | None = None
        self._start_monotonic: float | None = None
        self._start_visible_probe_used = False
        self._login_watch_generation: int | None = None

    def bind_status_callback(
        self,
        callback: Callable[[Mapping[str, Any]], None],
    ) -> None:
        with self._lock:
            self._status_callback = callback

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def prepare_window_before_start(
        self,
        show_login_if_required: bool = True,
    ) -> dict[str, Any]:
        """Create and bind the singleton helper before the GUI loop starts."""
        self._log_event("fd_work_prepare_requested")
        with self._lock:
            if self._shutdown:
                return self._failure_locked("window_unavailable")
            if not self._renderer_available:
                return self._failure_locked("renderer_unavailable")
            self._show_login_if_required = bool(show_login_if_required)
            if self._window is not None:
                return {"ok": True, "status": self._status_locked()}
            if self._creating_window:
                return self._failure_locked("session_starting")
            self._reserve_window_creation_locked()
            status = self._status_locked()
        self._log_event("fd_work_create_reserved")
        self._emit(status)
        return self._create_window()

    def on_renderer_initialized(self, renderer: str) -> None:
        safe_renderer = str(renderer or "").lower()
        if safe_renderer not in _SAFE_RENDERERS:
            safe_renderer = "unknown"
        with self._lock:
            if self._shutdown or not self._renderer_available:
                return
            self._renderer_initialized = True
            self._renderer_name = safe_renderer
            window = self._window
            generation = self._navigation_generation
            process_observed = bool(
                window is not None
                and self._session_state == "starting"
                and self._initial_load_observed
            )
            login_required = bool(
                window is not None and self._session_state == "login_required"
            )
        self._log_event("fd_work_renderer_initialized")
        if window is None:
            return
        if process_observed:
            self._schedule(
                lambda: self._process_loaded_page(window, generation)
            )
            return
        if login_required:
            self._arm_login_transition_watch_if_needed(window, generation)
            return
        self._arm_start_watchdog_if_needed(window, generation)

    def prepare_session(
        self,
        show_login_if_required: bool = True,
    ) -> dict[str, Any]:
        self._log_event("fd_work_prepare_requested")
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
            recover_starting = bool(
                window is not None
                and self._session_state == "starting"
                and show_login_if_required
            )
            restart_existing = bool(
                window is not None and self._session_state in {"idle", "error"}
            )
            if window is None and not self._creating_window:
                self._reserve_window_creation_locked()
                create = True
                creating = False
            elif window is None and self._creating_window:
                create = False
                creating = True
            else:
                create = False
                creating = False
            if restart_existing and window is not None:
                self._navigation_generation += 1
                self._operation_generation += 1
                generation = self._navigation_generation
                self._begin_start_generation_locked()
            state = self._session_state
            status = self._status_locked()
        self._emit(status)

        if create:
            self._log_event("fd_work_create_reserved")
            return self._create_window()
        if creating:
            return {"ok": False, "error": "session_starting", "status": status}
        if show_existing and window is not None:
            self._show_window_if_current(window, generation, focus=True)
            self._arm_login_transition_watch_if_needed(window, generation)
        elif (recover_starting or restart_existing) and window is not None:
            self._recover_starting_window(window, generation)
        elif window is not None and state == "starting":
            self._arm_start_watchdog_if_needed(window, generation)
        return {"ok": True, "status": self.get_status()}

    def _reserve_window_creation_locked(self) -> None:
        self._creating_window = True
        self._session_reload_used = False
        self._begin_start_generation_locked()

    def _begin_start_generation_locked(self) -> None:
        self._session_state = "starting"
        self._operation = "none"
        self._error_code = None
        self._initial_load_observed = False
        self._initial_probe_started = False
        self._start_watch_generation = None
        self._start_monotonic = None
        self._start_visible_probe_used = False
        self._login_watch_generation = None

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
                or self._operation not in {"none", "searching"}
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
            return {"ok": False, "error": "lookup_superseded"}
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
            self._initial_load_observed = False
            self._initial_probe_started = False
            self._start_watch_generation = None
            self._start_monotonic = None
            self._start_visible_probe_used = False
            self._login_watch_generation = None
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
            self._initial_load_observed = False
            self._initial_probe_started = False
            self._start_watch_generation = None
            self._start_monotonic = None
            self._start_visible_probe_used = False
            self._login_watch_generation = None
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
            self._initial_load_observed = False
            self._initial_probe_started = False
            self._start_watch_generation = None
            self._start_monotonic = None
            self._start_visible_probe_used = False
            self._login_watch_generation = None
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
        self._log_event("fd_work_create_begin")
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
            self._log_event("fd_work_create_returned", window_exists=True)
            before_load = getattr(window.events, "before_load", None)
            if before_load is not None:
                before_load += (
                    lambda *_args, _window=window: self._on_before_load(_window)
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
            self._log_event("fd_work_handlers_bound", window_exists=True)
        except Exception:
            with self._lock:
                self._creating_window = False
                self._session_state = "error"
                self._error_code = "session_start_failed"
                self._start_watch_generation = None
                self._start_monotonic = None
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
                renderer_initialized = self._renderer_initialized
            else:
                keep = False
                renderer_initialized = False
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
        elif renderer_initialized:
            self._arm_start_watchdog_if_needed(window, creation_generation)
        return {"ok": True, "status": status}

    def _on_before_load(self, window: Any) -> None:
        with self._lock:
            current = bool(not self._shutdown and self._window is window)
        if current:
            self._log_event("fd_work_before_load")

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
            self._initial_load_observed = True
            self._initial_probe_started = False
            self._start_watch_generation = None
            self._start_monotonic = None
            self._start_visible_probe_used = False
            self._login_watch_generation = None
            renderer_initialized = self._renderer_initialized
            status = self._status_locked()
        self._emit(status)
        self._log_event("fd_work_loaded")
        if renderer_initialized:
            self._schedule(lambda: self._process_loaded_page(window, generation))

    def _process_current_page(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            generation = self._navigation_generation
        self._process_loaded_page(window, generation)

    def _recover_starting_window(self, window: Any, generation: int) -> None:
        self._show_window_if_current(window, generation, focus=True)
        self._arm_start_watchdog_if_needed(window, generation)
        self._begin_initial_probe_if_needed(window, generation)

    def _arm_start_watchdog_if_needed(
        self,
        window: Any,
        generation: int,
    ) -> None:
        started = self._clock()
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or not self._renderer_initialized
                or self._session_state != "starting"
                or self._initial_load_observed
                or self._start_watch_generation == generation
            ):
                return
            self._start_watch_generation = generation
            self._start_monotonic = started
            self._start_visible_probe_used = False
        self._log_event("fd_work_start_watchdog_armed")
        self._schedule_after(
            self._start_probe_delay_seconds,
            lambda: self._run_start_watchdog_probe(window, generation),
        )
        self._schedule_after(
            self._start_timeout_seconds,
            lambda: self._run_start_watchdog_timeout(window, generation),
        )

    def _run_start_watchdog_probe(self, window: Any, generation: int) -> None:
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or self._start_watch_generation != generation
                or self._session_state != "starting"
                or self._initial_load_observed
            ):
                return
            self._start_visible_probe_used = True
        self._log_event("fd_work_start_watchdog_probe")
        self._show_window_if_current(window, generation, focus=True)
        self._log_event("fd_work_start_watchdog_visible")
        self._begin_initial_probe_if_needed(window, generation)

    def _run_start_watchdog_timeout(self, window: Any, generation: int) -> None:
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or self._start_watch_generation != generation
                or self._session_state != "starting"
            ):
                return
            self._session_state = "error"
            self._operation = "none"
            self._error_code = "session_start_timeout"
            self._initial_probe_started = False
            self._start_watch_generation = None
            status = self._status_locked()
        self._emit(status)
        self._log_event("fd_work_start_timeout")
        self._show_window_if_current(window, generation, focus=True)

    def _begin_initial_probe_if_needed(
        self,
        window: Any,
        generation: int,
    ) -> None:
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or not self._renderer_initialized
                or self._session_state != "starting"
                or self._initial_probe_started
            ):
                return
            self._initial_probe_started = True
        self._schedule(
            lambda: self._process_loaded_page(
                window,
                generation,
                initial_probe=True,
            )
        )

    def _finish_unresolved_initial_probe(
        self,
        window: Any,
        generation: int,
    ) -> None:
        with self._lock:
            if (
                self._navigation_is_current_locked(window, generation)
                and self._session_state == "starting"
            ):
                self._initial_probe_started = False

    def _process_loaded_page(
        self,
        window: Any,
        generation: int,
        work_readiness_attempt: int = 1,
        initial_probe: bool = False,
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
        try:
            url = window.get_current_url()
        except Exception:
            self._log_event("fd_work_page_detected", page_type="unknown")
            if initial_probe:
                self._finish_unresolved_initial_probe(window, generation)
                return
            self._set_page_error_if_current(
                window,
                generation,
                "page_contract_changed",
            )
            return
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
        try:
            navigation_allowed = self._page_adapter.navigation_allowed(url)
        except Exception:
            navigation_allowed = False
        if not navigation_allowed:
            self._log_event("fd_work_page_detected", page_type="unknown")
            self._set_page_error_if_current(window, generation, "navigation_blocked")
            try:
                window.load_url(self._page_adapter.business_url)
            except Exception:
                pass
            with self._lock:
                if not self._navigation_is_current_locked(window, generation):
                    return
            return

        try:
            page_type = self._page_adapter.detect_page(url)
        except Exception:
            self._log_event("fd_work_page_detected", page_type="unknown")
            if initial_probe:
                self._finish_unresolved_initial_probe(window, generation)
                return
            self._set_page_error_if_current(
                window,
                generation,
                "page_contract_changed",
            )
            return
        self._log_event(
            "fd_work_page_detected",
            page_type=self._safe_page_type(page_type),
        )
        if page_type is FDWorkPageType.LOGIN:
            self._accept_login_page(window, generation)
            return
        if page_type is not FDWorkPageType.WORK_HOUR_LIST:
            if initial_probe:
                self._finish_unresolved_initial_probe(window, generation)
                return
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
            initial_probe=initial_probe,
        )

    def _check_work_page_readiness(
        self,
        window: Any,
        generation: int,
        attempt: int,
        *,
        initial_probe: bool = False,
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
            if attempt >= self._work_readiness_attempts:
                if not self._load_login_page_once_if_current(
                    window,
                    generation,
                ):
                    if initial_probe:
                        self._finish_unresolved_initial_probe(window, generation)
                    else:
                        self._set_page_error_if_current(
                            window,
                            generation,
                            "page_contract_changed",
                        )
                return
            self._schedule_after(
                self._work_readiness_interval_seconds,
                lambda: self._process_loaded_page(
                    window,
                    generation,
                    attempt + 1,
                    initial_probe=initial_probe,
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

    def _load_login_page_once_if_current(
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
            self._begin_start_generation_locked()
            renderer_initialized = self._renderer_initialized
            status = self._status_locked()
        self._emit(status)
        try:
            window.load_url(self._page_adapter.login_url)
        except Exception:
            self._set_page_error_if_current(
                window,
                reload_generation,
                "session_start_failed",
            )
            return True
        if renderer_initialized:
            self._arm_start_watchdog_if_needed(window, reload_generation)
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
            self._initial_probe_started = False
            self._start_watch_generation = None
            show = bool(
                self._show_login_if_required or self._pending_draft is not None
            )
            status = self._status_locked()
        self._emit(status)
        self._log_event("fd_work_login_required", page_type="login")
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
                self._login_watch_generation = None
                self._session_state = "ready"
                self._operation = "none"
                self._error_code = None
                status = self._status_locked()
                hide = True
            else:
                self._operation_generation += 1
                self._login_watch_generation = None
                operation_generation = self._operation_generation
                self._session_state = "ready"
                self._operation = "filling"
                self._error_code = None
                status = self._status_locked()
                hide = False
        self._emit(status)
        self._log_event("fd_work_ready", page_type="work_hour_list")
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
                    arm_watch = True
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
                    arm_watch = True
                elif attempt >= self._login_readiness_attempts:
                    self._session_state = "login_required"
                    self._operation = "none"
                    self._error_code = "login_required"
                    show = False
                    status = self._status_locked()
                    retry = False
                    arm_watch = True
                else:
                    show = False
                    status = None
                    retry = True
                    arm_watch = False
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
            if arm_watch:
                self._arm_login_transition_watch_if_needed(window, generation)
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

    def _arm_login_transition_watch_if_needed(
        self,
        window: Any,
        generation: int,
    ) -> None:
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or not self._renderer_initialized
                or self._session_state != "login_required"
                or self._login_watch_generation == generation
            ):
                return
            self._login_watch_generation = generation
        self._log_event("fd_work_login_watch_armed", page_type="login")
        self._schedule_after(
            self._login_transition_interval_seconds,
            lambda: self._run_login_transition_probe(window, generation),
        )

    def _run_login_transition_probe(
        self,
        window: Any,
        generation: int,
    ) -> None:
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or self._session_state != "login_required"
                or self._login_watch_generation != generation
            ):
                return
        self._log_event("fd_work_login_watch_probe", page_type="login")

        settled_lock = threading.Lock()
        settled = False

        def accept_transition(result: Any) -> None:
            nonlocal settled
            with settled_lock:
                if settled:
                    return
                settled = True
            with self._lock:
                if (
                    not self._navigation_is_current_locked(window, generation)
                    or self._session_state != "login_required"
                    or self._login_watch_generation != generation
                ):
                    return
            if isinstance(result, Mapping) and result.get("ready") is True:
                self._accept_ready_work_page(window, generation)
                return
            self._schedule_after(
                self._login_transition_interval_seconds,
                lambda: self._run_login_transition_probe(window, generation),
            )

        self._schedule_after(
            self._login_readiness_timeout_seconds,
            lambda: accept_transition({"ready": False}),
        )
        try:
            self._page_adapter.check_work_hour_page_ready(
                window,
                accept_transition,
            )
        except Exception:
            accept_transition({"ready": False})

    def _on_closing(self, window: Any) -> bool:
        with self._lock:
            if self._shutdown or self._window is not window:
                return True
            self._navigation_generation += 1
            self._operation_generation += 1
            self._pending_draft = None
            self._review_visible = False
            self._operation = "none"
            self._error_code = None
            self._initial_load_observed = False
            self._initial_probe_started = False
            self._start_watch_generation = None
            self._start_monotonic = None
            self._start_visible_probe_used = False
            self._login_watch_generation = None
        return True

    def _on_closed(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            self._navigation_generation += 1
            self._operation_generation += 1
            self._window = None
            self._creating_window = False
            self._pending_draft = None
            self._review_visible = False
            self._session_state = "idle"
            self._operation = "none"
            self._error_code = None
            self._initial_load_observed = False
            self._initial_probe_started = False
            self._start_watch_generation = None
            self._start_monotonic = None
            self._start_visible_probe_used = False
            self._login_watch_generation = None
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
        self._log_event("fd_work_window_hide")
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
        self._log_event("fd_work_window_show")
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return

    def _destroy_window(self, window: Any | None) -> None:
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            pass
        self._log_event("fd_work_window_destroy", window_exists=True)

    @staticmethod
    def _safe_page_type(page_type: object) -> str:
        if page_type is FDWorkPageType.LOGIN:
            return "login"
        if page_type is FDWorkPageType.WORK_HOUR_LIST:
            return "work_hour_list"
        return "unknown"

    def _log_event(
        self,
        event: str,
        *,
        page_type: str = "none",
        window_exists: bool | None = None,
    ) -> None:
        if event not in _DIAGNOSTIC_EVENTS:
            return
        safe_page_type = page_type if page_type in _SAFE_PAGE_TYPES else "unknown"
        with self._lock:
            state = str(self._session_state)
            operation = str(self._operation)
            navigation_generation = self._navigation_generation
            operation_generation = self._operation_generation
            actual_window_exists = self._window is not None
            renderer = self._renderer_name
            started = self._start_monotonic
        if window_exists is None:
            window_exists = actual_window_exists
        elapsed_ms = (
            max(0, int((self._clock() - started) * 1000))
            if started is not None
            else 0
        )
        logging.info(
            "%s session_state=%s operation=%s navigation_generation=%d "
            "operation_generation=%d window_exists=%s renderer=%s "
            "page_type=%s elapsed_ms=%d",
            event,
            state,
            operation,
            navigation_generation,
            operation_generation,
            bool(window_exists),
            renderer,
            safe_page_type,
            elapsed_ms,
        )

    def _emit(self, status: Mapping[str, Any]) -> None:
        try:
            self._status_callback(dict(status))
        except Exception:
            pass


__all__ = ["FDWorkWindowController"]
