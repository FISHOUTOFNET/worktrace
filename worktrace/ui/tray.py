from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
from dataclasses import dataclass
from ctypes import wintypes


WM_TRAY_NOTIFY = 0x0400 + 31
WM_TRAY_REFRESH = 0x0400 + 32
TRAY_UID = 1
MENU_SHOW = 1001
MENU_TOGGLE = 1002
MENU_EXIT = 1003


@dataclass
class TrayState:
    status_text: str = "采集器未运行"
    is_recording: bool = False
    is_paused: bool = False


def create_tray_controller():
    if not sys.platform.startswith("win"):
        return None
    return WindowsNativeTray()


class WindowsNativeTray:
    def __init__(self) -> None:
        self._actions: queue.Queue[str] = queue.Queue()
        self._state = TrayState()
        self._state_lock = threading.Lock()
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._started = False
        self._failed = False
        self._hwnd: int | None = None
        self._thread: threading.Thread | None = None
        self._win32gui = None
        self._win32con = None
        self._icons: dict[str, int] = {}

    def start(self) -> bool:
        if self._started:
            return True
        self._thread = threading.Thread(target=self._run, name="WorkTraceTray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)
        self._started = bool(self._hwnd) and not self._failed
        return self._started

    def stop(self) -> None:
        self._stop_requested.set()
        win32gui = self._win32gui
        hwnd = self._hwnd
        if win32gui is not None and hwnd:
            try:
                win32gui.PostMessage(hwnd, self._win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)

    def drain_actions(self) -> list[str]:
        actions: list[str] = []
        while True:
            try:
                actions.append(self._actions.get_nowait())
            except queue.Empty:
                return actions

    def update_state(self, status_text: str, is_recording: bool, is_paused: bool = False) -> None:
        with self._state_lock:
            self._state = TrayState(status_text=status_text, is_recording=is_recording, is_paused=is_paused)
        win32gui = self._win32gui
        hwnd = self._hwnd
        if win32gui is not None and hwnd:
            try:
                win32gui.PostMessage(hwnd, WM_TRAY_REFRESH, 0, 0)
            except Exception:
                pass

    def _run(self) -> None:
        try:
            import win32api
            import win32con
            import win32gui

            self._win32gui = win32gui
            self._win32con = win32con
            self._icons = {
                "recording": _create_circle_icon((15, 139, 95)),
                "paused": _create_circle_icon((100, 116, 139)),
            }

            hinstance = win32api.GetModuleHandle(None)
            class_name = "WorkTraceTrayWindow"

            def wndproc(hwnd, message, wparam, lparam):
                return self._handle_message(hwnd, message, wparam, lparam)

            wndclass = win32gui.WNDCLASS()
            wndclass.hInstance = hinstance
            wndclass.lpszClassName = class_name
            wndclass.lpfnWndProc = wndproc
            try:
                win32gui.RegisterClass(wndclass)
            except Exception:
                pass
            hwnd = win32gui.CreateWindow(
                class_name,
                "WorkTrace Tray",
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                hinstance,
                None,
            )
            self._hwnd = hwnd
            self._add_or_update_icon(add=True)
            self._ready.set()
            win32gui.PumpMessages()
        except Exception:
            self._failed = True
            self._ready.set()
            logging.exception("failed to initialize WorkTrace tray")
        finally:
            self._delete_icon()
            self._destroy_icons()
            self._hwnd = None

    def _handle_message(self, hwnd, message, wparam, lparam):
        win32gui = self._win32gui
        win32con = self._win32con
        if win32gui is None or win32con is None:
            return 0
        if message == WM_TRAY_REFRESH:
            self._add_or_update_icon(add=False)
            return 0
        if message == WM_TRAY_NOTIFY:
            if int(lparam) == win32con.WM_LBUTTONDBLCLK:
                self._actions.put("show")
            elif int(lparam) == win32con.WM_RBUTTONUP:
                self._show_menu(hwnd)
            return 0
        if message == win32con.WM_COMMAND:
            command = int(wparam) & 0xFFFF
            if command == MENU_SHOW:
                self._actions.put("show")
            elif command == MENU_TOGGLE:
                self._actions.put("toggle")
            elif command == MENU_EXIT:
                self._actions.put("exit")
            return 0
        if message == win32con.WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
            return 0
        if message == win32con.WM_DESTROY:
            self._delete_icon()
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def _show_menu(self, hwnd) -> None:
        win32gui = self._win32gui
        win32con = self._win32con
        if win32gui is None or win32con is None:
            return
        with self._state_lock:
            state = self._state
        menu = win32gui.CreatePopupMenu()
        try:
            toggle_text = "暂停记录" if state.is_recording else "继续记录"
            win32gui.AppendMenu(menu, win32con.MF_STRING, MENU_SHOW, "显示 WorkTrace")
            win32gui.AppendMenu(menu, win32con.MF_STRING, MENU_TOGGLE, toggle_text)
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, None)
            win32gui.AppendMenu(menu, win32con.MF_STRING, MENU_EXIT, "退出 WorkTrace")
            x, y = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(hwnd)
            win32gui.TrackPopupMenu(menu, win32con.TPM_RIGHTBUTTON, x, y, 0, hwnd, None)
            win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        finally:
            try:
                win32gui.DestroyMenu(menu)
            except Exception:
                pass

    def _add_or_update_icon(self, add: bool) -> None:
        win32gui = self._win32gui
        win32con = self._win32con
        hwnd = self._hwnd
        if win32gui is None or win32con is None or not hwnd:
            return
        with self._state_lock:
            state = self._state
        icon = self._icons["recording" if state.is_recording else "paused"]
        tooltip = f"有迹 WorkTrace - {state.status_text}"[:127]
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        data = (hwnd, TRAY_UID, flags, WM_TRAY_NOTIFY, icon, tooltip)
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD if add else win32gui.NIM_MODIFY, data)
        except Exception:
            if not add:
                win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, data)

    def _delete_icon(self) -> None:
        win32gui = self._win32gui
        hwnd = self._hwnd
        if win32gui is None or not hwnd:
            return
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, TRAY_UID))
        except Exception:
            pass

    def _destroy_icons(self) -> None:
        win32gui = self._win32gui
        if win32gui is None:
            return
        for icon in self._icons.values():
            try:
                win32gui.DestroyIcon(icon)
            except Exception:
                pass
        self._icons = {}


def _create_circle_icon(rgb: tuple[int, int, int], size: int = 32) -> int:
    row_mask_bytes = ((size + 31) // 32) * 4
    and_mask = bytearray()
    xor_bits = bytearray()
    radius = size * 0.34
    center = (size - 1) / 2
    red, green, blue = rgb
    for y in reversed(range(size)):
        mask_row = bytearray(row_mask_bytes)
        for x in range(size):
            inside = (x - center) ** 2 + (y - center) ** 2 <= radius**2
            if inside:
                xor_bits.extend((blue, green, red, 255))
            else:
                xor_bits.extend((0, 0, 0, 0))
                mask_row[x // 8] |= 0x80 >> (x % 8)
        and_mask.extend(mask_row)
    create_icon = ctypes.windll.user32.CreateIcon
    create_icon.argtypes = [
        wintypes.HINSTANCE,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_ubyte,
        ctypes.c_ubyte,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    create_icon.restype = wintypes.HICON
    and_buffer = ctypes.create_string_buffer(bytes(and_mask))
    xor_buffer = ctypes.create_string_buffer(bytes(xor_bits))
    icon = create_icon(
        None,
        size,
        size,
        1,
        32,
        and_buffer,
        xor_buffer,
    )
    if not icon:
        raise ctypes.WinError()
    return int(icon)
