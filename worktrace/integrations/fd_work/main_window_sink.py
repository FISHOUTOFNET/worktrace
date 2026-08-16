"""Typed, fail-soft delivery from FD Work into the main WebView."""

from __future__ import annotations

import json
import threading
from typing import Any, Mapping


def _window_loaded(window: Any) -> bool:
    loaded_event = getattr(getattr(window, "events", None), "loaded", None)
    is_loaded = getattr(loaded_event, "is_set", None)
    if not callable(is_loaded):
        return False
    try:
        return is_loaded() is True
    except Exception:
        return False


class FDWorkMainWindowSink:
    """Own the two public main-window callbacks used by this integration."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window = None
        self._ready = False

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
        try:
            window.evaluate_js(script)
        except Exception:
            return


__all__ = ["FDWorkMainWindowSink"]
