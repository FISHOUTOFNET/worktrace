"""Timeline bridge mixin.

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
Timeline page method names stay on ``WebViewBridge``.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import (
    project_api,
    timeline_api,
    view_model_api,
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
# the activity split. Unknown codes collapse to the generic "操作失败" so
# internal details are never surfaced.
_SPLIT_ERROR_MESSAGES = {
    "in_progress": "进行中记录暂不支持拆分",
    "multi_activity": "多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动",
    "invalid_time": "拆分时间无效",
    "outside_range": "拆分时间无效",
    "invalid_id": "操作失败",
    "operation_failed": "操作失败",
}

# Maps ``TimelineMergeError.code`` to stable Chinese user-facing messages for
# the activity merge. Unknown codes collapse to the generic "操作失败" so
# internal details are never surfaced.
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
# for the hide / soft delete. Unknown codes collapse to the generic "操作失败"
# so internal details are never surfaced.
_VISIBILITY_ERROR_MESSAGES = {
    "invalid_id": "操作失败",
    "in_progress": "进行中记录暂不支持隐藏或删除",
    "multi_activity_hide": "多活动 session 暂不支持整体隐藏，请在活动详情中逐条处理",
    "multi_activity_delete": "多活动 session 暂不支持整体删除，请在活动详情中逐条处理",
    "operation_failed": "操作失败",
}

# Maps ``TimelineBatchProjectError.code`` to stable Chinese user-facing
# messages for the batch project reassignment. Unknown codes collapse to
# the generic "操作失败" so internal details are never surfaced.
_BATCH_PROJECT_ERROR_MESSAGES = {
    "invalid_selection": "请选择至少两个活动",
    "batch_too_large": "一次最多修改 100 条活动",
    "invalid_project": "请选择有效的项目",
    "in_progress": "进行中记录无法批量修改",
    "hidden_activity": "隐藏记录无法批量修改",
    "operation_failed": "操作失败",
}

# Maps ``TimelineBatchNoteError.code`` to stable Chinese user-facing
# messages for the batch note overwrite. Unknown codes collapse to the
# generic "操作失败" so internal details are never surfaced.
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
# messages for the single activity restore. Unknown codes collapse to the
# load-focused "恢复失败" so internal details are never shown to JS.
_RESTORE_ERROR_MESSAGES = {
    "invalid_activity": "请选择有效的活动",
    "not_found": "活动不存在",
    "not_restorable": "该活动无需恢复",
    "in_progress": "进行中记录无法恢复",
    "invalid_date": "日期无效",
    "operation_failed": "恢复失败",
}


class TimelineBridgeMixin:
    """Timeline page bridge methods.

    Mixed into ``WebViewBridge`` in ``bridge.py`` so the Timeline page
    method names stay on ``WebViewBridge``. The mixin must NOT add
    ``__init__``; it relies on the host class.
    """

    def get_timeline(self, date: str | None = None) -> dict[str, Any]:
        """Return the Timeline page ViewModel for a single date.

        The complete Timeline ViewModel (sessions, live_clock, Activity
        Display Model fields, persisted_open overlay, project transition,
        duration override, raw/display totals) is built by
        ``view_model_service`` from a single snapshot sample. The legacy
        ``live_projection`` alias is no longer surfaced; the Activity
        Display Model is the sole live semantics owner.
        """
        try:
            return view_model_api.get_timeline_view_model(date)
        except Exception:
            logger.exception("webview bridge get_timeline failed")
            return dict(_GENERIC_ERROR)

    def get_timeline_session_details(
        self,
        activity_ids: list[int],
        report_date: str | None = None,
    ) -> dict[str, Any]:
        """Return the Timeline Details ViewModel for a session.

        The complete Details ViewModel (DB detail rows, display-safe
        resource/project fields,
        edit_disabled / disable_reason, live clock fields, single-sample
        Activity Display Model contract) is built by
        ``view_model_service``. ``live_projection`` / ``live_display``
        aliases are not surfaced.
        """
        try:
            ids = [int(aid) for aid in (activity_ids or [])]
            return view_model_api.get_session_details_view_model(ids, report_date)
        except Exception:
            logger.exception("webview bridge get_timeline_session_details failed")
            return dict(_GENERIC_ERROR)


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
        activities move together). ``project_id`` must be one of the ids
        returned by ``list_projects_for_timeline``; the frontend must
        never pass a free-form value.
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
        viewed. The note is stored in ``project_session_note``. Legitimate
        newlines inside the note are preserved; whitespace-only notes
        delete the row.

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

    def update_timeline_note_and_duration(
        self,
        activity_ids: list[int],
        note: str,
        adjusted_duration_seconds: int | None,
        report_date: str,
    ) -> dict[str, Any]:
        """Write note + user-adjusted duration for a Timeline session.

        ``activity_ids`` is the session's activity id list; the first id is
        used as the session key (``first_activity_id``). ``note`` is the new
        note text. ``adjusted_duration_seconds`` is the user-accepted
        duration in seconds (``None`` clears the override, restoring the
        raw collected duration). ``report_date`` is the ``YYYY-MM-DD`` date
        being viewed.

        The adjusted duration is stored in
        ``project_session_note.adjusted_duration_seconds`` and NEVER
        modifies ``activity_log``. Clearing the duration input (passing
        ``None``) removes the override.

        Returns ``{"ok": true}`` on success or
        ``{"ok": false, "error": "<chinese message>"}`` on failure.
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
            if not _DATE_SHAPE_RE.match(report_date):
                return {"ok": False, "error": "日期无效"}
            # Validate adjusted duration: ``None`` clears the override;
            # ``0`` is valid and means display/declare zero duration;
            # negative is invalid. ``bool`` and non-numeric are rejected.
            duration_value: int | None = None
            if adjusted_duration_seconds is not None:
                if isinstance(adjusted_duration_seconds, bool):
                    return {"ok": False, "error": "时长无效"}
                try:
                    duration_value = int(adjusted_duration_seconds)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "时长无效"}
                if duration_value < 0:
                    return {"ok": False, "error": "时长无效"}
                if duration_value > timeline_api.TIMELINE_ADJUSTED_DURATION_MAX_SECONDS:
                    return {"ok": False, "error": "时长无效"}
            first_activity_id = ids[0]
            timeline_api.update_timeline_session_note_and_duration(
                report_date, first_activity_id, note, duration_value
            )
            return {"ok": True}
        except ValueError:
            return {"ok": False, "error": "操作失败"}
        except Exception:
            logger.exception("webview bridge update_timeline_note_and_duration failed")
            return dict(_GENERIC_ERROR)


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

        ``activity_ids`` is the session's full activity id list. Only
        supports sessions that resolve to a single activity (after
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

        ``activity_ids`` is the session's full activity id list. Only
        supports sessions that resolve to a single activity (after
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


    def merge_timeline_activities(self, activity_ids) -> dict[str, Any]:
        """Merge exactly two closed activities into one."""
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

        ``activity_ids`` is the session's full activity id list. Only
        supports sessions that resolve to a single activity (after
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

        ``activity_ids`` is the session's full activity id list. Only
        supports sessions that resolve to a single activity (after
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
        """Batch reclassify multiple closed activities to a project.

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
        """Batch overwrite the note on multiple closed activities.

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
