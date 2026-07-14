from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections import deque
from ctypes import wintypes
from datetime import datetime

from ..constants import TIME_FORMAT
from . import windows_adapter as legacy
from .base import ActiveWindow, ClipboardTextEvent

_PATH_SUCCESS_TTL_SECONDS = 3.0
_PATH_FAILURE_TTL_SECONDS = 0.75
_MAX_PATH_CACHE = 256
_MAX_CLIPBOARD_QUEUE = 100
_RESOLVER_CAPACITY = 2

_timeout_slots = threading.BoundedSemaphore(_RESOLVER_CAPACITY)


def _bounded_run_with_timeout(func, timeout_seconds: float, *args):
    """Bound abandoned blocking workers so repeated COM hangs cannot grow forever."""
    if not _timeout_slots.acquire(blocking=False):
        raise TimeoutError("blocking resolver capacity exhausted")
    result_box: list = [None]
    exc_box: list = [None]
    done = threading.Event()

    def worker() -> None:
        try:
            result_box[0] = func(*args)
        except Exception as exc:  # pragma: no cover - forwarded below
            exc_box[0] = exc
        finally:
            done.set()
            _timeout_slots.release()

    threading.Thread(target=worker, daemon=True).start()
    if not done.wait(timeout_seconds):
        raise TimeoutError(f"call timed out after {timeout_seconds:.1f}s")
    if exc_box[0] is not None:
        raise exc_box[0]
    return result_box[0]


# The existing catalog/resolver remains the single source of application-specific
# COM knowledge.  Only its timeout primitive is replaced with a bounded one.
legacy._run_with_timeout = _bounded_run_with_timeout


class HardenedWindowsAdapter:
    """Shipping Windows adapter with explicit, resettable runtime lifecycle."""

    def __init__(self) -> None:
        self._clipboard = _ClipboardMonitor()
        self._path_lock = threading.Lock()
        self._path_cache: dict[
            tuple[int | None, int | None, str, str], tuple[float, str | None]
        ] = {}

    def get_active_window(self) -> ActiveWindow:
        import psutil
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process_name = "unknown"
        app_name = "unknown"
        process_create_time: float | None = None
        try:
            process = psutil.Process(pid)
            process_name = process.name()
            app_name = process_name
            process_create_time = float(process.create_time())
        except psutil.Error:
            pass

        cache_key = (hwnd, pid, process_name, title)
        file_path_hint = legacy._resolve_title_file_path(title)
        if not file_path_hint:
            file_path_hint = self._cached_path(cache_key)
        if not file_path_hint:
            # Resolve before returning the first sample.  This prevents a
            # folder-only exclusion rule from seeing a real title before the
            # corresponding path is known.  The legacy resolver has its own
            # per-source timeouts and the global bounded timeout primitive.
            try:
                file_path_hint = legacy._resolve_active_file_path(
                    process_name,
                    title,
                    pid,
                )
            except Exception:
                logging.debug("synchronous active path resolution failed", exc_info=True)
                file_path_hint = None
            self._store_path(cache_key, file_path_hint)

        window_class = None
        try:
            window_class = win32gui.GetClassName(hwnd) or None
        except Exception:
            pass
        return ActiveWindow(
            app_name=app_name,
            process_name=process_name,
            window_title=title,
            file_path_hint=file_path_hint,
            pid=pid,
            hwnd=hwnd,
            window_class=window_class,
        )

    def _cached_path(
        self,
        key: tuple[int | None, int | None, str, str],
    ) -> str | None:
        now = time.monotonic()
        with self._path_lock:
            entry = self._path_cache.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._path_cache.pop(key, None)
                return None
            return value

    def _store_path(
        self,
        key: tuple[int | None, int | None, str, str],
        value: str | None,
    ) -> None:
        ttl = _PATH_SUCCESS_TTL_SECONDS if value else _PATH_FAILURE_TTL_SECONDS
        with self._path_lock:
            if len(self._path_cache) >= _MAX_PATH_CACHE:
                self._path_cache.clear()
            self._path_cache[key] = (time.monotonic() + ttl, value)

    def get_idle_seconds(self) -> int:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        last_input = LASTINPUTINFO()
        last_input.cbSize = ctypes.sizeof(last_input)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input)):
            return 0
        get_tick_count64 = ctypes.windll.kernel32.GetTickCount64
        get_tick_count64.restype = ctypes.c_ulonglong
        current_low = int(get_tick_count64()) & 0xFFFFFFFF
        elapsed_ms = (current_low - int(last_input.dwTime)) & 0xFFFFFFFF
        return max(0, elapsed_ms // 1000)

    def set_clipboard_capture_enabled(self, enabled: bool) -> None:
        self._clipboard.set_enabled(bool(enabled))

    def get_clipboard_events(self) -> list[ClipboardTextEvent]:
        return self._clipboard.drain()

    def reset_runtime_state(self) -> None:
        self._clipboard.set_enabled(False)
        self._clipboard.clear()
        with self._path_lock:
            self._path_cache.clear()

    def shutdown(self) -> None:
        self._clipboard.shutdown()
        with self._path_lock:
            self._path_cache.clear()


class _ClipboardMonitor:
    def __init__(self) -> None:
        self._events: deque[ClipboardTextEvent] = deque(maxlen=_MAX_CLIPBOARD_QUEUE)
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._enabled = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_sequence: int | None = None

    def set_enabled(self, enabled: bool) -> None:
        with self._lifecycle_lock:
            if not enabled:
                self._enabled = False
                self._last_sequence = None
                self.clear()
                return
            self._enabled = True
            if self._thread is None or not self._thread.is_alive():
                self._stop_event.clear()
                self._thread = threading.Thread(
                    target=self._run,
                    name="WorkTraceClipboardMonitor",
                    daemon=True,
                )
                self._thread.start()

    def drain(self) -> list[ClipboardTextEvent]:
        if not self._enabled:
            self.clear()
            return []
        with self._lock:
            events = list(self._events)
            self._events.clear()
        return events

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            self._enabled = False
            self._stop_event.set()
            thread = self._thread
        self.clear()
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop_event.wait(0.25):
            if not self._enabled:
                continue
            try:
                sequence = legacy._clipboard_sequence_number()
                if sequence is None:
                    continue
                if self._last_sequence is None:
                    self._last_sequence = sequence
                    continue
                if sequence != self._last_sequence:
                    self._last_sequence = sequence
                    self._capture(sequence)
            except Exception:
                logging.debug("clipboard monitor loop failed", exc_info=True)

    def _capture(self, sequence: int) -> None:
        if not self._enabled:
            return
        text = legacy._read_clipboard_unicode_text()
        if not text or not self._enabled:
            return
        event = ClipboardTextEvent(
            text=text,
            source_window=self._source_window(),
            copied_at=datetime.now().strftime(TIME_FORMAT),
            sequence_number=sequence,
        )
        with self._lock:
            if self._enabled:
                self._events.append(event)

    @staticmethod
    def _source_window() -> ActiveWindow:
        # Clipboard source resolution is deliberately lightweight.  The
        # collector's privacy check will re-evaluate this window before binding.
        return legacy._get_foreground_active_window()


__all__ = ["HardenedWindowsAdapter"]
