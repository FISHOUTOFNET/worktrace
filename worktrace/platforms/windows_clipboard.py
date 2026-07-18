"""Instance-owned Windows clipboard capture component."""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime
from typing import Callable

from ..constants import TIME_FORMAT
from .base import ActiveWindow, ClipboardTextEvent

_MAX_CLIPBOARD_QUEUE = 100


def clipboard_sequence_number() -> int | None:
    try:
        import win32clipboard

        return int(win32clipboard.GetClipboardSequenceNumber())
    except Exception:
        logging.debug("clipboard sequence read failed", exc_info=True)
        return None


def read_clipboard_unicode_text() -> str | None:
    opened = False
    try:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        opened = True
        if not win32clipboard.IsClipboardFormatAvailable(
            win32con.CF_UNICODETEXT
        ):
            return None
        value = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        text = str(value or "")
        return text if text else None
    except Exception:
        logging.debug("clipboard text read failed", exc_info=True)
        return None
    finally:
        if opened:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                logging.debug("clipboard close failed", exc_info=True)


class ClipboardMonitor:
    """Privacy-gated clipboard monitor with explicit lifecycle ownership."""

    def __init__(
        self,
        source_window_provider: Callable[[], ActiveWindow],
        *,
        poll_seconds: float = 0.25,
    ) -> None:
        self._events: deque[ClipboardTextEvent] = deque(
            maxlen=_MAX_CLIPBOARD_QUEUE
        )
        self._events_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._enabled = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_sequence: int | None = None
        self._generation = 0
        self._source_window_provider = source_window_provider
        self._poll_seconds = max(0.05, float(poll_seconds))

    def set_enabled(self, enabled: bool) -> None:
        with self._lifecycle_lock:
            requested = bool(enabled)
            if requested == self._enabled:
                if not requested:
                    self._clear_locked()
                return
            self._generation += 1
            self._enabled = requested
            self._last_sequence = None
            if not requested:
                self._clear_locked()
                return
            if self._thread is None or not self._thread.is_alive():
                self._stop_event.clear()
                self._thread = threading.Thread(
                    target=self._run,
                    name="WorkTraceClipboardMonitor",
                    daemon=True,
                )
                self._thread.start()

    def drain(self) -> list[ClipboardTextEvent]:
        with self._lifecycle_lock:
            if not self._enabled:
                self._clear_locked()
                return []
            with self._events_lock:
                events = list(self._events)
                self._events.clear()
            return events

    def clear(self) -> None:
        with self._lifecycle_lock:
            self._clear_locked()

    def _clear_locked(self) -> None:
        with self._events_lock:
            self._events.clear()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            self._generation += 1
            self._enabled = False
            self._last_sequence = None
            self._stop_event.set()
            self._clear_locked()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop_event.wait(self._poll_seconds):
            try:
                with self._lifecycle_lock:
                    if not self._enabled:
                        continue
                    sequence = clipboard_sequence_number()
                    if sequence is None:
                        continue
                    if self._last_sequence is None:
                        self._last_sequence = sequence
                        continue
                    if sequence == self._last_sequence:
                        continue
                    self._last_sequence = sequence
                    self._capture_locked(sequence, self._generation)
            except Exception:
                logging.debug(
                    "clipboard monitor loop failed",
                    exc_info=True,
                )

    def _capture_locked(self, sequence: int, generation: int) -> None:
        if not self._enabled or generation != self._generation:
            return
        # Bind the source before reading text so a subsequent window switch
        # cannot relabel the copied content.
        source_window = self._source_window_provider()
        text = read_clipboard_unicode_text()
        if (
            not text
            or not self._enabled
            or generation != self._generation
        ):
            return
        event = ClipboardTextEvent(
            text=text,
            source_window=source_window,
            copied_at=datetime.now().strftime(TIME_FORMAT),
            sequence_number=sequence,
        )
        with self._events_lock:
            if self._enabled and generation == self._generation:
                self._events.append(event)


__all__ = [
    "ClipboardMonitor",
    "clipboard_sequence_number",
    "read_clipboard_unicode_text",
]
