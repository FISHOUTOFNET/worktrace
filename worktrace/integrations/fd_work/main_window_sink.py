"""Typed, fail-soft delivery from FD Work into the main WebView."""

from __future__ import annotations

import json
import queue
import threading
from typing import Any, Mapping


def _window_loaded(window: Any) -> bool:
    events = getattr(window, "events", None)
    if events is None:
        # Non-pywebview test doubles and legacy adapters use the explicit ready
        # gate only. Shipping pywebview windows always expose lifecycle events.
        return True
    loaded_event = getattr(events, "loaded", None)
    is_loaded = getattr(loaded_event, "is_set", None)
    if not callable(is_loaded):
        return False
    try:
        return is_loaded() is True
    except Exception:
        return False


class FDWorkMainWindowSink:
    """Own the two public main-window callbacks used by this integration."""

    def __init__(
        self,
        *,
        deliver_asynchronously: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._window = None
        self._ready = False
        self._delivery_queue: queue.Queue[tuple[Any, str]] | None = None
        if deliver_asynchronously:
            self._delivery_queue = queue.Queue()
            threading.Thread(
                target=self._run_delivery_worker,
                name="fd-work-main-window-sink",
                daemon=True,
            ).start()

    def bind_window(self, window) -> None:
        with self._lock:
            self._window = window

    def mark_ready(self) -> None:
        with self._lock:
            self._ready = True

    def mark_unavailable(self) -> None:
        with self._lock:
            self._ready = False
            self._window = None

    def status_changed(self, status: Mapping[str, Any]) -> None:
        serialized = json.dumps(dict(status), ensure_ascii=True)
        self._deliver(
            "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkStatus("
            + serialized
            + ")"
        )

    def picker_result(self, result: Mapping[str, Any]) -> None:
        serialized = json.dumps(dict(result), ensure_ascii=True)
        self._deliver(
            "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkCasePickerResult("
            + serialized
            + ")"
        )

    def _deliver(self, script: str) -> None:
        with self._lock:
            window = self._window
            ready = self._ready
        # pywebview's EdgeChromium evaluate_js waits for the WinForms UI thread.
        # FD Work can emit navigation status while that thread is still creating
        # windows, so never enter evaluate_js until the main WebView itself loaded.
        if window is None or not ready or not _window_loaded(window):
            return
        delivery_queue = self._delivery_queue
        if delivery_queue is not None:
            # Keep one FIFO worker between FD Work lifecycle callbacks and
            # evaluate_js. This lets the GUI callback return before JS delivery
            # starts while preserving arrival order and avoiding one thread per
            # status update.
            delivery_queue.put_nowait((window, script))
            return
        self._evaluate(window, script)

    def _run_delivery_worker(self) -> None:
        delivery_queue = self._delivery_queue
        if delivery_queue is None:
            return
        while True:
            window, script = delivery_queue.get()
            try:
                with self._lock:
                    current_window = self._window
                    ready = self._ready
                # Revalidate at execution time. A queued notification must never
                # be delivered to a closed or rebound main window.
                if (
                    current_window is not window
                    or not ready
                    or not _window_loaded(window)
                ):
                    continue
                self._evaluate(window, script)
            finally:
                delivery_queue.task_done()

    @staticmethod
    def _evaluate(window: Any, script: str) -> None:
        try:
            window.evaluate_js(script)
        except Exception:
            return


__all__ = ["FDWorkMainWindowSink"]
