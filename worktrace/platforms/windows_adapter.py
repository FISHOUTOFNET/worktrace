from __future__ import annotations

import ctypes
from ctypes import wintypes

import psutil

from .base import ActiveWindow


class WindowsAdapter:
    def get_active_window(self) -> ActiveWindow:
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process_name = ""
        app_name = ""
        try:
            process = psutil.Process(pid)
            process_name = process.name()
            app_name = process_name
        except psutil.Error:
            process_name = "unknown"
            app_name = "unknown"
        return ActiveWindow(app_name=app_name, process_name=process_name, window_title=title)

    def get_idle_seconds(self) -> int:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        last_input = LASTINPUTINFO()
        last_input.cbSize = ctypes.sizeof(last_input)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input)):
            return 0
        tick_count = ctypes.windll.kernel32.GetTickCount()
        return int((tick_count - last_input.dwTime) / 1000)
