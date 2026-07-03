"""Statistics / Export bridge mixin.

Boundary rules (enforced by ``tests/test_ui_backend_boundary.py``):

- This module may import ``worktrace.api``, ``worktrace.constants``,
  ``worktrace.formatters``, and stdlib only. It must NOT import
  ``worktrace.services``, ``worktrace.db``, ``worktrace.collector``,
  ``worktrace.security``, ``worktrace.runtime``, or ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  style payloads without tracebacks.
- Methods do not log window titles, file paths, notes, or copied text.

``WebViewBridge`` in ``bridge.py`` inherits ``StatisticsBridgeMixin`` so the
Statistics / Export page method names (``get_statistics_export_summary`` /
``export_statistics_csv``) stay on ``WebViewBridge``. The mixin relies on the
host class also mixing in ``BridgeDialogMixin`` (for
``self._choose_csv_save_path``).
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


# Maps StatisticsSummaryError.code to Chinese messages. Unknown codes collapse to "加载统计失败"
# so internal details are never surfaced and a load failure never echoes a write-focused message.
_STATISTICS_ERROR_MESSAGES = {
    "invalid_date": "请选择有效日期",
    "invalid_range": "请选择有效日期范围",
    "range_too_large": "日期范围过大",
    "operation_failed": "加载统计失败",
}

# Maps StatisticsExportError.code to Chinese messages for the CSV export. Unknown codes collapse
# to "导出失败". permission_denied / file_busy / write_failed share one message so a low-level
# OS failure never distinguishes which kind of write error occurred.
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


class StatisticsBridgeMixin:
    """Statistics / Export bridge methods.

    Mixed into ``WebViewBridge`` in ``bridge.py`` so the Statistics / Export
    method names stay on ``WebViewBridge``. The mixin must NOT add
    ``__init__``; it relies on the host class.
    """


    def get_statistics_export_summary(self, date_from, date_to) -> dict[str, Any]:
        """Return a read-only statistics + export-preview summary.

        Read-only path: this method only reads closed activities through
        ``worktrace.api`` and never writes to the DB, never writes a file,
        and never opens a save dialog. ``date_from`` and ``date_to`` must
        be ``YYYY-MM-DD`` strings with ``date_from <= date_to`` and an
        inclusive span of at most 31 calendar days.

        Returns ``{"ok": true, "summary": {...}}`` on success or
        ``{"ok": false, "error": "<chinese message>", "summary": null}`` on
        failure. Known failure modes map to clear Chinese messages; unknown
        failures collapse to ``"加载统计失败"``. Tracebacks, SQL errors, raw
        ``window_title`` / ``file_path_hint`` / ``full_path`` / clipboard /
        note, and internal exception details are never surfaced.
        """
        try:
            # isinstance(..., str) rejects None/bool/int/etc. so True/False never reach the API/service validation.
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


    def export_statistics_csv(self, date_from, date_to) -> dict[str, Any]:
        """Export a display-safe CSV for the statistics date range."""
        try:
            # isinstance(..., str) rejects None/bool/int/etc. so True/False never reach the API.
            if not isinstance(date_from, str) or not isinstance(date_to, str):
                return {"ok": False, "error": "请选择有效日期", "cancelled": False}
            if not _DATE_SHAPE_RE.match(date_from) or not _DATE_SHAPE_RE.match(date_to):
                return {"ok": False, "error": "请选择有效日期", "cancelled": False}
            output_path = self._choose_csv_save_path()
            if output_path is None:
                # User cancelled the native save dialog (clean cancel, not an exception).
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


__all__ = ["StatisticsBridgeMixin", "_STATISTICS_EXPORT_ERROR_MESSAGES"]
