"""Statistics and CSV export semantic UI contracts."""
from __future__ import annotations

import os
import re
import sys
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import WEBVIEW_UI_DIR, func_body, html_section_by_id, read_js  # noqa: E402


def source() -> str:
    return read_js("statistics.js")


def section() -> str:
    index = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    return html_section_by_id(index, "page-statistics")


def test_statistics_surface_matches_current_information_architecture() -> None:
    html = section()
    for dom_id in (
        "statistics-range-mode", "statistics-custom-range", "statistics-date-from",
        "statistics-date-to", "statistics-project-filter", "statistics-today-btn",
        "statistics-week-btn", "statistics-month-btn", "statistics-update-status",
        "stats-total", "stats-activity-count", "stats-project-count", "stats-app-count",
        "stats-by-project", "stats-by-app", "stats-export-action-btn",
    ):
        assert f'id="{dom_id}"' in html
    for forbidden in ("statistics-load-btn", "statistics-7d-btn", "status-filter", "stats-by-status", "最近七天"):
        assert forbidden not in html
    assert "全部时间" in html and "自定义范围" in html


def test_statistics_uses_only_fixed_local_capabilities() -> None:
    js = source()
    assert set(re.findall(r"\bApp\.bridge\.([A-Za-z0-9_]+)\s*\(", js)) == {
        "getStatisticsExportSummary", "exportStatisticsCsv"
    }
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "window.pywebview"):
        assert forbidden not in js


def test_latest_query_owns_acceptance_and_keeps_one_export_ticket() -> None:
    body = func_body(source(), "loadStatisticsExportSummary")
    assert 'App.requestCoordinator.beginLatest("statistics"' in body
    assert "App.requestCoordinator.isCurrent(token)" in body
    assert "App.statisticsAcceptedPayload =" in body
    assert "exportTicket: data.export_ticket" in body
    assert "filters.dateFrom, filters.dateTo, filters.projectId" in body
    assert "showStatistics(data.summary, filters)" in body


def test_export_is_bound_to_accepted_snapshot_and_disabled_while_querying() -> None:
    loading = func_body(source(), "setStatisticsLoading")
    export = func_body(source(), "exportStatisticsCsv")
    assert "App.statisticsLoading" in loading
    assert "App.statisticsExportSaving" in loading
    assert "!App.statisticsAcceptedPayload" in loading
    assert "var accepted = App.statisticsAcceptedPayload" in export
    assert "accepted.exportTicket" in export
    assert "ticket.date_from, ticket.date_to, ticket.revision, ticket.project_id" in export
    assert "已取消导出" in export and "导出失败" in export and "已导出" in export


def test_custom_dates_validate_without_reviving_legacy_31_day_ui_limit() -> None:
    body = func_body(source(), "validateStatisticsDateRange")
    assert "dateFrom > dateTo" in body
    assert "请选择完整日期范围" in body
    assert "diffDays" not in body and "31" not in body


def test_filters_auto_query_and_quick_ranges_are_today_week_month() -> None:
    init = func_body(source(), "initStatisticsDefaults")
    quick = func_body(source(), "applyStatisticsQuickRange")
    assert 'statistics-range-mode' in init and 'statistics-project-filter' in init
    assert "scheduleStatisticsQuery" in init
    assert 'type === "week"' in quick and 'type === "month"' in quick
    assert "loadStatisticsExportSummary()" in quick
    buttons = func_body(read_js("init.js"), "initButtons")
    assert 'App.applyStatisticsQuickRange("today")' in buttons
    assert 'App.applyStatisticsQuickRange("week")' in buttons
    assert 'App.applyStatisticsQuickRange("month")' in buttons


def test_dynamic_table_values_are_escaped_and_preview_uses_text_content() -> None:
    assert "App.escapeHtml" in func_body(source(), "renderStatsTable")
    preview = func_body(source(), "renderExportPreview")
    assert "textContent" in preview and "innerHTML" not in preview


def test_statistics_styles_are_responsive_local_surfaces() -> None:
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for selector in (".statistics-toolbar", ".metric-strip", ".stats-result", ".table-scroll"):
        assert selector in styles
