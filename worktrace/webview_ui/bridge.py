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

Phase 5B adds the first minimal Project Rules WebView write foundation:
``get_project_rules`` remains the display-safe read path, and
``set_project_rule_enabled`` may only enable/disable one existing folder or
keyword rule per call. It does NOT create, edit, delete, enable, or disable
projects; it does NOT create, edit, or delete rules; it does NOT perform
conflict preview, backfill, automatic rules, DB schema changes, native
dialogs, file writes, or network access. Errors collapse to stable Chinese
messages without tracebacks, SQL, raw exception text, window titles,
clipboard, notes, paths, or internal fields.

Phase 5C adds the second minimal Project Rules WebView write foundation:
``create_project_keyword_rule`` creates one new keyword rule on an existing
rule-target project (validated via ``project_api.list_rule_target_projects``,
the same eligibility rule the legacy Tkinter dialog uses). It does NOT
create folder rules, projects, or edit/delete existing rules; it does NOT
perform conflict preview, backfill, automatic rules, DB schema changes,
native dialogs, file writes, or network access. The success payload is the
narrow created-rule summary only; the frontend re-fetches the full Project
Rules list via ``get_project_rules`` after success. Errors are mapped from
stable codes to Chinese messages without tracebacks, SQL, raw exception
text, window titles, clipboard, notes, paths, or internal fields.

Phase 5D adds the third minimal Project Rules WebView write foundation:
``delete_project_keyword_rule`` deletes one existing keyword rule. It only
deletes a keyword rule; it does not delete folder rules, projects, or
edit/enable/disable any rule or project. A ``rule_id`` that points at a
folder rule is rejected as ``关键词规则不存在`` rather than deleting the
folder rule. It does NOT perform conflict preview, backfill, automatic
rules, DB schema changes, native dialogs, file writes, or network access.
The success payload is the narrow deleted-rule summary only; the frontend
re-fetches the full Project Rules list via ``get_project_rules`` after
success. Errors are mapped from stable codes to Chinese messages without
tracebacks, SQL, raw exception text, window titles, clipboard, notes,
paths, or internal fields.

Phase 5E opens the Project Rules folder rule CRUD foundation:
``create_project_folder_rule`` creates one new folder rule on an existing
rule-target project (validated via ``project_api.list_rule_target_projects``,
the same eligibility rule the legacy Tkinter dialog and Phase 5C keyword
creation use). ``update_project_folder_rule`` updates one existing folder
rule's ``folder_path`` and ``recursive`` (a ``rule_id`` that points at a
keyword rule is rejected as ``文件夹规则不存在``; the existing ``project_id``
is preserved). ``delete_project_folder_rule`` deletes one existing folder
rule (a ``rule_id`` that points at a keyword rule is rejected as
``文件夹规则不存在``). The three facades together open the folder rule
create / edit / delete foundation; they do NOT perform conflict preview,
backfill, automatic rules, DB schema changes, native file picker dialogs,
file writes (beyond the rule row itself), or network access. The success
payload is the narrow written-rule summary only; the frontend re-fetches
the full Project Rules list via ``get_project_rules`` after success. Errors
are mapped from stable codes to Chinese messages without tracebacks, SQL,
raw exception text, window titles, clipboard, notes, paths, or internal
fields.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..api import app_api, settings_api, statistics_api, timeline_api, project_api, export_api, rule_api
from ..api.export_api import StatisticsExportError
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
    format_safe_display_name,
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

