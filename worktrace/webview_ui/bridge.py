"""Python bridge exposed to the WebView frontend via pywebview.

Boundary rules (enforced by tests/test_ui_backend_boundary.py):

- This module may import ``worktrace.api`` and nothing else from the backend.
  It must not import ``worktrace.services``, ``worktrace.db``,
  ``worktrace.collector``, ``worktrace.security``, ``worktrace.runtime``, or
  ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  without tracebacks.
- Methods do not log window titles, file paths, notes, or copied text.

The bridge is the only data path between JS and Python. As of Phase 1 the
Overview page is fully migrated: ``get_status``, ``toggle_pause``,
``get_overview``, and ``get_recent_activities`` are the production data path
for the Overview page. As of Phase 2 the Timeline page is migrated as a
read-only page: ``get_timeline`` and ``get_timeline_session_details`` are the
production data path for the Timeline page. The bridge does not implement
editing, export, import, or settings mutations beyond pause/resume.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import app_api, settings_api, statistics_api, timeline_api, project_api
from ..formatters import (
    format_activity_display_name,
    format_duration,
    format_project_label,
    format_resource_type,
)

logger = logging.getLogger(__name__)

_GENERIC_ERROR = {"ok": False, "error": "操作失败"}
_RECENT_LIMIT = 20


class WebViewBridge:
    """Bridge object exposed to JS through pywebview's JS API.

    Each method returns a plain dict (or list inside a dict) so pywebview can
    serialize it to JS. Errors never include tracebacks or sensitive fields.
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
        """
        try:
            raw_status = settings_api.get_collector_status()
            paused = settings_api.is_user_paused() or raw_status == "paused"
            if paused or raw_status != "running":
                settings_api.set_user_paused(False)
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
        """Return today's overview KPIs and current activity summary."""
        try:
            today = timeline_api.get_default_report_date()
            summary = statistics_api.get_summary(today, today, include_live=True)
            snapshot = settings_api.get_current_activity_snapshot()
            project_count = len(project_api.list_active_projects())
            current = _snapshot_summary(snapshot)
            return {
                "ok": True,
                "date": today,
                "total_duration": format_duration(summary.get("total_duration") or 0),
                "classified_duration": format_duration(summary.get("classified_duration") or 0),
                "uncategorized_duration": format_duration(summary.get("uncategorized_duration") or 0),
                "project_count": project_count,
                "current_activity": current,
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

    def get_timeline(self, date: str | None = None) -> dict[str, Any]:
        """Return read-only timeline data for a single date.

        Returns the date, total duration, current activity summary, and a
        list of project sessions. Each session includes the ``activity_ids``
        list needed to load detail rows via ``get_timeline_session_details``.
        No editing, correction, or write operations are exposed.
        """
        try:
            report_date = date or timeline_api.get_default_report_date()
            sessions_raw = timeline_api.get_project_sessions_by_date(
                report_date,
                include_hidden=False,
                ensure_context=True,
            )
            total_seconds = sum(s.get("duration_seconds") or 0 for s in sessions_raw)
            snapshot = settings_api.get_current_activity_snapshot()
            current = _snapshot_summary(snapshot)
            sessions: list[dict[str, Any]] = []
            for session in sessions_raw:
                sessions.append(
                    {
                        "session_id": str(session.get("session_id") or ""),
                        "project_name": str(session.get("project_name") or "未归类"),
                        "project_description": str(session.get("project_description") or ""),
                        "start_time": str(session.get("start_time") or ""),
                        "end_time": str(session.get("end_time") or ""),
                        "duration": format_duration(session.get("duration_seconds") or 0),
                        "status": str(session.get("status_summary") or session.get("status") or ""),
                        "event_count": int(session.get("event_count") or 0),
                        "is_uncategorized": bool(session.get("is_uncategorized")),
                        "activity_ids": list(session.get("activity_ids") or []),
                    }
                )
            return {
                "ok": True,
                "date": report_date,
                "total_duration": format_duration(total_seconds),
                "current_activity": current,
                "sessions": sessions,
            }
        except Exception:
            logger.exception("webview bridge get_timeline failed")
            return dict(_GENERIC_ERROR)

    def get_timeline_session_details(
        self,
        activity_ids: list[int],
        report_date: str | None = None,
    ) -> dict[str, Any]:
        """Return read-only activity detail rows for a session.

        Each row exposes display-safe fields only: time range, duration,
        app name, resource type, resource display name, project name, and
        status. Raw window titles, file paths, and notes are not surfaced.
        """
        try:
            ids = [int(aid) for aid in (activity_ids or [])]
            if not ids:
                return {"ok": True, "activities": []}
            date = report_date or timeline_api.get_default_report_date()
            rows = timeline_api.get_session_activity_details(
                ids,
                report_date=date,
                ensure_context=True,
            )
            activities: list[dict[str, Any]] = []
            for row in rows:
                activities.append(
                    {
                        "start_time": str(row.get("start_time") or ""),
                        "end_time": str(row.get("end_time") or ""),
                        "duration": format_duration(row.get("duration_seconds") or 0),
                        "app_name": str(row.get("app_name") or ""),
                        "resource_type": format_resource_type(
                            row.get("resource_kind"),
                            row.get("resource_subtype"),
                        ),
                        "resource_name": format_activity_display_name(row),
                        "project_name": str(row.get("project_name") or "未归类"),
                        "status": str(row.get("status") or ""),
                    }
                )
            return {"ok": True, "activities": activities}
        except Exception:
            logger.exception("webview bridge get_timeline_session_details failed")
            return dict(_GENERIC_ERROR)


def _snapshot_summary(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Build a non-sensitive current-activity summary from the snapshot.

    Only display-name, project, elapsed, and state are returned. Window titles,
    paths, and notes are never included.
    """
    if not snapshot:
        return {"active": False, "display": "无"}
    name = (
        snapshot.get("resource_display_name")
        or snapshot.get("activity_display_name")
        or snapshot.get("app_name")
        or snapshot.get("process_name")
        or "未知"
    )
    project = snapshot.get("inferred_project_name") or "未归类"
    elapsed = format_duration(
        (timeline_api.get_snapshot_elapsed_seconds(snapshot) or 0)
        + (timeline_api.get_snapshot_extra_seconds(snapshot) or 0)
    )
    state = "已进入历史" if snapshot.get("is_persisted") else "暂不入历史"
    if snapshot.get("status") == "idle":
        name = "空闲中"
    return {
        "active": True,
        "display": f"{name}｜{project}｜{elapsed}｜{state}",
    }


__all__ = ["WebViewBridge"]
