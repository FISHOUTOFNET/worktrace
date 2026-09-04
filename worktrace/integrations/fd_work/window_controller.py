"""Lifecycle, page phases, and dispatched mutations for one FD Work helper."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Mapping

from ...platforms.window_activation import (
    make_window_activatable,
    request_window_foreground,
)
from .page_adapter import FDWorkPageAdapter, FDWorkPagePhase
from .window_executor import (
    FDWorkCallbackScheduler,
    FDWorkExecutorWindow,
    FDWorkWindowCommandError,
    FDWorkWindowExecutor,
)

logger = logging.getLogger(__name__)


def _run_now(callback: Callable[[], None]) -> None:
    callback()


_PHASE_VALUES = frozenset({"none", *(phase.value for phase in FDWorkPagePhase)})
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
        "fd_work_page_phase_changed",
        "fd_work_login_required",
        "fd_work_login_transition_completed",
        "fd_work_ready",
        "fd_work_window_show",
        "fd_work_window_hide",
        "fd_work_window_destroy",
        "fd_work_adapter_installed",
    }
)
_SAFE_RENDERERS = frozenset({"edgechromium", "cef", "qt", "gtk", "mshtml"})
_SAFE_DIAGNOSTIC_FIELDS = frozenset(
    {
        "document_visibility",
        "viewport_available",
        "input_exists",
        "input_interactive",
        "form_exists",
        "wrapper_exists",
        "role_matches",
        "popup_exists",
        "popup_interactive",
        "loading_observed",
        "result_count",
        "elapsed_ms",
        "error_code",
    }
)


class FDWorkWindowController:
    """Own one helper window and keep shell readiness separate from interaction."""

    def __init__(
        self,
        webview: Any,
        *,
        page_adapter: FDWorkPageAdapter | None = None,
        helper_bridge: Any | None = None,
        schedule: Callable[[Callable[[], None]], None] = _run_now,
        schedule_after: Callable[[float, Callable[[], None]], None] | None = None,
        window_executor: FDWorkWindowExecutor | None = None,
        status_callback: Callable[[Mapping[str, Any]], None] | None = None,
        passive_probe_timeout_seconds: float = 4.0,
        work_shell_timeout_seconds: float = 12.0,
        probe_interval_seconds: float = 0.5,
        login_transition_interval_seconds: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
        **_retired_polling_options: Any,
    ) -> None:
        self._webview = webview
        self._page_adapter = page_adapter or FDWorkPageAdapter()
        self._helper_bridge = helper_bridge
        self._schedule = schedule
        self._callback_scheduler = (
            FDWorkCallbackScheduler() if schedule_after is None else None
        )
        self._schedule_after = (
            self._callback_scheduler.schedule
            if self._callback_scheduler is not None
            else schedule_after
        )
        self._window_executor = window_executor or FDWorkWindowExecutor()
        self._status_callback = status_callback or (lambda _status: None)
        self._passive_probe_timeout_seconds = max(
            0.1, float(passive_probe_timeout_seconds)
        )
        self._work_shell_timeout_seconds = max(
            0.1, float(work_shell_timeout_seconds)
        )
        self._probe_interval_seconds = max(0.05, float(probe_interval_seconds))
        self._login_transition_interval_seconds = max(
            0.1, float(login_transition_interval_seconds)
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._window: Any | None = None
        self._window_visible = False
        self._creating_window = False
        self._shutdown = False
        self._renderer_available = True
        self._renderer_initialized = False
        self._renderer_name = "unknown"
        self._loaded_generation: int | None = None
        self._navigation_generation = 0
        self._operation_generation = 0
        self._adapter_installed_generation: int | None = None
        self._session_state = "idle"
        self._page_phase = "none"
        self._operation = "none"
        self._error_code: str | None = None
        self._explicit_activation = False
        self._probe_generation: int | None = None
        self._probe_deadline: float | None = None
        self._login_watch_generation: int | None = None
        self._login_watch_deadline: float | None = None
        self._pending_close_generation: int | None = None
        self._close_callback: Callable[[int], None] = lambda _generation: None
        self._main_focus_callback: Callable[[], bool] = lambda: True

    def bind_status_callback(
        self, callback: Callable[[Mapping[str, Any]], None]
    ) -> None:
        with self._lock:
            self._status_callback = callback

    def bind_close_callback(self, callback: Callable[[int], None]) -> None:
        with self._lock:
            self._close_callback = callback

    def bind_main_focus_callback(self, callback: Callable[[], bool]) -> None:
        with self._lock:
            self._main_focus_callback = callback

    def schedule_callback(self, callback: Callable[[], None]) -> bool:
        try:
            return self._schedule_after(0.0, callback) is not False
        except Exception:
            return False

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def prepare_window_before_start(
        self, show_login_if_required: bool = False
    ) -> dict[str, Any]:
        return self._prepare_session(explicit=bool(show_login_if_required))

    def prepare_session(
        self, show_login_if_required: bool = True
    ) -> dict[str, Any]:
        return self._prepare_session(explicit=bool(show_login_if_required))

    def _prepare_session(self, *, explicit: bool) -> dict[str, Any]:
        self._log_event("fd_work_prepare_requested")
        with self._lock:
            if self._shutdown:
                return self._failure_locked("window_unavailable")
            if not self._renderer_available:
                return self._failure_locked("renderer_unavailable")
            if explicit:
                self._explicit_activation = True
            window = self._window
            if window is None and self._creating_window:
                return self._failure_locked("session_starting")
            if window is None:
                self._creating_window = True
                self._begin_probe_generation_locked(explicit=explicit)
                create = True
            else:
                create = False
                generation = self._navigation_generation
                if self._session_state in {"idle", "error"}:
                    page_loaded = self._loaded_generation is not None
                    self._begin_probe_generation_locked(explicit=explicit)
                    generation = self._navigation_generation
                    if page_loaded:
                        self._loaded_generation = generation
                status = self._status_locked()
        if create:
            self._log_event("fd_work_create_reserved")
            return self._create_window(explicit=explicit)
        self._emit(status)
        if explicit:
            self._show_window_if_current(window, generation, focus=True, restore=True)
        self._arm_probe_if_needed(window, generation)
        return {"ok": True, "status": self.get_status()}

    def _begin_probe_generation_locked(self, *, explicit: bool) -> None:
        self._navigation_generation += 1
        self._operation_generation += 1
        self._adapter_installed_generation = None
        self._loaded_generation = None
        self._session_state = "probing"
        self._page_phase = "none"
        self._operation = "none"
        self._error_code = None
        self._probe_generation = None
        self._probe_deadline = self._clock() + (
            self._work_shell_timeout_seconds
            if explicit
            else self._passive_probe_timeout_seconds
        )
        self._login_watch_generation = None
        self._login_watch_deadline = None

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
        self._log_event("fd_work_renderer_initialized")
        if window is not None:
            self._arm_probe_if_needed(window, generation)

    def disable(self) -> None:
        self._stop("idle", shutdown=False)

    def shutdown(self) -> None:
        self._stop("shutdown", shutdown=True)
        if self._callback_scheduler is not None:
            self._callback_scheduler.shutdown(timeout=2.0)
        self._window_executor.shutdown(timeout=2.0)

    def _stop(self, state: str, *, shutdown: bool) -> None:
        with self._lock:
            if shutdown and self._shutdown:
                return
            if shutdown:
                self._shutdown = True
            self._navigation_generation += 1
            self._operation_generation += 1
            self._adapter_installed_generation = None
            self._loaded_generation = None
            self._explicit_activation = False
            self._creating_window = False
            self._session_state = state
            self._page_phase = "none"
            self._operation = "none"
            self._error_code = None
            self._probe_generation = None
            self._probe_deadline = None
            self._login_watch_generation = None
            self._login_watch_deadline = None
            window = self._window
            self._window = None
            self._window_visible = False
            status = self._status_locked()
        self._cancel_pending_page_actions("window_closed" if shutdown else "navigation_changed")
        self._destroy_window(window)
        self._emit(status)

    def mark_renderer_unavailable(self) -> None:
        with self._lock:
            if not self._renderer_available:
                return
            self._renderer_available = False
            self._navigation_generation += 1
            self._operation_generation += 1
            self._adapter_installed_generation = None
            self._loaded_generation = None
            self._creating_window = False
            self._session_state = "error"
            self._page_phase = "none"
            self._operation = "none"
            self._error_code = "renderer_unavailable"
            self._probe_generation = None
            self._probe_deadline = None
            self._login_watch_generation = None
            self._login_watch_deadline = None
            window = self._window
            self._window = None
            self._window_visible = False
            status = self._status_locked()
        self._destroy_window(window)
        self._emit(status)

    def _create_window(self, *, explicit: bool) -> dict[str, Any]:
        window = None
        self._log_event("fd_work_create_begin")
        try:
            window = self._webview.create_window(
                "FD Work",
                self._page_adapter.business_url,
                width=980,
                height=760,
                resizable=True,
                js_api=self._helper_bridge,
                hidden=True,
                focus=False,
            )
            self._log_event("fd_work_create_returned", input_exists=True)
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
            self._log_event("fd_work_handlers_bound")
        except Exception:
            with self._lock:
                self._creating_window = False
                self._session_state = "error"
                self._page_phase = "none"
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
                self._window_visible = False
                self._creating_window = False
                generation = self._navigation_generation
            else:
                keep = False
                generation = self._navigation_generation
            status = self._status_locked()
        if not keep:
            self._destroy_window(window)
            return {"ok": False, "error": "window_unavailable", "status": status}
        self._emit(status)
        if explicit:
            self._show_window_if_current(window, generation, focus=True, restore=True)
        loaded_event = getattr(getattr(window, "events", None), "loaded", None)
        is_loaded = getattr(loaded_event, "is_set", None)
        if callable(is_loaded) and is_loaded():
            self._schedule(lambda: self._on_loaded(window))
        return {"ok": True, "status": self.get_status()}

    def _on_before_load(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            self._navigation_generation += 1
            self._operation_generation += 1
            self._adapter_installed_generation = None
            self._loaded_generation = None
            self._session_state = "probing"
            self._page_phase = "none"
            self._operation = "none"
            self._error_code = None
            self._probe_generation = None
            self._probe_deadline = None
            self._login_watch_generation = None
            self._login_watch_deadline = None
            status = self._status_locked()
        self._cancel_pending_page_actions("navigation_changed")
        self._emit(status)
        self._log_event("fd_work_before_load")

    def _on_loaded(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            self._navigation_generation += 1
            self._operation_generation += 1
            self._adapter_installed_generation = None
            self._session_state = "probing"
            self._page_phase = "none"
            self._operation = "none"
            self._error_code = None
            generation = self._navigation_generation
            self._loaded_generation = generation
            self._probe_generation = None
            if self._probe_deadline is None:
                self._probe_deadline = self._clock() + (
                    self._work_shell_timeout_seconds
                    if self._explicit_activation
                    else self._passive_probe_timeout_seconds
                )
            self._login_watch_generation = None
            self._login_watch_deadline = None
            renderer_initialized = self._renderer_initialized
            status = self._status_locked()
        self._emit(status)
        self._log_event("fd_work_loaded")
        if renderer_initialized:
            self._schedule(lambda: self._probe_current_page(window, generation))

    def _arm_probe_if_needed(self, window: Any, generation: int) -> None:
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or not self._renderer_initialized
                or self._loaded_generation != generation
                or self._session_state != "probing"
                or self._probe_generation == generation
            ):
                return
            self._probe_generation = generation
            deadline = self._probe_deadline or (
                self._clock() + self._passive_probe_timeout_seconds
            )
            self._probe_deadline = deadline
        delay = min(0.25, max(0.0, self._remaining(deadline)))
        self._schedule_after(delay, lambda: self._probe_current_page(window, generation))

    def _probe_current_page(self, window: Any, generation: int) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
            deadline = self._probe_deadline or self._clock()
            explicit = self._explicit_activation
            operation_generation = self._operation_generation
        guarded_window = self._executor_window(
            window,
            generation,
            operation_generation,
        )
        try:
            url = guarded_window.get_current_url()
        except FDWorkWindowCommandError as exc:
            if exc.kind == "guard_rejected":
                return
            if exc.kind in {"callback_timeout", "request_timeout", "executor_rejected"}:
                remaining = self._remaining(deadline)
                if remaining > 0:
                    self._schedule_after(
                        min(self._probe_interval_seconds, remaining),
                        lambda: self._probe_current_page(window, generation),
                    )
                    return
            error = (
                "window_executor_stalled"
                if exc.kind == "executor_stalled"
                else "window_probe_failed"
            )
            self._set_page_error_if_current(window, generation, error)
            return
        if not self._page_adapter.navigation_allowed(url):
            self._set_page_error_if_current(window, generation, "navigation_blocked")
            return

        settled_lock = threading.Lock()
        settled = False

        def accept_probe(value: Any) -> None:
            nonlocal settled
            with settled_lock:
                if settled:
                    return
                settled = True
            with self._lock:
                if not self._navigation_is_current_locked(window, generation):
                    return
            phase = str(value.get("phase") if isinstance(value, Mapping) else "unknown")
            safe_probe_fields = {
                key: value[key]
                for key in (
                    "input_exists",
                    "form_exists",
                    "wrapper_exists",
                    "role_matches",
                )
                if isinstance(value, Mapping) and type(value.get(key)) is bool
            }
            if phase in {
                FDWorkPagePhase.LOGIN_CREDENTIALS.value,
                FDWorkPagePhase.LOGIN_CONFIRMATION.value,
            }:
                self._accept_login_page(window, generation, phase)
                return
            if phase in {
                FDWorkPagePhase.WORK_SHELL.value,
            }:
                self._accept_work_shell(window, generation, login_transition=False)
                return
            if phase == FDWorkPagePhase.UNAUTHORIZED.value:
                self._set_page_phase_error(window, generation, phase, "unauthorized")
                return
            if phase == FDWorkPagePhase.ERROR.value:
                self._set_page_phase_error(window, generation, phase, "page_error")
                return
            remaining = self._remaining(deadline)
            if remaining > 0:
                self._schedule_after(
                    min(self._probe_interval_seconds, remaining),
                    lambda: self._probe_current_page(window, generation),
                )
                return
            error = "work_shell_timeout" if explicit else "session_probe_inconclusive"
            with self._lock:
                if not self._navigation_is_current_locked(window, generation):
                    return
                self._session_state = "error" if explicit else "idle"
                self._page_phase = FDWorkPagePhase.UNKNOWN.value
                self._operation = "none"
                self._error_code = error
                self._explicit_activation = False
                self._probe_generation = None
                status = self._status_locked()
            self._emit(status)
            self._log_event(
                "fd_work_page_phase_changed",
                error_code=error,
                **safe_probe_fields,
            )

        try:
            self._page_adapter.probe_page_phase(guarded_window, accept_probe)
        except Exception:
            accept_probe({"phase": "unknown"})

    def _accept_login_page(
        self, window: Any, generation: int, phase: str
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
            self._session_state = "login_required"
            self._page_phase = phase
            self._operation = "none"
            self._error_code = "login_required"
            self._probe_generation = None
            show = self._explicit_activation and not self._window_visible
            self._explicit_activation = False
            status = self._status_locked()
        self._emit(status)
        self._log_event("fd_work_page_phase_changed")
        self._log_event("fd_work_login_required")
        if show:
            self._show_window_if_current(window, generation, focus=True, restore=True)
        self._arm_login_transition_watch(window, generation)

    def _arm_login_transition_watch(self, window: Any, generation: int) -> None:
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or self._session_state != "login_required"
                or self._login_watch_generation == generation
            ):
                return
            self._login_watch_generation = generation
            self._login_watch_deadline = self._clock() + self._work_shell_timeout_seconds
        self._schedule_after(
            self._login_transition_interval_seconds,
            lambda: self._run_login_transition_probe(window, generation),
        )

    def _run_login_transition_probe(self, window: Any, generation: int) -> None:
        with self._lock:
            if (
                not self._navigation_is_current_locked(window, generation)
                or self._session_state != "login_required"
                or self._login_watch_generation != generation
            ):
                return
            deadline = self._login_watch_deadline or self._clock()
            operation_generation = self._operation_generation
        guarded_window = self._executor_window(
            window,
            generation,
            operation_generation,
        )
        if self._remaining(deadline) <= 0:
            with self._lock:
                if self._navigation_is_current_locked(window, generation):
                    self._login_watch_generation = None
            return

        def accept(value: Any) -> None:
            with self._lock:
                if (
                    not self._navigation_is_current_locked(window, generation)
                    or self._session_state != "login_required"
                    or self._login_watch_generation != generation
                ):
                    return
            phase = str(value.get("phase") if isinstance(value, Mapping) else "unknown")
            if phase in {
                FDWorkPagePhase.WORK_SHELL.value,
            }:
                self._accept_work_shell(window, generation, login_transition=True)
                return
            remaining = self._remaining(deadline)
            if remaining > 0:
                self._schedule_after(
                    min(self._login_transition_interval_seconds, remaining),
                    lambda: self._run_login_transition_probe(window, generation),
                )

        try:
            self._page_adapter.probe_page_phase(guarded_window, accept)
        except Exception:
            accept({"phase": "unknown"})

    def _accept_work_shell(
        self, window: Any, generation: int, *, login_transition: bool
    ) -> None:
        installed = self._ensure_adapter_installed(window, generation)
        if installed.get("ok") is not True:
            self._set_page_error_if_current(
                window,
                generation,
                str(installed.get("error") or "adapter_injection_failed"),
            )
            return
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
            if (
                self._session_state == "ready"
                and self._page_phase == FDWorkPagePhase.WORK_SHELL.value
            ):
                return
            self._session_state = "ready"
            self._page_phase = FDWorkPagePhase.WORK_SHELL.value
            self._operation = "none"
            self._error_code = None
            self._probe_generation = None
            self._login_watch_generation = None
            self._login_watch_deadline = None
            self._explicit_activation = False
            status = self._status_locked()
        self._emit(status)
        self._log_event("fd_work_page_phase_changed")
        self._log_event("fd_work_ready")
        if login_transition:
            self._log_event("fd_work_login_transition_completed")

    def _ensure_adapter_installed(
        self, window: Any, generation: int
    ) -> Mapping[str, Any]:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return {"ok": False, "error": "lookup_superseded"}
            if self._adapter_installed_generation == generation:
                return {"ok": True}
            operation_generation = self._operation_generation
        guarded_window = self._executor_window(
            window,
            generation,
            operation_generation,
        )
        try:
            result = dict(self._page_adapter.install_adapter(guarded_window))
        except Exception:
            result = {"ok": False, "error": "adapter_injection_failed"}
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return {"ok": False, "error": "lookup_superseded"}
            if result.get("ok") is True:
                self._adapter_installed_generation = generation
        if result.get("ok") is True:
            self._log_event("fd_work_adapter_installed")
        return result

    def _on_closing(self, window: Any) -> bool:
        with self._lock:
            if self._shutdown or self._window is not window:
                return True
            self._navigation_generation += 1
            self._operation_generation += 1
            self._adapter_installed_generation = None
            self._loaded_generation = None
            self._explicit_activation = False
            self._window_visible = False
            self._session_state = "idle"
            self._page_phase = "none"
            self._operation = "none"
            self._error_code = None
            self._probe_generation = None
            self._probe_deadline = None
            self._login_watch_generation = None
            self._login_watch_deadline = None
            self._pending_close_generation = self._navigation_generation
        self._cancel_pending_page_actions("window_closed")
        return True

    def _on_closed(self, window: Any) -> None:
        with self._lock:
            if self._shutdown or self._window is not window:
                return
            generation = self._pending_close_generation
            if generation is None:
                self._navigation_generation += 1
                self._operation_generation += 1
                generation = self._navigation_generation
            self._window = None
            self._window_visible = False
            self._creating_window = False
            self._adapter_installed_generation = None
            self._loaded_generation = None
            self._explicit_activation = False
            self._session_state = "idle"
            self._page_phase = "none"
            self._operation = "none"
            self._error_code = None
            self._pending_close_generation = None
            close_callback = self._close_callback
            status = self._status_locked()
        self._emit(status)
        self.schedule_callback(lambda: close_callback(generation))

    def _cancel_pending_page_actions(self, error_kind: str) -> None:
        callback = getattr(self._page_adapter, "cancel_pending_actions", None)
        if callable(callback):
            callback(error_kind)

    def _set_page_phase_error(
        self, window: Any, generation: int, phase: str, error: str
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
            self._page_phase = phase if phase in _PHASE_VALUES else "unknown"
        self._set_page_error_if_current(window, generation, error)

    def _set_page_error_if_current(
        self, window: Any, generation: int, error: str
    ) -> None:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return
            self._session_state = "error"
            self._operation = "none"
            self._error_code = error
            status = self._status_locked()
        self._emit(status)
        self._log_event("fd_work_page_phase_changed", error_code=error)

    def foreground(
        self,
        owner: str,
        operation_generation: int,
        guard: Callable[[], bool],
    ) -> dict[str, Any]:
        if owner not in {"user_auth", "user_picker", "automation_fill"}:
            return {"ok": False, "error": "invalid_interaction_owner"}
        with self._lock:
            window = self._window
            navigation_generation = self._navigation_generation
            controller_operation_generation = self._operation_generation
            if self._shutdown or window is None:
                return self._failure_locked("window_unavailable")
            if owner in {"user_picker", "automation_fill"} and self._session_state != "ready":
                return self._failure_locked("fd_work_not_ready")

        def current() -> bool:
            return bool(
                self._navigation_is_current(window, navigation_generation)
                and guard()
            )

        if not self._show_window_if_current(
            window,
            navigation_generation,
            focus=True,
            restore=True,
            external_guard=current,
        ):
            if current():
                return {"ok": False, "error": "window_activation_failed"}
            return {"ok": False, "error": "lookup_superseded"}
        guarded_window = self._executor_window(
            window,
            navigation_generation,
            controller_operation_generation,
            external_guard=current,
        )
        return {
            "ok": True,
            "window": guarded_window,
            "navigation_generation": navigation_generation,
            "operation_generation": operation_generation,
        }

    def hide_and_restore_main(
        self,
        navigation_generation: int,
        operation_generation: int,
        guard: Callable[[], bool],
    ) -> None:
        del operation_generation
        with self._lock:
            window = self._window
            main_focus = self._main_focus_callback
        if window is None:
            return

        def current() -> bool:
            return bool(
                self._navigation_is_current(window, navigation_generation)
                and guard()
            )

        if not current():
            return
        try:
            if main_focus() is not True:
                logger.debug("FD Work main-window restore request was rejected")
                return
        except Exception:
            logger.debug("FD Work main-window restore request failed", exc_info=True)
            return
        if not current():
            return

        def hide_helper() -> None:
            callback = getattr(window, "hide", None)
            if callable(callback):
                callback()

        if not self._dispatch_window_mutation(hide_helper, current):
            return
        with self._lock:
            if self._window is window:
                self._window_visible = False
        self._log_event("fd_work_window_hide")

    def _show_window_if_current(
        self,
        window: Any,
        generation: int,
        *,
        focus: bool,
        restore: bool,
        external_guard: Callable[[], bool] | None = None,
    ) -> bool:
        with self._lock:
            if not self._navigation_is_current_locked(window, generation):
                return False
            already_visible = self._window_visible

        def guard() -> bool:
            return bool(
                self._navigation_is_current(window, generation)
                and (external_guard is None or external_guard())
            )

        if focus:
            activation_ready = {"ok": False}

            def enable_activation() -> None:
                activation_ready["ok"] = make_window_activatable(
                    window,
                    fallback_title="FD Work",
                    logger=logger,
                )

            if not self._dispatch_window_mutation(enable_activation, guard):
                return False
            if activation_ready["ok"] is not True:
                return False

        if not already_visible:
            def show_helper() -> None:
                callback = getattr(window, "show", None)
                if callable(callback):
                    callback()

            if not self._dispatch_window_mutation(show_helper, guard):
                return False
            with self._lock:
                if not self._navigation_is_current_locked(window, generation):
                    return False
                self._window_visible = True
            self._log_event("fd_work_window_show")

            def restore_and_focus() -> None:
                for action in (
                    "restore" if restore else None,
                    "focus" if focus else None,
                ):
                    if action:
                        callback = getattr(window, action, None)
                        if callable(callback):
                            try:
                                callback()
                            except Exception:
                                logger.debug(
                                    "FD Work pywebview activation step failed",
                                    exc_info=True,
                                )

            if restore or focus:
                if not self._dispatch_window_mutation(restore_and_focus, guard):
                    return False

        if focus:
            native_foreground = {"ok": False}

            def request_native_foreground() -> None:
                native_foreground["ok"] = request_window_foreground(
                    window,
                    fallback_title="FD Work",
                    restore=restore,
                    logger=logger,
                )

            if not self._dispatch_window_mutation(request_native_foreground, guard):
                return False
            if native_foreground["ok"] is not True:
                return False
        return guard()

    def _destroy_window(self, window: Any | None) -> None:
        if window is None:
            return
        callback = getattr(window, "destroy", None)
        if not callable(callback):
            return

        def guard() -> bool:
            with self._lock:
                return self._window is not window

        if self._dispatch_window_mutation(callback, guard):
            self._log_event("fd_work_window_destroy")

    def _dispatch_window_mutation(
        self,
        mutation: Callable[[], None],
        guard: Callable[[], bool],
    ) -> bool:
        def command(done: Callable[[Any], None]) -> None:
            mutation()
            done(True)

        result = self._window_executor.submit(command, guard, 2.0)
        return bool(result.ok is True and result.value is True)

    def _executor_window(
        self,
        window: Any,
        navigation_generation: int,
        operation_generation: int,
        *,
        external_guard: Callable[[], bool] | None = None,
    ) -> FDWorkExecutorWindow:
        def guard() -> bool:
            with self._lock:
                current = bool(
                    self._navigation_is_current_locked(
                        window,
                        navigation_generation,
                    )
                    and self._operation_generation == operation_generation
                )
            return bool(
                current
                and (external_guard is None or external_guard())
            )

        return FDWorkExecutorWindow(
            window,
            self._window_executor,
            guard,
        )

    def _navigation_is_current(self, window: Any, generation: int) -> bool:
        with self._lock:
            return self._navigation_is_current_locked(window, generation)

    def _navigation_is_current_locked(
        self, window: Any, generation: int
    ) -> bool:
        return bool(
            not self._shutdown
            and self._renderer_available
            and self._window is window
            and self._navigation_generation == generation
        )

    def _status_locked(self) -> dict[str, Any]:
        state = "shutdown" if self._shutdown else self._session_state
        return {
            "session_state": state,
            "page_phase": self._page_phase,
            "operation": self._operation,
            "ready": state == "ready",
            "login_required": state == "login_required",
            "error_code": self._error_code,
            "navigation_generation": self._navigation_generation,
        }

    def _failure_locked(self, error: str) -> dict[str, Any]:
        return {"ok": False, "error": error, "status": self._status_locked()}

    def _remaining(self, deadline: float) -> float:
        return max(0.0, float(deadline) - self._clock())

    def _log_event(self, event: str, **fields: Any) -> None:
        if event not in _DIAGNOSTIC_EVENTS:
            return
        with self._lock:
            base = {
                "session_state": self._session_state,
                "page_phase": self._page_phase,
                "operation": self._operation,
                "navigation_generation": self._navigation_generation,
                "operation_generation": self._operation_generation,
            }
        for key, value in fields.items():
            if key in _SAFE_DIAGNOSTIC_FIELDS:
                base[key] = value
        logging.info(
            "%s %s",
            event,
            " ".join(f"{key}={value}" for key, value in base.items()),
        )

    def _emit(self, status: Mapping[str, Any]) -> None:
        try:
            self._status_callback(dict(status))
        except Exception:
            pass


__all__ = ["FDWorkWindowController"]