"""Python bridge exposed to the WebView frontend via pywebview.

Boundary rules (enforced by tests/test_ui_backend_boundary.py):

- This module composes the page-level bridge mixins and does NOT import
  ``worktrace.api`` directly; each mixin imports the API facades it needs
  from its own module namespace. It must not import ``worktrace.services``,
  ``worktrace.db``, ``worktrace.collector``, ``worktrace.security``,
  ``worktrace.runtime``, or ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  without tracebacks. Errors must not leak traceback, SQL, or raw sensitive
  fields.
- Methods do not log window titles, file paths, notes, or copied text.

``WebViewBridge`` is the JS/Python bridge layer and the only data path
between JS and Python. It composes the page-level bridge mixins.

Composition structure:

``WebViewBridge`` is a thin composition class that inherits from six
mixins, each owning a page-level slice of the bridge surface:

- ``BridgeDialogMixin`` (``bridge_dialogs.py``): native save / open file
  dialog helpers (``_choose_csv_save_path`` / ``_choose_backup_save_path``
  / ``_choose_backup_open_path``).
- ``OverviewBridgeMixin`` (``bridge_overview.py``): ``get_status``,
  ``toggle_pause``, ``get_overview``, ``get_recent_activities``.
- ``SettingsBridgeMixin`` (``bridge_settings.py``): first-run notice,
  settings / privacy status, clipboard capture toggle, encrypted backup
  export / import / manifest preview, clear-all-local-data.
- ``StatisticsBridgeMixin`` (``bridge_statistics.py``):
  ``get_statistics_export_summary``, ``export_statistics_csv``.
- ``TimelineBridgeMixin`` (``bridge_timeline.py``): all timeline read /
  edit / split / merge / hide / delete / batch / restore methods.
- ``ProjectRulesBridgeMixin`` (``bridge_rules.py``): the Project Rules
  bridge methods.

Shared helpers (``_coerce_activity_ids``, ``_validate_datetime_inputs``,
``_safe_resource_display_name``, ``_snapshot_summary``,
``_statistics_summary_payload``, ``_GENERIC_ERROR``, ``_RECENT_LIMIT``,
``_DATE_SHAPE_RE``, ``_DATETIME_SHAPE_RE``) live in ``bridge_common.py``.
Each mixin imports what it needs from its own owning module; this module
only exposes ``WebViewBridge``.
"""

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
    public bridge method is inherited.
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
