"""Canonical Windows platform adapter."""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

from ..worker_health import WorkerHealthReporter
from .base import ActiveWindow, ClipboardTextEvent
from .windows_clipboard import ClipboardMonitor
from .windows_path_resolver import WindowsPathResolver, resolve_title_file_path


class WindowsAdapter:
    """Explicit, resettable owner of Windows collection resources."""

    def __init__(
        self,
        *,
        path_resolver: WindowsPathResolver | None = None,
    ) -> None:
        self._path_resolver = path_resolver or WindowsPathResolver()
        self._clipboard = ClipboardMonitor(self.get_active_window)

    def get_active_window(self) -> ActiveWindow:
        import psutil
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process_name = "unknown"
        app_name = "unknown"
        try:
            process = psutil.Process(pid)
            process_name = process.name()
            app_name = process_name
        except psutil.Error:
            pass

        requires_path = self._path_resolver.privacy_path_required(process_name, title)
        file_path_hint = resolve_title_file_path(title)
        if not file_path_hint and requires_path:
            file_path_hint = self._path_resolver.resolve(
                (hwnd, pid, process_name, title),
                process_name,
                title,
                pid,
            )

        window_class = None
        try:
            window_class = win32gui.GetClassName(hwnd) or None
        except Exception:
            logging.debug("active window class lookup failed", exc_info=True)
        return ActiveWindow(
            app_name=app_name,
            process_name=process_name,
            window_title=title,
            file_path_hint=file_path_hint,
            pid=pid,
            hwnd=hwnd,
            window_class=window_class,
            privacy_path_required=requires_path,
        )

    def get_idle_seconds(self) -> int:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwTime", wintypes.DWORD),
            ]

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

    def run_clipboard_capture(
        self,
        stop_event: threading.Event,
        *,
        health: WorkerHealthReporter,
    ) -> None:
        self._clipboard.run(stop_event, health=health)

    def reset_runtime_state(self) -> None:
        self._clipboard.reset()
        self._path_resolver.reset()

    def shutdown(self) -> None:
        self._clipboard.shutdown()
        self._path_resolver.reset()


__all__ = ["WindowsAdapter"]
