"""Process-level application runtime.

Encapsulates the collector thread, folder-index worker, stop event, single
instance lock, and recovery logic.
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
from ..collector.collector import CollectorControl, run_collector
from ..collector.single_instance import acquire_single_instance, release_single_instance
from ..services import activity_lifecycle_service, folder_index_service, recovery_service
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
        # Privacy gate: only after first-run notice accepted:
        runtime.start_background_workers()  # folder index worker (local path probing)
        runtime.start_collector()           # collector thread
        runtime.shutdown()                  # join threads, close open record, release lock

    Both ``start_background_workers`` and ``start_collector`` are gated by
    the first-run privacy notice in ``webview_main.main`` /
    ``bridge.toggle_pause`` / ``bridge.accept_first_run_notice``. The
    folder index worker probes local ``os.path.exists(file_path)`` for
    ready indexes, which is privacy-relevant local path probing; it must
    not start before the user has accepted the privacy notice.
    """

    def __init__(self, paths: "_Paths") -> None:
        self.paths = paths
        self.stop_event = threading.Event()
        self.owns_collector = False
        self.collector_control = CollectorControl()
        self._collector_thread: threading.Thread | None = None
        self._index_thread: threading.Thread | None = None
        self._initialized = False
        self._shutdown = False

    def initialize(self) -> None:
        """Initialize the database, acquire single-instance lock, and recover
        unclosed records.

        Privacy gate: ``initialize`` only does non-collection startup work
        (DB init, single-instance lock, recovery). It must NOT start the
        folder index worker because the worker probes local
        ``os.path.exists(file_path)`` paths for ready indexes, which is
        privacy-relevant local path probing. The worker is started
        separately via ``start_background_workers`` only after the
        first-run privacy notice has been accepted.
        """
        db.initialize_database(self.paths.db_path)

        self.owns_collector = acquire_single_instance()
        if not self.owns_collector:
            logging.warning(
                "single instance collector lock not acquired; UI will start without collector"
            )

        recovery_service.recover_unclosed_records()
        self._initialized = True

    def start_background_workers(self) -> bool:
        """Start the folder index worker once. Safe to call multiple times.

        Returns ``True`` when this call actually started the worker,
        ``False`` when the worker was already running or this instance
        does not own the collector (no-op). Idempotent: repeated calls
        do not spawn duplicate workers.

        Privacy gate: callers (``webview_main.main``,
        ``bridge.toggle_pause``, ``bridge.accept_first_run_notice``)
        must only invoke this after the first-run privacy notice has
        been accepted. The worker's ``validate_ready_indexes`` startup
        pass probes ``os.path.exists(file_path)`` for ready indexes,
        which is privacy-relevant local path probing.
        """
        if not self.owns_collector:
            return False
        if self._index_thread is not None:
            return False
        thread = folder_index_service.start_folder_index_worker(self.stop_event)
        if thread is None:
            return False
        self._index_thread = thread
        return True

    def start_collector(self) -> None:
        """Start the collector thread once. Safe to call multiple times."""
        if not self.owns_collector or self._collector_thread is not None:
            return
        self._collector_thread = threading.Thread(
            target=run_collector,
            args=(_choose_adapter(), self.stop_event, self.collector_control),
            name="WorkTraceCollector",
            daemon=True,
        )
        self._collector_thread.start()

    def pause_collection_now(self, timeout_seconds: float = 5.0) -> dict[str, object]:
        """Ask the collector to finalize the current activity before pausing."""
        if (
            not self.owns_collector
            or self._collector_thread is None
            or not self._collector_thread.is_alive()
        ):
            set_setting("user_paused", "true")
            return {"ok": False, "pause_pending": True}
        return self.collector_control.request_pause(timeout_seconds=timeout_seconds)

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
        activity_lifecycle_service.close_all_open_activities()
        set_setting("collector_status", "stopped")
        release_single_instance()
        logging.info("app shutdown")


__all__ = ["AppRuntime"]
