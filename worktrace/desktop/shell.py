"""Window/tray state owner outside AppRuntime."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
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


def _run_window_action_deferred(action: Callable[[], None]) -> None:
    threading.Thread(
        target=action,
        name="WorkTraceWindowAction",
        daemon=True,
    ).start()


class DesktopShellController:
    """Own visible/hidden/exiting transitions and the real window exit."""

    def __init__(
        self,
        *,
        window: Any,
        tray: TrayHost,
        initial_hidden: bool = False,
        deferred_window_action_executor: (
            Callable[[Callable[[], None]], None] | None
        ) = None,
    ) -> None:
        self._window = window
        self._tray = tray
        self._lock = threading.RLock()
        self._window_action_lock = threading.Lock()
        self._defer_window_action = (
            deferred_window_action_executor
            if deferred_window_action_executor is not None
            else _run_window_action_deferred
        )
        self._tray_available = False
        self._notice_shown = False
        self._exit_requested = False
        self._window_loaded = False
        self._show_when_loaded = not initial_hidden
        self._hide_scheduled = False
        self._show_scheduled = False
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
            if not available and self.state is ShellState.HIDDEN:
                self.state = ShellState.VISIBLE
                self._show_when_loaded = True
        if not available:
            logger.error(
                "Windows tray unavailable; window close retains full-exit behavior"
            )
            try:
                self._tray.stop()
            except Exception:
                logger.warning("failed tray initialization cleanup", exc_info=True)
        return available

    def handle_window_loaded(self) -> None:
        with self._lock:
            self._window_loaded = True
            logger.info("desktop shell window loaded")
            if self.state is ShellState.EXITING:
                return
            if self.state is ShellState.VISIBLE:
                self._show_when_loaded = False
                self._schedule_show_locked()
                return
        self._submit_window_action(self._sync_hidden_visibility)

    def handle_window_closing(self) -> bool:
        """Return False to cancel pywebview close, True to allow it."""

        with self._lock:
            if self.state is ShellState.EXITING:
                return True
            if not self._tray_available:
                self.state = ShellState.EXITING
                return True
            if self.state is ShellState.HIDDEN:
                return False
            self.state = ShellState.HIDDEN
            self._show_when_loaded = False
            self._schedule_hide_locked()
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
            self._show_when_loaded = False
            self._schedule_hide_locked()
            return True

    def show_window(self) -> bool:
        with self._lock:
            if self.state is ShellState.EXITING:
                return False
            self.state = ShellState.VISIBLE
            if not self._window_loaded:
                self._show_when_loaded = True
                return True
            self._show_when_loaded = False
            self._schedule_show_locked()
            return True

    def exit_application(self) -> bool:
        with self._lock:
            if self._exit_requested:
                return False
            self._exit_requested = True
            self.state = ShellState.EXITING
            self._show_when_loaded = False
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
            self._show_when_loaded = False
        if tray_available:
            try:
                self._tray.stop()
            except Exception:
                logger.warning("desktop shell tray cleanup failed", exc_info=True)

    def _schedule_hide_locked(self) -> None:
        if self._hide_scheduled:
            return
        self._hide_scheduled = True
        self._submit_window_action(self._execute_pending_hide)

    def _schedule_show_locked(self) -> None:
        if self._show_scheduled:
            return
        self._show_scheduled = True
        self._submit_window_action(self._execute_pending_show)

    def _submit_window_action(self, action: Callable[[], None]) -> None:
        try:
            self._defer_window_action(action)
        except Exception:
            logger.exception("desktop shell failed to schedule window action")
            with self._lock:
                if action == self._execute_pending_hide:
                    self._hide_scheduled = False
                    if self.state is ShellState.HIDDEN:
                        self.state = ShellState.VISIBLE
                elif action == self._execute_pending_show:
                    self._show_scheduled = False

    def _execute_pending_hide(self) -> None:
        with self._window_action_lock:
            with self._lock:
                self._hide_scheduled = False
                if (
                    self.state is not ShellState.HIDDEN
                    or not self._tray_available
                ):
                    return
                show_notice = not self._notice_shown
            try:
                self._window.hide()
            except Exception:
                logger.exception("desktop shell failed to hide window")
                with self._lock:
                    if self.state is ShellState.HIDDEN:
                        self.state = ShellState.VISIBLE
                return
            with self._lock:
                if (
                    self.state is not ShellState.HIDDEN
                    or not self._tray_available
                ):
                    return
            self._set_webview_visibility(False)
            if show_notice:
                try:
                    self._tray.show_background_notice()
                except Exception:
                    logger.warning(
                        "desktop shell background notice failed",
                        exc_info=True,
                    )
                else:
                    with self._lock:
                        self._notice_shown = True

    def _execute_pending_show(self) -> None:
        with self._window_action_lock:
            with self._lock:
                self._show_scheduled = False
                if (
                    self.state is not ShellState.VISIBLE
                    or not self._window_loaded
                ):
                    return
            try:
                self._window.show()
            except Exception:
                logger.exception("desktop shell failed to show window")
                return
            try:
                self._window.restore()
            except Exception:
                logger.warning(
                    "desktop shell failed to restore window",
                    exc_info=True,
                )
            self._focus_native_window()
            self._set_webview_visibility(True)

    def _sync_hidden_visibility(self) -> None:
        with self._window_action_lock:
            with self._lock:
                if (
                    self.state is not ShellState.HIDDEN
                    or not self._window_loaded
                ):
                    return
            self._set_webview_visibility(False)

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
