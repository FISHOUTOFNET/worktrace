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

``WebViewBridge`` in ``bridge.py`` inherits ``OverviewBridgeMixin`` so the
Overview page method names (``get_status`` / ``toggle_pause`` /
``get_overview`` / ``get_recent_activities``) stay on ``WebViewBridge``.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import (
    app_api,
    live_display_api,
    project_api,
    settings_api,
    statistics_api,
    timeline_api,
)
from ..constants import UNCATEGORIZED_PROJECT
from ..formatters import format_duration
from .bridge_common import (
    _GENERIC_ERROR,
    _RECENT_LIMIT,
    _snapshot_summary,
)

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
        the collector; otherwise set user_paused, mark collector_status
        paused, and clear the current activity snapshot.

        Before any path that could start the collector, verify the
        first-run privacy notice has been accepted. If not accepted (or
        the read itself fails), fail closed: do not start the collector,
        do not mutate ``user_paused`` / ``collector_status``, and return
        the stable Chinese error ``请先确认隐私说明``.
        """
        try:
            # First-run gate: the collector must not start until the user
            # has accepted the privacy notice. ``toggle_pause`` is the
            # only sidebar action that can start the collector besides
            # ``accept_first_run_notice``; both must respect the gate.
            # Fail-closed on any read error so a settings hiccup cannot
            # accidentally bypass the gate.
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
                # Ensure the folder index worker is running before the
                # collector starts matching activities. The worker is
                # gated by the same privacy notice as the collector
                # (checked above). ``start_background_workers`` is
                # idempotent and a no-op when this instance does not own
                # the collector.
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

        The ``current_activity`` payload is built by the unified
        live-display model (``live_display_api.build_current_activity_summary``)
        so Overview / Recent / Timeline share the same live-state
        classification, display project, fetched snapshot duration, and
        ``live_display_key``. The frontend ticker increments
        ``today_total_seconds`` / ``classified_seconds`` /
        ``uncategorized_seconds`` by the unified live clock delta
        (``live_started_at_epoch_ms`` + ``carry_seconds``) only when
        ``current_activity.is_virtual_live`` or
        ``current_activity.is_in_progress`` is true AND ``status ==
        "normal"``. idle / paused / excluded / error never increment the
        normal project live duration.
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
            return {
                "ok": True,
                "date": today,
                "total_duration": format_duration(total_seconds),
                "classified_duration": format_duration(classified_seconds),
                "uncategorized_duration": format_duration(uncategorized_seconds),
                "project_count": project_count,
                "current_activity": current,
                # Unified live-display payload so the frontend ticker can
                # decide eligibility (normal / virtual / persisted_open)
                # without re-reading the raw snapshot.
                "live_display": current,
                # Raw seconds for the 1-second local ticker. The ticker
                # only updates DOM text; it never calls a bridge method or
                # writes the DB.
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
        """Return up to 20 recent project sessions for today."""
        try:
            today = timeline_api.get_default_report_date()
            snapshot = settings_api.get_current_activity_snapshot()
            return self._build_recent_payload(snapshot, today)
        except Exception:
            logger.exception("webview bridge get_recent_activities failed")
            return dict(_GENERIC_ERROR)

    def _build_recent_payload(
        self,
        snapshot: dict[str, Any] | None,
        today: str,
    ) -> dict[str, Any]:
        """Build the recent-activities payload from a single snapshot.

        Shared by :meth:`get_recent_activities` and
        :meth:`get_overview_live_bundle` so both paths consume the SAME
        snapshot sample (no multi-sample drift).
        """
        sessions = timeline_api.get_project_sessions_by_date(
            today,
            include_hidden=False,
            ensure_context=True,
        )
        live_display = live_display_api.build_current_activity_summary(
            snapshot, report_date=today, today=today
        )
        persisted_overlay = live_display_api.build_persisted_open_overlay(
            snapshot, report_date=today, today=today
        )
        items: list[dict[str, Any]] = []
        if live_display.get("is_virtual_live"):
            virtual = live_display_api.build_virtual_session(
                snapshot, report_date=today, today=today
            )
            if virtual:
                items.append(
                    {
                        "project_name": str(virtual.get("project_name") or "未归类"),
                        "project_description": str(virtual.get("project_description") or ""),
                        "start_time": str(virtual.get("start_time") or ""),
                        "end_time": "",
                        "duration": str(virtual.get("duration") or "00:00:00"),
                        "duration_seconds": int(virtual.get("duration_seconds") or 0),
                        "is_in_progress": True,
                        "is_live_projected": True,
                        "is_virtual": True,
                        "is_virtual_live": True,
                        "live_display_key": str(virtual.get("live_display_key") or ""),
                        "stable_live_key": str(virtual.get("stable_live_key") or ""),
                        "stable_live_key_hash": str(virtual.get("stable_live_key_hash") or ""),
                        "live_state": "virtual",
                        "live_started_at_epoch_ms": int(virtual.get("live_started_at_epoch_ms") or 0),
                        "carry_seconds": int(virtual.get("carry_seconds") or 0),
                        "disable_reason": str(virtual.get("disable_reason") or ""),
                        "activity_id": 0,
                        "source": "snapshot",
                        "edit_disabled": True,
                        "status": "进行中",
                    }
                )
        limited = sessions[:_RECENT_LIMIT]
        for session in limited:
            base_seconds = int(session.get("duration_seconds") or 0)
            is_in_progress = bool(session.get("is_in_progress"))
            row = {
                "project_name": str(session.get("project_name") or "未归类"),
                "project_description": str(session.get("project_description") or ""),
                "start_time": str(session.get("start_time") or ""),
                "end_time": str(session.get("end_time") or ""),
                "duration": format_duration(base_seconds),
                "duration_seconds": base_seconds,
                "is_in_progress": is_in_progress,
                "is_live_projected": is_in_progress,
                "is_virtual": False,
                "is_virtual_live": False,
                "live_display_key": "",
                "live_state": "",
                "stable_live_key": "",
                "stable_live_key_hash": "",
                "live_started_at_epoch_ms": 0,
                "carry_seconds": 0,
                "activity_id": int(session.get("first_activity_id") or 0) or 0,
                "source": "db",
                "edit_disabled": False,
                "disable_reason": "",
                "status": str(session.get("status_summary") or session.get("status") or ""),
            }
            live_display_api.apply_persisted_open_overlay_to_row(row, persisted_overlay)
            items.append(row)
        return {
            "ok": True,
            "activities": items,
            "live_display": live_display,
        }

    def get_overview_live_bundle(self) -> dict[str, Any]:
        """Return Overview KPI + current activity + recent activities + live"""
        try:
            today = timeline_api.get_default_report_date()
            snapshot = settings_api.get_current_activity_snapshot()
            # Build every sub-payload from the SAME snapshot sample.
            live_projection = live_display_api.build_live_projection(
                snapshot, report_date=today, today=today
            )
            summary = statistics_api.get_summary(today, today, include_live=True)
            project_count = len(project_api.list_active_projects())
            current = _snapshot_summary(snapshot)
            recent = self._build_recent_payload(snapshot, today)
            total_seconds = int(summary.get("total_duration") or 0)
            classified_seconds = int(summary.get("classified_duration") or 0)
            uncategorized_seconds = int(summary.get("uncategorized_duration") or 0)
            sample_id = str(live_projection.get("stable_live_key_hash") or "")
            return {
                "ok": True,
                "date": today,
                "sample_id": sample_id,
                "live_projection": live_projection,
                "overview": {
                    "total_duration": format_duration(total_seconds),
                    "classified_duration": format_duration(classified_seconds),
                    "uncategorized_duration": format_duration(uncategorized_seconds),
                    "project_count": project_count,
                    "today_total_seconds": total_seconds,
                    "classified_seconds": classified_seconds,
                    "uncategorized_seconds": uncategorized_seconds,
                },
                "current_activity": current,
                "activities": recent.get("activities", []),
                # ``live_display`` is an alias of the live projection's
                # current-activity summary, kept for frontend code that
                # still reads that key.
                "live_display": current,
                "current_activity_elapsed_seconds": int(current.get("elapsed_seconds") or 0),
            }
        except Exception:
            logger.exception("webview bridge get_overview_live_bundle failed")
            return dict(_GENERIC_ERROR)

    def get_refresh_state(self, report_date=None) -> dict[str, Any]:
        """Return a lightweight refresh-state snapshot for the heartbeat."""
        try:
            return settings_api.get_refresh_state(report_date)
        except Exception:
            logger.exception("webview bridge get_refresh_state failed")
            return dict(_GENERIC_ERROR)


__all__ = ["OverviewBridgeMixin"]
