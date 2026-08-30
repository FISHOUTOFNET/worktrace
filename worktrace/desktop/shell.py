"""Window/tray state owner outside AppRuntime."""
from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from enum import Enum
from typing import Any, Protocol

from .. import PRODUCT_DISPLAY_NAME
from ..platforms.window_activation import (
    GWL_EXSTYLE as _GWL_EXSTYLE,
    SW_RESTORE as _SW_RESTORE,
    SWP_FRAMECHANGED as _SWP_FRAMECHANGED,
    SWP_NOACTIVATE as _SWP_NOACTIVATE,
    SWP_NOMOVE as _SWP_NOMOVE,
    SWP_NOSIZE as _SWP_NOSIZE,
    SWP_NOZORDER as _SWP_NOZORDER,
    WS_EX_NOACTIVATE as _WS_EX_NOACTIVATE,
    make_window_activatable,
    native_window_handle,
    request_window_foreground,
)

logger = logging.getLogger(__name__)


class ShellState(str, Enum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    EXITING = "exiting"


class TrayHost(Protocol):
    def start(self) -> bool: ...
    def stop(self) -> None: ...
    def can_restore_window(self) -> bool: ...
    def show_background_notice(self) -> None: ...
    def set_collection_active(self, active: bool) -> None: ...


class WindowIconHost(Protocol):
    def set_collection_active(self, active: bool) -> None: ...
    def refresh(self) -> None: ...
    def stop(self) -> None: ...


class WebViewPowerHost(Protocol):
    def enter_hidden_mode(self) -> None: ...
    def prepare_for_show(self) -> None: ...


def _run_window_action_deferred(action: Callable[[], None]) -> None:
    threading.Thread(
        target=action,
        name="WorkTraceWindowAction",
        daemon=True,
    ).start()


class DesktopShellController:
    """Own visible/hidden/exiting transitions and desktop state projection."""

    def __init__(
        self,
        *,
        window: Any,
        tray: TrayHost,
        initial_hidden: bool = False,
        deferred_window_action_executor: (
            Callable[[Callable[[], None]], None] | None
        ) = None,
        window_icons: WindowIconHost | None = None,
        webview_power: WebViewPowerHost | None = None,
        collection_active_provider: Callable[[], bool] | None = None,
        collection_icon_refresh_seconds: float = 1.0,
    ) -> None:
        self._window = window
        self._tray = tray
        self._window_icons = window_icons
        self._webview_power = webview_power
        self._collection_active_provider = collection_active_provider
        self._collection_icon_refresh_seconds = max(
            0.25,
            float(collection_icon_refresh_seconds),
        )
        self._lock = threading.RLock()
        self._window_action_lock = threading.Lock()
        self._defer_window_action = (
            deferred_window_action_executor
            if deferred_window_action_executor is not None
            else _run_window_action_deferred
        )
        # This flag records lifecycle ownership only. Runtime hide decisions use
        # the tray's live can_restore_window() capability instead of treating a
        # successful startup as a sticky promise that Explorer still has an icon.
        self._tray_available = False
        self._notice_shown = False
        self._exit_completed = False
        self._window_loaded = False
        self._show_when_loaded = not initial_hidden
        self._activation_requested = False
        self._hide_scheduled = False
        self._show_scheduled = False
        self._collection_active = False
        self._icon_provider_failed = False
        self._icon_monitor_stop = threading.Event()
        self._icon_monitor_thread: threading.Thread | None = None
        self.state = ShellState.HIDDEN if initial_hidden else ShellState.VISIBLE

    @property
    def tray_available(self) -> bool:
        with self._lock:
            started = self._tray_available
        return bool(started and self._tray_can_restore_window())

    def _tray_can_restore_window(self) -> bool:
        capability = getattr(self._tray, "can_restore_window", None)
        if not callable(capability):
            # Compatibility for narrow test/injected tray capabilities. Shipping
            # WindowsTrayHost implements can_restore_window().
            with self._lock:
                return bool(self._tray_available)
        try:
            return capability() is True
        except Exception:
            logger.warning("desktop shell tray restore capability failed", exc_info=True)
            return False

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
        self._start_icon_monitor()
        return available

    def handle_window_loaded(self) -> None:
        with self._lock:
            self._window_loaded = True
            logger.info("desktop shell window loaded")
            exiting = self.state is ShellState.EXITING
            visible = self.state is ShellState.VISIBLE
            if visible:
                self._show_when_loaded = False
        self._refresh_window_icon()
        if exiting:
            return
        if visible:
            with self._lock:
                self._schedule_show_locked()
            return
        self._submit_window_action(self._sync_hidden_visibility)

    def handle_window_closing(self) -> bool:
        """Return False to cancel pywebview close, True to allow it."""

        restore_available = self._tray_can_restore_window()
        with self._lock:
            if self.state is ShellState.EXITING:
                return True
            if not self._tray_available or not restore_available:
                self.state = ShellState.EXITING
                self._activation_requested = False
                return True
            if self.state is ShellState.HIDDEN:
                return False
            self.state = ShellState.HIDDEN
            self._show_when_loaded = False
            self._activation_requested = False
            self._schedule_hide_locked()
        return False

    def hide_window(self) -> bool:
        restore_available = self._tray_can_restore_window()
        with self._lock:
            if (
                self.state is ShellState.EXITING
                or self.state is ShellState.HIDDEN
                or not self._tray_available
                or not restore_available
            ):
                return False
            self.state = ShellState.HIDDEN
            self._show_when_loaded = False
            self._activation_requested = False
            self._schedule_hide_locked()
            return True

    def show_window(self) -> bool:
        """Reveal the main window and activate an already-visible window inline.

        For a loaded visible Windows window, activation is attempted synchronously
        so an explicit tray/helper/instance user gesture does not lose foreground
        eligibility by first crossing the deferred window-action thread. A failed
        inline activation is still queued for the ordinary bounded show/restore
        retry, but False is returned so handoff callers do not hide their only
        foreground window before activation has actually succeeded.
        """

        with self._lock:
            if self.state is ShellState.EXITING:
                return False
            already_visible = self.state is ShellState.VISIBLE
            self.state = ShellState.VISIBLE
            self._activation_requested = True
            if not self._window_loaded:
                self._show_when_loaded = True
                return True
            self._show_when_loaded = False
            immediate_activation = already_visible and sys.platform.startswith("win")
            if not immediate_activation:
                self._schedule_show_locked()
                return True

        with self._window_action_lock:
            with self._lock:
                if (
                    self.state is not ShellState.VISIBLE
                    or not self._window_loaded
                ):
                    return False
            self._make_window_activatable()
            activated = self._focus_native_window()

        if activated:
            with self._lock:
                if self.state is ShellState.VISIBLE:
                    self._activation_requested = False
            self._set_webview_visibility(True)
            return True

        with self._lock:
            if (
                self.state is ShellState.VISIBLE
                and self._window_loaded
            ):
                self._schedule_show_locked()
        return False

    def exit_application(self) -> bool:
        with self._lock:
            self.state = ShellState.EXITING
            self._show_when_loaded = False
            self._activation_requested = False
            if self._exit_completed:
                return False
        self._stop_icon_monitor()
        with self._window_action_lock:
            with self._lock:
                if self._exit_completed:
                    return False
            try:
                logger.info("desktop shell exit destroy begin")
                self._window.destroy()
                logger.info("desktop shell exit destroy returned")
            except Exception:
                logger.exception("desktop shell failed to destroy window")
                return False
            with self._lock:
                self._exit_completed = True
        self.stop()
        return True

    def stop(self) -> None:
        self._stop_icon_monitor()
        with self._lock:
            tray_available = self._tray_available
            self._tray_available = False
            self._show_when_loaded = False
            self._activation_requested = False
        if tray_available:
            try:
                self._tray.stop()
            except Exception:
                logger.warning("desktop shell tray cleanup failed", exc_info=True)
        self._stop_window_icons()

    def _start_icon_monitor(self) -> None:
        if self._collection_active_provider is None:
            return
        with self._lock:
            if self._icon_monitor_thread is not None:
                return
            self._icon_monitor_stop.clear()
        self._refresh_collection_icon_state(force=True)
        thread = threading.Thread(
            target=self._run_icon_monitor,
            name="WorkTraceCollectionIcon",
            daemon=True,
        )
        with self._lock:
            self._icon_monitor_thread = thread
        thread.start()

    def _stop_icon_monitor(self) -> None:
        self._icon_monitor_stop.set()
        with self._lock:
            thread = self._icon_monitor_thread
            self._icon_monitor_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _run_icon_monitor(self) -> None:
        while not self._icon_monitor_stop.wait(self._collection_icon_refresh_seconds):
            self._refresh_collection_icon_state(force=False)

    def _refresh_collection_icon_state(self, *, force: bool) -> None:
        provider = self._collection_active_provider
        if provider is None:
            return
        try:
            active = bool(provider())
        except Exception:
            with self._lock:
                first_failure = not self._icon_provider_failed
                self._icon_provider_failed = True
            if first_failure:
                logger.warning("collection icon state provider failed", exc_info=True)
            active = False
        else:
            with self._lock:
                recovered = self._icon_provider_failed
                self._icon_provider_failed = False
            if recovered:
                logger.info("collection icon state provider recovered")
        self._apply_collection_icon_state(active, force=force)

    def _apply_collection_icon_state(self, active: bool, *, force: bool) -> None:
        active = bool(active)
        with self._lock:
            changed = active != self._collection_active
            self._collection_active = active
            tray_started = self._tray_available
            window_icons = self._window_icons
        if not force and not changed:
            return
        if tray_started and self._tray_can_restore_window():
            try:
                self._tray.set_collection_active(active)
            except Exception:
                logger.warning("desktop shell tray icon update failed", exc_info=True)
        if window_icons is not None:
            try:
                window_icons.set_collection_active(active)
            except Exception:
                logger.warning("desktop shell window icon update failed", exc_info=True)

    def _refresh_window_icon(self) -> None:
        window_icons = self._window_icons
        if window_icons is None:
            return
        try:
            window_icons.refresh()
        except Exception:
            logger.debug("desktop shell window icon refresh failed", exc_info=True)

    def _stop_window_icons(self) -> None:
        window_icons = self._window_icons
        if window_icons is None:
            return
        try:
            window_icons.stop()
        except Exception:
            logger.debug("desktop shell window icon cleanup failed", exc_info=True)

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
            restore_available = self._tray_can_restore_window()
            with self._lock:
                self._hide_scheduled = False
                if (
                    self.state is not ShellState.HIDDEN
                    or not self._tray_available
                    or not restore_available
                ):
                    if self.state is ShellState.HIDDEN and not restore_available:
                        self.state = ShellState.VISIBLE
                        self._activation_requested = True
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

            # Closing and the deferred native hide are separate turns. Re-check
            # after the actual hide so a tray crash/restart in that gap cannot
            # strand the user with no restore entry point.
            if not self._tray_can_restore_window():
                with self._lock:
                    if self.state is ShellState.HIDDEN:
                        self.state = ShellState.VISIBLE
                        self._activation_requested = True
                try:
                    self._window.show()
                    self._window.restore()
                except Exception:
                    logger.exception("desktop shell failed to recover unsafe tray hide")
                self._set_webview_visibility(True)
                return

            with self._lock:
                if self.state is not ShellState.HIDDEN:
                    return
            self._set_webview_visibility(False)
            self._enter_webview_hidden_mode()
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
                activation_requested = self._activation_requested
                self._activation_requested = False
            self._make_window_activatable()
            self._prepare_webview_for_show()
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
            if activation_requested:
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
            self._enter_webview_hidden_mode()

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

    def _enter_webview_hidden_mode(self) -> None:
        power = self._webview_power
        if power is None:
            return
        try:
            power.enter_hidden_mode()
        except Exception:
            logger.debug("desktop shell WebView suspend failed", exc_info=True)

    def _prepare_webview_for_show(self) -> None:
        power = self._webview_power
        if power is None:
            return
        try:
            power.prepare_for_show()
        except Exception:
            logger.debug("desktop shell WebView resume failed", exc_info=True)

    def _make_window_activatable(self) -> None:
        make_window_activatable(
            self._window,
            fallback_title=PRODUCT_DISPLAY_NAME,
            logger=logger,
        )

    def _native_window_handle(self) -> int:
        return native_window_handle(
            self._window,
            fallback_title=PRODUCT_DISPLAY_NAME,
            logger=logger,
        )

    def _focus_native_window(self) -> bool:
        if not sys.platform.startswith("win"):
            return True
        activated = request_window_foreground(
            self._window,
            fallback_title=PRODUCT_DISPLAY_NAME,
            restore=True,
            logger=logger,
        )
        if not activated:
            logger.warning("desktop shell foreground activation was not accepted")
        return activated


__all__ = [
    "DesktopShellController",
    "ShellState",
    "TrayHost",
    "WebViewPowerHost",
    "WindowIconHost",
]
