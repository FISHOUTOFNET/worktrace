"""Python bridge exposed to the WebView frontend via pywebview."""

from __future__ import annotations

import logging
from typing import Any

from .bridge_dialogs import BridgeDialogMixin
from .bridge_overview import OverviewBridgeMixin
from .bridge_rules import ProjectRulesBridgeMixin
from .bridge_settings import SettingsBridgeMixin
from .bridge_statistics import StatisticsBridgeMixin
from .bridge_timeline import TimelineBridgeMixin

logger = logging.getLogger(__name__)


class WebViewBridge(
    BridgeDialogMixin,
    OverviewBridgeMixin,
    SettingsBridgeMixin,
    StatisticsBridgeMixin,
    TimelineBridgeMixin,
    ProjectRulesBridgeMixin,
):
    """Bridge object exposed to JS through pywebview's JS API.

    Each method returns a plain dict (or list inside a dict) so pyweb view can
    serialize it to JS. Errors never include tracebacks or sensitive fields.

    Inherits from six mixins, each owning a page-level slice.
    ``WebViewBridge`` itself only owns ``__init__`` and ``set_window``; every
    public bridge method is inherited, including get_statistics_export_summary.
    """

    def __init__(self) -> None:
        # The pywebview window is injected by ``webview_main.py`` after
        # ``create_window`` so the bridge can open a native save dialog for
        # the CSV export. Stays ``None`` until ``set_window`` is called, so
        # importing / unit-testing the bridge never starts the GUI.
        self._window: Any = None

    def set_window(self, window: Any) -> None:
        """Inject the pywebview window so the bridge can open native dialogs.

        Called by ``worktrace.webview_main`` after ``webview.create_window``
        returns. The bridge must not construct a window itself: that would
        start the GUI on import / during tests. Until this is called the
        CSV export save dialog is unavailable and returns a stable error.
        """
        self._window = window


__all__ = ["WebViewBridge"]
