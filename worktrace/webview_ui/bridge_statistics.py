"""Statistics / Export bridge mixin.

This bridge exposes display-safe summaries and a separate export ticket. It
imports only API facades and formatting helpers; DB and service ownership stay
behind the API boundary.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import export_api, statistics_api
from ..api.export_api import StatisticsExportError
from ..api.statistics_api import StatisticsSummaryError
from ..formatters import format_duration
from .bridge_common import _DATE_SHAPE_RE, _statistics_summary_payload

logger = logging.getLogger(__name__)

_STATISTICS_ERROR_MESSAGES = {
    "invalid_date": "请选择有效日期",
    "invalid_range": "请选择有效日期范围",
    "range_too_large": "日期范围过大",
    "operation_failed": "加载统计失败",
}

_STATISTICS_EXPORT_ERROR_MESSAGES = {
    "invalid_date": "请选择有效日期",
    "invalid_range": "请选择有效日期范围",
    "range_too_large": "日期范围过大",
    "empty_data": "当前范围没有可导出的记录",
    "invalid_path": "请选择有效保存位置",
    "permission_denied": "无法写入文件，请检查权限或文件是否被占用",
    "file_busy": "无法写入文件，请检查权限或文件是否被占用",
    "stale_statistics_snapshot": "统计数据已更新，请重新加载后导出",
    "write_failed": "无法写入文件，请检查权限或文件是否被占用",
    "operation_failed": "导出失败",
}


class StatisticsBridgeMixin:
    """Statistics / Export bridge methods."""

    def get_statistics_export_summary(self, date_from, date_to) -> dict[str, Any]:
        try:
            # bool, None, and every other non-string input are rejected explicitly.
            if not isinstance(date_from, str) or not isinstance(date_to, str):
                return {"ok": False, "error": "请选择有效日期", "summary": None}
            if not _DATE_SHAPE_RE.match(date_from) or not _DATE_SHAPE_RE.match(date_to):
                return {"ok": False, "error": "请选择有效日期", "summary": None}
            summary = statistics_api.get_statistics_export_summary(date_from, date_to)
            revision = str(summary.get("export_revision") or "")
            return {
                "ok": True,
                "summary": _statistics_summary_payload(summary),
                "export_ticket": {
                    "date_from": str(summary.get("date_from") or date_from),
                    "date_to": str(summary.get("date_to") or date_to),
                    "revision": revision,
                },
            }
        except StatisticsSummaryError as exc:
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
        expected_snapshot_revision=None,
    ) -> dict[str, Any]:
        try:
            if not isinstance(date_from, str) or not isinstance(date_to, str):
                return {"ok": False, "error": "请选择有效日期", "cancelled": False}
            if not _DATE_SHAPE_RE.match(date_from) or not _DATE_SHAPE_RE.match(date_to):
                return {"ok": False, "error": "请选择有效日期", "cancelled": False}
            if expected_snapshot_revision is not None and (
                not isinstance(expected_snapshot_revision, str)
                or not expected_snapshot_revision.strip()
            ):
                return {
                    "ok": False,
                    "error": "统计数据已更新，请重新加载后导出",
                    "cancelled": False,
                }
            output_path = self._choose_csv_save_path()
            if output_path is None:
                return {"ok": False, "cancelled": True, "error": "已取消导出"}
            result = export_api.export_statistics_csv(
                date_from,
                date_to,
                output_path,
                expected_snapshot_revision.strip()
                if isinstance(expected_snapshot_revision, str)
                else None,
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


__all__ = ["StatisticsBridgeMixin", "_STATISTICS_EXPORT_ERROR_MESSAGES"]
