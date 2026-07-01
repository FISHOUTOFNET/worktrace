"""Timeline bridge mixin, split out of ``bridge.py``.

Boundary rules (enforced by ``tests/test_ui_backend_boundary.py``):

- This module may import ``worktrace.api``, ``worktrace.constants``,
  ``worktrace.formatters``, and stdlib only. It must NOT import
  ``worktrace.services``, ``worktrace.db``, ``worktrace.collector``,
  ``worktrace.security``, ``worktrace.runtime``, or ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  style payloads without tracebacks.
- Methods do not log window titles, file paths, notes, or copied text.

``WebViewBridge`` in ``bridge.py`` inherits ``TimelineBridgeMixin`` so the
Timeline page method names stay on ``WebViewBridge`` and the frontend /
tests see no API-surface change.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import (
    live_display_api,
    project_api,
    settings_api,
    timeline_api,
)
from ..api.timeline_api import (
    TimelineBatchNoteError,
    TimelineBatchProjectError,
    TimelineMergeError,
    TimelineRestoreActivityError,
    TimelineSplitError,
    TimelineTimeEditError,
    TimelineVisibilityError,
)
from ..formatters import format_duration, format_resource_type
from .bridge_common import (
    _DATE_SHAPE_RE,
    _GENERIC_ERROR,
    _coerce_activity_ids,
    _safe_resource_display_name,
    _snapshot_summary,
    _validate_datetime_inputs,
    _validate_split_time_input,
)

logger = logging.getLogger(__name__)


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
    "in_progress": "进行中记录无法批量修改",
    "hidden_activity": "隐藏记录无法批量修改",
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
    "in_progress": "进行中记录无法批量修改",
    "hidden_activity": "隐藏记录无法批量修改",
    "operation_failed": "操作失败",
}

# Maps ``TimelineRestoreActivityError.code`` to stable Chinese user-facing
# messages for the Phase 3B.8 single activity restore. Unknown codes
# collapse to the load-focused "恢复失败" so internal details are never
# surfaced.
_RESTORE_ERROR_MESSAGES = {
    "invalid_activity": "请选择有效的活动",
    "not_found": "活动不存在",
    "not_restorable": "该活动无需恢复",
    "in_progress": "进行中记录无法恢复",
    "invalid_date": "日期无效",
    "operation_failed": "恢复失败",
}


class TimelineBridgeMixin:
    """Timeline page bridge methods, split out of ``WebViewBridge``.

    The mixin is mixed into ``WebViewBridge`` in ``bridge.py`` so the
    Timeline page method names stay on ``WebViewBridge``. The mixin
    must NOT add ``__init__``; it relies on the host class.
    """

    def get_timeline(self, date: str | None = None) -> dict[str, Any]:
        """Return read-only timeline data for a single date.

        Unified live-display model. The payload supports three session kinds:

        - **virtual live session** — prepended when the viewed date is today
          AND the current snapshot is a normal unpersisted <30s activity.
          ``is_virtual`` / ``is_virtual_live`` are true, ``activity_id`` is
          ``0``, ``source`` is ``"snapshot"``, ``edit_disabled`` is true,
          and the time range shows "进行中". The DB is NEVER written.
        - **persisted open session** — a real DB session whose
          ``is_in_progress`` is true. ``duration_seconds`` already includes
          the live seconds from ``timeline_service._live_duration_for_row``.
        - **closed DB session** — a finalized session row.

        ``today_total_seconds`` includes the virtual live session's fetched
        snapshot duration so the displayed total matches the sum of session
        durations. The frontend ticker adds the unified live clock delta
        (``live_started_at_epoch_ms`` + ``carry_seconds``) only to the
        virtual / in-progress session. Historical dates are never projected.
        idle / paused / excluded / error snapshots never produce a virtual
        session.
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
            today = timeline_api.get_default_report_date()
            current = _snapshot_summary(snapshot)
            live_display = live_display_api.build_current_activity_summary(
                snapshot, report_date=report_date, today=today
            )
            # Build the persisted-open overlay once so every DB session
            # that matches the persisted_activity_id can carry the same
            # stable live fields as the virtual session (verification
            # items 12, 16, 21).
            persisted_overlay = live_display_api.build_persisted_open_overlay(
                snapshot, report_date=report_date, today=today
            )
            sessions: list[dict[str, Any]] = []
            virtual_session_seconds = 0
            # Prepend a virtual live session when the current snapshot is a
            # normal unpersisted activity on today's date. This is
            # display-only; the DB is never written.
            virtual_session = live_display_api.build_virtual_session(
                snapshot, report_date=report_date, today=today
            )
            if virtual_session is not None:
                vseconds = int(virtual_session.get("duration_seconds") or 0)
                virtual_session_seconds = vseconds
                sessions.append(
                    {
                        "session_id": str(virtual_session.get("session_id") or "virtual-live"),
                        "project_name": str(virtual_session.get("project_name") or "未归类"),
                        "project_description": str(virtual_session.get("project_description") or ""),
                        "project_id": int(virtual_session.get("project_id") or 0),
                        "start_time": str(virtual_session.get("start_time") or ""),
                        "end_time": "",
                        "duration": str(virtual_session.get("duration") or "00:00:00"),
                        "duration_seconds": vseconds,
                        "status": "进行中",
                        "event_count": int(virtual_session.get("event_count") or 0),
                        "is_uncategorized": bool(virtual_session.get("is_uncategorized")),
                        "is_in_progress": True,
                        "is_live_projected": True,
                        "is_virtual": True,
                        "is_virtual_live": True,
                        "live_display_key": str(virtual_session.get("live_display_key") or ""),
                        # Stable live identity so the frontend continuity
                        # key survives the virtual → persisted_open
                        # transition (verification items 12, 16, 21).
                        "stable_live_key": str(virtual_session.get("stable_live_key") or ""),
                        "stable_live_key_hash": str(virtual_session.get("stable_live_key_hash") or ""),
                        # Unified live clock fields (scheme A).
                        "live_state": "virtual",
                        "live_started_at_epoch_ms": int(virtual_session.get("live_started_at_epoch_ms") or 0),
                        "carry_seconds": int(virtual_session.get("carry_seconds") or 0),
                        "activity_ids": [],
                        "first_activity_id": None,
                        "session_note": "",
                        "edit_disabled": True,
                        "disable_reason": str(virtual_session.get("disable_reason") or ""),
                        "source": "snapshot",
                    }
                )
            for session in sessions_raw:
                start_time = str(session.get("start_time") or "")
                end_time = str(session.get("end_time") or "")
                session_seconds = int(session.get("duration_seconds") or 0)
                is_in_progress = bool(session.get("is_in_progress"))
                row = {
                    "session_id": str(session.get("session_id") or ""),
                    "project_name": str(session.get("project_name") or "未归类"),
                    "project_description": str(session.get("project_description") or ""),
                    "project_id": int(session.get("project_id") or 0),
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": format_duration(session_seconds),
                    "duration_seconds": session_seconds,
                    "status": str(session.get("status_summary") or session.get("status") or ""),
                    "event_count": int(session.get("event_count") or 0),
                    "is_uncategorized": bool(session.get("is_uncategorized")),
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
                    "activity_ids": list(session.get("activity_ids") or []),
                    "first_activity_id": int(session.get("first_activity_id") or 0) or None,
                    "session_note": str(session.get("session_note") or ""),
                    "edit_disabled": False,
                    "disable_reason": "",
                    "source": "db",
                }
                # Apply the persisted-open overlay so the matching DB
                # session carries the same stable live fields as the
                # virtual session. No-op for closed / non-matching rows.
                live_display_api.apply_persisted_open_overlay_to_row(row, persisted_overlay)
                sessions.append(row)
            # Include the virtual session's fetched snapshot duration in
            # the totals so the displayed total matches the sum of session
            # durations. The frontend ticker only adds the unified live
            # clock delta on top, so there is no double-counting.
            display_total_seconds = total_seconds + virtual_session_seconds
            return {
                "ok": True,
                "date": report_date,
                "total_duration": format_duration(display_total_seconds),
                "total_seconds": display_total_seconds,
                "current_activity": current,
                "live_display": live_display,
                "sessions": sessions,
                # Raw seconds for the 1-second local ticker. The ticker
                # only updates DOM text; it never calls a bridge method or
                # writes the DB.
                "today_total_seconds": display_total_seconds,
                "current_activity_elapsed_seconds": int(current.get("elapsed_seconds") or 0),
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

        Unified live-display model. When ``activity_ids`` is empty AND the
        viewed date is today AND the current snapshot is a normal
        unpersisted <30s activity, the bridge returns a single display-only
        **virtual detail row** (``is_virtual`` / ``is_virtual_live`` true,
        ``activity_id`` ``0``, ``source`` ``"snapshot"``,
        ``edit_disabled`` true). The virtual row uses the snapshot's
        display-safe resource / app / project — it is NEVER projected onto
        an old DB row. The DB is never written.

        For real DB activity ids, each row exposes display-safe fields
        only: time range, duration, app name, resource type, resource
        display name, project name, and status. The ``resource_name`` is
        built from sanitized display fields and **never** falls back to
        the raw ``window_title`` column. Raw window titles, file paths,
        and notes are not surfaced.

        Each row carries ``duration_seconds`` (fetched snapshot duration),
        ``is_in_progress``, ``is_virtual``, ``is_virtual_live``,
        ``live_display_key``, ``activity_id``, ``source``,
        ``edit_disabled``, and ``disable_reason`` so the frontend ticker
        can locate the live row by flag and increment its duration by the
        unified live clock delta (``live_started_at_epoch_ms`` +
        ``carry_seconds``).
        """
        try:
            ids = [int(aid) for aid in (activity_ids or [])]
            date = report_date or timeline_api.get_default_report_date()
            today = timeline_api.get_default_report_date()
            snapshot = settings_api.get_current_activity_snapshot()
            # Build the unified live-display summary from the same snapshot
            # sample so the detail ticker can compute its own live delta
            # (verification item 8). This is built before the virtual-row
            # branch so both the virtual-row return and the DB-row return
            # carry the same ``live_display`` payload.
            live_display = live_display_api.build_current_activity_summary(
                snapshot, report_date=date, today=today
            )
            # Build the persisted-open overlay once so every DB detail row
            # that matches the persisted_activity_id can carry the same
            # stable live fields as the virtual detail row (verification
            # items 12, 16, 21).
            persisted_overlay = live_display_api.build_persisted_open_overlay(
                snapshot, report_date=date, today=today
            )
            activities: list[dict[str, Any]] = []
            # When the requested session is the virtual live session
            # (empty activity_ids) and the snapshot is eligible, return a
            # single virtual detail row. This avoids projecting the
            # unpersisted activity onto an old DB row.
            if not ids:
                virtual_row = live_display_api.build_virtual_detail_row(
                    snapshot, report_date=date, today=today
                )
                if virtual_row is not None:
                    activities.append(
                        {
                            "activity_id": 0,
                            "start_time": str(virtual_row.get("start_time") or ""),
                            "end_time": "",
                            "duration": str(virtual_row.get("duration") or "00:00:00"),
                            "duration_seconds": int(virtual_row.get("duration_seconds") or 0),
                            "app_name": str(virtual_row.get("app_name") or ""),
                            "resource_type": str(virtual_row.get("resource_type") or ""),
                            "resource_name": str(virtual_row.get("resource_name") or "未知"),
                            "project_name": str(virtual_row.get("project_name") or "未归类"),
                            "status": str(virtual_row.get("status") or ""),
                            "is_in_progress": True,
                            "is_live_projected": True,
                            "is_virtual": True,
                            "is_virtual_live": True,
                            "live_display_key": str(virtual_row.get("live_display_key") or ""),
                            # Stable live identity so the frontend continuity
                            # key survives the virtual → persisted_open
                            # transition (verification items 12, 16, 21).
                            "stable_live_key": str(virtual_row.get("stable_live_key") or ""),
                            "stable_live_key_hash": str(virtual_row.get("stable_live_key_hash") or ""),
                            # Unified live clock fields (scheme A).
                            "live_state": "virtual",
                            "live_started_at_epoch_ms": int(virtual_row.get("live_started_at_epoch_ms") or 0),
                            "carry_seconds": int(virtual_row.get("carry_seconds") or 0),
                            "source": "snapshot",
                            "edit_disabled": True,
                            "disable_reason": str(virtual_row.get("disable_reason") or ""),
                        }
                    )
                return {
                    "ok": True,
                    "activities": activities,
                    # Unified live-display payload for the detail ticker
                    # (verification item 8: detail ticker must not use
                    # Timeline main payload delta).
                    "live_display": live_display,
                }
            rows = timeline_api.get_session_activity_details(
                ids,
                report_date=date,
                ensure_context=True,
            )
            for row in rows:
                start_time = str(row.get("start_time") or "")
                end_time = str(row.get("end_time") or "")
                row_seconds = int(row.get("duration_seconds") or 0)
                is_in_progress = bool(row.get("is_in_progress"))
                detail_row = {
                    "activity_id": int(row.get("id") or 0),
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": format_duration(row_seconds),
                    "duration_seconds": row_seconds,
                    "app_name": str(row.get("app_name") or ""),
                    "resource_type": format_resource_type(
                        row.get("resource_kind"),
                        row.get("resource_subtype"),
                    ),
                    "resource_name": _safe_resource_display_name(row),
                    "project_name": str(row.get("project_name") or "未归类"),
                    "status": str(row.get("status") or ""),
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
                    "source": "db",
                    "edit_disabled": False,
                    "disable_reason": "",
                }
                # Apply the persisted-open overlay so the matching DB
                # detail row carries the same stable live fields as the
                # virtual detail row. No-op for closed / non-matching rows.
                live_display_api.apply_persisted_open_overlay_to_row(detail_row, persisted_overlay)
                activities.append(detail_row)
            return {
                "ok": True,
                "activities": activities,
                # Unified live-display payload so the detail ticker can
                # compute its own live delta from ``live_started_at_epoch_ms``
                # + ``carry_seconds`` instead of reusing the Timeline main
                # payload's delta (verification item 8). The detail payload
                # and the Timeline main payload are separate bridge calls
                # that may arrive at different times; using the main
                # payload's delta for the detail ticker caused the detail
                # duration to drift relative to its own baseline.
                "live_display": live_display,
            }
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


__all__ = ["TimelineBridgeMixin"]
