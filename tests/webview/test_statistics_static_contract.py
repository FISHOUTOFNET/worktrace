"""Statistics and CSV export WebView owner contracts."""

from __future__ import annotations

import os
import re
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import (  # noqa: E402
    WEBVIEW_UI_DIR,
    func_body,
    html_element_by_id,
    html_section_by_id,
    read_js,
)


def _statistics_source() -> str:
    return read_js("statistics.js")


def test_statistics_page_has_complete_csv_surface() -> None:
    index = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    section = html_section_by_id(index, "page-statistics")
    assert 'data-page="statistics"' in index
    assert "统计与导出" in index
    assert "查看统计并导出当前范围内的活动记录为 CSV 文件" in section
    assert "WebView 迁移中" not in section

    required_ids = (
        "statistics-date-from",
        "statistics-date-to",
        "statistics-load-btn",
        "statistics-today-btn",
        "statistics-7d-btn",
        "statistics-month-btn",
        "statistics-loading",
        "statistics-error",
        "stats-total",
        "stats-activity-count",
        "stats-project-count",
        "stats-app-count",
        "stats-by-project",
        "stats-by-app",
        "stats-by-status",
        "stats-empty-project",
        "stats-empty-app",
        "stats-empty-status",
        "statistics-export-preview",
        "stats-export-range",
        "stats-export-count",
        "stats-export-duration",
        "stats-export-formats",
        "stats-export-action-btn",
        "stats-export-status",
    )
    for dom_id in required_ids:
        assert 'id="' + dom_id + '"' in section

    export_button = html_element_by_id(index, "stats-export-action-btn")
    assert "导出 CSV" in export_button
    assert "disabled" not in export_button.split(">", 1)[0]


def test_statistics_page_exposes_only_csv_and_privacy_safe_scope() -> None:
    index = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    section = html_section_by_id(index, "page-statistics")
    assert "导出当前范围内已结束、非隐藏的活动记录为 CSV" in section
    assert "导出范围最多 31 天" in section
    assert "不包含窗口标题、文件路径等敏感信息" in section
    lowered = section.lower()
    for forbidden in (
        "export-excel-btn",
        "export-pdf-btn",
        "export-timesheet-btn",
        "save-file-btn",
        "open-folder-btn",
        "auto-submit-btn",
        "导出excel",
        "导出pdf",
    ):
        assert forbidden not in lowered


def test_statistics_uses_fixed_bridge_capabilities_only() -> None:
    source = _statistics_source()
    calls = set(re.findall(r"\bApp\.bridge\.([A-Za-z0-9_]+)\s*\(", source))
    assert calls == {"getStatisticsExportSummary", "exportStatisticsCsv"}
    assert "App.callBridge" not in source
    assert "window.pywebview" not in source
    assert "invokeBridge(" not in source
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "navigator.clipboard",
    ):
        assert forbidden not in source


def test_statistics_load_accepts_one_export_snapshot() -> None:
    source = _statistics_source()
    load = func_body(source, "loadStatisticsExportSummary")
    assert "App.statisticsLoading" in load
    assert "App.requestCoordinator.beginLatest" in load
    assert "App.bridge.getStatisticsExportSummary" in load
    assert "App.statisticsAcceptedPayload =" in load
    assert "dateFrom" in load
    assert "dateTo" in load
    assert "exportRevision" in load
    assert "App.statisticsSnapshotRevision" in load
    assert "App.statisticsLoaded = true" in load

    invalidate = func_body(source, "invalidateStatisticsSelection")
    assert "App.statisticsAcceptedPayload = null" in invalidate
    assert 'App.statisticsSnapshotRevision = ""' in invalidate
    assert "App.statisticsLoaded = false" in invalidate


def test_statistics_export_uses_accepted_payload_and_independent_guards() -> None:
    source = _statistics_source()
    export = func_body(source, "exportStatisticsCsv")
    guard = export[: export.index("var accepted")]
    assert "App.statisticsExportSaving" in guard
    assert "App.statisticsLoading" in guard
    assert "var accepted = App.statisticsAcceptedPayload" in export
    assert "accepted.dateFrom" in export
    assert "accepted.dateTo" in export
    assert "accepted.exportRevision" in export
    assert "App.bridge.exportStatisticsCsv" in export
    assert export.index("validateStatisticsDateRange") < export.index(
        "App.bridge.exportStatisticsCsv"
    )

    core = read_js("core.js")
    assert "App.statisticsLoading" in core
    assert "App.statisticsExportSaving" in core
    assert "App.statisticsAcceptedPayload = null" in read_js("init.js")


