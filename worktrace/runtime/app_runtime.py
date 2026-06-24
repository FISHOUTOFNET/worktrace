"""Process-level application runtime.

Encapsulates the collector thread, folder-index worker, stop event, single
instance lock, and recovery logic that previously lived inline in ``main.py``.
``main.py`` now only creates an ``AppRuntime``, initializes it, runs the UI
main loop, and shuts it down.

The runtime is single-process, multi-thread: UI thread + collector thread.
No network service, no background Windows service, no cloud sync.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING

from .. import db
from ..collector.collector import run_collector
from ..collector.single_instance import acquire_single_instance, release_single_instance
from ..services import activity_service, folder_index_service, recovery_service
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
        from ..platforms.windows_adapter import WindowsAdapter

        return WindowsAdapter()
    from ..platforms.fake_adapter import FakeAdapter

    return FakeAdapter()


class AppRuntime:
    """Owns collector and folder-index threads plus the stop event.

    Lifecycle::

        runtime = AppRuntime(paths)
        runtime.initialize()
        runtime.start_collector()   # may be called later, e.g. after privacy gate
        runtime.shutdown()          # join threads, close open record, release lock
    """

    def __init__(self, paths: "_Paths") -> None:
        self.paths = paths
        self.stop_event = threading.Event()
        self.owns_collector = False
        self._collector_thread: threading.Thread | None = None
        self._index_thread: threading.Thread | None = None
        self._initialized = False
        self._shutdown = False

    def initialize(self) -> None:
        """Initialize the database, acquire single-instance lock, recover
        unclosed records, and start the folder-index worker.

        Mirrors the pre-refactor startup order from ``main.py``.
        """
        db.initialize_database(self.paths.db_path)

        self.owns_collector = acquire_single_instance()
        if not self.owns_collector:
            logging.warning(
                "single instance collector lock not acquired; UI will start without collector"
            )

        recovery_service.recover_unclosed_records()
        self._index_thread = folder_index_service.start_folder_index_worker(self.stop_event)
        self._initialized = True

    def start_collector(self) -> None:
        """Start the collector thread once. Safe to call multiple times."""
        if not self.owns_collector or self._collector_thread is not None:
            return
        self._collector_thread = threading.Thread(
            target=run_collector,
            args=(_choose_adapter(), self.stop_event),
            name="WorkTraceCollector",
            daemon=True,
        )
        self._collector_thread.start()

    def request_shutdown(self) -> None:
        """Signal the collector and index threads to stop."""
        self.stop_event.set()

    def shutdown(self) -> None:
        """Join threads, close the current open record, and release the lock.

        Idempotent: safe to call more than once.
        """
        if self._shutdown:
            return
        self._shutdown = True
        self.stop_event.set()
        if self._index_thread:
            self._index_thread.join(timeout=5)
        if self._collector_thread:
            self._collector_thread.join(timeout=5)
        activity_service.close_current_open_record()
        set_setting("collector_status", "stopped")
        release_single_instance()
        logging.info("app shutdown")


__all__ = ["AppRuntime"]
