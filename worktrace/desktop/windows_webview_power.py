"""Best-effort WebView2 power control for hidden main-window periods."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class WindowsWebView2PowerController:
    """Marshal main WebView2 visibility/power changes onto its WinForms UI thread.

    The optimization is deliberately fail-open: pywebview/native capability
    differences must never prevent the ordinary shell hide/show lifecycle.
    """

    def __init__(
        self,
        window: Any,
        *,
        action_factory: Callable[[Callable[[], None]], Any] | None = None,
    ) -> None:
        self._window = window
        self._action_factory = action_factory

    def enter_hidden_mode(self) -> None:
        """Make the renderer invisible and request best-effort suspension."""

        def apply() -> None:
            webview_control = self._native_webview()
            if webview_control is None:
                return
            try:
                webview_control.Visible = False
            except Exception:
                logger.debug("WebView2 hidden visibility update failed", exc_info=True)
                return

            core = getattr(webview_control, "CoreWebView2", None)
            suspend = getattr(core, "TrySuspendAsync", None) if core is not None else None
            if not callable(suspend):
                return
            try:
                # Do not wait on the returned Task. WebView2 requires its UI
                # message pump to remain unblocked while suspension completes.
                suspend()
            except Exception:
                logger.debug("WebView2 suspend request failed", exc_info=True)

        self._invoke_on_ui_thread(apply, operation="suspend")

    def prepare_for_show(self) -> None:
        """Resume a suspended renderer, then make the native WebView visible."""

        def apply() -> None:
            webview_control = self._native_webview()
            if webview_control is None:
                return
            try:
                core = getattr(webview_control, "CoreWebView2", None)
                if core is not None and bool(getattr(core, "IsSuspended", False)):
                    resume = getattr(core, "Resume", None)
                    if callable(resume):
                        resume()
            except Exception:
                logger.debug("WebView2 resume failed", exc_info=True)
            finally:
                try:
                    webview_control.Visible = True
                except Exception:
                    logger.debug(
                        "WebView2 visible restore failed",
                        exc_info=True,
                    )

        self._invoke_on_ui_thread(apply, operation="resume")

    def _native_webview(self) -> Any | None:
        native = getattr(self._window, "native", None)
        return getattr(native, "webview", None) if native is not None else None

    def _invoke_on_ui_thread(
        self,
        callback: Callable[[], None],
        *,
        operation: str,
    ) -> bool:
        webview_control = self._native_webview()
        if webview_control is None:
            return False
        invoke = getattr(webview_control, "Invoke", None)
        if not callable(invoke):
            return False
        try:
            factory = self._action_factory
            if factory is None:
                from System import Action

                factory = Action
            invoke(factory(callback))
            return True
        except Exception:
            logger.debug(
                "WebView2 UI-thread marshal failed operation=%s",
                operation,
                exc_info=True,
            )
            return False


__all__ = ["WindowsWebView2PowerController"]
