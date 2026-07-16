"""Process-level application runtime.

Owns every long-lived runtime component: application instance lease, collector,
folder-index and history workers, platform adapter, maintenance command channels,
and startup recovery. A process without the application lease never opens the
business database or creates the WebView.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING, Any

from .. import db
from ..collector import collector_health
from ..collector.collector import CollectorControl, run_collector
from ..collector.single_instance import acquire_single_instance, release_single_instance
from ..services import (
    activity_lifecycle_service,
    folder_index_service,
    history_mutation_job_service,
    recovery_service,
)
from ..services.folder_index_recovery_service import recover_interrupted_indexes
from ..services.runtime_snapshot_barrier import (
    clear_quiesce_handler,
    register_quiesce_handler,
)
from ..services.secure_backup_service import (
    clear_collector_pause_handler,
    clear_collector_reset_handler,
    register_collector_pause_handler,
    register_collector_reset_handler,
)
from ..services.settings_service import get_bool_setting, get_setting, set_setting

if TYPE_CHECKING:
    class _Paths:
        db_path: str
        log_path: str

    _Paths = _Paths  # noqa: F811


def _choose_adapter():
    if sys.platform.startswith("win"):
        from ..platforms.hardened_windows_adapter import HardenedWindowsAdapter

        return HardenedWindowsAdapter()
    from ..platforms.fake_adapter import FakeAdapter

    return FakeAdapter()


def _thread_reference_is_alive(thread: Any | None) -> bool:
    if thread is None:
        return False
    checker = getattr(thread, "is_alive", None)
    return True if checker is None else bool(checker())


class AppRuntime:
    """Single owner for application, worker and adapter lifecycle."""

    def __init__(self, paths: "_Paths") -> None:
        self.paths = paths
        self.stop_event = threading.Event()
        self.owns_application_instance = False
        self.collector_control = CollectorControl()
        self._lifecycle_lock = threading.RLock()
        self._adapter = _choose_adapter()
        self._collector_thread: threading.Thread | None = None
        self._index_thread: threading.Thread | None = None
        self._history_thread: threading.Thread | None = None
        self._initialized = False
        self._shutdown = False

    @property
    def owns_collector(self) -> bool:
        return bool(self.owns_application_instance)

    @owns_collector.setter
    def owns_collector(self, value: bool) -> None:
        self.owns_application_instance = bool(value)

    def initialize(self) -> bool:
        with self._lifecycle_lock:
            if self._initialized:
                return self.owns_application_instance
            if self._shutdown:
                return False
            self.owns_application_instance = acquire_single_instance()
            if not self.owns_application_instance:
                logging.warning(
                    "single application instance lock not acquired; startup aborted"
                )
                return False
            try:
                db.initialize_database(self.paths.db_path)
                recovery_service.recover_unclosed_records()
            except Exception:
                release_single_instance()
                self.owns_application_instance = False
                raise
            self._initialized = True
            return True

    def start_background_workers(self) -> bool:
        """Start both derived-state workers and report complete readiness."""

        with self._lifecycle_lock:
            if (
                not self.owns_application_instance
                or self._shutdown
                or self.stop_event.is_set()
            ):
                return False

            index_ready = _thread_reference_is_alive(self._index_thread)
            if not index_ready:
                recover_interrupted_indexes()
                self._index_thread = folder_index_service.start_folder_index_worker(
                    self.stop_event
                )
                index_ready = self._index_thread is not None

            history_ready = _thread_reference_is_alive(self._history_thread)
            if not history_ready:
                self._history_thread = (
                    history_mutation_job_service.start_history_worker(
                        self.stop_event
                    )
                )
                history_ready = self._history_thread is not None

            return bool(index_ready and history_ready)

    def start_collector(self) -> dict[str, object]:
        with self._lifecycle_lock:
            if self._shutdown or self.stop_event.is_set():
                return {"ok": False, "error": "runtime_stopping"}
            if not self.owns_application_instance:
                return {"ok": False, "error": "collector_not_owned"}
            if _thread_reference_is_alive(self._collector_thread):
                self._register_maintenance_handlers()
                return {"ok": True, "started": False, "already_running": True}
            if self._collector_thread is not None:
                collector_health.record_health_code("thread_dead_replaced")
                self._collector_thread = None
                self.collector_control = CollectorControl()
            try:
                self._collector_thread = threading.Thread(
                    target=run_collector,
                    args=(self._adapter, self.stop_event, self.collector_control),
                    name="WorkTraceCollector",
                    daemon=True,
                )
                self._collector_thread.start()
            except Exception:
                logging.exception("collector thread start failed")
                self._collector_thread = None
                return {"ok": False, "error": "collector_start_failed"}
            set_setting("collector_status", "running")
            set_setting("collector_health_state", "healthy")
            self._register_maintenance_handlers()
            return {"ok": True, "started": True, "already_running": False}

    def _register_maintenance_handlers(self) -> None:
        register_collector_pause_handler(self.quiesce_collection_now)
        register_collector_reset_handler(self.reset_collection_runtime_now)
        register_quiesce_handler(self.quiesce_collection_now)

    def pause_collection_now(self, timeout_seconds: float = 5.0) -> dict[str, object]:
        if not self.owns_application_instance or not _thread_reference_is_alive(
            self._collector_thread
        ):
            return {"ok": True, "pause_pending": False, "collector_active": False}
        return self.collector_control.request_pause(timeout_seconds=timeout_seconds)

    def quiesce_collection_now(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        prior_user_paused = get_bool_setting("user_paused", False)
        prior_collector_status = get_setting("collector_status", "stopped") or "stopped"
        result = self.pause_collection_now(timeout_seconds=timeout_seconds)
        if bool(result.get("ok")):
            set_setting(
                "user_paused",
                "true" if prior_user_paused else "false",
            )
            set_setting("collector_status", prior_collector_status)
        return result

    def reset_collection_runtime_now(
        self, timeout_seconds: float = 5.0
    ) -> dict[str, object]:
        if not self.owns_application_instance or not _thread_reference_is_alive(
            self._collector_thread
        ):
            self._reset_adapter_runtime_state()
            return {"ok": True, "reset_pending": False, "collector_active": False}
        result = self.collector_control.request_reset(timeout_seconds=timeout_seconds)
        if bool(result.get("ok")):
            self._reset_adapter_runtime_state()
        return result

    def _reset_adapter_runtime_state(self) -> None:
        resetter = getattr(self._adapter, "reset_runtime_state", None)
        if resetter is not None:
            resetter()

    def set_clipboard_capture_enabled(self, enabled: bool) -> bool:
        setter = getattr(self._adapter, "set_clipboard_capture_enabled", None)
        if setter is not None:
            setter(bool(enabled))
        return True

    def request_shutdown(self) -> None:
        self.stop_event.set()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if self._shutdown:
                return
            self._shutdown = True
            clear_collector_pause_handler(self.quiesce_collection_now)
            clear_collector_reset_handler(self.reset_collection_runtime_now)
            clear_quiesce_handler(self.quiesce_collection_now)
            self.set_clipboard_capture_enabled(False)
            self.stop_event.set()
            workers = [
                self._index_thread,
                self._history_thread,
                self._collector_thread,
            ]

        adapter_shutdown = False
        collector_thread = self._collector_thread
        if collector_thread:
            joiner = getattr(collector_thread, "join", None)
            if joiner is not None:
                joiner(timeout=5)
            if _thread_reference_is_alive(collector_thread):
                shutdown_adapter = getattr(self._adapter, "shutdown", None)
                if shutdown_adapter is not None:
                    shutdown_adapter()
                    adapter_shutdown = True
                if joiner is not None:
                    joiner(timeout=5)

        for thread in (self._index_thread, self._history_thread):
            if thread:
                joiner = getattr(thread, "join", None)
                if joiner is not None:
                    joiner(timeout=5)

        writers_stopped = not any(
            _thread_reference_is_alive(thread) for thread in workers
        )
        if self.owns_application_instance and writers_stopped:
            if self._initialized:
                activity_lifecycle_service.close_all_open_activities()
                set_setting("collector_status", "stopped")
            release_single_instance()
            self.owns_application_instance = False
        elif self.owns_application_instance:
            collector_health.record_health_code("shutdown_writer_still_alive")
            logging.error("app shutdown retained instance lock: writer alive")

        if not adapter_shutdown:
            shutdown_adapter = getattr(self._adapter, "shutdown", None)
            if shutdown_adapter is not None:
                shutdown_adapter()
        logging.info("app shutdown writers_stopped=%s", writers_stopped)
