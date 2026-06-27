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

Phase 3B.3 adds the minimal activity-merge foundation:
``merge_timeline_activities`` is the production write path for merging
exactly two closed, adjacent, same-project/same-resource/same-status
activities into one. The earlier activity keeps its id and start_time; its
end_time is extended to the later activity's end_time. The later activity
is soft-deleted. Only two activities can be merged per call; arbitrary-
length batch merge and multi-activity session whole-merge are NOT
supported. Errors are mapped from stable ``TimelineMergeError`` codes to
Chinese messages without echoing tracebacks, SQL, or internal field names.

Phase 3B.4 adds the minimal hide / soft-delete foundation:
``hide_timeline_activity``, ``soft_delete_timeline_activity``,
``hide_timeline_session``, and ``soft_delete_timeline_session`` are the
production write path for hiding or soft-deleting a single closed activity.
Hide sets ``is_hidden = 1``; soft delete sets ``is_deleted = 1``. Neither
physically deletes the row or touches assignment / resource / note /
session-note rows. Session-level operations only support single-activity
sessions; multi-activity sessions return a clear Chinese message directing
the user to per-activity editing. In-progress activities cannot be hidden
or deleted. Errors are mapped from stable ``TimelineVisibilityError`` codes
to Chinese messages without echoing tracebacks, SQL, or internal field
names. This phase does not change the existing project / note / time /
split / merge semantics.

Phase 3B.6 adds the first batch write capability:
``batch_update_timeline_activities_project`` reclassifies multiple closed,
non-hidden, non-deleted activities to the same project in a single atomic
transaction. It is the production write path for batch project
reassignment only; batch hide / delete / time correction / split / merge
are NOT supported. In-progress, hidden, and deleted activities are
rejected. The service layer uses a rowcount guard and rollback so no
partial write is ever persisted. Errors are mapped from stable
``TimelineBatchProjectError`` codes to Chinese messages without echoing
tracebacks, SQL, window titles, file paths, notes, or internal exception
details.

Phase 3B.7 adds the second batch write capability:
``batch_update_timeline_activities_note`` overwrites the note on multiple
closed, non-hidden, non-deleted activities with the same note value in a
single atomic transaction. It is the production write path for batch note
overwrite only; batch note append / merge, batch hide / delete / time
correction / split / merge are NOT supported. Only ``activity_log.note``
and ``updated_at`` are modified (``source`` is intentionally not changed).
Empty string is allowed and is used to batch-clear notes. In-progress,
hidden, and deleted activities are rejected. The service layer uses a
rowcount guard and rollback so no partial write is ever persisted. Errors
are mapped from stable ``TimelineBatchNoteError`` codes to Chinese
messages without echoing tracebacks, SQL, window titles, file paths,
notes, or internal exception details.

Phase 3B.8 adds the single activity restore foundation:
``restore_timeline_activity`` restores a single hidden or soft-deleted
activity by setting ``is_hidden = 0`` and ``is_deleted = 0`` in a single
atomic UPDATE with a rowcount guard. ``get_timeline_restorable_activities``
returns a display-safe recovery list of hidden / deleted closed activities
for a given date so the user can select which activity to restore. Only
``is_hidden``, ``is_deleted``, and ``updated_at`` are modified; no other
fields, resource rows, assignment rows, or session notes are touched. The
row is never physically deleted. In-progress activities cannot be
restored. Activities that are neither hidden nor deleted are rejected as
``not_restorable``. Errors are mapped from stable
``TimelineRestoreActivityError`` codes to Chinese messages without
echoing tracebacks, SQL, window titles, file paths, notes, or internal
exception details. This phase does NOT implement batch restore, undo
stack, permanent delete, or any new DB schema.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..api import app_api, settings_api, statistics_api, timeline_api, project_api
from ..api.statistics_api import StatisticsSummaryError
from ..api.timeline_api import (
    TimelineBatchNoteError,
    TimelineBatchProjectError,
    TimelineMergeError,
    TimelineRestoreActivityError,
    TimelineSplitError,
    TimelineTimeEditError,
    TimelineVisibilityError,
)
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