def test_statistics_loading_and_saving_cross_disable_controls() -> None:
    source = _statistics_source()
    loading = func_body(source, "setStatisticsLoading")
    saving = func_body(source, "setStatisticsExportSaving")
    for body in (loading, saving):
        assert "statistics-load-btn" in body
        assert "stats-export-action-btn" in body
        assert "App.statisticsLoading" in body
        assert "App.statisticsExportSaving" in body
    assert "!App.statisticsAcceptedPayload" in loading
    assert "!App.statisticsAcceptedPayload" in saving


def test_statistics_date_range_is_validated_before_reads_and_writes() -> None:
    source = _statistics_source()
    validate = func_body(source, "validateStatisticsDateRange")
    assert "if (!dateFrom || !dateTo)" in validate
    assert "if (from > to)" in validate
    assert "diffDays > 30" in validate
    assert "请选择有效日期" in validate
    assert "日期范围过大" in validate

    load = func_body(source, "loadStatisticsExportSummary")
    export = func_body(source, "exportStatisticsCsv")
    assert "validateStatisticsDateRange" in load
    assert "validateStatisticsDateRange" in export


def test_statistics_rendering_escapes_dynamic_table_values() -> None:
    source = _statistics_source()
    table = func_body(source, "renderStatsTable")
    assert "App.safeText" in table
    assert "App.escapeHtml" in table
    assert "innerHTML" in table
    assert "g.display_name" in table
    assert "g.duration" in table

    preview = func_body(source, "renderExportPreview")
    assert "textContent" in preview
    assert "innerHTML" not in preview

    status = func_body(source, "setStatisticsExportStatus")
    assert "textContent" in status
    assert "className" in status


def test_statistics_export_result_has_clear_user_states() -> None:
    export = func_body(_statistics_source(), "exportStatisticsCsv")
    for message in (
        "请先加载统计数据",
        "正在导出",
        "导出失败",
        "已取消导出",
        "导出成功",
    ):
        assert message in export
    assert ".catch(function" in export
    assert ".finally(function" in export
    assert "setStatisticsExportSaving(false)" in export
    assert "error.message" not in export
    assert "err.message" not in export


def test_statistics_quick_ranges_invalidate_then_reload() -> None:
    body = func_body(_statistics_source(), "applyStatisticsQuickRange")
    assert 'type === "today"' in body
    assert 'type === "7d"' in body
    assert 'type === "month"' in body
    assert "invalidateStatisticsSelection()" in body
    assert "loadStatisticsExportSummary()" in body


def test_statistics_navigation_and_buttons_use_named_capabilities() -> None:
    init = read_js("init.js")
    switch = func_body(init, "switchPage")
    assert 'pageId === "statistics"' in switch
    assert "App.initStatisticsDefaults()" in switch
    assert "App.loadStatisticsExportSummary()" in switch

    buttons = func_body(init, "initButtons")
    bindings = (
        ("statistics-load-btn", "App.loadStatisticsExportSummary"),
        ("statistics-today-btn", 'App.applyStatisticsQuickRange("today")'),
        ("statistics-7d-btn", 'App.applyStatisticsQuickRange("7d")'),
        ("statistics-month-btn", 'App.applyStatisticsQuickRange("month")'),
        ("stats-export-action-btn", "App.exportStatisticsCsv"),
    )
    for dom_id, capability in bindings:
        assert dom_id in buttons
        assert capability in buttons


def test_statistics_styles_match_the_rendered_surface() -> None:
    index = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    section = html_section_by_id(index, "page-statistics")
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")

    for class_name in (
        "stats-header",
        "stats-loading",
        "stats-summary-grid",
        "stats-table",
        "stats-export-status",
    ):
        assert 'class="' + class_name in section or (" " + class_name) in section
        assert "." + class_name in styles

    assert 'id="statistics-error" class="error-banner"' in section
    assert ".error-banner" in styles
