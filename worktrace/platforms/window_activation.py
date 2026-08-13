"""Narrow pywebview window activation helpers for native desktop windows."""
from __future__ import annotations

import logging
import sys
from typing import Any

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


def _debug(logger: logging.Logger | None, message: str, *, exc_info: bool = False) -> None:
    if logger is not None:
        logger.debug(message, exc_info=exc_info)


def native_window_handle(
    window: Any,
    *,
    fallback_title: str | None = None,
    logger: logging.Logger | None = None,
) -> int:
    """Return a stable native HWND when available without making it an owner."""

    native = getattr(window, "native", None)
    handle = getattr(native, "Handle", None)
    for converter_name in ("ToInt64", "ToInt32"):
        converter = getattr(handle, converter_name, None)
        if callable(converter):
            try:
                hwnd = int(converter())
                if hwnd > 0:
                    return hwnd
            except Exception:
                _debug(logger, "native window handle lookup failed", exc_info=True)
    if handle is not None:
        try:
            hwnd = int(handle)
            if hwnd > 0:
                return hwnd
        except Exception:
            _debug(logger, "native window handle conversion failed", exc_info=True)

    if not sys.platform.startswith("win") or not fallback_title:
        return 0
    try:
        import win32gui

        return int(win32gui.FindWindow(None, fallback_title) or 0)
    except Exception:
        _debug(logger, "fallback window handle lookup failed", exc_info=True)
        return 0


def make_window_activatable(
    window: Any,
    *,
    fallback_title: str | None = None,
    logger: logging.Logger | None = None,
) -> bool:
    """Remove pywebview's background-only no-activate state before interaction."""

    try:
        focus_value = getattr(window, "focus", None)
        if not callable(focus_value):
            window.focus = True
    except Exception:
        _debug(logger, "failed to enable pywebview window focus", exc_info=True)

    if not sys.platform.startswith("win"):
        return True

    try:
        import win32gui

        hwnd = native_window_handle(
            window,
            fallback_title=fallback_title,
            logger=logger,
        )
        if hwnd <= 0:
            return False
        ex_style = int(win32gui.GetWindowLong(hwnd, GWL_EXSTYLE))
        if ex_style & WS_EX_NOACTIVATE:
            win32gui.SetWindowLong(
                hwnd,
                GWL_EXSTYLE,
                ex_style & ~WS_EX_NOACTIVATE,
            )
            set_window_pos = getattr(win32gui, "SetWindowPos", None)
            if callable(set_window_pos):
                set_window_pos(
                    hwnd,
                    0,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOSIZE
                    | SWP_NOMOVE
                    | SWP_NOZORDER
                    | SWP_NOACTIVATE
                    | SWP_FRAMECHANGED,
                )
        return True
    except Exception:
        _debug(logger, "failed to clear no-activate window style", exc_info=True)
        return False


def request_window_foreground(
    window: Any,
    *,
    fallback_title: str | None = None,
    restore: bool = True,
    logger: logging.Logger | None = None,
) -> bool:
    """Best-effort native foreground request after the window is activatable."""

    if not sys.platform.startswith("win"):
        return False
    try:
        import win32gui

        hwnd = native_window_handle(
            window,
            fallback_title=fallback_title,
            logger=logger,
        )
        if hwnd <= 0:
            return False
        if restore:
            win32gui.ShowWindow(hwnd, SW_RESTORE)
        result = win32gui.SetForegroundWindow(hwnd)
        return result is not False
    except Exception:
        _debug(logger, "native foreground request failed", exc_info=True)
        return False


__all__ = [
    "GWL_EXSTYLE",
    "SW_RESTORE",
    "SWP_FRAMECHANGED",
    "SWP_NOACTIVATE",
    "SWP_NOMOVE",
    "SWP_NOSIZE",
    "SWP_NOZORDER",
    "WS_EX_NOACTIVATE",
    "make_window_activatable",
    "native_window_handle",
    "request_window_foreground",
]