# Maps ``TimelineMergeError.code`` to stable Chinese user-facing messages for
# the Phase 3B.3 activity merge. Unknown codes collapse to the generic
# "操作失败" so internal details are never surfaced.
_MERGE_ERROR_MESSAGES = {
    "invalid_selection": "请选择两个活动进行合并",
    "invalid_id": "操作失败",
    "in_progress": "进行中记录暂不支持合并",
    "different_project": "项目不同，暂不支持合并",
    "different_resource": "资源不同，暂不支持合并",
    "incompatible_activity": "活动类型不同，暂不支持合并",
    "not_adjacent": "活动时间不连续，暂不支持合并",
    "invalid_time": "时间无效",
    "operation_failed": "操作失败",
}

# Maps ``TimelineVisibilityError.code`` to stable Chinese user-facing messages
# for the Phase 3B.4 hide / soft delete. Unknown codes collapse to the generic
# "操作失败" so internal details are never surfaced.
_VISIBILITY_ERROR_MESSAGES = {
    "invalid_id": "操作失败",
    "in_progress": "进行中记录暂不支持隐藏或删除",
    "multi_activity_hide": "多活动 session 暂不支持整体隐藏，请在活动详情中逐条处理",
    "multi_activity_delete": "多活动 session 暂不支持整体删除，请在活动详情中逐条处理",
    "operation_failed": "操作失败",
}

# Maps ``TimelineBatchProjectError.code`` to stable Chinese user-facing
# messages for the Phase 3B.6 batch project reassignment. Unknown codes
# collapse to the generic "操作失败" so internal details are never surfaced.
_BATCH_PROJECT_ERROR_MESSAGES = {
    "invalid_selection": "请选择至少两个活动",
    "batch_too_large": "一次最多修改 100 条活动",
    "invalid_project": "请选择有效的项目",
    "in_progress": "进行中记录暂不支持批量修改",
    "hidden_activity": "隐藏记录暂不支持批量修改",
    "operation_failed": "操作失败",
}

# Maps ``TimelineBatchNoteError.code`` to stable Chinese user-facing
# messages for the Phase 3B.7 batch note overwrite. Unknown codes collapse
# to the generic "操作失败" so internal details are never surfaced.
_BATCH_NOTE_ERROR_MESSAGES = {
    "invalid_selection": "请选择至少两个活动",
    "batch_too_large": "一次最多修改 100 条活动",
    "invalid_note": "请输入有效备注",
    "note_too_long": "备注过长",
    "in_progress": "进行中记录暂不支持批量修改",
    "hidden_activity": "隐藏记录暂不支持批量修改",
    "operation_failed": "操作失败",
}

# Maps ``TimelineRestoreActivityError.code`` to stable Chinese user-facing
# messages for the Phase 3B.8 single activity restore. Unknown codes
# collapse to the generic "恢复失败" so internal details are never surfaced.
_RESTORE_ERROR_MESSAGES = {
    "invalid_activity": "请选择有效的活动",
    "not_found": "活动不存在",
    "not_restorable": "该活动无需恢复",
    "in_progress": "进行中记录暂不支持恢复",
    "invalid_date": "日期无效",
    "operation_failed": "恢复失败",
}

