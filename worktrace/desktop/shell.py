"""Window/tray state owner outside AppRuntime."""
from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ShellState(str, Enum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    EXITING = "exiting"


class TrayHost(Protocol):
    def start(self) -> bool: ...
    def stop(self) -> None: ...
    def show_background_notice(self) -> None: ...


class DesktopShellController:
    """Own visible/hidden/exiting transitions and the real window exit."""

    def __init__(
        self,
        *,
        window: Any,
        tray: TrayHost,
        initial_hidden: bool = False,
    ) -> None:
        self._window = window
        self._tray = tray
        self._lock = threading.RLock()
        self._tray_available = False
        self._notice_shown = False
        self._exit_requested = False
        self.state = ShellState.HIDDEN if initial_hidden else ShellState.VISIBLE

    @property
    def tray_available(self) -> bool:
        with self._lock:
            return self._tray_available

    def start(self) -> bool:
        try:
            available = self._tray.start() is True
        except Exception:
            logger.exception("Windows tray initialization failed")
            available = False
        with self._lock:
            self._tray_available = available
            initial_hidden = self.state is ShellState.HIDDEN
        if not available:
            logger.error(
                "Windows tray unavailable; window close retains full-exit behavior"
            )
            try:
                self._tray.stop()
            except Exception:
                logger.warning("failed tray initialization cleanup", exc_info=True)
            if initial_hidden:
                self.show_window()
        elif initial_hidden:
            self._set_webview_visibility(False)
        return available

    def handle_window_loaded(self) -> None:
        with self._lock:
            hidden = self.state is ShellState.HIDDEN
        self._set_webview_visibility(not hidden)

    def handle_window_closing(self) -> bool:
        """Return False to cancel pywebview close, True to allow it."""

        with self._lock:
            if self.state is ShellState.EXITING:
                return True
            if not self._tray_available:
                self.state = ShellState.EXITING
                return True
        self.hide_window()
        return False

    def hide_window(self) -> bool:
        with self._lock:
            if (
                self.state is ShellState.EXITING
                or self.state is ShellState.HIDDEN
                or not self._tray_available
            ):
                return False
            self.state = ShellState.HIDDEN
            show_notice = not self._notice_shown
            self._notice_shown = True
        self._set_webview_visibility(False)
        try:
            self._window.hide()
        except Exception:
            logger.exception("desktop shell failed to hide window")
            self.show_window()
            return False
        if show_notice:
            try:
                self._tray.show_background_notice()
            except Exception:
                logger.warning("desktop shell background notice failed", exc_info=True)
        return True

    def show_window(self) -> bool:
        with self._lock:
            if self.state is ShellState.EXITING:
                return False
            already_visible = self.state is ShellState.VISIBLE
            self.state = ShellState.VISIBLE
        if not already_visible:
            try:
                self._window.show()
            except Exception:
                logger.exception("desktop shell failed to show window")
                return False
        try:
            self._window.restore()
        except Exception:
            logger.warning("desktop shell failed to restore window", exc_info=True)
        self._focus_native_window()
        self._set_webview_visibility(True)
        return True

    def exit_application(self) -> bool:
        with self._lock:
            if self._exit_requested:
                return False
            self._exit_requested = True
            self.state = ShellState.EXITING
            tray_available = self._tray_available
            self._tray_available = False
        if tray_available:
            try:
                self._tray.stop()
            except Exception:
                logger.warning("desktop shell tray stop failed", exc_info=True)
        try:
            self._window.destroy()
        except Exception:
            logger.exception("desktop shell failed to destroy window")
        return True

    def stop(self) -> None:
        with self._lock:
            tray_available = self._tray_available
            self._tray_available = False
        if tray_available:
            try:
                self._tray.stop()
            except Exception:
                logger.warning("desktop shell tray cleanup failed", exc_info=True)

    def _set_webview_visibility(self, visible: bool) -> None:
        source = (
            "window.WorkTraceApp && "
            f"window.WorkTraceApp.setShellVisibility({str(visible).lower()});"
        )
        try:
            self._window.evaluate_js(source)
        except Exception:
            logger.debug(
                "desktop shell visibility notification deferred",
                exc_info=True,
            )

    @staticmethod
    def _focus_native_window() -> None:
        try:
            import win32con
            import win32gui

            hwnd = win32gui.FindWindow(None, "WorkTrace")
            if hwnd:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
        except Exception:
            logger.debug("desktop shell foreground request failed", exc_info=True)


__all__ = ["DesktopShellController", "ShellState", "TrayHost"]
