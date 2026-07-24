"""Statistics / Export bridge mixin.

The bridge validates transport shapes, calls API capabilities and maps stable
error codes. Statistics aggregation and display DTO shaping remain behind the
API boundary. Unexpected failures are logged internally; no full traceback is
returned to the WebView caller.
"""
from __future__ import annotations

import logging
from typing import Any

from .bridge_common import _DATE_SHAPE_RE

logger = logging.getLogger(__name__)

_STATISTICS_ERROR_MESSAGES = {
    "invalid_date": "请选择有效日期",
    "invalid_range": "请选择有效日期范围",
    "range_too_large": "日期范围过大",
    "invalid_project": "请选择有效项目",
    "operation_failed": "加载统计失败",
}

_STATISTICS_EXPORT_ERROR_MESSAGES = {
    "invalid_date": "请选择有效日期",
    "invalid_range": "请选择有效日期范围",
    "range_too_large": "日期范围过大",
    "invalid_project": "请选择有效项目",
    "empty_data": "当前范围没有可导出的记录",
    "invalid_path": "请选择有效保存位置",
    "permission_denied": "导出失败，请检查保存位置和权限",
    "file_busy": "文件可能被占用，请关闭后重试",
    "storage_unavailable": "存储空间或设备不可用",
    "cleanup_failed": "导出未完成，临时文件清理失败",
    "stale_statistics_snapshot": "统计数据已更新，请重新加载后导出",
    "write_failed": "导出失败，请检查保存位置和权限",
    "operation_failed": "导出失败",
}


class StatisticsBridgeMixin:
    """Statistics / Export bridge methods."""

    def get_statistics_export_summary(self, date_from, date_to, project_id=None) -> dict[str, Any]:
        """Reject non-string transport values, including bool, before the API."""
        try:
            if not isinstance(date_from, str) or not isinstance(date_to, str):
                return {"ok": False, "error": "请选择有效日期", "summary": None}
            all_time = date_from == "" and date_to == ""
            if not all_time and (
                not _DATE_SHAPE_RE.match(date_from) or not _DATE_SHAPE_RE.match(date_to)
            ):
                return {"ok": False, "error": "请选择有效日期", "summary": None}
            if project_id is not None and not isinstance(project_id, (str, int)):
                return {"ok": False, "error": "请选择有效项目", "summary": None}
            if project_id in (None, ""):
                envelope = self._services.statistics.get_statistics_export_view_model(date_from, date_to)
            else:
                envelope = self._services.statistics.get_statistics_export_view_model(
                    date_from, date_to, project_id
                )
            return {
                "ok": True,
                "summary": envelope["summary"],
                "export_ticket": envelope["export_ticket"],
            }
        except self._services.statistics.StatisticsSummaryError as exc:
            return {
                "ok": False,
                "error": _STATISTICS_ERROR_MESSAGES.get(exc.code, "加载统计失败"),
                "summary": None,
            }
        except Exception:
            logger.exception("webview bridge get_statistics_export_summary failed")
            return {"ok": False, "error": "加载统计失败", "summary": None}

    def export_statistics_csv(
        self,
        date_from,
        date_to,
        expected_export_ticket_revision,
        project_id=None,
    ) -> dict[str, Any]:
        try:
            if not isinstance(date_from, str) or not isinstance(date_to, str):
                return {"ok": False, "error": "请选择有效日期", "cancelled": False}
            all_time = date_from == "" and date_to == ""
            if not all_time and (
                not _DATE_SHAPE_RE.match(date_from) or not _DATE_SHAPE_RE.match(date_to)
            ):
                return {"ok": False, "error": "请选择有效日期", "cancelled": False}
            if project_id is not None and not isinstance(project_id, (str, int)):
                return {"ok": False, "error": "请选择有效项目", "cancelled": False}
            # The export ticket is a mandatory backend contract. Validate it
            # before opening the save dialog so a stale or missing ticket never
            # creates a target file or temp residue.
            if not isinstance(expected_export_ticket_revision, str) or not expected_export_ticket_revision.strip():
                return {
                    "ok": False,
                    "error": "统计数据已更新，请重新加载后导出",
                    "cancelled": False,
                }
            output_path = self._choose_csv_save_path()
            if output_path is None:
                return {"ok": False, "cancelled": True, "error": "已取消导出"}
            revision = expected_export_ticket_revision.strip()
            if project_id in (None, ""):
                result = self._services.statistics.export_statistics_csv(
                    date_from, date_to, output_path, revision
                )
            else:
                result = self._services.statistics.export_statistics_csv(
                    date_from, date_to, output_path, revision, project_id
                )
            return {
                "ok": True,
                "filename": str(result.get("filename") or ""),
                "activity_count": int(result.get("activity_count") or 0),
                "duration": self._services.statistics.format_export_duration(
                    int(result.get("duration_seconds") or 0)
                ),
                "cancelled": False,
            }
        except self._services.statistics.StatisticsExportError as exc:
            return {
                "ok": False,
                "error": _STATISTICS_EXPORT_ERROR_MESSAGES.get(exc.code, "导出失败"),
                "cancelled": False,
            }
        except Exception:
            logger.exception("webview bridge export_statistics_csv failed")
            return {"ok": False, "error": "导出失败", "cancelled": False}


__all__ = ["StatisticsBridgeMixin", "_STATISTICS_EXPORT_ERROR_MESSAGES"]
