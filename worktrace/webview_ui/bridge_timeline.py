"""Timeline bridge mixin.

The bridge owns transport validation and public error mapping only. Timeline
queries, mutation validation and DTO construction stay behind API capabilities.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import errors as api_errors
from .bridge_common import _DATE_SHAPE_RE

logger = logging.getLogger(__name__)


class TimelineBridgeMixin:
    """Timeline page bridge methods."""

    def get_timeline(self, date: str | None = None) -> dict[str, Any]:
        try:
            return self._services.timeline.get_timeline_view_model(
                date,
                runtime=self._runtime(),
                collector_status=self._collector_status(),
            )
        except Exception:
            logger.exception("webview bridge get_timeline failed")
            return {"ok": False, "error": "operation_failed", "message": "操作失败"}

    def get_timeline_session_activity_summary(
        self,
        projection_instance_key: str,
        report_date: str | None = None,
        expected_projection_revision: str | None = None,
    ) -> dict[str, Any]:
        try:
            if report_date is not None and (
                not isinstance(report_date, str)
                or not _DATE_SHAPE_RE.match(report_date)
            ):
                return {"ok": False, "error": "invalid_input", "message": "日期无效"}
            if (
                not isinstance(projection_instance_key, str)
                or not projection_instance_key.strip()
            ):
                return {
                    "ok": False,
                    "error": "invalid_input",
                    "message": "请选择有效的活动时段",
                }
            return self._services.timeline.get_session_activity_summary_view_model(
                report_date=report_date,
                projection_instance_key=projection_instance_key.strip(),
                expected_projection_revision=(
                    (expected_projection_revision or "").strip() or None
                ),
                runtime=self._runtime(),
                collector_status=self._collector_status(),
            )
        except Exception as exc:
            return self._public_operation_error(
                exc,
                "webview bridge get_timeline_session_activity_summary failed",
            )

    def list_projects_for_timeline(self) -> dict[str, Any]:
        try:
            projects = self._services.timeline.list_selectable_projects()
            return {
                "ok": True,
                "projects": [
                    {
                        "id": int(project.get("id") or 0),
                        "name": str(project.get("name") or ""),
                        "description": str(project.get("description") or ""),
                    }
                    for project in projects
                ],
            }
        except Exception:
            logger.exception("webview bridge list_projects_for_timeline failed")
            return {"ok": False, "error": "operation_failed", "message": "操作失败"}

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
        try:
            if not isinstance(report_date, str) or not _DATE_SHAPE_RE.match(report_date):
                return {"ok": False, "error": "invalid_input", "message": "日期无效"}
            if (
                not isinstance(projection_instance_key, str)
                or not projection_instance_key.strip()
                or not isinstance(projection_revision, str)
                or not projection_revision.strip()
            ):
                return {
                    "ok": False,
                    "error": "invalid_input",
                    "message": "请选择有效的活动时段",
                }
            if not isinstance(note, str):
                return {"ok": False, "error": "invalid_input", "message": "备注内容无效"}
            if len(note) > self._services.timeline.TIMELINE_NOTE_MAX_LENGTH:
                return {"ok": False, "error": "invalid_input", "message": "备注过长"}

            pid: int | None = None
            if project_id is not None:
                if isinstance(project_id, bool):
                    return {
                        "ok": False,
                        "error": "invalid_input",
                        "message": "请选择有效的项目",
                    }
                pid = int(project_id)

            duration_value: int | None = None
            if adjusted_duration_seconds is not None:
                if isinstance(adjusted_duration_seconds, bool):
                    return {"ok": False, "error": "invalid_input", "message": "时长无效"}
                duration_value = int(adjusted_duration_seconds)

            return self._services.timeline.save_timeline_session_edit(
                report_date,
                projection_instance_key.strip(),
                projection_revision.strip(),
                str(request_id or "").strip(),
                pid,
                duration_value,
                note,
            )
        except Exception as exc:
            return self._public_operation_error(
                exc,
                "webview bridge save_timeline_session_edit failed",
            )

    def hide_timeline_session(
        self,
        report_date: str,
        projection_instance_key: str,
        projection_revision: str,
        request_id: str,
    ) -> dict[str, Any]:
        return self._run_session_operation(
            self._services.timeline.hide_timeline_session,
            report_date,
            projection_instance_key,
            projection_revision,
            request_id,
        )

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
            return {
                "ok": False,
                "error": "invalid_input",
                "message": "只能合并相邻时段。",
            }
        return self._run_session_operation(
            self._services.timeline.merge_timeline_session,
            report_date,
            projection_instance_key,
            direction,
            projection_revision,
            request_id,
            target_projection_instance_key,
            target_projection_revision,
        )

    def split_timeline_session(
        self,
        report_date: str,
        projection_instance_key: str,
        projection_revision: str,
        request_id: str,
    ) -> dict[str, Any]:
        return self._run_session_operation(
            self._services.timeline.split_timeline_session,
            report_date,
            projection_instance_key,
            projection_revision,
            request_id,
        )

    def copy_timeline_session(
        self,
        report_date: str,
        projection_instance_key: str,
        projection_revision: str,
        request_id: str,
    ) -> dict[str, Any]:
        return self._run_session_operation(
            self._services.timeline.copy_timeline_session,
            report_date,
            projection_instance_key,
            projection_revision,
            request_id,
        )

    def hide_timeline_session_activity(
        self,
        report_date: str,
        projection_instance_key: str,
        summary_id: str,
        projection_revision: str,
        request_id: str,
    ) -> dict[str, Any]:
        if not isinstance(summary_id, str) or not summary_id.strip():
            return {
                "ok": False,
                "error": "invalid_input",
                "message": "请选择有效的活动时段",
            }
        return self._run_session_operation(
            self._services.timeline.hide_timeline_session_activity,
            report_date,
            projection_instance_key,
            summary_id.strip(),
            projection_revision,
            request_id,
        )

    @staticmethod
    def _run_session_operation(
        action,
        report_date: str,
        projection_instance_key: str,
        *args,
    ) -> dict[str, Any]:
        if not isinstance(report_date, str) or not _DATE_SHAPE_RE.match(report_date):
            return {"ok": False, "error": "invalid_input", "message": "日期无效"}
        if (
            not isinstance(projection_instance_key, str)
            or not projection_instance_key.strip()
        ):
            return {
                "ok": False,
                "error": "invalid_input",
                "message": "请选择有效的活动时段",
            }
        try:
            return action(report_date, projection_instance_key.strip(), *args)
        except Exception as exc:
            return TimelineBridgeMixin._public_operation_error(
                exc,
                "webview bridge session operation failed",
            )

    @staticmethod
    def _public_operation_error(exc: Exception, log_message: str) -> dict[str, Any]:
        code = api_errors.error_code_from_exception(exc)
        if code == api_errors.OPERATION_FAILED:
            logger.exception(log_message)
        return {
            "ok": False,
            "error": code,
            "message": api_errors.public_message_for_code(code),
        }


__all__ = ["TimelineBridgeMixin"]