# Maps ``StatisticsExportError.code`` to stable Chinese user-facing messages
# for the Phase 4B CSV export write action. Unknown codes collapse to
# "导出失败" so internal details are never surfaced. ``permission_denied`` /
# ``file_busy`` / ``write_failed`` share one message so a low-level OS
# failure never distinguishes which kind of write error occurred.
_STATISTICS_EXPORT_ERROR_MESSAGES = {
    "invalid_date": "请选择有效日期",
    "invalid_range": "请选择有效日期范围",
    "range_too_large": "日期范围过大",
    "empty_data": "当前范围没有可导出的记录",
    "invalid_path": "请选择有效保存位置",
    "permission_denied": "无法写入文件，请检查权限或文件是否被占用",
    "file_busy": "无法写入文件，请检查权限或文件是否被占用",
    "write_failed": "无法写入文件，请检查权限或文件是否被占用",
    "operation_failed": "导出失败",
}

# Maps Project Rules write API stable codes to Phase 5B user-facing messages.
# Unknown codes collapse to the generic update failure.
_PROJECT_RULE_WRITE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "规则不存在",
    "operation_failed": "更新规则状态失败",
}

# Maps Project Rules keyword-create API stable codes to Phase 5C user-facing
# messages. Unknown codes collapse to the generic create failure so internal
# details are never surfaced.
_PROJECT_RULE_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "project_not_found": "项目不存在",
    "duplicate_rule": "关键词规则已存在",
    "operation_failed": "新增关键词规则失败",
}

# Maps Project Rules keyword-delete API stable codes to Phase 5D user-facing
# messages. Unknown codes collapse to the generic delete failure so internal
# details are never surfaced. ``not_found`` covers both "id does not exist"
# and "id is a folder rule" — both are reported as ``关键词规则不存在`` so the
# user never learns which table the id belonged to.
_PROJECT_RULE_DELETE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "关键词规则不存在",
    "operation_failed": "删除关键词规则失败",
}

# Maps Project Rules folder-create API stable codes to Phase 5E user-facing
# messages. Unknown codes collapse to the generic create failure so internal
# details are never surfaced.
_PROJECT_RULE_FOLDER_CREATE_MESSAGES = {
    "invalid_input": "操作无效",
    "project_not_found": "项目不存在或不可用",
    "operation_failed": "新增文件夹规则失败",
}

# Maps Project Rules folder-update API stable codes to Phase 5E user-facing
# messages. Unknown codes collapse to the generic update failure so internal
# details are never surfaced. ``not_found`` covers both "id does not exist"
# and "id is a keyword rule" — both are reported as ``文件夹规则不存在`` so the
# user never learns which table the id belonged to.
_PROJECT_RULE_FOLDER_UPDATE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "文件夹规则不存在",
    "operation_failed": "保存文件夹规则失败",
}

# Maps Project Rules folder-delete API stable codes to Phase 5E user-facing
# messages. Unknown codes collapse to the generic delete failure so internal
# details are never surfaced. ``not_found`` covers both "id does not exist"
# and "id is a keyword rule" — both are reported as ``文件夹规则不存在`` so the
# user never learns which table the id belonged to.
_PROJECT_RULE_FOLDER_DELETE_MESSAGES = {
    "invalid_input": "操作无效",
    "not_found": "文件夹规则不存在",
    "operation_failed": "删除文件夹规则失败",
}


