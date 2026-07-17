"""Canonical Windows platform adapter."""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

from ..resources.title_parsing import extract_file_name_from_title
from ..services.folder_index_query_service import resolve_unique_path_from_title
from .base import ActiveWindow, ClipboardTextEvent
from .windows_clipboard import ClipboardMonitor
from .windows_path_resolver import (
    WindowsPathResolver,
    _match_open_file_path,
    resolve_title_file_path,
)


class CanonicalWindowsPathResolver(WindowsPathResolver):
    """Path resolver whose folder-index dependency is a deterministic read model."""

    def resolve(
        self,
        window_key: tuple,
        process_name: str,
        title: str,
        pid: int,
    ) -> str | None:
        current = time.monotonic()
        cached = self._cache.get(window_key)
        if cached and current - cached[0] < self._cache_seconds:
            return cached[1]
        negative_until = self._negative_cache.get(window_key)
        if negative_until and current < negative_until:
            return None

        title_path = resolve_title_file_path(title)
        if title_path:
            self._remember(window_key, title_path, current)
            return title_path

        title_file = extract_file_name_from_title(title)
        result: str | None = None
        try:
            result = self._run_with_timeout(
                lambda: _match_open_file_path(
                    title_file or "",
                    self._com_paths(process_name),
                ),
                self._com_timeout_seconds,
            )
        except Exception:
            logging.debug("COM path resolver failed", exc_info=True)
        if not result and title_file:
            try:
                result = self._run_with_timeout(
                    lambda: _match_open_file_path(
                        title_file,
                        self._get_process_open_file_paths(pid),
                    ),
                    self._process_timeout_seconds,
                )
            except Exception:
                logging.debug("open-file path resolver failed", exc_info=True)
        if not result and title_file:
            result = resolve_unique_path_from_title(
                title,
                include_excluded=True,
            )
        self._remember(window_key, result, current)
        return result


class WindowsAdapter:
    """Explicit, resettable owner of Windows collection resources."""

    def __init__(
        self,
        *,
        path_resolver: WindowsPathResolver | None = None,
    ) -> None:
        self._path_resolver = path_resolver or CanonicalWindowsPathResolver()
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
            pass
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

    def reset_runtime_state(self) -> None:
        self._clipboard.set_enabled(False)
        self._clipboard.clear()
        self._path_resolver.reset()

    def shutdown(self) -> None:
        self._clipboard.shutdown()
        self._path_resolver.reset()


__all__ = ["CanonicalWindowsPathResolver", "WindowsAdapter"]
