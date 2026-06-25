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
production data path for the Timeline page. Phase 2.1 hardens the Timeline
bridge so the ``resource_name`` never falls back to the raw ``window_title``
column (which can contain file paths, URLs, or email subjects) and passes
through an explicit ``is_in_progress`` flag for open sessions/activities.
The timeline service marks ``is_in_progress`` before projecting or replacing
an open activity's ``end_time`` for display; the API and bridge only pass
this flag through. Consumers must not infer in-progress state from the
displayed ``end_time``, because open activities may carry a projected
display ``end_time``.

Phase 3A adds minimal Timeline editing: ``list_projects_for_timeline``,
``update_timeline_project``, and ``update_timeline_note`` are the production
write path for project reclassification and session-note editing. They go
through ``worktrace.api`` only, validate input, and never return tracebacks
or sensitive raw fields. The session note returned by ``get_timeline`` is
the user-authored note (the editing target), not captured metadata.

Phase 3B.1 adds the minimal time-correction foundation:
``update_timeline_activity_time`` and ``update_timeline_session_time`` are
the production write path for correcting a single closed activity's
``start_time``/``end_time``. Session-level correction is only supported for
single-activity sessions; multi-activity sessions return a clear Chinese
message directing the user to per-activity editing. In-progress activities
cannot be edited (their displayed ``end_time`` may be a projected value).
Errors are mapped from stable ``TimelineTimeEditError`` codes to Chinese
messages without echoing tracebacks, SQL, or internal field names.

Phase 3B.2 adds the minimal activity-split foundation:
``split_timeline_activity`` and ``split_timeline_session`` are the production
write path for splitting a single closed activity into two at a given
``split_time``. The original activity keeps its id and becomes the front
half; a new activity is inserted for the back half. Session-level split is
only supported for single-activity sessions; multi-activity sessions return
a clear Chinese message directing the user to per-activity splitting.
In-progress activities cannot be split. Errors are mapped from stable
``TimelineSplitError`` codes to Chinese messages without echoing
tracebacks, SQL, or internal field names.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..api import app_api, settings_api, statistics_api, timeline_api, project_api
from ..api.timeline_api import TimelineSplitError, TimelineTimeEditError
from ..formatters import (
    format_duration,
    format_project_label,
    format_resource_type,
)

logger = logging.getLogger(__name__)

_GENERIC_ERROR = {"ok": False, "error": "操作失败"}
_RECENT_LIMIT = 20

# Lightweight YYYY-MM-DD shape check at the bridge layer. The API layer
# performs the full ``date.fromisoformat`` validation; this guard just gives
# the user a clearer "日期无效" message instead of the generic "操作失败"
# when the date string is obviously malformed.
_DATE_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Lightweight ``YYYY-MM-DD HH:MM:SS`` shape check at the bridge layer. The
# API layer performs the full ``datetime.strptime`` validation; this guard
# gives the user a clearer "时间无效" message for obviously malformed input.
_DATETIME_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

# Maps ``TimelineTimeEditError.code`` to stable Chinese user-facing messages.
# Unknown codes collapse to the generic "操作失败" so internal details are
# never surfaced.
_TIME_ERROR_MESSAGES = {
    "in_progress": "进行中记录暂不支持时间修正",
    "multi_activity": "多活动 session 暂不支持整体时间修改",
    "invalid_time": "时间无效",
    "invalid_id": "操作失败",
}

