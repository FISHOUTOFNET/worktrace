"""Single owner for projecting collection liveness onto desktop icons."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class CollectionIconProjectionHost:
    """Decorate a tray host with one process-long collection-state projection.

    The wrapped tray keeps ownership of Explorer registration and commands. This
    class owns only the periodic projection of the authoritative collection-state
    provider onto desktop icon sinks. A main-window icon sink may be attached
    later when headless startup eventually creates the renderer.
    """

    def __init__(
        self,
        *,
        tray: Any,
        collection_active_provider: Callable[[], bool],
        refresh_seconds: float = 1.0,
    ) -> None:
        self._tray = tray
        self._provider = collection_active_provider
        self._refresh_seconds = max(0.25, float(refresh_seconds))
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._window_icons: Any | None = None
        self._tray_available = False
        self._active = False
        self._has_sample = False
        self._provider_failed = False

    def start(self) -> bool:
        """Start/retry the tray and ensure exactly one projection monitor."""

        # Prime the tray's cached icon variant before Explorer registration. If
        # the collector is still starting, the monitor will project the later
        # transition without requiring a WebView to exist.
        self._refresh(force=True)
        if self.can_restore_window():
            self._ensure_monitor()
            return True
        try:
            available = self._tray.start() is True
        except Exception:
            logger.exception("collection icon tray initialization failed")
            available = False
        with self._lock:
            self._tray_available = available
        self._ensure_monitor()
        # Some injected/narrow tray capabilities do not cache state before
        # start; replay the current projection after the native host starts.
        self._apply_current(force=True)
        return available

    def stop(self) -> None:
        """Stop projection before releasing the wrapped tray capability."""

        self._stop_monitor()
        with self._lock:
            self._tray_available = False
        try:
            self._tray.stop()
        except Exception:
            logger.warning("collection icon tray cleanup failed", exc_info=True)

    def can_restore_window(self) -> bool:
        capability = getattr(self._tray, "can_restore_window", None)
        if callable(capability):
            try:
                return capability() is True
            except Exception:
                logger.warning("collection icon tray restore capability failed", exc_info=True)
                return False
        with self._lock:
            return self._tray_available

    def is_running(self) -> bool:
        """Compatibility alias for tray callers that still ask is_running()."""

        return self.can_restore_window()

    def show_background_notice(self) -> None:
        self._tray.show_background_notice()

    def attach_window_icons(self, window_icons: Any) -> None:
        """Attach a renderer-created window icon sink without adding an owner."""

        with self._lock:
            self._window_icons = window_icons
            has_sample = self._has_sample
            active = self._active
        if has_sample:
            try:
                window_icons.set_collection_active(active)
            except Exception:
                logger.warning("window icon projection attach failed", exc_info=True)

    def detach_window_icons(self, window_icons: Any | None = None) -> None:
        with self._lock:
            if window_icons is None or self._window_icons is window_icons:
                self._window_icons = None

    def set_collection_active(self, active: bool) -> None:
        """Compatibility sink; shipping code uses the provider-owned monitor."""

        self._apply(bool(active), force=True)

    def _ensure_monitor(self) -> None:
        with self._lock:
            thread = self._monitor_thread
            if thread is not None and thread.is_alive():
                return
            self._stop_event.clear()
            thread = threading.Thread(
                target=self._run_monitor,
                name="WorkTraceCollectionIcon",
                daemon=True,
            )
            self._monitor_thread = thread
        thread.start()

    def _stop_monitor(self) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._monitor_thread
            self._monitor_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _run_monitor(self) -> None:
        while not self._stop_event.wait(self._refresh_seconds):
            self._refresh(force=False)

    def _refresh(self, *, force: bool) -> None:
        try:
            active = bool(self._provider())
        except Exception:
            with self._lock:
                first_failure = not self._provider_failed
                self._provider_failed = True
            if first_failure:
                logger.warning("collection icon state provider failed", exc_info=True)
            active = False
        else:
            with self._lock:
                recovered = self._provider_failed
                self._provider_failed = False
            if recovered:
                logger.info("collection icon state provider recovered")
        self._apply(active, force=force)

    def _apply_current(self, *, force: bool) -> None:
        with self._lock:
            if not self._has_sample:
                return
            active = self._active
        self._apply(active, force=force)

    def _apply(self, active: bool, *, force: bool) -> None:
        active = bool(active)
        with self._lock:
            changed = not self._has_sample or active != self._active
            self._active = active
            self._has_sample = True
            window_icons = self._window_icons
        if not force and not changed:
            return
        try:
            # WindowsTrayHost intentionally accepts updates before native start
            # and carries the cached state across Explorer-host restarts.
            self._tray.set_collection_active(active)
        except Exception:
            logger.warning("tray collection icon projection failed", exc_info=True)
        if window_icons is not None:
            try:
                window_icons.set_collection_active(active)
            except Exception:
                logger.warning("window collection icon projection failed", exc_info=True)


__all__ = ["CollectionIconProjectionHost"]
