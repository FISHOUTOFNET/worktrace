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
    errors as api_errors,
    project_api,
    timeline_api,
    view_model_api,
)
from ..formatters import format_duration, format_resource_type
from .bridge_common import (
    _DATE_SHAPE_RE,
    _GENERIC_ERROR,
    _coerce_activity_ids,
)

logger = logging.getLogger(__name__)



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

    def get_timeline_session_activity_summary(
        self,
        projection_instance_key: str,
        report_date: str | None = None,
        expected_projection_revision: str | None = None,
    ) -> dict[str, Any]:
        """Return session-scoped activity duration summaries for Timeline."""
        try:
            if report_date is not None and (
                not isinstance(report_date, str) or not _DATE_SHAPE_RE.match(report_date)
            ):
                return {"ok": False, "error": "invalid_input", "message": "日期无效"}
            if not isinstance(projection_instance_key, str) or not projection_instance_key.strip():
                return {"ok": False, "error": "invalid_input", "message": "请选择有效的活动时段"}
            return view_model_api.get_session_activity_summary_view_model(
                report_date=report_date,
                projection_instance_key=projection_instance_key.strip(),
                expected_projection_revision=(expected_projection_revision or "").strip() or None,
            )
        except ValueError as exc:
            code = str(exc)
            if code == "stale_selection":
                return {"ok": False, "error": "stale_selection", "message": "活动时段已更新，正在刷新"}
            return {"ok": False, "error": "invalid_input", "message": "请选择有效的活动时段"}
        except Exception:
            logger.exception("webview bridge get_timeline_session_activity_summary failed")
            return {"ok": False, "error": "operation_failed", "message": "加载项目活动耗时失败"}

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

    def save_timeline_session_edit(
        self,
        report_date: str,
        projection_instance_key: str,
        projection_revision: str,
        request_id: str,
        project_id: int | None,
        adjusted_duration_seconds: int | None,
        note: str,
    ) -> dict[str, Any]:
        """Save Timeline session edits by projection identity and revision."""
        try:
            if not isinstance(report_date, str) or not _DATE_SHAPE_RE.match(report_date):
                return {"ok": False, "error": "invalid_input", "message": "日期无效"}
            if not isinstance(projection_instance_key, str) or not projection_instance_key.strip():
                return {"ok": False, "error": "invalid_input", "message": "请选择有效的活动时段"}
            if not isinstance(projection_revision, str) or not projection_revision.strip():
                return {"ok": False, "error": "invalid_input", "message": "请选择有效的活动时段"}
            if not isinstance(note, str):
                return {"ok": False, "error": "invalid_input", "message": "备注内容无效"}
            if len(note) > timeline_api.TIMELINE_NOTE_MAX_LENGTH:
                return {"ok": False, "error": "invalid_input", "message": "备注过长"}
            pid: int | None = None
            if project_id is not None:
                if isinstance(project_id, bool):
                    return {"ok": False, "error": "invalid_input", "message": "请选择有效的项目"}
                pid = int(project_id)
            duration_value: int | None = None
            if adjusted_duration_seconds is not None:
                if isinstance(adjusted_duration_seconds, bool):
                    return {"ok": False, "error": "invalid_input", "message": "时长无效"}
                duration_value = int(adjusted_duration_seconds)
            return timeline_api.save_timeline_session_edit(
                report_date,
                projection_instance_key.strip(),
                projection_revision.strip(),
                str(request_id or "").strip(),
                pid,
                duration_value,
                note,
            )
        except Exception as exc:
            code = api_errors.error_code_from_exception(exc)
            if code == api_errors.OPERATION_FAILED:
                logger.exception("webview bridge save_timeline_session_edit failed")
            return {"ok": False, "error": code, "message": api_errors.public_message_for_code(code)}

    def hide_timeline_session(self, report_date: str, projection_instance_key: str, projection_revision: str, request_id: str) -> dict[str, Any]:
        return self._run_session_operation(timeline_api.hide_timeline_session, report_date, projection_instance_key, projection_revision, request_id)

    def merge_timeline_session(
        self,
        report_date: str,
        projection_instance_key: str,
        direction: str,
        projection_revision: str,
        request_id: str,
        target_projection_instance_key: str,
        target_projection_revision: str,
    ) -> dict[str, Any]:
        if direction not in {"previous", "next"}:
            return {"ok": False, "error": "只能合并相邻时段。"}
        return self._run_session_operation(
            timeline_api.merge_timeline_session,
            report_date,
            projection_instance_key,
            direction,
            projection_revision,
            request_id,
            target_projection_instance_key,
            target_projection_revision,
        )

    def split_timeline_session(self, report_date: str, projection_instance_key: str, projection_revision: str, request_id: str) -> dict[str, Any]:
        return self._run_session_operation(timeline_api.split_timeline_session, report_date, projection_instance_key, projection_revision, request_id)

    def copy_timeline_session(self, report_date: str, projection_instance_key: str, projection_revision: str, request_id: str) -> dict[str, Any]:
        return self._run_session_operation(timeline_api.copy_timeline_session, report_date, projection_instance_key, projection_revision, request_id)

    def hide_timeline_session_activity(
        self,
        report_date: str,
        projection_instance_key: str,
        summary_id: str,
        projection_revision: str,
        request_id: str,
    ) -> dict[str, Any]:
        if not isinstance(summary_id, str) or not summary_id.strip():
            return {"ok": False, "error": "请选择有效的活动时段"}
        return self._run_session_operation(
            timeline_api.hide_timeline_session_activity,
            report_date,
            projection_instance_key,
            summary_id.strip(),
            projection_revision,
            request_id,
        )

    @staticmethod
    def _run_session_operation(action, report_date: str, projection_instance_key: str, *args) -> dict[str, Any]:
        if not isinstance(report_date, str) or not _DATE_SHAPE_RE.match(report_date):
            return {"ok": False, "error": "日期无效"}
        if not isinstance(projection_instance_key, str) or not projection_instance_key.strip():
            return {"ok": False, "error": "请选择有效的活动时段"}
        try:
            return action(report_date, projection_instance_key.strip(), *args)
        except Exception as exc:
            code = api_errors.error_code_from_exception(exc)
            if code == api_errors.OPERATION_FAILED:
                logger.exception("webview bridge session operation failed")
            return {"ok": False, "error": code, "message": api_errors.public_message_for_code(code)}