# Maps ``TimelineSplitError.code`` to stable Chinese user-facing messages for
# the Phase 3B.2 activity split. Unknown codes collapse to the generic
# "操作失败" so internal details are never surfaced.
_SPLIT_ERROR_MESSAGES = {
    "in_progress": "进行中记录暂不支持拆分",
    "multi_activity": "多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动",
    "invalid_time": "拆分时间无效",
    "outside_range": "拆分时间无效",
    "invalid_id": "操作失败",
    "operation_failed": "操作失败",
}


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
                start_time = str(session.get("start_time") or "")
                end_time = str(session.get("end_time") or "")
                sessions.append(
                    {
                        "session_id": str(session.get("session_id") or ""),
                        "project_name": str(session.get("project_name") or "未归类"),
                        "project_description": str(session.get("project_description") or ""),
                        "project_id": int(session.get("project_id") or 0),
                        "start_time": start_time,
                        "end_time": end_time,
                        "duration": format_duration(session.get("duration_seconds") or 0),
                        "status": str(session.get("status_summary") or session.get("status") or ""),
                        "event_count": int(session.get("event_count") or 0),
                        "is_uncategorized": bool(session.get("is_uncategorized")),
                        "is_in_progress": bool(session.get("is_in_progress")),
                        "activity_ids": list(session.get("activity_ids") or []),
                        "first_activity_id": int(session.get("first_activity_id") or 0) or None,
                        "session_note": str(session.get("session_note") or ""),
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
        status. The ``resource_name`` is built from sanitized display fields
        (``resource_display_name`` → ``activity_display_name`` → ``app_name``
        → ``process_name``) and **never** falls back to the raw
        ``window_title`` column, which can contain file paths, URLs, or email
        subjects. Raw window titles, file paths, and notes are not surfaced.
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
                start_time = str(row.get("start_time") or "")
                end_time = str(row.get("end_time") or "")
                activities.append(
                    {
                        "activity_id": int(row.get("id") or 0),
                        "start_time": start_time,
                        "end_time": end_time,
                        "duration": format_duration(row.get("duration_seconds") or 0),
                        "app_name": str(row.get("app_name") or ""),
                        "resource_type": format_resource_type(
                            row.get("resource_kind"),
                            row.get("resource_subtype"),
                        ),
                        "resource_name": _safe_resource_display_name(row),
                        "project_name": str(row.get("project_name") or "未归类"),
                        "status": str(row.get("status") or ""),
                        "is_in_progress": bool(row.get("is_in_progress")),
                    }
                )
            return {"ok": True, "activities": activities}
        except Exception:
            logger.exception("webview bridge get_timeline_session_details failed")
            return dict(_GENERIC_ERROR)

    # --- Phase 3A: Timeline basic editing (project reclassification + note) ---

    def list_projects_for_timeline(self) -> dict[str, Any]:
        """Return the list of projects selectable for Timeline reclassification.

        Returns only display-safe fields (``id``, ``name``, ``description``).
        The "未归类" system project is included so the frontend can represent
        "uncategorized" without inventing a sentinel value. No sensitive
        fields are surfaced.
        """
        try:
            projects = project_api.list_selectable_projects()
            items: list[dict[str, Any]] = []
            for project in projects:
                items.append(
                    {
                        "id": int(project.get("id") or 0),
                        "name": str(project.get("name") or ""),
                        "description": str(project.get("description") or ""),
                    }
                )
            return {"ok": True, "projects": items}
        except Exception:
            logger.exception("webview bridge list_projects_for_timeline failed")
            return dict(_GENERIC_ERROR)

    def update_timeline_project(
        self,
        activity_ids: list[int],
        project_id: int,
    ) -> dict[str, Any]:
        """Reclassify a Timeline session's activities to a project.

        ``activity_ids`` is the session's full activity id list (all
        activities move together, matching the legacy Tkinter behavior).
        ``project_id`` must be one of the ids returned by
        ``list_projects_for_timeline``; the frontend must never pass a
        free-form value.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "操作失败"}`` on any failure. Errors never
        include tracebacks, SQL messages, file paths, or window titles.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择有效的活动"}
            # ``bool`` is a subclass of ``int``; reject it so ``True`` is
            # not coerced to project id ``1``.
            if isinstance(project_id, bool):
                return {"ok": False, "error": "请选择有效的项目"}
            try:
                pid = int(project_id)
            except (TypeError, ValueError):
                return {"ok": False, "error": "请选择有效的项目"}
            timeline_api.reclassify_timeline_session_project(ids, pid)
            return {"ok": True}
        except ValueError:
            # Input validation failed. Return a generic message without
            # echoing the underlying ValueError text, which could reveal
            # internal field names or ids.
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge update_timeline_project failed")
            return dict(_GENERIC_ERROR)

    def update_timeline_note(
        self,
        activity_ids: list[int],
        note: str,
        report_date: str,
    ) -> dict[str, Any]:
        """Write the session note for a Timeline session.

        ``activity_ids`` is the session's activity id list; the first id is
        used as the session-note key (``first_activity_id``). ``note`` is the
        new note text. ``report_date`` is the ``YYYY-MM-DD`` date being
        viewed. The note is stored in ``project_session_note`` (the same
        model the legacy Tkinter Timeline uses). Legitimate newlines inside
        the note are preserved; whitespace-only notes delete the row.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "操作失败"}`` on any failure.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择有效的活动"}
            if not isinstance(note, str):
                return {"ok": False, "error": "备注内容无效"}
            if len(note) > timeline_api.TIMELINE_NOTE_MAX_LENGTH:
                return {"ok": False, "error": "备注过长"}
            if not isinstance(report_date, str) or not report_date:
                return {"ok": False, "error": "日期无效"}
            # Lightweight shape check; the API does the full validation.
            if not _DATE_SHAPE_RE.match(report_date):
                return {"ok": False, "error": "日期无效"}
            first_activity_id = ids[0]
            timeline_api.update_timeline_session_note(
                report_date, first_activity_id, note
            )
            return {"ok": True}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge update_timeline_note failed")
            return dict(_GENERIC_ERROR)

    # --- Phase 3B.1: Timeline time correction (single-activity foundation) ---

    def update_timeline_activity_time(
        self,
        activity_id: int,
        start_time: str,
        end_time: str,
    ) -> dict[str, Any]:
        """Correct a single activity's ``start_time`` and ``end_time``.

        ``activity_id`` must be a positive int (``bool`` rejected).
        ``start_time`` and ``end_time`` must be ``YYYY-MM-DD HH:MM:SS``
        strings with ``start_time < end_time``. In-progress activities
        (``end_time IS NULL``) cannot be edited.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "<chinese message>"}`` on failure. Known
        failure modes map to clear Chinese messages; unknown failures
        collapse to ``"操作失败"``. Tracebacks, SQL errors, file paths,
        window titles, and notes are never surfaced.
        """
        try:
            if isinstance(activity_id, bool):
                return {"ok": False, "error": "操作失败"}
            try:
                aid = int(activity_id)
            except (TypeError, ValueError):
                return {"ok": False, "error": "操作失败"}
            if aid <= 0:
                return {"ok": False, "error": "操作失败"}
            msg = _validate_datetime_inputs(start_time, end_time)
            if msg is not None:
                return {"ok": False, "error": msg}
            timeline_api.update_timeline_activity_time(aid, start_time, end_time)
            return {"ok": True}
        except TimelineTimeEditError as exc:
            return {"ok": False, "error": _TIME_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge update_timeline_activity_time failed")
            return dict(_GENERIC_ERROR)

    def update_timeline_session_time(
        self,
        activity_ids: list[int],
        start_time: str,
        end_time: str,
    ) -> dict[str, Any]:
        """Apply a session-level time correction.

        ``activity_ids`` is the session's full activity id list. Phase 3B.1
        only supports sessions that resolve to a single activity (after
        deduplication); multi-activity sessions return a clear Chinese
        message directing the user to per-activity editing.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "<chinese message>"}`` on failure.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择有效的活动"}
            msg = _validate_datetime_inputs(start_time, end_time)
            if msg is not None:
                return {"ok": False, "error": msg}
            # Multi-activity check at the bridge layer so the user gets a
            # clear message without a round-trip through the API.
            if len(ids) > 1:
                return {"ok": False, "error": "多活动 session 暂不支持整体时间修改"}
            timeline_api.update_timeline_session_time(ids, start_time, end_time)
            return {"ok": True}
        except TimelineTimeEditError as exc:
            return {"ok": False, "error": _TIME_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge update_timeline_session_time failed")
            return dict(_GENERIC_ERROR)

    # --- Phase 3B.2: Timeline activity split (single-activity foundation) ---

    def split_timeline_activity(
        self,
        activity_id: int,
        split_time: str,
    ) -> dict[str, Any]:
        """Split a single closed activity into two at ``split_time``.

        ``activity_id`` must be a positive int (``bool`` rejected).
        ``split_time`` must be a ``YYYY-MM-DD HH:MM:SS`` string strictly
        between the activity's ``start_time`` and ``end_time``. In-progress
        activities (``end_time IS NULL``) cannot be split.

        Returns ``{"ok": true, "original_activity_id": int, "new_activity_id": int}``
        on success or ``{"ok": false, "error": "<chinese message>"}`` on
        failure. Known failure modes map to clear Chinese messages; unknown
        failures collapse to ``"操作失败"``. Tracebacks, SQL errors, file
        paths, window titles, and notes are never surfaced.
        """
        try:
            if isinstance(activity_id, bool):
                return {"ok": False, "error": "操作失败"}
            try:
                aid = int(activity_id)
            except (TypeError, ValueError):
                return {"ok": False, "error": "操作失败"}
            if aid <= 0:
                return {"ok": False, "error": "操作失败"}
            msg = _validate_split_time_input(split_time)
            if msg is not None:
                return {"ok": False, "error": msg}
            result = timeline_api.split_timeline_activity(aid, split_time)
            return {
                "ok": True,
                "original_activity_id": int(result.get("original_activity_id") or 0),
                "new_activity_id": int(result.get("new_activity_id") or 0),
            }
        except TimelineSplitError as exc:
            return {"ok": False, "error": _SPLIT_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge split_timeline_activity failed")
            return dict(_GENERIC_ERROR)

    def split_timeline_session(
        self,
        activity_ids: list[int],
        split_time: str,
    ) -> dict[str, Any]:
        """Apply a session-level split.

        ``activity_ids`` is the session's full activity id list. Phase 3B.2
        only supports sessions that resolve to a single activity (after
        deduplication); multi-activity sessions return a clear Chinese
        message directing the user to per-activity splitting.

        Returns ``{"ok": true, "original_activity_id": int, "new_activity_id": int}``
        on success or ``{"ok": false, "error": "<chinese message>"}`` on
        failure.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择有效的活动"}
            msg = _validate_split_time_input(split_time)
            if msg is not None:
                return {"ok": False, "error": msg}
            # Multi-activity check at the bridge layer so the user gets a
            # clear message without a round-trip through the API.
            if len(ids) > 1:
                return {"ok": False, "error": "多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动"}
            result = timeline_api.split_timeline_session(ids, split_time)
            return {
                "ok": True,
                "original_activity_id": int(result.get("original_activity_id") or 0),
                "new_activity_id": int(result.get("new_activity_id") or 0),
            }
        except TimelineSplitError as exc:
            return {"ok": False, "error": _SPLIT_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge split_timeline_session failed")
            return dict(_GENERIC_ERROR)


def _coerce_activity_ids(activity_ids: list[int]) -> list[int] | None:
    """Validate and normalize the ``activity_ids`` argument from JS.

    Returns a deduplicated list of positive ints, or ``None`` if the input
    is not a usable list of positive integers. This is a bridge-level guard
    so the API layer always receives clean ints; the API layer performs the
    deeper existence checks. ``bool`` values are rejected explicitly so
    ``True``/``False`` are not coerced to ``1``/``0``.
    """
    if not isinstance(activity_ids, list) or not activity_ids:
        return None
    ids: list[int] = []
    seen: set[int] = set()
    for raw in activity_ids:
        if isinstance(raw, bool):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return ids if ids else None


def _validate_datetime_inputs(start_time: str, end_time: str) -> str | None:
    """Bridge-level guard for ``start_time`` / ``end_time`` inputs.

    Returns ``None`` if both values pass the lightweight shape check, or a
    Chinese error message string otherwise. The API layer performs the full
    ``datetime.strptime`` validation and the ``start < end`` ordering check;
    this guard just gives the user a clearer ``"时间无效"`` message for
    obviously malformed input (non-strings, empty, wrong shape).
    """
    if not isinstance(start_time, str) or not isinstance(end_time, str):
        return "时间无效"
    if not start_time or not end_time:
        return "时间无效"
    if not _DATETIME_SHAPE_RE.match(start_time) or not _DATETIME_SHAPE_RE.match(end_time):
        return "时间无效"
    return None


def _validate_split_time_input(split_time: str) -> str | None:
    """Bridge-level guard for the ``split_time`` input.

    Returns ``None`` if the value passes the lightweight shape check, or a
    Chinese error message string otherwise. The API layer performs the full
    ``datetime.strptime`` validation and the strict range check; this guard
    just gives the user a clearer ``"拆分时间无效"`` message for obviously
    malformed input (non-string, empty, wrong shape).
    """
    if not isinstance(split_time, str) or not split_time:
        return "拆分时间无效"
    if not _DATETIME_SHAPE_RE.match(split_time):
        return "拆分时间无效"
    return None


def _safe_resource_display_name(row: dict[str, Any]) -> str:
    """Return a display-safe resource name for a Timeline detail row.

    The fallback chain is intentionally ordered to surface the most
    sanitized field first:

    1. ``resource_display_name`` — already sanitized by the resource
       service (basename for files, cleaned title for browsers, app name
       for generic apps).
    2. ``activity_display_name`` — set to ``resource_display_name`` or
       ``app_name`` by the resource service, so still safe.
    3. ``app_name`` — application name only, no path or window title.
    4. ``process_name`` — process executable name only.

    The raw ``window_title`` column is **deliberately skipped** because it
    can contain full file paths, URLs, or email subjects. ``file_path_hint``
    and ``note`` are also skipped. If all safe fields are empty the row
    falls back to ``"未知"`` rather than leaking sensitive metadata.
    """
    for key in (
        "resource_display_name",
        "activity_display_name",
        "app_name",
        "process_name",
    ):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return "未知"


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
