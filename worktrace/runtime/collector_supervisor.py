"""Process-scoped supervision for an authorized Collector runtime."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable, Protocol

from ..services import database_maintenance_service, privacy_gate_service
from ..services.settings_service import get_bool_setting

_SUPERVISOR_POLL_SECONDS = 5.0
_RESTART_WINDOW_SECONDS = 60.0
_MAX_RESTART_ATTEMPTS = 3
_RESTART_STARTUP_TIMEOUT_SECONDS = 5.0


class CollectorRuntimeCapability(Protocol):
    stop_event: threading.Event
    owns_application_instance: bool

    def is_collection_running_for_maintenance(self) -> bool: ...

    def start_collector(
        self,
        *,
        startup_timeout_seconds: float = 5.0,
    ) -> dict[str, object]: ...


class CollectorSupervisor:
    """Keep an authorized Collector alive without bypassing AppRuntime ownership."""

    def __init__(
        self,
        runtime: CollectorRuntimeCapability,
        *,
        poll_seconds: float = _SUPERVISOR_POLL_SECONDS,
        restart_window_seconds: float = _RESTART_WINDOW_SECONDS,
        max_restart_attempts: int = _MAX_RESTART_ATTEMPTS,
        startup_timeout_seconds: float = _RESTART_STARTUP_TIMEOUT_SECONDS,
        privacy_allowed_reader: Callable[[], bool] = (
            privacy_gate_service.is_sensitive_runtime_allowed
        ),
        user_paused_reader: Callable[[], bool] = lambda: get_bool_setting(
            "user_paused", False
        ),
        maintenance_in_progress_reader: Callable[[], bool] = (
            database_maintenance_service.is_maintenance_in_progress
        ),
        recovery_blocked_reader: Callable[[], bool] = (
            database_maintenance_service.MAINTENANCE_COORDINATOR.recovery_blocked
        ),
        monotonic_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runtime = runtime
        self._poll_seconds = max(0.1, float(poll_seconds))
        self._restart_window_seconds = max(1.0, float(restart_window_seconds))
        self._max_restart_attempts = max(1, int(max_restart_attempts))
        self._startup_timeout_seconds = max(0.1, float(startup_timeout_seconds))
        self._privacy_allowed_reader = privacy_allowed_reader
        self._user_paused_reader = user_paused_reader
        self._maintenance_in_progress_reader = maintenance_in_progress_reader
        self._recovery_blocked_reader = recovery_blocked_reader
        self._monotonic = monotonic_func
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._privacy_authorized = False
        self._restart_attempts: deque[float] = deque()
        self._rate_limit_logged_until = 0.0

    def set_privacy_authorized(self, authorized: bool) -> None:
        with self._lock:
            self._privacy_authorized = bool(authorized)

    def prepare_after_privacy(self, *, pre_start: bool) -> None:
        del pre_start
        if self._privacy_authorized:
            self.start()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._runtime.stop_event.is_set():
                return
            thread = threading.Thread(
                target=self._run,
                name="WorkTraceCollectorSupervisor",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def check_once(self) -> bool:
        """Run one bounded liveness check; return True only when restart is attempted."""

        if not self._restart_allowed():
            return False
        if self._runtime.is_collection_running_for_maintenance():
            return False

        now = self._monotonic()
        with self._lock:
            self._prune_restart_attempts_locked(now)
            if len(self._restart_attempts) >= self._max_restart_attempts:
                limit_until = self._restart_attempts[0] + self._restart_window_seconds
                if now >= self._rate_limit_logged_until:
                    logging.error(
                        "collector supervisor restart rate limited attempts=%s window_seconds=%s",
                        len(self._restart_attempts),
                        int(self._restart_window_seconds),
                    )
                    self._rate_limit_logged_until = limit_until
                return False
            self._restart_attempts.append(now)

        result = self._runtime.start_collector(
            startup_timeout_seconds=self._startup_timeout_seconds
        )
        if bool(result.get("ok")):
            logging.warning("collector supervisor restored stopped collector")
        else:
            logging.error(
                "collector supervisor restart failed error=%s",
                str(result.get("error") or "collector_start_failed"),
            )
        return True

    def _run(self) -> None:
        while not self._runtime.stop_event.wait(self._poll_seconds):
            try:
                self.check_once()
            except Exception:
                # The supervisor must not become a second single point of failure.
                # AppRuntime remains authoritative for all Collector mutations.
                logging.exception("collector supervisor check failed")

    def _restart_allowed(self) -> bool:
        if self._runtime.stop_event.is_set():
            return False
        if not bool(self._runtime.owns_application_instance):
            return False
        with self._lock:
            if not self._privacy_authorized:
                return False
        try:
            if not self._privacy_allowed_reader():
                return False
            if self._user_paused_reader():
                return False
            if self._maintenance_in_progress_reader():
                return False
            if self._recovery_blocked_reader():
                return False
        except Exception:
            return False
        return True

    def _prune_restart_attempts_locked(self, now: float) -> None:
        cutoff = now - self._restart_window_seconds
        while self._restart_attempts and self._restart_attempts[0] <= cutoff:
            self._restart_attempts.popleft()
        if not self._restart_attempts:
            self._rate_limit_logged_until = 0.0


__all__ = ["CollectorRuntimeCapability", "CollectorSupervisor"]
