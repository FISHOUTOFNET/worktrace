"""Overview bridge mixin, split out of ``bridge.py``.

Boundary rules (enforced by ``tests/test_ui_backend_boundary.py``):

- This module may import ``worktrace.api``, ``worktrace.constants``,
  ``worktrace.formatters``, and stdlib only. It must NOT import
  ``worktrace.services``, ``worktrace.db``, ``worktrace.collector``,
  ``worktrace.security``, ``worktrace.runtime``, or ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  style payloads without tracebacks.
- Methods do not log window titles, file paths, notes, or copied text.

``WebViewBridge`` in ``bridge.py`` inherits ``OverviewBridgeMixin`` so the
Overview page method names (``get_status`` / ``toggle_pause`` /
``get_overview`` / ``get_recent_activities``) stay on ``WebViewBridge`` and
the frontend / tests see no API-surface change.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..api import app_api, project_api, settings_api, statistics_api, timeline_api
from ..constants import UNCATEGORIZED_PROJECT
from ..formatters import format_duration
from .bridge_common import _GENERIC_ERROR, _RECENT_LIMIT, _snapshot_summary

logger = logging.getLogger(__name__)


class OverviewBridgeMixin:
    """Overview page bridge methods, split out of ``WebViewBridge``.

    The mixin is mixed into ``WebViewBridge`` in ``bridge.py`` so the
    Overview page method names stay on ``WebViewBridge``. The mixin must
    NOT add ``__init__``; it relies on the host class.
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

        Mirrors the Tkinter sidebar toggle: if currently paused or not running,
        clear user_paused and start the collector; otherwise set user_paused,
        mark collector_status paused, and clear the current activity snapshot.

        Phase 6E: before any path that could start the collector, verify
        the first-run privacy notice has been accepted. If not accepted
        (or the read itself fails), fail closed: do not start the
        collector, do not mutate ``user_paused`` / ``collector_status``,
        and return the stable Chinese error ``请先确认隐私说明``.
        """
        try:
            # Phase 6E first-run gate: the collector must not start until
            # the user has accepted the privacy notice. ``toggle_pause``
            # is the only sidebar action that can start the collector
            # besides ``accept_first_run_notice``; both must respect the
            # gate. Fail-closed on any read error so a settings hiccup
            # cannot accidentally bypass the gate.
            try:
                notice_accepted = settings_api.first_run_notice_accepted()
            except Exception:
                logger.exception(
                    "webview bridge toggle_pause first-run notice read failed; "
                    "failing closed"
                )
                return {"ok": False, "error": "请先确认隐私说明"}
            if not notice_accepted:
                return {"ok": False, "error": "请先确认隐私说明"}

            raw_status = settings_api.get_collector_status()
            paused = settings_api.is_user_paused() or raw_status == "paused"
            if paused or raw_status != "running":
                settings_api.set_user_paused(False)
                # Phase 6G: ensure the folder index worker is running
                # before the collector starts matching activities. The
                # worker is gated by the same privacy notice as the
                # collector (checked above). ``start_background_workers``
                # is idempotent and a no-op when this instance does not
                # own the collector.
                app_api.start_background_workers()
                app_api.start_collector()
            else:
                settings_api.set_user_paused(True)
                settings_api.set_collector_status("paused")
                settings_api.set_current_activity_snapshot("")
            return self.get_status()
        except Exception:
            logger.exception("webview bridge toggle_pause failed")
            return dict(_GENERIC_ERROR)

    def get_overview(self) -> dict[str, Any]:
        """Return today's overview KPIs and current activity summary.

        Returns raw seconds + snapshot fields so the frontend 1-second
        ticker can increment the display without a bridge round-trip.
        ``today_total_seconds`` already includes the current activity's
        live seconds (the summary is built with ``include_live=True``);
        the ticker must NOT add ``current_activity_elapsed_seconds`` on
        top of it. Instead the ticker adds ``(now - snapshot_at_epoch_ms)``
        to ``today_total_seconds`` and to EITHER ``classified_seconds``
        OR ``uncategorized_seconds`` (never both) depending on whether
        the current activity is classified, and only when the activity
        is running (not paused / not idle).
        """
        try:
            today = timeline_api.get_default_report_date()
            summary = statistics_api.get_summary(today, today, include_live=True)
            snapshot = settings_api.get_current_activity_snapshot()
            project_count = len(project_api.list_active_projects())
            current = _snapshot_summary(snapshot)
            total_seconds = int(summary.get("total_duration") or 0)
            classified_seconds = int(summary.get("classified_duration") or 0)
            uncategorized_seconds = int(summary.get("uncategorized_duration") or 0)
            # Determine whether the current activity is classified or
            # uncategorized so the frontend ticker knows which KPI to
            # increment. Uses the snapshot's inferred_project_name; if
            # it equals UNCATEGORIZED_PROJECT the activity is
            # uncategorized. No file path / window title / clipboard
            # content is surfaced.
            current_project_name = ""
            current_is_uncategorized = True
            if snapshot and current.get("active"):
                current_project_name = str(snapshot.get("inferred_project_name") or "")
                current_is_uncategorized = (
                    not current_project_name
                    or current_project_name == UNCATEGORIZED_PROJECT
                )
            current["is_uncategorized"] = bool(current_is_uncategorized)
            current["is_classified"] = not bool(current_is_uncategorized)
            return {
                "ok": True,
                "date": today,
                "total_duration": format_duration(total_seconds),
                "classified_duration": format_duration(classified_seconds),
                "uncategorized_duration": format_duration(uncategorized_seconds),
                "project_count": project_count,
                "current_activity": current,
                # Raw seconds + snapshot fields for the 1-second local
                # ticker. The ticker only updates DOM text; it never
                # calls a bridge method or writes the DB.
                "snapshot_at_epoch_ms": int(time.time() * 1000),
                "today_total_seconds": total_seconds,
                "current_activity_elapsed_seconds": int(current.get("elapsed_seconds") or 0),
                # Display-safe raw seconds for classified / uncategorized
                # so the frontend ticker can increment the correct KPI
                # without parsing "HH:MM:SS" strings.
                "classified_seconds": classified_seconds,
                "uncategorized_seconds": uncategorized_seconds,
            }
        except Exception:
            logger.exception("webview bridge get_overview failed")
            return dict(_GENERIC_ERROR)

    def get_recent_activities(self) -> dict[str, Any]:
        """Return up to 20 recent project sessions for today.

        Returns a dict with an ``activities`` list to keep the contract stable
        if the underlying shape changes.
        """
        try:
            today = timeline_api.get_default_report_date()
            sessions = timeline_api.get_project_sessions_by_date(
                today,
                include_hidden=False,
                ensure_context=True,
            )
            items: list[dict[str, Any]] = []
            for session in sessions[:_RECENT_LIMIT]:
                items.append(
                    {
                        "project_name": str(session.get("project_name") or "未归类"),
                        "start_time": str(session.get("start_time") or ""),
                        "end_time": str(session.get("end_time") or ""),
                        "duration": format_duration(session.get("duration_seconds") or 0),
                        "status": str(session.get("status_summary") or session.get("status") or ""),
                    }
                )
            return {"ok": True, "activities": items}
        except Exception:
            logger.exception("webview bridge get_recent_activities failed")
            return dict(_GENERIC_ERROR)


__all__ = ["OverviewBridgeMixin"]