# Maps ``StatisticsSummaryError.code`` to stable Chinese user-facing messages
# for the Phase 4A read-only statistics / export summary. Unknown codes
# collapse to the load-focused "加载统计失败" so internal details are never
# surfaced and a statistics load failure never echoes a write-focused message.
_STATISTICS_ERROR_MESSAGES = {
    "invalid_date": "请选择有效日期",
    "invalid_range": "请选择有效日期范围",
    "range_too_large": "日期范围过大",
    "operation_failed": "加载统计失败",
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

    # --- Phase 3B.3: Timeline activity merge (two-activity foundation) ---

    def merge_timeline_activities(self, activity_ids) -> dict[str, Any]:
        """Merge exactly two closed activities into one.

        ``activity_ids`` must be a list of exactly two positive integers
        (``bool`` rejected). The earlier activity (by start_time, then id)
        is kept: its start_time is unchanged and its end_time is extended
        to the later activity's end_time. The later activity is
        soft-deleted.

        The two activities must be closed, non-overlapping, adjacent
        (within ``MERGE_GAP_TOLERANCE_SECONDS``), and share the same
        project, resource, status, and source. In-progress activities
        cannot be merged.

        Returns ``{"ok": true, "kept_activity_id": int, "merged_activity_id": int}``
        on success or ``{"ok": false, "error": "<chinese message>"}`` on
        failure. Known failure modes map to clear Chinese messages; unknown
        failures collapse to ``"操作失败"``. Tracebacks, SQL errors, file
        paths, window titles, and notes are never surfaced.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择两个活动进行合并"}
            # Exactly two ids required after dedup. This check at the
            # bridge layer gives the user an immediate clear message
            # without a round-trip through the API.
            if len(ids) != 2:
                return {"ok": False, "error": "请选择两个活动进行合并"}
            result = timeline_api.merge_timeline_activities(ids)
            return {
                "ok": True,
                "kept_activity_id": int(result.get("kept_activity_id") or 0),
                "merged_activity_id": int(result.get("merged_activity_id") or 0),
            }
        except TimelineMergeError as exc:
            return {"ok": False, "error": _MERGE_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge merge_timeline_activities failed")
            return dict(_GENERIC_ERROR)

    # --- Phase 3B.4: Timeline hide / soft delete (single-activity foundation) ---

    def hide_timeline_activity(self, activity_id) -> dict[str, Any]:
        """Hide a single closed activity from the default Timeline.

        ``activity_id`` must be a positive int (``bool`` rejected). Sets
        ``is_hidden = 1``; the row is not physically deleted. In-progress
        activities (``end_time IS NULL``) cannot be hidden. Hiding an
        already-hidden activity succeeds (idempotent).

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
            timeline_api.hide_timeline_activity(aid)
            return {"ok": True}
        except TimelineVisibilityError as exc:
            return {"ok": False, "error": _VISIBILITY_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge hide_timeline_activity failed")
            return dict(_GENERIC_ERROR)

    def soft_delete_timeline_activity(self, activity_id) -> dict[str, Any]:
        """Soft-delete a single closed activity from the Timeline.

        ``activity_id`` must be a positive int (``bool`` rejected). Sets
        ``is_deleted = 1``; the row is not physically deleted. In-progress
        activities (``end_time IS NULL``) cannot be deleted.

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
            timeline_api.soft_delete_timeline_activity(aid)
            return {"ok": True}
        except TimelineVisibilityError as exc:
            return {"ok": False, "error": _VISIBILITY_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge soft_delete_timeline_activity failed")
            return dict(_GENERIC_ERROR)

    def hide_timeline_session(self, activity_ids) -> dict[str, Any]:
        """Apply a session-level hide.

        ``activity_ids`` is the session's full activity id list. Phase 3B.4
        only supports sessions that resolve to a single activity (after
        deduplication); multi-activity sessions return a clear Chinese
        message directing the user to per-activity hiding.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "<chinese message>"}`` on failure.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "操作失败"}
            # Multi-activity check at the bridge layer so the user gets a
            # clear message without a round-trip through the API.
            if len(ids) > 1:
                return {"ok": False, "error": "多活动 session 暂不支持整体隐藏，请在活动详情中逐条处理"}
            timeline_api.hide_timeline_session(ids)
            return {"ok": True}
        except TimelineVisibilityError as exc:
            return {"ok": False, "error": _VISIBILITY_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge hide_timeline_session failed")
            return dict(_GENERIC_ERROR)

    def soft_delete_timeline_session(self, activity_ids) -> dict[str, Any]:
        """Apply a session-level soft delete.

        ``activity_ids`` is the session's full activity id list. Phase 3B.4
        only supports sessions that resolve to a single activity (after
        deduplication); multi-activity sessions return a clear Chinese
        message directing the user to per-activity deletion.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "<chinese message>"}`` on failure.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "操作失败"}
            if len(ids) > 1:
                return {"ok": False, "error": "多活动 session 暂不支持整体删除，请在活动详情中逐条处理"}
            timeline_api.soft_delete_timeline_session(ids)
            return {"ok": True}
        except TimelineVisibilityError as exc:
            return {"ok": False, "error": _VISIBILITY_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge soft_delete_timeline_session failed")
            return dict(_GENERIC_ERROR)

    def batch_update_timeline_activities_project(self, activity_ids, project_id) -> dict[str, Any]:
        """Phase 3B.6: batch reclassify multiple closed activities to a project.

        ``activity_ids`` must be a list of at least two positive ints after
        deduplication (``bool`` rejected); ``project_id`` must be a positive
        int (``bool`` rejected). The API/service layer performs all deeper
        validation (project exists / not archived / enabled, every activity
        exists / not deleted / not hidden / closed).

        Returns ``{"ok": true, "updated_count": n}`` on success or
        ``{"ok": false, "error": "<chinese message>"}`` on failure. Errors are
        mapped from stable ``TimelineBatchProjectError`` codes so tracebacks,
        SQL, window titles, file paths, notes, and internal exception details
        are never surfaced to JS.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择至少两个活动"}
            if len(ids) < 2:
                return {"ok": False, "error": "请选择至少两个活动"}
            if isinstance(project_id, bool):
                return {"ok": False, "error": "请选择有效的项目"}
            try:
                pid = int(project_id)
            except (TypeError, ValueError):
                return {"ok": False, "error": "请选择有效的项目"}
            if pid <= 0:
                return {"ok": False, "error": "请选择有效的项目"}
            result = timeline_api.batch_update_timeline_activities_project(ids, pid)
            return {"ok": True, "updated_count": int(result.get("updated_count", 0))}
        except TimelineBatchProjectError as exc:
            return {"ok": False, "error": _BATCH_PROJECT_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge batch_update_timeline_activities_project failed")
            return dict(_GENERIC_ERROR)

    def batch_update_timeline_activities_note(self, activity_ids, note) -> dict[str, Any]:
        """Phase 3B.7: batch overwrite the note on multiple closed activities.

        ``activity_ids`` must be a list of at least two positive ints after
        deduplication (``bool`` rejected). ``note`` must be a ``str``
        (``None`` rejected); empty string is allowed and is used to
        batch-clear notes. The API/service layer performs all deeper
        validation (every activity exists / not deleted / not hidden /
        closed).

        Returns ``{"ok": true, "updated_count": n}`` on success or
        ``{"ok": false, "error": "<chinese message>"}`` on failure. Errors are
        mapped from stable ``TimelineBatchNoteError`` codes so tracebacks,
        SQL, window titles, file paths, notes, and internal exception details
        are never surfaced to JS.
        """
        try:
            ids = _coerce_activity_ids(activity_ids)
            if ids is None:
                return {"ok": False, "error": "请选择至少两个活动"}
            if len(ids) < 2:
                return {"ok": False, "error": "请选择至少两个活动"}
            if not isinstance(note, str):
                return {"ok": False, "error": "请输入有效备注"}
            if len(note) > timeline_api.TIMELINE_NOTE_MAX_LENGTH:
                return {"ok": False, "error": "备注过长"}
            result = timeline_api.batch_update_timeline_activities_note(ids, note)
            return {"ok": True, "updated_count": int(result.get("updated_count", 0))}
        except TimelineBatchNoteError as exc:
            return {"ok": False, "error": _BATCH_NOTE_ERROR_MESSAGES.get(exc.code, "操作失败")}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge batch_update_timeline_activities_note failed")
            return dict(_GENERIC_ERROR)

    # --- Phase 3B.8: Timeline single activity restore foundation ---

    def restore_timeline_activity(self, activity_id) -> dict[str, Any]:
        """Restore a single hidden or soft-deleted activity.

        ``activity_id`` must be a positive int (``bool`` rejected). Sets
        ``is_hidden = 0`` and ``is_deleted = 0`` in a single atomic UPDATE;
        the row is not physically deleted. In-progress activities
        (``end_time IS NULL``) cannot be restored. Activities that are
        neither hidden nor deleted are rejected as ``not_restorable``.

        Returns ``{"ok": true, "activity_id": int}`` on success or
        ``{"ok": false, "error": "<chinese message>"}`` on failure. Known
        failure modes map to clear Chinese messages; unknown failures
        collapse to ``"恢复失败"``. Tracebacks, SQL errors, file paths,
        window titles, and notes are never surfaced.
        """
        try:
            if isinstance(activity_id, bool):
                return {"ok": False, "error": "请选择有效的活动"}
            try:
                aid = int(activity_id)
            except (TypeError, ValueError):
                return {"ok": False, "error": "请选择有效的活动"}
            if aid <= 0:
                return {"ok": False, "error": "请选择有效的活动"}
            result = timeline_api.restore_timeline_activity(aid)
            return {"ok": True, "activity_id": int(result.get("activity_id") or 0)}
        except TimelineRestoreActivityError as exc:
            return {"ok": False, "error": _RESTORE_ERROR_MESSAGES.get(exc.code, "恢复失败")}
        except ValueError:
            return {"ok": False, "error": "恢复失败"}
        except Exception:
            logger.exception("webview bridge restore_timeline_activity failed")
            return {"ok": False, "error": "恢复失败"}

    def get_timeline_restorable_activities(self, date) -> dict[str, Any]:
        """Return a display-safe recovery list for a date.

        Returns ``{"ok": true, "activities": [...]}`` where each item has
        display-safe fields only (time range, duration, app/resource/
        project name, status, restore_state). No raw ``window_title``,
        ``file_path_hint``, ``full_path``, ``clipboard``, ``note``, or
        exception details are surfaced. Only hidden / deleted closed
        activities are returned, sorted by ``start_time``.

        Returns ``{"ok": false, "error": "<chinese message>",
        "activities": []}`` on failure.
        """
        try:
            if not isinstance(date, str) or not date:
                return {"ok": False, "error": "加载可恢复记录失败", "activities": []}
            if not _DATE_SHAPE_RE.match(date):
                return {"ok": False, "error": "加载可恢复记录失败", "activities": []}
            result = timeline_api.get_timeline_restorable_activities(date)
            items: list[dict[str, Any]] = []
            for row in result.get("activities") or []:
                items.append(
                    {
                        "activity_id": int(row.get("activity_id") or 0),
                        "start_time": str(row.get("start_time") or ""),
                        "end_time": str(row.get("end_time") or ""),
                        "duration": format_duration(row.get("duration_seconds") or 0),
                        "app_name": str(row.get("app_name") or ""),
                        "resource_type": format_resource_type(
                            row.get("resource_kind"),
                            row.get("resource_subtype"),
                        ),
                        "resource_name": str(row.get("resource_display_name") or "未知"),
                        "project_name": str(row.get("project_name") or "未归类"),
                        "status": str(row.get("status") or ""),
                        "restore_state": str(row.get("restore_state") or ""),
                        "is_hidden": int(row.get("is_hidden") or 0),
                        "is_deleted": int(row.get("is_deleted") or 0),
                    }
                )
            return {"ok": True, "activities": items}
        except TimelineRestoreActivityError as exc:
            # Only ``invalid_date`` has a distinct user-facing message; all
            # other known codes (``operation_failed`` etc.) and unknown codes
            # collapse to the load-focused ``加载可恢复记录失败`` so a
            # recovery-list failure never surfaces a restore-focused message.
            if exc.code == "invalid_date":
                msg = "日期无效"
            else:
                msg = "加载可恢复记录失败"
            return {
                "ok": False,
                "error": msg,
                "activities": [],
            }
        except Exception:
            logger.exception("webview bridge get_timeline_restorable_activities failed")
            return {"ok": False, "error": "加载可恢复记录失败", "activities": []}

    # --- Phase 4A: Statistics / Export read-only summary ----------------

    def get_statistics_export_summary(self, date_from, date_to) -> dict[str, Any]:
        """Return a read-only statistics + export-preview summary.

        Phase 4A read-only path: this method only reads closed activities
        through ``worktrace.api`` and never writes to the DB, never writes a
        file, and never opens a save dialog. ``date_from`` and ``date_to``
        must be ``YYYY-MM-DD`` strings with ``date_from <= date_to`` and an
        inclusive span of at most 31 calendar days.

        Returns ``{"ok": true, "summary": {...}}`` on success or
        ``{"ok": false, "error": "<chinese message>", "summary": null}`` on
        failure. Known failure modes map to clear Chinese messages; unknown
        failures collapse to ``"加载统计失败"``. Tracebacks, SQL errors, raw
        ``window_title`` / ``file_path_hint`` / ``full_path`` / clipboard /
        note, and internal exception details are never surfaced.
        """
        try:
            if not isinstance(date_from, str) or not isinstance(date_to, str):
                return {"ok": False, "error": "请选择有效日期", "summary": None}
            if not _DATE_SHAPE_RE.match(date_from) or not _DATE_SHAPE_RE.match(date_to):
                return {"ok": False, "error": "请选择有效日期", "summary": None}
            summary = statistics_api.get_statistics_export_summary(date_from, date_to)
            return {"ok": True, "summary": _statistics_summary_payload(summary)}
        except StatisticsSummaryError as exc:
            return {
                "ok": False,
                "error": _STATISTICS_ERROR_MESSAGES.get(exc.code, "加载统计失败"),
                "summary": None,
            }
        except Exception:
            logger.exception("webview bridge get_statistics_export_summary failed")
            return {"ok": False, "error": "加载统计失败", "summary": None}


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


def _statistics_summary_payload(summary: dict[str, Any]) -> dict[str, Any]:
    """Build the display-safe Phase 4A statistics summary for JS.

    The service already returns a display-safe dict; this helper adds
    pre-formatted duration strings (matching the Timeline bridge convention)
    so the frontend can render without a second bridge round-trip. Only
    aggregated numbers and display names are surfaced — raw ``window_title``,
    ``file_path_hint``, ``full_path``, ``clipboard``, ``note``, SQL, and
    tracebacks are never present.
    """
    by_project = [
        {
            "key": str(group.get("key") or ""),
            "display_name": str(group.get("display_name") or ""),
            "duration_seconds": int(group.get("duration_seconds") or 0),
            "duration": format_duration(group.get("duration_seconds") or 0),
            "activity_count": int(group.get("activity_count") or 0),
            "percentage": float(group.get("percentage") or 0.0),
        }
        for group in (summary.get("by_project") or [])
    ]
    by_app = [
        {
            "key": str(group.get("key") or ""),
            "display_name": str(group.get("display_name") or ""),
            "duration_seconds": int(group.get("duration_seconds") or 0),
            "duration": format_duration(group.get("duration_seconds") or 0),
            "activity_count": int(group.get("activity_count") or 0),
            "percentage": float(group.get("percentage") or 0.0),
        }
        for group in (summary.get("by_app") or [])
    ]
    by_status = [
        {
            "key": str(group.get("key") or ""),
            "display_name": str(group.get("display_name") or ""),
            "duration_seconds": int(group.get("duration_seconds") or 0),
            "duration": format_duration(group.get("duration_seconds") or 0),
            "activity_count": int(group.get("activity_count") or 0),
            "percentage": float(group.get("percentage") or 0.0),
        }
        for group in (summary.get("by_status") or [])
    ]
    total_seconds = int(summary.get("total_duration_seconds") or 0)
    preview = summary.get("export_preview") or {}
    return {
        "date_from": str(summary.get("date_from") or ""),
        "date_to": str(summary.get("date_to") or ""),
        "total_duration_seconds": total_seconds,
        "total_duration": format_duration(total_seconds),
        "activity_count": int(summary.get("activity_count") or 0),
        "project_count": int(summary.get("project_count") or 0),
        "app_count": int(summary.get("app_count") or 0),
        "by_project": by_project,
        "by_app": by_app,
        "by_status": by_status,
        "export_preview": {
            "date_from": str(preview.get("date_from") or ""),
            "date_to": str(preview.get("date_to") or ""),
            "included_activity_count": int(preview.get("included_activity_count") or 0),
            "included_duration_seconds": int(preview.get("included_duration_seconds") or 0),
            "included_duration": format_duration(preview.get("included_duration_seconds") or 0),
            "available_formats": list(preview.get("available_formats") or []),
            "export_actions_enabled": bool(preview.get("export_actions_enabled")),
        },
    }


__all__ = ["WebViewBridge"]
