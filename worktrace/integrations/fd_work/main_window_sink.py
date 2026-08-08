"""Typed, fail-soft delivery from FD Work into the main WebView."""

from __future__ import annotations

import json
import threading
from typing import Any, Mapping


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
            + ")",
            require_ready=True,
        )

    def picker_result(self, result: Mapping[str, Any]) -> None:
        serialized = json.dumps(dict(result), ensure_ascii=True)
        self._deliver(
            "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkCasePickerResult("
            + serialized
            + ")",
            require_ready=False,
        )

    def _deliver(
        self,
        script: str,
        *,
        require_ready: bool,
    ) -> None:
        with self._lock:
            window = self._window
            ready = self._ready
        if window is None or (require_ready and not ready):
            return
        try:
            window.evaluate_js(script)
        except Exception:
            return


__all__ = ["FDWorkMainWindowSink"]
