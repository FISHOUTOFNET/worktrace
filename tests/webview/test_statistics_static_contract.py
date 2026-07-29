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
        "statistics-date-from", "statistics-date-to", "statistics-project-filter",
        "statistics-today-btn", "statistics-week-btn", "statistics-month-btn",
        "statistics-all-btn", "statistics-results", "statistics-update-status",
        "statistics-apply-range-btn", "statistics-date-status",
        "stats-total", "stats-activity-count", "stats-project-count", "stats-app-count",
        "stats-by-project", "stats-by-app", "stats-export-action-btn",
    ):
        assert f'id="{dom_id}"' in html
    for forbidden in (
        "statistics-range-mode", "statistics-custom-range", "statistics-load-btn",
        "statistics-7d-btn", "status-filter", "stats-by-status", "最近七天",
        "自定义范围", "导出范围与隐私说明",
    ):
        assert forbidden not in html
    assert [html.index(f'id="statistics-{name}-btn"') for name in ("today", "week", "month", "all")] == sorted(
        html.index(f'id="statistics-{name}-btn"') for name in ("today", "week", "month", "all")
    )
    assert html.count('aria-pressed="false"') >= 4


def test_statistics_uses_only_fixed_local_capabilities() -> None:
    js = source()
    assert set(re.findall(r"\bApp\.bridge\.([A-Za-z0-9_]+)\s*\(", js)) == {
        "getStatisticsExportSummary", "exportStatisticsCsv"
    }
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "window.pywebview"):
        assert forbidden not in js


def test_latest_query_owns_acceptance_and_keeps_one_export_ticket() -> None:
    body = func_body(source(), "beginStatisticsQuery")
    execute = func_body(source(), "executeStatisticsQuery")
    assert 'App.requestCoordinator.beginLatest("statistics"' in body
    assert "App.requestCoordinator.isCurrent(token)" in execute
    assert "App.statisticsAcceptedPayload =" in execute
    assert "exportTicket: data.export_ticket" in execute
    assert "filters.dateFrom, filters.dateTo, filters.projectId" in execute
    assert "showStatistics(data.summary, filters)" in execute


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


def test_draft_dates_apply_once_while_project_and_quick_ranges_query_immediately() -> None:
    init = func_body(source(), "initStatisticsDefaults")
    quick = func_body(source(), "applyStatisticsQuickRange")
    draft = func_body(source(), "handleStatisticsDraftDateChange")
    apply = func_body(source(), "applyStatisticsDraftSelection")
    week = func_body(source(), "statisticsWeekRange")
    assert 'statistics-range-mode' not in source()
    assert 'statistics-custom-range' not in source()
    assert 'statistics-project-filter' in init
    assert "handleStatisticsDraftDateChange" in init
    assert "scheduleStatisticsQuery" not in draft
    assert "beginStatisticsQuery" not in draft
    assert "setStatisticsSelection" not in draft
    assert "validateStatisticsDateRange" in apply
    assert apply.count("beginStatisticsQuery(0)") == 1
    assert "statisticsWeekRange(new Date())" in source()
    assert "start.getDay() + 6" in week
    assert 'type === "all"' in quick
    assert "beginStatisticsQuery(0)" in quick
    buttons = func_body(read_js("init.js"), "initButtons")
    for name in ("today", "week", "month", "all"):
        assert f'App.applyStatisticsQuickRange("{name}")' in buttons


def test_dynamic_table_values_are_escaped_without_export_preview_ui() -> None:
    assert "App.escapeHtml" in func_body(source(), "renderStatsTable")
    assert "renderExportPreview" not in source()
    assert "stats-export-range" not in section()


def test_statistics_styles_are_responsive_local_surfaces() -> None:
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for selector in (
        ".statistics-toolbar", ".statistics-date-range", ".quick-ranges",
        "#statistics-results", ".metric-strip", ".stats-result", ".table-scroll",
    ):
        assert selector in styles


def test_statistics_dates_reuse_timeline_native_date_control() -> None:
    html = section()
    index = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    date_inputs = re.findall(
        r'<input id="statistics-date-(?:from|to)" class="date-control" type="date"',
        html,
    )
    date_range = re.search(r"\.statistics-date-range\s*\{([^}]*)\}", styles)
    all_time = re.search(r"\.statistics-all-time-label\s*\{([^}]*)\}", styles)
    assert len(date_inputs) == 2
    assert '<span class="statistics-date-label">日期范围</span>' not in html
    assert 'aria-label="统计日期范围"' in html
    assert "statistics-date-field" not in html
    assert "statistics-date-display" not in html
    assert "statistics-date-icon" not in html
    assert "statistics-date-from-display" not in html
    assert "statistics-date-to-display" not in html
    assert html.count('<use href="#icon-calendar"/>') == 0
    assert 'id="timeline-date-input" class="date-control" type="date"' in index
    assert date_range is not None
    assert "width: fit-content" in date_range.group(1)
    assert "276px" not in date_range.group(1)
    assert all_time is not None and "--date-control-width" in all_time.group(1)
    assert "--statistics-date-width" not in styles
    assert ".statistics-date-field" not in styles
    assert ".statistics-date-display" not in styles
    assert ".statistics-date-icon" not in styles
    assert "278px" not in styles
    assert "@media (max-width: 767px)" in styles
    assert "@media (max-width: 719px)" not in styles


def test_metric_strip_is_open_and_not_a_surface_card() -> None:
    html = section()
    metric = re.search(r'<div class="([^"]*\bmetric-strip\b[^"]*)">', html)
    assert metric is not None
    assert metric.group(1).split() == ["metric-strip"]


def test_metric_strip_remains_one_row_at_narrow_widths() -> None:
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    metric = re.search(r"\.metric-strip\s*\{([^}]*)\}", styles)
    narrow = styles[styles.index("@media (max-width: 959px)") :]
    assert metric is not None
    assert "repeat(4, minmax(0, 1fr))" in metric.group(1)
    assert "white-space: nowrap" in metric.group(1)
    assert "repeat(2, minmax(0, 1fr))" not in narrow
    assert ".metric:nth-child(2)" not in narrow
    assert ".metric:nth-child(-n+2)" not in narrow


def test_statistics_table_adds_visual_comparison_without_changing_values() -> None:
    body = func_body(source(), "renderStatsTable")
    assert 'class="stats-share-bar"' in body
    assert "Math.max(0, Math.min(100" in body
    assert "group.duration" in body and "group.activity_count" in body and "group.percentage" in body
