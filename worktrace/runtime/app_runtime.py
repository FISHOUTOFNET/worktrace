"""Process-level application runtime.

Owns every long-lived runtime component: collector, folder-index worker,
platform adapter, pause/reset command channel, single-instance lock and
startup recovery.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING

from .. import db
from ..collector import collector_health
from ..collector.collector import CollectorControl, run_collector
from ..collector.single_instance import acquire_single_instance, release_single_instance
from ..services import activity_lifecycle_service, folder_index_service, recovery_service
from ..services.secure_backup_service import (
    clear_collector_pause_handler,
    clear_collector_reset_handler,
    register_collector_pause_handler,
    register_collector_reset_handler,
)
from ..services.settings_service import set_setting

if TYPE_CHECKING:
    from .. import config

    class _Paths:
        db_path: str
        log_path: str

    _Paths = _Paths  # noqa: F811


def _choose_adapter():
    """Return the platform adapter for the current OS."""
    if sys.platform.startswith("win"):
        from ..platforms.hardened_windows_adapter import HardenedWindowsAdapter

        return HardenedWindowsAdapter()
    from ..platforms.fake_adapter import FakeAdapter

    return FakeAdapter()


class AppRuntime:
    """Single owner for process-level worker and adapter lifecycle."""

    def __init__(self, paths: "_Paths") -> None:
        self.paths = paths
        self.stop_event = threading.Event()
        self.owns_collector = False
        self.collector_control = CollectorControl()
        self._lifecycle_lock = threading.RLock()
        self._adapter = _choose_adapter()
        self._collector_thread: threading.Thread | None = None
        self._index_thread: threading.Thread | None = None
        self._initialized = False
        self._shutdown = False

    def initialize(self) -> None:
        """Initialize the DB, acquire the instance lock and recover stale rows."""
        db.initialize_database(self.paths.db_path)
        self.owns_collector = acquire_single_instance()
        if not self.owns_collector:
            logging.warning(
                "single instance collector lock not acquired; UI will start without collector"
            )
        if self.owns_collector:
            recovery_service.recover_unclosed_records()
        self._initialized = True

    def start_background_workers(self) -> bool:
        """Start or replace the folder-index worker under the lifecycle lock."""
        with self._lifecycle_lock:
            if not self.owns_collector or self._shutdown or self.stop_event.is_set():
                return False
            if self._index_thread is not None and self._index_thread.is_alive():
                return False
            self._index_thread = folder_index_service.start_folder_index_worker(
                self.stop_event
            )
            return self._index_thread is not None

    def start_collector(self) -> dict[str, object]:
        """Start the collector exactly once under the lifecycle lock."""
        with self._lifecycle_lock:
            if self._shutdown or self.stop_event.is_set():
                return {"ok": False, "error": "runtime_stopping"}
            if not self.owns_collector:
                return {"ok": False, "error": "collector_not_owned"}
            if self._collector_thread is not None and self._collector_thread.is_alive():
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
        register_collector_pause_handler(self.pause_collection_now)
        register_collector_reset_handler(self.reset_collection_runtime_now)

    def pause_collection_now(self, timeout_seconds: float = 5.0) -> dict[str, object]:
        """Finalize the current activity and establish the paused state."""
        if (
            not self.owns_collector
            or self._collector_thread is None
            or not self._collector_thread.is_alive()
        ):
            return {"ok": True, "pause_pending": False, "collector_active": False}
        return self.collector_control.request_pause(timeout_seconds=timeout_seconds)

    def reset_collection_runtime_now(
        self, timeout_seconds: float = 5.0
    ) -> dict[str, object]:
        """Forget all collector/adapter identity before destructive DB work."""
        if (
            not self.owns_collector
            or self._collector_thread is None
            or not self._collector_thread.is_alive()
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

    def set_clipboard_capture_enabled(self, enabled: bool) -> None:
        setter = getattr(self._adapter, "set_clipboard_capture_enabled", None)
        if setter is not None:
            setter(bool(enabled))

    def request_shutdown(self) -> None:
        """Signal the collector and index threads to stop."""
        self.stop_event.set()

    def shutdown(self) -> None:
        """Join workers, close rows, stop adapter services and release the lock."""
        with self._lifecycle_lock:
            if self._shutdown:
                return
            self._shutdown = True
            clear_collector_pause_handler(self.pause_collection_now)
            clear_collector_reset_handler(self.reset_collection_runtime_now)
            self.stop_event.set()
            index_thread = self._index_thread
            collector_thread = self._collector_thread

        if index_thread:
            index_thread.join(timeout=5)
        if collector_thread:
            collector_thread.join(timeout=5)
        if self.owns_collector:
            activity_lifecycle_service.close_all_open_activities()
            set_setting("collector_status", "stopped")
            release_single_instance()
        shutdown_adapter = getattr(self._adapter, "shutdown", None)
        if shutdown_adapter is not None:
            shutdown_adapter()
        logging.info("app shutdown")


__all__ = ["AppRuntime"]
