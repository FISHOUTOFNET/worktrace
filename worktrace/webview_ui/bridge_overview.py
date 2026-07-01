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

        The ``current_activity`` payload is built by the unified
        live-display model (``live_display_api.build_current_activity_summary``)
        so Overview / Recent / Timeline share the same live-state
        classification, display project, baseline seconds, and
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
        """Return up to 20 recent project sessions for today.

        Unified live-display model. The payload supports three item kinds:

        - **virtual live item** — prepended when the current snapshot is a
          normal unpersisted <30s activity. ``is_virtual`` /
          ``is_virtual_live`` are true, ``activity_id`` is ``0``,
          ``source`` is ``"snapshot"``, ``edit_disabled`` is true, and the
          time range shows "进行中". The DB is NEVER written.
        - **persisted open live item** — a real DB session whose
          ``is_in_progress`` is true. ``duration_seconds`` already includes
          the live seconds from ``timeline_service._live_duration_for_row``.
        - **closed DB item** — a finalized session row.

        Each item carries ``duration_seconds`` (backend response-time
        baseline), ``is_in_progress``, ``is_live_projected`` (kept for
        backward compat; true for virtual live items), ``is_virtual``,
        ``is_virtual_live``, ``live_display_key``, ``activity_id``,
        ``source``, and ``edit_disabled``. The frontend ticker locates the
        live item by flag (not by a single-scenario index) and increments
        its ``duration_seconds`` by the unified live clock delta
        (``live_started_at_epoch_ms`` + ``carry_seconds``).
        """
        try:
            today = timeline_api.get_default_report_date()
            sessions = timeline_api.get_project_sessions_by_date(
                today,
                include_hidden=False,
                ensure_context=True,
            )
            snapshot = settings_api.get_current_activity_snapshot()
            live_display = live_display_api.build_current_activity_summary(
                snapshot, report_date=today, today=today
            )
            # Build the persisted-open overlay once so every DB session
            # item that matches the persisted_activity_id can carry the
            # same stable live fields as the virtual item (verification
            # items 12, 16, 21). The overlay is None when the snapshot is
            # not persisted_open.
            persisted_overlay = live_display_api.build_persisted_open_overlay(
                snapshot, report_date=today, today=today
            )
            items: list[dict[str, Any]] = []
            # Prepend a virtual live item when the current snapshot is a
            # normal unpersisted activity. This is display-only; the DB is
            # never written and the 30-second persistence threshold is
            # preserved.
            if live_display.get("is_virtual_live"):
                virtual = live_display_api.build_virtual_session(
                    snapshot, report_date=today, today=today
                )
                if virtual:
                    items.append(
                        {
                            "project_name": str(virtual.get("project_name") or "未归类"),
                            "start_time": str(virtual.get("start_time") or ""),
                            "end_time": "",
                            "duration": str(virtual.get("duration") or "00:00:00"),
                            "duration_seconds": int(virtual.get("duration_seconds") or 0),
                            "is_in_progress": True,
                            "is_live_projected": True,
                            "is_virtual": True,
                            "is_virtual_live": True,
                            "live_display_key": str(virtual.get("live_display_key") or ""),
                            # Stable live identity so the frontend continuity
                            # key survives the virtual → persisted_open
                            # transition (verification items 12, 16, 21).
                            "stable_live_key": str(virtual.get("stable_live_key") or ""),
                            "stable_live_key_hash": str(virtual.get("stable_live_key_hash") or ""),
                            # Unified live clock fields (scheme A).
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
                # Apply the persisted-open overlay so the matching DB row
                # carries the same stable live fields as the virtual item.
                # This is a no-op for closed / non-matching rows.
                live_display_api.apply_persisted_open_overlay_to_row(row, persisted_overlay)
                items.append(row)
            return {
                "ok": True,
                "activities": items,
                # Unified live-display payload so the frontend ticker can
                # decide eligibility without re-reading the raw snapshot.
                "live_display": live_display,
            }
        except Exception:
            logger.exception("webview bridge get_recent_activities failed")
            return dict(_GENERIC_ERROR)

    def get_refresh_state(self, report_date=None) -> dict[str, Any]:
        """Return a lightweight refresh-state snapshot for the heartbeat.

        Phase 6H-followup. The frontend heartbeat calls this once per second
        after running the local ticker. It compares the returned
        ``refresh_revision`` with the previous tick's value: if unchanged,
        no heavy interface (``get_overview`` / ``get_recent_activities`` /
        ``get_timeline``) is invoked. If changed, only the data needed by
        the current page is re-pulled.

        ``report_date`` (optional) scopes the structural signature to the
        currently viewed Timeline date (verification item 8). When omitted
        the facade defaults to today.

        The payload is display-safe: no raw ``window_title``,
        ``file_path_hint``, ``note``, ``clipboard``, ``traceback`` or SQL
        is surfaced. ``refresh_revision`` is a structural-only signature
        (it excludes ``elapsed_seconds`` / ``extra_seconds`` /
        ``snapshot_updated_at`` / ``Date.now()``) so natural time
        progression within the same activity does not trigger a heavy
        refresh.

        The payload also carries the unified live clock fields
        (``live_started_at_epoch_ms``, ``carry_seconds``,
        ``stable_live_key``, ``stable_live_key_hash``) so the frontend
        ticker can compute the live duration from a stable start-time
        anchor instead of a response-time baseline (verification item 6).

        The bridge method only calls the ``settings_api.get_refresh_state``
        facade and wraps the result with a stable error payload. It does
        not import services / db / collector / runtime / config / security.
        """
        try:
            return settings_api.get_refresh_state(report_date)
        except Exception:
            logger.exception("webview bridge get_refresh_state failed")
            return dict(_GENERIC_ERROR)


__all__ = ["OverviewBridgeMixin"]
