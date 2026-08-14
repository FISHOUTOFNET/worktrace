"""Minimal pywin32 notification-area host."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from .windows_icons import load_icon_variant

logger = logging.getLogger(__name__)


class WindowsTrayHost:
    """Own one Explorer notification icon and send shell commands only."""

    _WM_TRAY = 0x0400 + 20
    _WM_STOP = 0x0400 + 21
    _CMD_OPEN = 1001
    _CMD_EXIT = 1002

    def __init__(
        self,
        *,
        icon_path: Path,
        on_open: Callable[[], object],
        on_exit: Callable[[], object],
    ) -> None:
        self._icon_path = Path(icon_path)
        self._on_open = on_open
        self._on_exit = on_exit
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._failed = threading.Event()
        self._stop_requested = threading.Event()
        self._hwnd: int | None = None
        self._active_icon_handle = None
        self._inactive_icon_handle = None
        self._icon_handle = None
        self._collection_active = False
        self._taskbar_created = 0
        self._deleted = False

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None:
                return self._ready.is_set() and not self._failed.is_set()
            if not self._icon_path.is_file():
                logger.error("tray icon missing: %s", self._icon_path)
                self._failed.set()
                return False
            self._stop_requested.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="WorkTraceWindowsTray",
                daemon=True,
            )
            self._thread.start()
        if not self._ready.wait(5.0):
            logger.error("tray initialization timed out")
            self._failed.set()
        return self._ready.is_set() and not self._failed.is_set()

    def stop(self) -> None:
        self._stop_requested.set()
        with self._lock:
            thread = self._thread
            hwnd = self._hwnd
            self._thread = None
        if thread is None:
            return
        if hwnd:
            try:
                import win32gui

                win32gui.PostMessage(hwnd, self._WM_STOP, 0, 0)
            except Exception:
                logger.warning("tray stop post failed", exc_info=True)
        if thread is not threading.current_thread():
            thread.join(timeout=5.0)

    def set_collection_active(self, active: bool) -> None:
        """Switch the notification icon without changing collector ownership."""

        with self._lock:
            active = bool(active)
            if self._collection_active is active and self._icon_handle is not None:
                return
            self._collection_active = active
            hwnd = self._hwnd
            icon = (
                self._active_icon_handle if active else self._inactive_icon_handle
            )
            if not hwnd or not icon:
                return
            self._icon_handle = icon
        try:
            import win32gui

            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, self._notify_data())
        except Exception:
            logger.warning("tray collection icon update failed", exc_info=True)

    def show_background_notice(self) -> None:
        with self._lock:
            hwnd = self._hwnd
            icon = self._icon_handle
        if not hwnd or not icon:
            return
        import win32gui

        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        flags |= getattr(win32gui, "NIF_INFO", 0x10)
        data = (
            hwnd,
            0,
            flags,
            self._WM_TRAY,
            icon,
            "WorkTrace",
            "WorkTrace 仍在后台记录，可右键通知区域图标退出。",
            5000,
            "WorkTrace",
        )
        win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, data)

    def _notify_data(self):
        import win32gui

        with self._lock:
            return (
                self._hwnd,
                0,
                win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                self._WM_TRAY,
                self._icon_handle,
                "WorkTrace",
            )

    def _add_icon(self) -> None:
        import win32gui

        self._deleted = False
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self._notify_data())

    def _delete_icon(self) -> None:
        if self._deleted or not self._hwnd:
            return
        self._deleted = True
        try:
            import win32gui

            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self._hwnd, 0))
        except Exception:
            logger.warning("tray icon deletion failed", exc_info=True)

    def _destroy_icon_handles(self) -> None:
        with self._lock:
            handles = [self._active_icon_handle, self._inactive_icon_handle]
            self._active_icon_handle = None
            self._inactive_icon_handle = None
            self._icon_handle = None
        try:
            import win32gui

            for handle in dict.fromkeys(handle for handle in handles if handle):
                try:
                    win32gui.DestroyIcon(handle)
                except Exception:
                    logger.debug("tray icon handle cleanup failed", exc_info=True)
        except Exception:
            logger.debug("tray icon cleanup unavailable", exc_info=True)

    def _run(self) -> None:
        try:
            import win32api
            import win32con
            import win32gui

            self._taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
            message_map = {
                self._WM_TRAY: self._on_tray_message,
                self._WM_STOP: self._on_stop,
                win32con.WM_COMMAND: self._on_command,
                win32con.WM_DESTROY: self._on_destroy,
                self._taskbar_created: self._on_taskbar_created,
            }
            class_name = f"WorkTraceTrayHost_{id(self)}"
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = class_name
            wc.lpfnWndProc = message_map
            win32gui.RegisterClass(wc)
            self._hwnd = win32gui.CreateWindow(
                class_name,
                "WorkTrace Tray Host",
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                wc.hInstance,
                None,
            )
            self._active_icon_handle = load_icon_variant(
                self._icon_path,
                active=True,
            )
            self._inactive_icon_handle = load_icon_variant(
                self._icon_path,
                active=False,
            )
            with self._lock:
                self._icon_handle = (
                    self._active_icon_handle
                    if self._collection_active
                    else self._inactive_icon_handle
                )
            self._add_icon()
            self._ready.set()
            if self._stop_requested.is_set():
                self._delete_icon()
                win32gui.DestroyWindow(self._hwnd)
            else:
                win32gui.PumpMessages()
        except Exception:
            logger.exception("tray host failed")
            self._failed.set()
            self._ready.set()
        finally:
            self._delete_icon()
            self._destroy_icon_handles()
            with self._lock:
                self._hwnd = None

    def _on_tray_message(self, hwnd, _msg, _wparam, lparam):
        import win32con

        if lparam == win32con.WM_LBUTTONDBLCLK:
            self._on_open()
        elif lparam == win32con.WM_RBUTTONUP:
            self._show_menu(hwnd)
        return 0

    def _show_menu(self, hwnd) -> None:
        import win32api
        import win32con
        import win32gui

        menu = win32gui.CreatePopupMenu()
        try:
            win32gui.AppendMenu(menu, win32con.MF_STRING, self._CMD_OPEN, "打开 WorkTrace")
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(menu, win32con.MF_STRING, self._CMD_EXIT, "退出 WorkTrace")
            x, y = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(hwnd)
            win32gui.TrackPopupMenu(
                menu,
                win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON,
                x,
                y,
                0,
                hwnd,
                None,
            )
            win32api.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        finally:
            win32gui.DestroyMenu(menu)

    def _on_command(self, _hwnd, _msg, wparam, _lparam):
        command = int(wparam) & 0xFFFF
        if command == self._CMD_OPEN:
            self._on_open()
        elif command == self._CMD_EXIT:
            self._on_exit()
        return 0

    def _on_taskbar_created(self, _hwnd, _msg, _wparam, _lparam):
        try:
            self._add_icon()
        except Exception:
            logger.exception("tray icon re-registration failed")
        return 0

    def _on_stop(self, hwnd, _msg, _wparam, _lparam):
        import win32gui

        self._delete_icon()
        win32gui.DestroyWindow(hwnd)
        return 0

    def _on_destroy(self, _hwnd, _msg, _wparam, _lparam):
        import win32gui

        self._delete_icon()
        win32gui.PostQuitMessage(0)
        return 0


__all__ = ["WindowsTrayHost"]