class WebViewBridge:
    """Bridge object exposed to JS through pywebview's JS API.

    Each method returns a plain dict (or list inside a dict) so pywebview can
    serialize it to JS. Errors never include tracebacks or sensitive fields.
    """

    def __init__(self) -> None:
        # Phase 4B: the pywebview window is injected by ``webview_main.py``
        # after ``create_window`` so the bridge can open a native save dialog
        # for the CSV export. Stays ``None`` until ``set_window`` is called,
        # so importing / unit-testing the bridge never starts the GUI.
        self._window: Any = None

    def set_window(self, window: Any) -> None:
        """Inject the pywebview window so the bridge can open native dialogs.

        Called by ``worktrace.webview_main`` after ``webview.create_window``
        returns. The bridge must not construct a window itself: that would
        start the GUI on import / during tests. Until this is called the
        CSV export save dialog is unavailable and returns a stable error.
        """
        self._window = window

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

    # --- Phase 5B: Project Rules rule enable/disable foundation ---------

    def get_project_rules(self) -> dict[str, Any]:
        """Return display-safe Project Rules data for the WebView page.

        Read path: this method delegates to
        ``project_api.list_project_bindings()`` and projects the result into
        a stable display payload. It never writes projects/rules, never opens
        native dialogs, and never exposes traceback / SQL / raw exception
        details.
        """
        try:
            projects = project_api.list_project_bindings()
            return {
                "ok": True,
                "projects": [_project_rules_project_payload(project) for project in projects],
            }
        except Exception:
            logger.exception("webview bridge get_project_rules failed")
            return {"ok": False, "error": "加载项目规则失败", "projects": []}

    def set_project_rule_enabled(self, rule_type, rule_id, enabled) -> dict[str, Any]:
        """Enable/disable one existing folder or keyword rule.

        Phase 5B write path only: strict bridge validation rejects bool-as-int
        ids and non-bool enabled values before calling ``rule_api``. The bridge
        never exposes raw exceptions or backend details in the payload.
        """
        try:
            # ``isinstance(rule_type, str)`` short-circuits the set membership
            # check so unhashable non-string types (list / dict) collapse to
            # ``操作无效`` instead of being caught by the outer except and
            # reported as ``更新规则状态失败``.
            if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
                return {"ok": False, "error": "操作无效"}
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(enabled) is not bool:
                return {"ok": False, "error": "操作无效"}
            result = rule_api.set_project_rule_enabled(rule_type, rule_id, enabled)
            if result.get("ok") is True:
                return {
                    "ok": True,
                    "rule_type": str(result.get("rule_type") or rule_type),
                    "rule_id": int(result.get("rule_id") or rule_id),
                    "enabled": bool(result.get("enabled")),
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_WRITE_MESSAGES.get(code, "更新规则状态失败"),
            }
        except Exception:
            logger.exception("webview bridge set_project_rule_enabled failed")
            return {"ok": False, "error": "更新规则状态失败"}

    # --- Phase 5C: Project Rules keyword rule creation foundation ------

    def create_project_keyword_rule(self, project_id, keyword) -> dict[str, Any]:
        """Create one new keyword rule on an existing rule-target project.

        Phase 5C write path only. Strict bridge validation rejects
        bool-as-int ``project_id``, non-int ``project_id``, non-positive
        ids, non-string ``keyword``, and whitespace-only ``keyword`` before
        calling ``rule_api.create_project_keyword_rule``. The bridge never
        exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload.

        Returns ``{"ok": True, "rule": {"kind": "keyword", "id": int,
        "project_id": int, "keyword": str, "enabled": True}}`` on success
        (the narrow created-rule summary only — the frontend re-fetches the
        full Project Rules list via ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B toggle validation pattern.
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(keyword) is not str or not keyword.strip():
                return {"ok": False, "error": "操作无效"}
            # Phase 5C.1: pass the trimmed keyword to the API so the bridge
            # never forwards leading/trailing whitespace even if a future API
            # change drops the trim. Behavior-neutral: the API already trims.
            trimmed_keyword = keyword.strip()
            result = rule_api.create_project_keyword_rule(project_id, trimmed_keyword)
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "keyword",
                        "id": int(rule.get("id") or 0),
                        "project_id": int(rule.get("project_id") or project_id),
                        "keyword": str(rule.get("keyword") or ""),
                        "enabled": bool(rule.get("enabled")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_CREATE_MESSAGES.get(code, "新增关键词规则失败"),
            }
        except Exception:
            logger.exception("webview bridge create_project_keyword_rule failed")
            return {"ok": False, "error": "新增关键词规则失败"}

    # --- Phase 5D: Project Rules keyword rule deletion foundation -------

    def delete_project_keyword_rule(self, rule_id) -> dict[str, Any]:
        """Delete one existing keyword rule.

        Phase 5D write path only. Strict bridge validation rejects
        bool-as-int ``rule_id``, non-int ``rule_id``, and non-positive ids
        before calling ``rule_api.delete_project_keyword_rule``. The bridge
        never exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload.

        Returns ``{"ok": True, "rule": {"kind": "keyword", "id": int,
        "deleted": True}}`` on success (the narrow deleted-rule summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C validation pattern.
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            result = rule_api.delete_project_keyword_rule(rule_id)
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "keyword",
                        "id": int(rule.get("id") or rule_id),
                        "deleted": bool(rule.get("deleted")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_DELETE_MESSAGES.get(code, "删除关键词规则失败"),
            }
        except Exception:
            logger.exception("webview bridge delete_project_keyword_rule failed")
            return {"ok": False, "error": "删除关键词规则失败"}

    # --- Phase 5E: Project Rules folder rule CRUD foundation ---------

    def create_project_folder_rule(self, project_id, folder_path, recursive) -> dict[str, Any]:
        """Create one new folder rule on an existing rule-target project.

        Phase 5E write path only. Strict bridge validation rejects
        bool-as-int ``project_id``, non-int ``project_id``, non-positive
        ids, non-string ``folder_path``, whitespace-only ``folder_path``,
        and non-bool ``recursive`` before calling
        ``rule_api.create_project_folder_rule``. The bridge never exposes
        raw exceptions, tracebacks, SQL, paths, window titles, clipboard, or
        notes in the payload.

        Returns ``{"ok": True, "rule": {"kind": "folder", "id": int,
        "project_id": int, "folder_path": str, "recursive": bool,
        "enabled": True}}`` on success (the narrow created-rule summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C / 5D validation pattern.
            if type(project_id) is not int or project_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(folder_path) is not str or not folder_path.strip():
                return {"ok": False, "error": "操作无效"}
            if type(recursive) is not bool:
                return {"ok": False, "error": "操作无效"}
            # Pass the trimmed folder_path to the API so the bridge never
            # forwards leading/trailing whitespace even if a future API
            # change drops the trim. Behavior-neutral: the API already trims.
            trimmed_path = folder_path.strip()
            result = rule_api.create_project_folder_rule(
                project_id, trimmed_path, recursive
            )
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "folder",
                        "id": int(rule.get("id") or 0),
                        "project_id": int(rule.get("project_id") or project_id),
                        "folder_path": str(rule.get("folder_path") or ""),
                        "recursive": bool(rule.get("recursive")),
                        "enabled": bool(rule.get("enabled")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_FOLDER_CREATE_MESSAGES.get(
                    code, "新增文件夹规则失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge create_project_folder_rule failed")
            return {"ok": False, "error": "新增文件夹规则失败"}

    def update_project_folder_rule(self, rule_id, folder_path, recursive) -> dict[str, Any]:
        """Update one existing folder rule's ``folder_path`` and ``recursive``.

        Phase 5E write path only. Strict bridge validation rejects
        bool-as-int ``rule_id``, non-int ``rule_id``, non-positive ids,
        non-string ``folder_path``, whitespace-only ``folder_path``, and
        non-bool ``recursive`` before calling
        ``rule_api.update_project_folder_rule``. The bridge never exposes
        raw exceptions, tracebacks, SQL, paths, window titles, clipboard, or
        notes in the payload. A ``rule_id`` that points at a keyword rule is
        rejected as ``文件夹规则不存在`` rather than modifying the keyword rule.

        Returns ``{"ok": True, "rule": {"kind": "folder", "id": int,
        "project_id": int, "folder_path": str, "recursive": bool,
        "enabled": True}}`` on success (the narrow updated-rule summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C / 5D validation pattern.
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            if type(folder_path) is not str or not folder_path.strip():
                return {"ok": False, "error": "操作无效"}
            if type(recursive) is not bool:
                return {"ok": False, "error": "操作无效"}
            trimmed_path = folder_path.strip()
            result = rule_api.update_project_folder_rule(
                rule_id, trimmed_path, recursive
            )
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "folder",
                        "id": int(rule.get("id") or rule_id),
                        "project_id": int(rule.get("project_id") or 0),
                        "folder_path": str(rule.get("folder_path") or ""),
                        "recursive": bool(rule.get("recursive")),
                        "enabled": bool(rule.get("enabled")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_FOLDER_UPDATE_MESSAGES.get(
                    code, "保存文件夹规则失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge update_project_folder_rule failed")
            return {"ok": False, "error": "保存文件夹规则失败"}

    def delete_project_folder_rule(self, rule_id) -> dict[str, Any]:
        """Delete one existing folder rule.

        Phase 5E write path only. Strict bridge validation rejects
        bool-as-int ``rule_id``, non-int ``rule_id``, and non-positive ids
        before calling ``rule_api.delete_project_folder_rule``. The bridge
        never exposes raw exceptions, tracebacks, SQL, paths, window titles,
        clipboard, or notes in the payload. A ``rule_id`` that points at a
        keyword rule is rejected as ``文件夹规则不存在`` rather than deleting the
        keyword rule.

        Returns ``{"ok": True, "rule": {"kind": "folder", "id": int,
        "deleted": True}}`` on success (the narrow deleted-rule summary
        only — the frontend re-fetches the full Project Rules list via
        ``get_project_rules`` after success) or
        ``{"ok": False, "error": "<chinese message>"}`` on failure.
        """
        try:
            # ``type(...) is not int`` rejects ``bool`` (``type(True) is
            # bool``), ``float``, ``str``, ``None``, and container types in
            # one check, matching the Phase 5B / 5C / 5D validation pattern.
            if type(rule_id) is not int or rule_id <= 0:
                return {"ok": False, "error": "操作无效"}
            result = rule_api.delete_project_folder_rule(rule_id)
            if result.get("ok") is True:
                rule = result.get("rule") or {}
                return {
                    "ok": True,
                    "rule": {
                        "kind": "folder",
                        "id": int(rule.get("id") or rule_id),
                        "deleted": bool(rule.get("deleted")),
                    },
                }
            code = str(result.get("error") or "operation_failed")
            return {
                "ok": False,
                "error": _PROJECT_RULE_FOLDER_DELETE_MESSAGES.get(
                    code, "删除文件夹规则失败"
                ),
            }
        except Exception:
            logger.exception("webview bridge delete_project_folder_rule failed")
            return {"ok": False, "error": "删除文件夹规则失败"}

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
            # ``isinstance(..., str)`` rejects ``None``, ``bool``, ``int``,
            # and any other non-string type. ``bool`` is explicitly not a
            # string and is rejected here so ``True``/``False`` never reach
            # the API/service validation.
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

    # --- Phase 4B: Statistics CSV export (controlled file write) ---------

    def export_statistics_csv(self, date_from, date_to) -> dict[str, Any]:
        """Export a display-safe CSV for the statistics date range.

        Phase 4B controlled write path. ``date_from`` / ``date_to`` must be
        ``YYYY-MM-DD`` strings sharing the same rules as the read-only
        summary. The save path is chosen by the user through the native
        pywebview save dialog (the window is injected via ``set_window``);
        the bridge never writes to a hard-coded location.

        The bridge only validates the obvious date shape and opens the
        save dialog; all deeper validation and the file write happen in
        ``worktrace.api.export_api.export_statistics_csv`` (which goes
        through ``export_service``). The bridge does not import services /
        db / collector / runtime / config / security.

        Returns one of:

        - ``{"ok": True, "filename": "<basename.csv>", "activity_count": n,
          "duration": "HH:MM:SS", "cancelled": False}`` on success. Only
          the basename is surfaced; the full local path never leaves the
          bridge.
        - ``{"ok": False, "cancelled": True, "error": "已取消导出"}`` when
          the user cancels the save dialog. No API write is called.
        - ``{"ok": False, "error": "<chinese message>", "cancelled":
          False}`` on any failure. Known failure modes map to clear
          Chinese messages; unknown failures collapse to ``"导出失败"``.

        Tracebacks, SQL, full local paths, raw exception text, window
        titles, file paths, and notes are never surfaced to JS.
        """
        try:
            # ``isinstance(..., str)`` rejects ``None``, ``bool``, ``int``,
            # and any other non-string type (``bool`` is not a string).
            if not isinstance(date_from, str) or not isinstance(date_to, str):
                return {"ok": False, "error": "请选择有效日期", "cancelled": False}
            if not _DATE_SHAPE_RE.match(date_from) or not _DATE_SHAPE_RE.match(date_to):
                return {"ok": False, "error": "请选择有效日期", "cancelled": False}
            output_path = self._choose_csv_save_path()
            if output_path is None:
                # User cancelled the native save dialog. This is a clean
                # cancel result, not a Python exception or "操作失败".
                return {"ok": False, "cancelled": True, "error": "已取消导出"}
            result = export_api.export_statistics_csv(
                date_from, date_to, output_path
            )
            return {
                "ok": True,
                "filename": str(result.get("filename") or ""),
                "activity_count": int(result.get("activity_count") or 0),
                "duration": format_duration(result.get("duration_seconds") or 0),
                "cancelled": False,
            }
        except StatisticsExportError as exc:
            return {
                "ok": False,
                "error": _STATISTICS_EXPORT_ERROR_MESSAGES.get(exc.code, "导出失败"),
                "cancelled": False,
            }
        except Exception:
            logger.exception("webview bridge export_statistics_csv failed")
            return {"ok": False, "error": "导出失败", "cancelled": False}

    def _choose_csv_save_path(self) -> str | None:
        """Open the native save dialog and return the chosen path or ``None``.

        Returns ``None`` when the user cancels. Raises
        ``StatisticsExportError("operation_failed")`` when no window has
        been injected or the pywebview save dialog API is unavailable / raises.

        The returned path is the user-chosen string verbatim; path
        normalization (``.csv`` suffix, parent existence) is handled by the
        service layer. The full path never leaves the bridge except as the
        argument to the API write call (which is the only path the bridge
        is allowed to touch).
        """
        window = self._window
        if window is None:
            raise StatisticsExportError("operation_failed")
        # Resolve the save dialog type constant lazily so the bridge module
        # does not import pywebview at import time (which would pull the
        # WebView backend into unit tests). Newer pywebview exposes
        # ``FileDialog.SAVE``; the deprecated ``SAVE_DIALOG`` is the fallback.
        dialog_type = None
        try:
            import webview  # noqa: WPS433 (lazy import, UI-only dependency)

            file_dialog = getattr(webview, "FileDialog", None)
            if file_dialog is not None:
                dialog_type = getattr(file_dialog, "SAVE", None)
            if dialog_type is None:
                dialog_type = getattr(webview, "SAVE_DIALOG", None)
        except Exception:
            dialog_type = None
        if dialog_type is None:
            raise StatisticsExportError("operation_failed")
        try:
            result = window.create_file_dialog(
                dialog_type,
                save_filename="worktrace-export.csv",
                file_types=("CSV Files (*.csv)",),
            )
        except Exception:
            raise StatisticsExportError("operation_failed")
        if not result:
            return None
        # pywebview returns a sequence of strings (or None on cancel). For a
        # save dialog exactly one path is expected; take the first.
        if isinstance(result, (tuple, list)):
            if not result:
                return None
            return str(result[0])
        return str(result)


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

    Delegates to the shared ``formatters.format_safe_display_name`` helper
    so the Timeline detail rows and the Phase 4B CSV export use the same
    display-safe fallback chain (``resource_display_name`` →
    ``activity_display_name`` → ``app_name`` → ``process_name`` → ``未知``)
    without the bridge reverse-depending on the export service.

    The raw ``window_title`` column is **deliberately skipped** because it
    can contain full file paths, URLs, or email subjects. ``file_path_hint``
    and ``note`` are also skipped. If all safe fields are empty the row
    falls back to ``"未知"`` rather than leaking sensitive metadata.
    """
    return format_safe_display_name(row)


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


def _project_rules_project_payload(project: dict[str, Any]) -> dict[str, Any]:
    """Build one Phase 5A Project Rules display payload."""
    project = _project_rules_mapping(project)
    project_name = _project_rules_text(project.get("name"), "未知项目")
    project_enabled = _project_rules_bool(project.get("enabled"), default=True)
    is_excluded = project_name == "排除规则"
    folder_rules = [
        _project_rules_folder_payload(rule, project_name)
        for rule in _project_rules_list(project.get("folder_rules"))
    ]
    keyword_rules = [
        _project_rules_keyword_payload(rule, project_name)
        for rule in _project_rules_list(project.get("keyword_rules"))
    ]
    folder_count = len(folder_rules)
    keyword_count = len(keyword_rules)
    rule_count = folder_count + keyword_count
    summary = _project_rules_summary(
        project_enabled=project_enabled,
        is_excluded=is_excluded,
        folder_count=folder_count,
        keyword_count=keyword_count,
    )
    return {
        "id": _project_rules_int(project.get("id")),
        "name": project_name,
        "description": _project_rules_text(project.get("description"), ""),
        "enabled": project_enabled,
        "created_by": _project_rules_text(project.get("created_by"), ""),
        "is_excluded": is_excluded,
        "summary": summary,
        "folder_rule_count": folder_count,
        "keyword_rule_count": keyword_count,
        "rule_count": rule_count,
        "rules": [*folder_rules, *keyword_rules],
    }


def _project_rules_folder_payload(rule: dict[str, Any], project_name: str) -> dict[str, Any]:
    rule = _project_rules_mapping(rule)
    enabled = _project_rules_bool(rule.get("enabled"), default=True)
    recursive = _project_rules_bool(rule.get("recursive"), default=True)
    scope = "包含子文件夹" if recursive else "仅直接文件"
    state = "已启用" if enabled else "已禁用"
    return {
        "kind": "folder",
        "kind_label": "文件夹",
        "id": _project_rules_int(rule.get("id")),
        "target": _project_rules_text(rule.get("folder_path"), ""),
        "enabled": enabled,
        "recursive": recursive,
        "detail": f"归属项目：{project_name} | {scope} | {state}",
    }


def _project_rules_keyword_payload(rule: dict[str, Any], project_name: str) -> dict[str, Any]:
    rule = _project_rules_mapping(rule)
    enabled = _project_rules_bool(rule.get("enabled"), default=True)
    state = "已启用" if enabled else "已禁用"
    return {
        "kind": "keyword",
        "kind_label": "关键词",
        "id": _project_rules_int(rule.get("id")),
        "target": _project_rules_text(rule.get("keyword"), ""),
        "enabled": enabled,
        "recursive": None,
        "detail": f"归属项目：{project_name} | {state}",
    }


def _project_rules_summary(
    *,
    project_enabled: bool,
    is_excluded: bool,
    folder_count: int,
    keyword_count: int,
) -> str:
    parts: list[str] = []
    if not project_enabled:
        parts.append("已禁用")
    if is_excluded:
        parts.append("命中后匿名记录")
    total = folder_count + keyword_count
    if total == 0:
        parts.append("暂无规则")
    else:
        parts.append(f"{total} 条规则：文件夹 {folder_count}，关键词 {keyword_count}")
    return " | ".join(parts)


def _project_rules_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return default


def _project_rules_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _project_rules_text(value: Any, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _project_rules_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _project_rules_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


__all__ = ["WebViewBridge"]
