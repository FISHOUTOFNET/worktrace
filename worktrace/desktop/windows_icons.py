"""Windows icon variants and taskbar-window icon projection."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


def load_icon_variant(
    icon_path: Path,
    *,
    active: bool,
    width: int = 0,
    height: int = 0,
):
    """Load the canonical icon, deriving the inactive variant via Win32."""

    import win32con
    import win32gui

    flags = win32con.LR_LOADFROMFILE
    if width <= 0 or height <= 0:
        flags |= win32con.LR_DEFAULTSIZE
        width = 0
        height = 0
    if not active:
        flags |= getattr(win32con, "LR_MONOCHROME", 0x00000001)
    return win32gui.LoadImage(
        0,
        str(Path(icon_path)),
        win32con.IMAGE_ICON,
        int(width),
        int(height),
        flags,
    )


class WindowsWindowIconHost:
    """Project collection state onto the main window/taskbar icon."""

    def __init__(self, *, window_title: str, icon_path: Path) -> None:
        self._window_title = str(window_title)
        self._icon_path = Path(icon_path)
        self._lock = threading.RLock()
        self._collection_active = False
        self._handles: dict[bool, tuple[object, object]] = {}
        self._applied_hwnd: int | None = None
        self._applied_active: bool | None = None

    def set_collection_active(self, active: bool) -> None:
        with self._lock:
            self._collection_active = bool(active)
        self._apply(force=False)

    def refresh(self) -> None:
        self._apply(force=True)

    def stop(self) -> None:
        with self._lock:
            handles = [handle for pair in self._handles.values() for handle in pair]
            self._handles.clear()
            self._applied_hwnd = None
            self._applied_active = None
        if not handles:
            return
        try:
            import win32gui

            for handle in dict.fromkeys(handles):
                try:
                    win32gui.DestroyIcon(handle)
                except Exception:
                    logger.debug("window icon handle cleanup failed", exc_info=True)
        except Exception:
            logger.debug("window icon cleanup unavailable", exc_info=True)

    def _apply(self, *, force: bool) -> None:
        try:
            import win32con
            import win32gui

            hwnd = win32gui.FindWindow(None, self._window_title)
            if not hwnd:
                return
            with self._lock:
                active = self._collection_active
                if (
                    not force
                    and self._applied_hwnd == hwnd
                    and self._applied_active is active
                ):
                    return
                large, small = self._handles_for_state(active)
            wm_seticon = getattr(win32con, "WM_SETICON", 0x0080)
            icon_big = getattr(win32con, "ICON_BIG", 1)
            icon_small = getattr(win32con, "ICON_SMALL", 0)
            win32gui.SendMessage(hwnd, wm_seticon, icon_big, large)
            win32gui.SendMessage(hwnd, wm_seticon, icon_small, small)
            with self._lock:
                self._applied_hwnd = int(hwnd)
                self._applied_active = active
        except Exception:
            logger.debug("main window icon update failed", exc_info=True)

    def _handles_for_state(self, active: bool) -> tuple[object, object]:
        cached = self._handles.get(active)
        if cached is not None:
            return cached

        import win32api
        import win32con

        large_width = win32api.GetSystemMetrics(getattr(win32con, "SM_CXICON", 11))
        large_height = win32api.GetSystemMetrics(getattr(win32con, "SM_CYICON", 12))
        small_width = win32api.GetSystemMetrics(getattr(win32con, "SM_CXSMICON", 49))
        small_height = win32api.GetSystemMetrics(getattr(win32con, "SM_CYSMICON", 50))
        pair = (
            load_icon_variant(
                self._icon_path,
                active=active,
                width=large_width,
                height=large_height,
            ),
            load_icon_variant(
                self._icon_path,
                active=active,
                width=small_width,
                height=small_height,
            ),
        )
        self._handles[active] = pair
        return pair


__all__ = ["WindowsWindowIconHost", "load_icon_variant"]
