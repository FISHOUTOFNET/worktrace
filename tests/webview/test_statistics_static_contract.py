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
    index = (WEBVIEW_UI_DIR / "index_fd_work_v5.html").read_text(encoding="utf-8")
    return html_section_by_id(index, "page-statistics")


def test_statistics_surface_matches_current_information_architecture() -> None:
    html = section()
    for dom_id in (
        "statistics-date-from", "statistics-date-to", "statistics-project-filter",
        "statistics-today-btn", "statistics-week-btn", "statistics-month-btn",
        "statistics-all-btn", "statistics-results",
        "statistics-apply-range-btn", "statistics-date-status",
        "stats-total", "stats-activity-count", "stats-project-count", "stats-file-count", "stats-app-count",
        "stats-project-tab", "stats-file-tab", "stats-app-tab",
        "stats-project-panel", "stats-file-panel", "stats-app-panel",
        "stats-by-project", "stats-by-file", "stats-by-app",
        "stats-empty-project", "stats-empty-file", "stats-empty-app",
        "stats-export-action-btn",
    ):
        assert f'id="{dom_id}"' in html
    for forbidden in (
        "statistics-range-mode", "statistics-custom-range", "statistics-load-btn",
        "statistics-7d-btn", "status-filter", "stats-by-status", "最近七天",
        "自定义范围", "导出范围与隐私说明", "stats-scope-row",
        "statistics-update-status", "statistics-all-time-label",
    ):
        assert forbidden not in html
    assert [html.index(f'id="statistics-{name}-btn"') for name in ("today", "week", "month", "all")] == sorted(
        html.index(f'id="statistics-{name}-btn"') for name in ("today", "week", "month", "all")
    )
    assert [html.index(f'id="stats-{name}-tab"') for name in ("project", "file", "app")] == sorted(
        html.index(f'id="stats-{name}-tab"') for name in ("project", "file", "app")
    )
    assert "按项目" in html and "按文件" in html and "按应用" in html
    assert ">今日</button>" in html
    assert html.count('aria-pressed="false"') >= 4
    assert '<header class="page-header page-header-compact">' in html


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
    assert "showStatistics(data.summary)" in execute


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


def test_draft_dates_stay_local_while_project_and_quick_ranges_query_immediately() -> None:
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
    assert "draft.allTime" in apply
    assert 'setStatisticsSelection(true, "", "")' in apply
    assert "setStatisticsSelection(false, draft.dateFrom, draft.dateTo)" in apply
    assert "statisticsWeekRange(new Date())" in source()
    assert "start.getDay() + 6" in week
    assert 'type === "all"' in quick
    assert "beginStatisticsQuery(0)" in quick
    buttons = func_body(source(), "bindStatisticsEvents")
    for name in ("today", "week", "month", "all"):
        assert f'App.applyStatisticsQuickRange("{name}")' in buttons


def test_statistics_tabs_share_keyboard_activation_path() -> None:
    init = func_body(source(), "initStatisticsDefaults")
    activate = func_body(source(), "activateStatisticsTab")
    keyboard = func_body(source(), "handleStatisticsTabKeydown")
    assert "Object.keys(statisticsTabs)" in init
    assert "activateStatisticsTab(view)" in init
    assert "handleStatisticsTabKeydown(event, view)" in init
    assert "Object.keys(statisticsTabs)" in activate
    assert 'setAttribute("aria-selected"' in activate
    assert "tabIndex = selected ? 0 : -1" in activate
    assert "panel).hidden" in activate
    for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
        assert key in keyboard


def test_dynamic_table_values_are_escaped_without_export_preview_ui() -> None:
    body = func_body(source(), "renderStatsTable")
    assert "App.escapeHtml" in body
    assert "statisticsGroupRecordCount(group)" in body
    assert "renderExportPreview" not in source()
    assert "stats-export-range" not in section()


def test_statistics_styles_are_responsive_local_surfaces() -> None:
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for selector in (
        ".statistics-toolbar", ".statistics-date-range", ".quick-ranges",
        "#statistics-results", ".metric-strip", ".stats-result", ".table-scroll",
    ):
        assert selector in styles


def test_statistics_dates_keep_native_picker_with_controlled_empty_copy() -> None:
    html = section()
    index = (WEBVIEW_UI_DIR / "index_fd_work_v5.html").read_text(encoding="utf-8")
    final = (WEBVIEW_UI_DIR / "ui_components.css").read_text(encoding="utf-8")
    js = source()
    date_inputs = re.findall(
        r'<input id="statistics-date-(?:from|to)" class="date-control statistics-date-control" type="date" data-empty="true"',
        html,
    )
    assert len(date_inputs) == 2
    assert html.count('class="statistics-date-empty-label" aria-hidden="true">YYYY/MM/DD</span>') == 2
    assert 'aria-label="统计日期范围"' in html
    assert 'id="timeline-date-input" class="date-control" type="date"' in index
    assert "input.type" not in js
    assert "syncStatisticsDateInputMode" not in js
    assert 'setAttribute("data-empty"' in js
    assert ".statistics-date-control-shell" in final
    assert ".statistics-date-empty-label" in final
    assert "pointer-events: none" in final
    assert "::-webkit-datetime-edit" in final
    assert 'statistics-date-control[data-empty="true"]' in final


def test_metric_strip_is_open_and_not_a_surface_card() -> None:
    html = section()
    metric = re.search(r'<div class="([^"]*\bmetric-strip\b[^"]*)">', html)
    assert metric is not None
    assert metric.group(1).split() == ["metric-strip"]


def test_metric_strip_remains_one_row_with_file_kpi() -> None:
    final = (WEBVIEW_UI_DIR / "ui_components.css").read_text(encoding="utf-8")
    metric = re.search(r"\.metric-strip\s*\{([^}]*)\}", final)
    assert metric is not None
    assert "repeat(5, minmax(0, 1fr))" in metric.group(1)
    assert section().count('class="metric"') == 5


def test_statistics_time_segment_column_uses_report_record_count() -> None:
    js = source()
    body = func_body(js, "statisticsGroupRecordCount")
    table = func_body(js, "renderStatsTable")
    assert "group.record_count" in body
    assert "group.session_count" in body
    assert "group.activity_count" in body
    assert "statisticsGroupRecordCount(group)" in table


def test_file_kpi_reuses_existing_file_groups_without_new_backend_contract() -> None:
    js = source()
    count = func_body(js, "statisticsConcreteFileCount")
    metrics = func_body(js, "renderStatisticsMetrics")
    assert '!== "file:excluded"' in count
    assert "summary && summary.by_file" in metrics
    assert 'element("stats-file-count")' in metrics


def test_statistics_table_adds_visual_comparison_without_changing_duration_or_percentage() -> None:
    body = func_body(source(), "renderStatsTable")
    assert 'class="stats-share-bar"' in body
    assert "Math.max(0, Math.min(100" in body
    assert "group.duration" in body and "group.percentage" in body
