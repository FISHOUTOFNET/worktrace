"""Overview page bridge mixin.

Boundary rules (enforced by ``tests/test_ui_backend_boundary.py``):

- This module may import ``worktrace.api``, ``worktrace.constants``,
  ``worktrace.formatters``, and stdlib only. It must NOT import
  ``worktrace.services``, ``worktrace.db``, ``worktrace.collector``,
  ``worktrace.security``, ``worktrace.runtime``, or ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  style payloads without tracebacks.
- Methods do not log window titles, file paths, notes, or copied text.
- Page display ViewModels (Overview / Recent / Refresh State) are built
  solely by ``worktrace.api.view_model_api``; this mixin never constructs
  live display / virtual live / persisted_open / project transition /
  duration override / stable live key / live clock fields.

``WebViewBridge`` in ``bridge.py`` inherits ``OverviewBridgeMixin`` so the
Overview page method names (``get_status`` / ``toggle_pause`` /
``get_overview`` / ``get_recent_activities`` / ``get_refresh_state``) stay
on ``WebViewBridge``.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import app_api, settings_api, view_model_api
from .bridge_common import _GENERIC_ERROR

logger = logging.getLogger(__name__)


class OverviewBridgeMixin:
    """Overview page bridge methods.

    Mixed into ``WebViewBridge`` in ``bridge.py`` so the Overview page
    method names stay on ``WebViewBridge``. The mixin must NOT add
    ``__init__``; it relies on the host class.
    """

    def get_status(self) -> dict[str, Any]:
        """Return the current collector status and pause state."""
        try:
            raw_status = settings_api.get_collector_status()
            user_paused = settings_api.is_user_paused()
            paused = user_paused or raw_status == "paused"
            if paused or raw_status == "paused":
                display = "已暂停"
            elif raw_status == "running":
                display = "记录中"
            elif raw_status == "error":
                display = "状态异常"
            else:
                display = "采集器未运行"
            return {
                "ok": True,
                "status": raw_status,
                "paused": paused,
                "display": display,
            }
        except Exception:
            logger.exception("webview bridge get_status failed")
            return dict(_GENERIC_ERROR)

    def toggle_pause(self) -> dict[str, Any]:
        """Toggle the collector pause state.

        If currently paused or not running, clear user_paused and start
        the collector via the unified privacy-gated entry; otherwise set
        user_paused, mark collector_status paused, and clear the current
        activity snapshot.

        The first-run privacy gate is enforced solely by
        :func:`app_api.start_collection_after_privacy_gate`. If the notice
        has not been accepted (or the read itself fails) the unified
        entry fail-closes: no worker / collector starts and no caller
        state is mutated. This method does NOT duplicate the gate check.
        """
        try:
            raw_status = settings_api.get_collector_status()
            paused = settings_api.is_user_paused() or raw_status == "paused"
            if paused or raw_status != "running":
                result = app_api.start_collection_after_privacy_gate()
                if not result.get("ok"):
                    return result
                settings_api.set_user_paused(False)
            else:
                settings_api.set_user_paused(True)
                settings_api.set_collector_status("paused")
                settings_api.set_current_activity_snapshot("")
            return self.get_status()
        except Exception:
            logger.exception("webview bridge toggle_pause failed")
            return dict(_GENERIC_ERROR)

    def get_overview(self) -> dict[str, Any]:
        """Return today's Overview page ViewModel.

        The complete Overview ViewModel (KPIs, current activity, recent
        activities, live_projection, sample_id, live clock fields) is
        built by ``view_model_service`` from a single snapshot sample.
        """
        try:
            return view_model_api.get_overview_view_model()
        except Exception:
            logger.exception("webview bridge get_overview failed")
            return dict(_GENERIC_ERROR)

    def get_recent_activities(self) -> dict[str, Any]:
        """Return up to 20 recent project sessions for today.

        Selects the recent-activities sub-payload and the live-display
        summary from the unified Overview ViewModel so the recent list
        and the Overview share the same snapshot sample.
        """
        try:
            vm = view_model_api.get_overview_view_model()
            return {
                "ok": True,
                "activities": vm.get("activities", []),
                "live_display": vm.get("live_display", {}),
            }
        except Exception:
            logger.exception("webview bridge get_recent_activities failed")
            return dict(_GENERIC_ERROR)

    def get_refresh_state(self, report_date=None) -> dict[str, Any]:
        """Return the heartbeat / refresh-state ViewModel."""
        try:
            return view_model_api.get_refresh_state_view_model(report_date)
        except Exception:
            logger.exception("webview bridge get_refresh_state failed")
            return dict(_GENERIC_ERROR)


__all__ = ["OverviewBridgeMixin"]
