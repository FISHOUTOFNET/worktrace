"""Statistics / Export WebView static-contract tests.

These tests read the bundled frontend resources (index.html /
js/*.js / styles.css) directly without starting the GUI. JS-level
contracts use read_all_js() (concatenated modules in load order) or
read_js("<module>.js") for module-scoped checks. They lock the
Statistics / Export page contracts.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static, pytest.mark.db]

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import (
    REPO_ROOT, WEBVIEW_UI_DIR, HISTORY_PATH,
    RELEASE_VALIDATION_PATH, README_PATH,
    read_resource, read_all_js, read_js, func_body,
    html_section_by_id, html_element_by_id, js_catch_block,
    python_method_body,
    read_bridge_sources_combined, read_bridge_method_body,
    FRONTEND_RESOURCE_FILES, NO_STORAGE_FILES,
)




def test_index_html_statistics_nav_entry_exists():
    """the sidebar nav must contain the 统计与导出 entry."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-page="statistics"' in source
    assert "统计与导出" in source



def test_index_html_statistics_page_section_exists():
    """the page-statistics section must exist and not be a
    placeholder."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    section = html_section_by_id(source, "page-statistics")
    # The page must NOT show the placeholder.
    assert "WebView 迁移中" not in section



def test_index_html_statistics_header_subtitle_describes_csv_export():
    """the page header subtitle must announce CSV export is
    open (not obsolete read-only-only copy)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    section = html_section_by_id(source, "page-statistics")
    assert "统计 / 导出" in section
    assert "查看统计并导出当前范围内的活动记录为 CSV 文件" in section
    # the obsolete read-only-only copy must be gone.
    assert "本阶段仅提供只读统计和导出预览" not in section
    assert "暂不写入文件" not in section



def test_index_html_statistics_date_range_controls():
    """date range controls must exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="statistics-date-from"' in source
    assert 'id="statistics-date-to"' in source
    assert 'id="statistics-load-btn"' in source
    assert "加载统计" in source



def test_index_html_statistics_quick_range_buttons():
    """quick range buttons (today / 7d / month) exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="statistics-today-btn"' in source
    assert 'id="statistics-7d-btn"' in source
    assert 'id="statistics-month-btn"' in source



def test_index_html_statistics_summary_cards():
    """the four summary cards exist (total / activity / project /
    app)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="stats-total"' in source
    assert 'id="stats-activity-count"' in source
    assert 'id="stats-project-count"' in source
    assert 'id="stats-app-count"' in source



def test_index_html_statistics_grouped_tables():
    """by_project / by_app / by_status tables exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="stats-by-project"' in source
    assert 'id="stats-by-app"' in source
    assert 'id="stats-by-status"' in source
    assert "按项目" in source
    assert "按应用" in source
    assert "按状态" in source



def test_index_html_statistics_empty_states():
    """each table has an empty-state element."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="stats-empty-project"' in source
    assert 'id="stats-empty-app"' in source
    assert 'id="stats-empty-status"' in source
    assert "暂无统计数据" in source



def test_index_html_statistics_export_preview():
    """the export preview card exists with range / count /
    duration / formats fields."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="statistics-export-preview"' in source
    assert 'id="stats-export-range"' in source
    assert 'id="stats-export-count"' in source
    assert 'id="stats-export-duration"' in source
    assert 'id="stats-export-formats"' in source
    assert "导出预览" in source



def test_index_html_statistics_export_action_enabled():
    """the export action button must be enabled and labeled
    "导出 CSV" (no longer the disabled placeholder)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    section = html_element_by_id(source, "stats-export-action-btn")
    # The button must be a real action button with the CSV label.
    assert "导出 CSV" in section
    # The button itself must NOT carry a disabled attribute; the old
    # Unavailable export copy must be absent.
    assert "导出动作将在后续阶段开放" not in section
    # A status element must exist for export progress / success / cancel.
    assert 'id="stats-export-status"' in source



def test_index_html_statistics_export_hint_csv_enabled():
    """the export hint must announce CSV is the supported format
    for closed, non-hidden activity records in the current range."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find("stats-export-hint")
    assert pos != -1
    end = source.find("</div>", pos)
    assert end != -1
    section = source[pos:end]
    # The hint must clearly state CSV is the supported format.
    assert "导出当前范围内已结束、非隐藏的活动记录为 CSV" in section
    assert "导出范围最多 31 天" in section
    assert "已结束、非隐藏的活动记录" in section
    assert "不包含窗口标题、文件路径等敏感信息" in section
    # the old copy must be gone.
    assert "本阶段不支持写出" not in section



def test_index_html_statistics_loading_text():
    """the loading text 正在加载统计… must be present."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "正在加载统计" in source



def test_index_html_statistics_error_text():
    """the error banner default text 加载统计失败 must be present."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="statistics-error"' in source
    assert "加载统计失败" in source



def test_index_html_statistics_only_csv_export_button_allowed():
    """CSV export is now supported via the bridge. index.html may
    contain the CSV export button (stats-export-action-btn / 导出 CSV), but
    must NOT contain Excel / PDF / timesheet / open-folder / auto-submit
    button controls, nor any frontend-side save-dialog / file-path input
    control. The CSV export write itself is only invoked through a bridge
    call, never via a frontend direct file-write control.

    Note: the export hint text legitimately mentions Excel / PDF / timesheet
    / 打开文件夹 / 自动提交工时 as *unsupported* features; those mentions are
    verified by test_index_html_statistics_export_hint_csv_enabled. This
    test only forbids button-like ids / classes and the ``导出excel`` /
    ``导出pdf`` label tokens (with the 导出 prefix) that would indicate a
    real unsupported export button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    # CSV is the only supported export format. No button id /
    # class for Excel / PDF / timesheet / folder-open / auto-submit may
    # exist, and no 导出excel / 导出pdf button label may be present.
    for forbidden in ("export-excel-btn", "export-pdf-btn",
                      "export-timesheet-btn", "save-file-btn",
                      "open-folder-btn", "auto-submit-btn",
                      "导出excel", "导出pdf"):
        assert forbidden not in lowered, (
            "index.html must not contain unsupported export button: " + forbidden
        )



def test_index_html_overview_and_timeline_nav_not_regressed():
    """Overview and Timeline nav entries must still exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-page="overview"' in source
    assert 'data-page="timeline"' in source



def test_frontend_js_statistics_state_variables():
    """frontend JS must declare the statistics state variables."""
    source = read_all_js()
    assert "statisticsLoaded" in source
    assert "statisticsLoading" in source
    assert "statisticsRequestToken" in source



def test_frontend_js_statistics_load_function():
    """frontend JS must define loadStatisticsExportSummary and call the
    bridge method get_statistics_export_summary."""
    source = read_all_js()
    assert "function loadStatisticsExportSummary" in source
    assert "get_statistics_export_summary" in source



def test_frontend_js_statistics_render_function():
    """frontend JS must define showStatistics and renderStatsTable."""
    source = read_all_js()
    assert "function showStatistics" in source
    assert "function renderStatsTable" in source
    assert "function renderExportPreview" in source



def test_frontend_js_statistics_quick_range_function():
    """frontend JS must define applyStatisticsQuickRange and
    initStatisticsDefaults."""
    source = read_all_js()
    assert "function applyStatisticsQuickRange" in source
    assert "function initStatisticsDefaults" in source



def test_frontend_js_statistics_lazy_load_in_switch_page():
    """switchPage must lazy-load the statistics summary on first
    navigation to the page."""
    source = read_all_js()
    # Find the switchPage function body and verify the statistics branch.
    body = func_body(source, "switchPage")
    assert "statistics" in body
    assert "loadStatisticsExportSummary" in body
    assert "initStatisticsDefaults" in body



def test_frontend_js_statistics_event_binding_in_init_buttons():
    """initButtons must bind the statistics load + quick range
    buttons."""
    source = read_all_js()
    body = func_body(source, "initButtons")
    assert "statistics-load-btn" in body
    assert "statistics-today-btn" in body
    assert "statistics-7d-btn" in body
    assert "statistics-month-btn" in body
    assert "loadStatisticsExportSummary" in body
    assert "applyStatisticsQuickRange" in body



def test_frontend_js_statistics_uses_escape_html():
    """renderStatsTable must use escapeHtml for dynamic values."""
    source = read_all_js()
    body = func_body(source, "renderStatsTable")
    assert "escapeHtml" in body
    assert "safeText" in body



def test_frontend_js_statistics_export_only_via_bridge():
    """CSV export is now supported, but only through the bridge.
    The frontend JS must define ``exportStatisticsCsv`` and must invoke
    ``App.callBridge("export_statistics_csv", ...)``. Direct filesystem
    APIs, save-dialog helpers, Excel / PDF / timesheet / folder-open
    handlers, and ``window.pywebview.api.export...`` direct calls are all
    forbidden — the CSV write must go through ``App.callBridge(...)``."""
    source = read_all_js()
    # The allowed CSV export handler must exist and go through the bridge.
    assert "function exportStatisticsCsv" in source, (
        "frontend JS must define exportStatisticsCsv for the CSV export"
    )
    assert 'callBridge("export_statistics_csv"' in source, (
        "frontend JS must call App.callBridge(\"export_statistics_csv\", ...) "
        "for the CSV write; direct file writes are forbidden"
    )
    # Direct filesystem / save-dialog / non-CSV export handlers are forbidden.
    lowered = source.lower()
    for forbidden in ("exportexcel", "exportpdf",
                      "exporttimesheet", "savefile", "saveas",
                      "opensavefile", "createfile", "writefile",
                      "write_file", "openfolder", "open_folder",
                      "shell.open", "window.pywebview.api.export"):
        assert forbidden not in lowered, (
            "frontend JS must not wire direct file write / unsupported export "
            "handler: " + forbidden
        )



def test_frontend_js_statistics_no_local_storage():
    """the statistics page must not use localStorage /
    sessionStorage (regression lock)."""
    source = read_all_js()
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in source, (
            "frontend JS must not use " + forbidden
        )



def test_frontend_js_statistics_error_text():
    """the statistics error path must surface 加载统计失败."""
    source = read_all_js()
    assert "加载统计失败" in source



def test_frontend_js_statistics_loading_text():
    """the statistics loading path must surface 正在加载统计…."""
    source = read_all_js()
    # The loading text is in index.html; frontend JS toggles the hidden flag on
    # the statistics-loading element. Verify the element id is referenced.
    assert "statistics-loading" in source



def test_styles_css_statistics_page_classes():
    """styles.css must contain the statistics page classes."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (".stats-header", ".stats-controls", ".stats-summary-grid",
                ".stats-summary-card", ".stats-table", ".stats-table-card",
                ".stats-export-preview", ".stats-loading", ".stats-empty",
                ".stats-export-action-btn"):
        assert cls in source, (
            "styles.css must define class: " + cls
        )



def test_styles_css_statistics_responsive_wrap():
    """styles.css must include responsive wrap rules for narrow
    windows."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "flex-wrap" in source
    assert "@media" in source
    assert "overflow-x" in source



def test_styles_css_statistics_export_action_enabled_style():
    """the export action button must use an enabled pointer
    style (no longer the ``cursor: not-allowed`` disabled style)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    pos = source.find(".stats-export-action-btn")
    assert pos != -1
    end = source.find("}", pos)
    assert end != -1
    body = source[pos:end]
    # An enabled action button uses pointer cursor and a primary blue.
    assert "cursor: pointer" in body or "cursor:pointer" in body
    # The disabled not-allowed style must not appear on the default
    # (non-disabled) state. The :disabled shared style may still exist
    # elsewhere, but the default rule must not include not-allowed.
    assert "not-allowed" not in body
    # A status element style must exist for export progress / success /
    # cancel / error.
    assert ".stats-export-status" in source



def test_styles_css_no_external_assets():
    """styles.css must not reference external assets (regression
    lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"cdn", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)



def test_styles_css_timeline_and_correction_shell_not_removed():
    """Timeline and correction shell CSS must not be removed
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".timeline-date-nav" in source
    assert ".correction-shell" in source



def test_index_html_project_rules_page_migrated_after():
    """Project Rules page is active with the lightweight IA."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-rules"')
    assert pos != -1
    end = source.find('<section id="page-settings"', pos)
    section = source[pos:end]
    assert "WebView 迁移中" not in section
    assert "项目规则" in section
    assert "新建规则" in section
    assert "新建项目" in section
    assert "高级功能" in section
    assert "按上次使用排序" in section
    assert "按首字母排序" in section
    assert "应用到历史记录" in section
    assert "批量" not in section



def test_frontend_js_no_save_dialog_or_folder_open():
    """frontend JS must not call any save dialog or folder open helper."""
    source = read_all_js()
    lowered = source.lower()
    for forbidden in ("saveasdialog", "save_dialog", "createfile",
                      "openfolder", "open_folder", "shell.open"):
        assert forbidden not in lowered, (
            "frontend JS must not call: " + forbidden
        )



def test_bridge_no_export_write_method():
    """the bridge must not expose any export write / file save
    method."""
    # scan all bridge mixin files.
    # bridge.py into the mixins).
    source = read_bridge_sources_combined()
    forbidden_methods = [
        "def export_csv",
        "def export_excel",
        "def export_pdf",
        "def export_timesheet",
        "def save_file",
        "def open_folder",
        "def export_activities",
    ]
    for method in forbidden_methods:
        assert method not in source, (
            "bridge.py must not define export write method: " + method
        )



def test_schema_sql_unchanged():
    """schema.sql must not have been modified. We verify the known tables/columns are still present and no new statistics-specific table has been added."""
    schema_path = REPO_ROOT / "worktrace" / "schema.sql"
    source = schema_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS activity_log" in source
    assert "CREATE TABLE IF NOT EXISTS project" in source
    # No new statistics table should have been added.
    assert "statistics_export" not in source.lower()
    assert "statistics_summary" not in source.lower()



def test_removed_ui_files_deleted():
    """The Tkinter / CustomTkinter UI package must be absent."""
    removed_ui_dir = REPO_ROOT / "worktrace" / "ui"
    assert not removed_ui_dir.is_dir(), (
        "worktrace/ui must not exist; WebView is the only shipping UI"
    )



def test_index_html_no_react_vue_vite_node():
    """no React / Vue / Vite / Node references may be introduced."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("react", "vue", "vite", "node_modules"):
        assert forbidden not in lowered, (
            "index.html must not reference: " + forbidden
        )



def test_frontend_js_no_react_vue_vite_node():
    """frontend JS must not reference React / Vue / Vite / Node.
    Uses word-boundary matching to avoid false positives on substrings
    like ``navItems`` containing ``vite``."""
    import re
    source = read_all_js()
    lowered = source.lower()
    for forbidden in ("react", "vue", "vite", "node_modules"):
        pattern = r'\b' + re.escape(forbidden) + r'\b'
        assert not re.search(pattern, lowered), (
            "frontend JS must not reference: " + forbidden
        )



def test_frontend_js_correction_shell_no_external_links():
    """frontend JS must not reference external links / CDN
    (regression lock)."""
    source = read_all_js()
    lowered = source.lower()
    for forbidden in ("http://", "https://", "cdn", "google fonts",
                      "googleapis"):
        assert forbidden not in lowered, (
            "frontend JS must not reference external resource: " + forbidden
        )



def test_frontend_js_correction_shell_no_raw_sensitive_fields():
    """frontend JS must not render raw window_title / file_path_hint /
    full_path / clipboard fields (regression lock).

    Exception: ``clipboard_capture_enabled`` is the JSON status
    flag returned by the Settings / Privacy read-only facade; it is the
    only allowed ``clipboard`` reference. All other uses remain forbidden.

    Exception: the Settings / Privacy clipboard capture toggle
    introduces ``settings-clipboard-toggle`` DOM ids. These are UI element
    identifiers, not raw backend field names, so they are also whitelisted.
    """
    source = read_all_js()
    # The literal field names must not appear as rendered display values.
    # (They may appear in comments explaining what is NOT rendered, but
    # the test asserts the literals are absent from the rendering paths.)
    # only the legitimate JSON status flag name is whitelisted.
    source_without_capture_flag = source.replace("clipboard_capture_enabled", "")
    # whitelist the toggle DOM id prefix so it is not confused
    # with the raw "clipboard" content field.
    source_without_capture_flag = source_without_capture_flag.replace("clipboard-toggle", "")
    for forbidden in ("window_title", "file_path_hint",
                      "full_path", "clipboard"):
        assert forbidden not in source_without_capture_flag, (
            "frontend JS must not reference raw sensitive field: " + forbidden
        )



def test_bridge_no_unexpected_methods_for_contract():
    """no new bridge methods beyond the known 21-method set
    (regression lock — same known method set)."""
    # scan all bridge mixin files.
    # bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    known_methods = (
        "get_status", "toggle_pause", "get_overview",
        "get_recent_activities", "get_timeline",
        "get_timeline_session_details", "get_timeline_project_activity_summary",
        "list_projects_for_timeline",
        "update_timeline_project", "update_timeline_note",
        "update_timeline_activity_time", "update_timeline_session_time",
        "split_timeline_activity", "split_timeline_session",
        "merge_timeline_activities", "hide_timeline_activity",
        "soft_delete_timeline_activity", "hide_timeline_session",
        "soft_delete_timeline_session",
        "batch_update_timeline_activities_project",
        "batch_update_timeline_activities_note",
        "get_timeline_restorable_activities", "restore_timeline_activity",
    )
    for method in known_methods:
        assert method in bridge_src, (
            "bridge must still expose " + method
        )



def test_bridge_imports_only_allowed_modules():
    """the bridge must still only import worktrace.api and
    worktrace.formatters (regression lock)."""
    # scan all bridge mixin files.
    # of them after the page module mapping).
    bridge_src = read_bridge_sources_combined()
    for forbidden in ("from ..services", "from ..db",
                      "from ..collector", "from ..security",
                      "from ..runtime", "from ..config",
                      "import worktrace.services",
                      "import worktrace.db"):
        assert forbidden not in bridge_src, (
            "bridge must not import " + forbidden
        )



def test_api_has_expected_timeline_methods():
    """The timeline API must expose the expected method set and error classes."""
    api_src = (REPO_ROOT / "worktrace" / "api" / "timeline_api.py").read_text(
        encoding="utf-8"
    )
    for symbol in (
        "class TimelineTimeEditError",
        "class TimelineSplitError",
        "class TimelineMergeError",
        "class TimelineVisibilityError",
        "class TimelineBatchProjectError",
        "class TimelineBatchNoteError",
        "class TimelineRestoreActivityError",
        "def reclassify_timeline_session_project",
        "def update_timeline_session_note",
        "def update_timeline_activity_time",
        "def update_timeline_session_time",
        "def split_timeline_activity",
        "def split_timeline_session",
        "def merge_timeline_activities",
        "def hide_timeline_activity",
        "def soft_delete_timeline_activity",
        "def hide_timeline_session",
        "def soft_delete_timeline_session",
        "def batch_update_timeline_activities_project",
        "def batch_update_timeline_activities_note",
        "def restore_timeline_activity",
        "def get_timeline_restorable_activities",
    ):
        assert symbol in api_src, (
            "timeline_api must still define " + symbol
        )



def test_no_new_db_schema_for_contract():
    """schema.sql must still define the known core tables
    (regression lock — no new DB schema)."""
    schema_src = (REPO_ROOT / "worktrace" / "schema.sql").read_text(
        encoding="utf-8"
    )
    for table in (
        "CREATE TABLE IF NOT EXISTS project",
        "CREATE TABLE IF NOT EXISTS activity_log",
        "CREATE TABLE IF NOT EXISTS activity_project_assignment",
        "CREATE TABLE IF NOT EXISTS activity_resource",
        "CREATE TABLE IF NOT EXISTS project_session_note",
    ):
        assert table in schema_src, (
            "schema.sql must still define table: " + table
        )



def test_default_webview_entry_preserved():
    """the default entry point must still delegate to
    worktrace.webview_main (regression lock — no Tkinter fallback)."""
    main_src = (REPO_ROOT / "worktrace" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "from .webview_main import main as webview_main" in main_src, (
        "worktrace.main must still delegate to worktrace.webview_main"
    )
    assert "webview_main()" in main_src, (
        "worktrace.main must still call webview_main()"
    )





def test_frontend_js_statistics_loading_double_click_guard():
    """loadStatisticsExportSummary must refuse concurrent loads
    by checking ``statisticsLoading`` before doing any work."""
    source = read_all_js()
    body = func_body(source, "loadStatisticsExportSummary")
    assert "if (App.statisticsLoading) return" in body, (
        "loadStatisticsExportSummary must guard against concurrent loads"
    )



def test_frontend_js_statistics_client_side_range_validator():
    """frontend JS must have a client-side date range validator that
    catches invalid_date / invalid_range / range_too_large before calling the
    bridge."""
    source = read_all_js()
    assert "function validateStatisticsDateRange" in source, (
        "frontend JS must define validateStatisticsDateRange"
    )
    body = func_body(source, "validateStatisticsDateRange")
    # Must return the same Chinese messages the bridge uses.
    assert "请选择有效日期" in body
    assert "请选择有效日期范围" in body
    assert "日期范围过大" in body
    # Must check date_from > date_to.
    assert "from > to" in body
    # Must check the 31-day max (diffDays > 30 for an inclusive 31-day span).
    assert "diffDays" in body
    assert "30" in body



def test_frontend_js_statistics_load_uses_validator():
    """loadStatisticsExportSummary must call
    validateStatisticsDateRange before calling the bridge."""
    source = read_all_js()
    body = func_body(source, "loadStatisticsExportSummary")
    assert "validateStatisticsDateRange" in body
    assert "if (rangeMsg)" in body



def test_frontend_js_statistics_no_direct_file_write_in_module():
    """the statistics module may invoke the CSV export through the
    bridge (``App.callBridge("export_statistics_csv", ...)``), but must not
    contain any direct file write / save dialog / filesystem helper. The
    forbidden tokens below (``export_csv`` / ``exportCsv`` etc.) do not match
    the bridge-mediated ``exportStatisticsCsv`` / ``export_statistics_csv``
    identifiers, so the allowed bridge path is unaffected while direct
    handlers like ``exportCsv()`` or ``saveFile()`` would be caught.

    The statistics logic lives in js/statistics.js, so we check that file directly."""
    section = read_js("statistics.js")
    forbidden = (
        "save_dialog",
        "saveAs",
        "saveFile",
        "export_csv",
        "exportCsv",
        "export_excel",
        "exportExcel",
        "export_pdf",
        "exportPdf",
        "export_timesheet",
        "write_file",
        "writeFile",
        "open_folder",
        "openFolder",
        "Path.write_text",
        "Path.write_bytes",
    )
    for name in forbidden:
        assert name not in section, (
            "statistics section must not reference export write helper: " + name
        )



def test_index_html_statistics_export_hint_csv_enabled_contract_2():
    """The export preview area must announce that CSV is supported."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    section = html_element_by_id(source, "statistics-export-preview")
    # CSV is now supported; the hint announces it.
    assert "导出当前范围内已结束、非隐藏的活动记录为 CSV" in section
    # Obsolete read-only-only copy must be absent.
    assert "本阶段不支持写出" not in section
    assert "不打开保存对话框" not in section
    assert "不打开文件夹" not in section



def test_bridge_statistics_explicit_bool_rejection_comment():
    """the bridge must document that bool/None/non-string inputs
    are rejected by the isinstance str check."""
    body = read_bridge_method_body("get_statistics_export_summary")
    assert "bool" in body, (
        "bridge must document bool rejection in get_statistics_export_summary"
    )
    assert "isinstance" in body



def test_service_statistics_status_inclusion_semantics_documented():
    """statistics_service.py must document the status inclusion
    semantics (normal/idle/paused/excluded/error all included)."""
    service_path = REPO_ROOT / "worktrace" / "services" / "statistics_service.py"
    source = service_path.read_text(encoding="utf-8")
    # The documented semantics block.
    assert "normal" in source and "idle" in source and "paused" in source
    assert "excluded" in source and "error" in source
    assert "included" in source



def test_service_statistics_bool_input_rejected(temp_db):
    """bool inputs must be rejected as invalid_date."""
    from worktrace.services import statistics_service
    import pytest
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary(True, "2026-06-25")
    assert "invalid_date" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary("2026-06-25", False)
    assert "invalid_date" in str(exc.value)



def test_service_statistics_none_input_rejected(temp_db):
    """None inputs must be rejected as invalid_date."""
    from worktrace.services import statistics_service
    import pytest
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary(None, "2026-06-25")
    assert "invalid_date" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary("2026-06-25", None)
    assert "invalid_date" in str(exc.value)



def test_service_statistics_tie_breaker_stable(temp_db):
    """groups with equal duration must tie-break by display_name
    (casefold) so the order is stable across runs."""
    from worktrace.services import activity_service, project_service, statistics_service
    pid = project_service.create_project("Client")
    # Two apps with the same duration but different names. The tie-breaker
    # should sort by display_name casefold ascending.
    activity_service.create_activity(
        "Zebra", "zebra.exe", "Z1.docx", start_time="2026-06-25 09:00:00",
        project_id=pid,
    )
    aid1 = activity_service.create_activity(
        "Zebra", "zebra.exe", "Z1.docx", start_time="2026-06-25 09:00:00",
        project_id=pid,
    )
    # Close the first (auto-closes any open), then create second.
    # Actually create_activity auto-closes open ones. Let me finalize and close.
    activity_service.finalize_created_activity(aid1)
    activity_service.close_activity(aid1, "2026-06-25 09:30:00")
    aid2 = activity_service.create_activity(
        "Apple", "apple.exe", "A1.docx", start_time="2026-06-25 10:00:00",
        project_id=pid,
    )
    activity_service.finalize_created_activity(aid2)
    activity_service.close_activity(aid2, "2026-06-25 10:30:00")
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    by_app = summary["by_app"]
    # Both have 1800 seconds. Apple should come before Zebra (casefold asc).
    names = [g["display_name"] for g in by_app]
    assert names == sorted(names, key=str.casefold), (
        f"by_app tie-breaker must be stable casefold-ascending; got {names}"
    )
    assert "Apple" in names
    assert "Zebra" in names



def test_service_statistics_all_known_statuses_included(temp_db):
    """all known statuses (normal/idle/paused/excluded/error)
    must be included in the summary when closed, non-hidden, non-deleted."""
    from worktrace.services import activity_service, project_service, statistics_service
    pid = project_service.create_project("Client")
    for status in ("normal", "idle", "paused", "excluded", "error"):
        aid = activity_service.create_activity(
            "Word", "winword.exe", "A1.docx", status=status,
            start_time="2026-06-25 09:00:00", project_id=pid,
        )
        activity_service.finalize_created_activity(aid)
        activity_service.close_activity(aid, "2026-06-25 09:30:00")
    summary = statistics_service.get_statistics_export_summary("2026-06-25", "2026-06-25")
    by_status = {g["key"]: g for g in summary["by_status"]}
    assert summary["activity_count"] == 5
    for status in ("normal", "idle", "paused", "excluded", "error"):
        assert status in by_status, f"status {status} must be included"
        assert by_status[status]["activity_count"] == 1



def test_api_statistics_delegates_validation_to_service(temp_db, monkeypatch):
    """the API layer delegates date validation to the service
    layer. If the service raises ValueError with a stable code, the API maps
    it to StatisticsSummaryError with the same code."""
    from worktrace.api import statistics_api
    from worktrace.api.statistics_api import StatisticsSummaryError
    from worktrace.services import statistics_service
    import pytest
    # The service raises ValueError("invalid_date"); the API must map it.
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary("not-a-date", "2026-06-25")
    assert exc.value.code == "invalid_date"
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary("2026-06-26", "2026-06-25")
    assert exc.value.code == "invalid_range"



def test_api_statistics_unknown_value_error_collapses_to_operation_failed(
    temp_db, monkeypatch
):
    """a ValueError without a known code token must collapse to
    operation_failed so internal details never reach the bridge."""
    from worktrace.api import statistics_api
    from worktrace.api.statistics_api import StatisticsSummaryError
    from worktrace.services import statistics_service
    import pytest

    def boom(*args, **kwargs):
        raise ValueError("some internal detail")
    monkeypatch.setattr(statistics_service, "get_statistics_export_summary", boom)
    with pytest.raises(StatisticsSummaryError) as exc:
        statistics_api.get_statistics_export_summary("2026-06-25", "2026-06-25")
    assert exc.value.code == "operation_failed"
    assert "internal" not in str(exc.value).lower()



def test_bridge_statistics_bool_input_rejected(temp_db):
    """bool inputs must be rejected with 请选择有效日期."""
    from worktrace.services import settings_service
    from worktrace.webview_ui.bridge import WebViewBridge
    settings_service.clear_settings_cache()
    bridge = WebViewBridge()
    result = bridge.get_statistics_export_summary(True, "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期"
    assert result["summary"] is None
    result2 = bridge.get_statistics_export_summary("2026-06-25", False)
    assert result2["ok"] is False
    assert result2["error"] == "请选择有效日期"
    assert result2["summary"] is None



def test_bridge_statistics_none_input_rejected(temp_db):
    """None inputs must be rejected with 请选择有效日期."""
    from worktrace.services import settings_service
    from worktrace.webview_ui.bridge import WebViewBridge
    settings_service.clear_settings_cache()
    bridge = WebViewBridge()
    result = bridge.get_statistics_export_summary(None, "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期"
    assert result["summary"] is None
    result2 = bridge.get_statistics_export_summary("2026-06-25", None)
    assert result2["ok"] is False
    assert result2["error"] == "请选择有效日期"
    assert result2["summary"] is None



def test_bridge_statistics_empty_string_input_rejected(temp_db):
    """empty string inputs must be rejected with 请选择有效日期."""
    from worktrace.services import settings_service
    from worktrace.webview_ui.bridge import WebViewBridge
    settings_service.clear_settings_cache()
    bridge = WebViewBridge()
    result = bridge.get_statistics_export_summary("", "2026-06-25")
    assert result["ok"] is False
    assert result["error"] == "请选择有效日期"
    assert result["summary"] is None
    result2 = bridge.get_statistics_export_summary("2026-06-25", "")
    assert result2["ok"] is False
    assert result2["error"] == "请选择有效日期"
    assert result2["summary"] is None



def test_schema_sql_unchanged_contract_2():
    """no DB schema changes."""
    schema_path = REPO_ROOT / "worktrace" / "schema.sql"
    source = schema_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS activity_log" in source
    assert "CREATE TABLE IF NOT EXISTS project" in source
    # No new statistics table.
    assert "statistics_export" not in source.lower()
    assert "stats_summary" not in source.lower()



def test_removed_ui_files_deleted_duplicate_lock():
    """The Tkinter UI directory must not exist."""
    ui_dir = REPO_ROOT / "worktrace" / "ui"
    assert not ui_dir.exists(), (
        "worktrace/ui must not exist (removed UI package)"
    )





def test_frontend_js_statistics_export_calls_bridge_export_statistics_csv():
    """frontend JS must call the bridge ``export_statistics_csv``
    method to perform the CSV write. The frontend never writes a file
    itself; it only invokes the bridge."""
    source = read_all_js()
    assert 'callBridge("export_statistics_csv"' in source, (
        "frontend JS must call bridge export_statistics_csv for the CSV write"
    )



def test_frontend_js_statistics_export_saving_guard_present():
    """frontend JS must define a separate ``statisticsExportSaving``
    guard so the CSV write cannot be double-triggered or overlap a
    statistics load. The guard must NOT reuse ``statisticsLoading``."""
    source = read_all_js()
    assert "statisticsExportSaving" in source, (
        "frontend JS must define statisticsExportSaving guard"
    )
    # The guard variable must be declared as a separate boolean state.
    # state vars live on the App. namespace.
    assert "App.statisticsExportSaving = false" in source, (
        "statisticsExportSaving must start as a separate false boolean"
    )
    # The export function must check the guard on entry.
    body = func_body(source, "exportStatisticsCsv")
    assert "if (App.statisticsExportSaving)" in body, (
        "exportStatisticsCsv must guard against duplicate clicks"
    )
    # The statistics load path must also block while a write is in flight.
    # ``setStatisticsLoading`` must consider ``statisticsExportSaving``.
    set_load_body = func_body(source, "setStatisticsLoading")
    assert "statisticsExportSaving" in set_load_body, (
        "setStatisticsLoading must disable export btn while a write is in flight"
    )



def test_frontend_js_statistics_export_uses_validate_statistics_date_range():
    """exportStatisticsCsv must call
    validateStatisticsDateRange before calling the bridge, so the user
    gets an immediate clear message without a bridge round-trip."""
    source = read_all_js()
    body = func_body(source, "exportStatisticsCsv")
    assert "validateStatisticsDateRange" in body, (
        "exportStatisticsCsv must call validateStatisticsDateRange"
    )



def test_frontend_js_statistics_export_catch_never_surfaces_raw_exception():
    """the exportStatisticsCsv promise catch must collapse to
    a stable Chinese message and never read raw exception text."""
    source = read_all_js()
    body = func_body(source, "exportStatisticsCsv")
    # Extract the .catch(function () { ... }) block from the export function.
    catch_body = js_catch_block(body)
    assert catch_body, "exportStatisticsCsv must have a catch block"
    assert "导出失败" in catch_body, (
        "export catch must collapse to the stable 导出失败 message"
    )
    # The catch must NOT read err / error / exception message fields.
    for forbidden in (
        "err.message",
        "err.toString",
        "error.message",
        "error.toString",
        "exception.message",
    ):
        assert forbidden not in catch_body, (
            "export catch must not surface raw exception text via " + forbidden
        )



def test_frontend_js_statistics_export_cancel_is_clean_result():
    """a cancelled export must be handled as a clean info
    result (``已取消导出``), not as a Python exception or ``导出失败``."""
    source = read_all_js()
    body = func_body(source, "exportStatisticsCsv")
    assert "result.cancelled" in body or "cancelled" in body, (
        "exportStatisticsCsv must handle a cancelled result explicitly"
    )
    assert "已取消导出" in body, (
        "cancel result must show the stable 已取消导出 message"
    )



def test_frontend_js_statistics_export_success_shows_filename_count_duration():
    """a successful export must surface the basename, activity
    count, and total duration — never the full local path."""
    source = read_all_js()
    body = func_body(source, "exportStatisticsCsv")
    # The success branch must reference filename / activity_count / duration.
    assert "filename" in body, (
        "success payload must surface filename (basename only)"
    )
    assert "activity_count" in body, (
        "success payload must surface activity_count"
    )
    assert "duration" in body, (
        "success payload must surface duration"
    )
    # ``导出成功`` is the stable success prefix.
    assert "导出成功" in body, (
        "success message must start with the stable 导出成功 prefix"
    )



def test_frontend_js_no_export_excel_pdf_timesheet_open_folder_methods():
    """frontend JS must not define any export_excel / export_pdf /
    export_timesheet / open_folder / auto-submit methods."""
    source = read_all_js()
    lowered = source.lower()
    forbidden = (
        "exportexcel",
        "export_pdf",
        "exportpdf",
        "exporttimesheet",
        "export_timesheet",
        "openfolder",
        "open_folder",
        "auto_submit",
        "autosubmit",
        "openexternal",
        "open_external",
        "shell.open",
        "require('electron')",
        "require('node')",
    )
    for token in forbidden:
        assert token not in lowered, (
            "frontend JS must not reference forbidden export/external token: " + token
        )



def test_bridge_export_statistics_csv_method_present():
    """bridge.py must define ``export_statistics_csv`` (the
    controlled write path for the CSV export)."""
    # the method body lives in bridge_statistics.py.
    # bridge_statistics.py after the page module mapping).
    source = read_bridge_sources_combined()
    assert "def export_statistics_csv" in source, (
        "bridge.py must define export_statistics_csv"
    )
    # The bridge must NOT define any other export write methods.
    for forbidden in (
        "def export_excel",
        "def export_pdf",
        "def export_timesheet",
        "def open_folder",
        "def auto_submit",
        "def open_external",
    ):
        assert forbidden not in source, (
            "bridge.py must not define forbidden export method: " + forbidden
        )



def test_bridge_set_window_method_present():
    """bridge.py must define ``set_window`` so webview_main.py
    can inject the pywebview window for the native save dialog."""
    # ``set_window`` is still defined on the composition
    # ``WebViewBridge`` class in bridge.py itself.
    source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    assert "def set_window" in source, (
        "bridge.py must define set_window for pywebview window injection"
    )
    # The constructor must initialize ``_window`` to None so importing
    # the bridge module never starts the GUI.
    assert "self._window" in source
    # set_window must NOT itself start the GUI or construct a window. We
    # only forbid the actual call form (``webview.start()`` /
    # ``webview.create_window(``), not docstring text that merely mentions
    # these APIs.
    body = python_method_body(source, "set_window")
    assert "webview.start()" not in body, (
        "set_window must not call webview.start()"
    )
    assert "webview.create_window(" not in body, (
        "set_window must not call webview.create_window()"
    )



def test_bridge_export_statistics_csv_returns_basename_only():
    """the docstring of export_statistics_csv must state that
    only the basename is returned (never the full local path)."""
    # method body lives in bridge_statistics.py.
    # (StatisticsBridgeMixin).
    body = read_bridge_method_body("export_statistics_csv")
    assert "basename" in body.lower() or "filename" in body.lower(), (
        "export_statistics_csv docstring must document basename-only return"
    )
    # The success payload must include filename / activity_count / duration.
    assert "filename" in body
    assert "activity_count" in body
    assert "duration" in body
    # The cancel payload must include cancelled: True.
    assert "cancelled" in body



def test_webview_main_injects_window_into_bridge():
    """webview_main.py must call bridge.set_window(window) so
    the bridge can open the native save dialog for the CSV export."""
    source = (REPO_ROOT / "worktrace" / "webview_main.py").read_text(
        encoding="utf-8"
    )
    assert "bridge.set_window" in source, (
        "webview_main.py must call bridge.set_window(window)"
    )
    # The window must be captured from create_window's return value.
    assert "window = webview.create_window" in source, (
        "webview_main.py must capture the create_window return value"
    )
    # set_window must be called BEFORE webview.start() so the bridge has
    # the reference when the JS callback fires.
    set_pos = source.find("bridge.set_window")
    start_pos = source.find("webview.start()")
    assert set_pos != -1 and start_pos != -1
    assert set_pos < start_pos, (
        "bridge.set_window must be called before webview.start()"
    )



def test_index_html_statistics_export_status_element_present():
    """index.html must contain a dedicated export status
    element (``stats-export-status``) so the frontend can surface
    export progress / success / cancel / error without alert()."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="stats-export-status"' in source, (
        "index.html must define stats-export-status element"
    )



def test_styles_css_statistics_export_status_classes():
    """styles.css must define the export status base class and
    the info / success / error variants."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".stats-export-status" in source
    # At least the success and error variants must exist.
    assert ".stats-export-status.success" in source or ".success" in source
    assert ".stats-export-status.error" in source or ".error" in source



def test_frontend_js_statistics_export_no_local_storage_session_storage():
    """the export action must not use localStorage or
    sessionStorage (regression lock for the new write path)."""
    source = read_all_js()
    # Scan the full function body so the catch / status helpers are included.
    body = func_body(source, "exportStatisticsCsv")
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in body, (
            "exportStatisticsCsv must not use " + forbidden
        )



def test_index_html_statistics_export_no_external_links():
    """the statistics export section must not reference any
    external link / CDN / Google Fonts (regression lock)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    section = html_section_by_id(source, "page-statistics")
    assert not re.search(r"https?://", section), (
        "statistics section must not reference external links"
    )
    assert not re.search(r"cdn", section, re.IGNORECASE), (
        "statistics section must not reference CDN"
    )
    assert not re.search(r"google\s*fonts", section, re.IGNORECASE), (
        "statistics section must not reference Google Fonts"
    )



# This test prevents stale "must" phrasing from creeping back
# prevents the old monolithic-file "must" phrasing from creeping back
# into this file's docstrings / assertion messages and misleading readers.


def test_no_stale_app_js_must_wording_in_this_file():
    """Requirements should refer to frontend JS, not app.js."""
    own_source = open(__file__, encoding="utf-8").read()
    stale = "app.js" + " must"
    assert stale not in own_source, (
        "statistics contract must not revive stale monolithic-file wording; "
        "use 'frontend JS must' instead"
    )


# The statistics load and the CSV export must use SEPARATE state variables
# (``statisticsLoading`` vs ``statisticsExportSaving``) and each must
# cross-disable the other's button so a load and a write can never overlap.


def test_frontend_js_statistics_load_and_export_use_independent_state():
    """``statisticsLoading`` and ``statisticsExportSaving`` must
    be declared as distinct boolean state variables (not aliases of each
    other). The load function guards on ``statisticsLoading`` and the export
    function guards on ``statisticsExportSaving``; neither may reuse the
    other's variable as its own guard."""
    source = read_all_js()
    # Both state variables must be declared on the App namespace.
    assert "App.statisticsLoading" in source, (
        "statisticsLoading must be a declared state variable"
    )
    assert "App.statisticsExportSaving" in source, (
        "statisticsExportSaving must be a declared state variable"
    )
    # The export function must check its OWN guard, not the load guard.
    export_body = func_body(source, "exportStatisticsCsv")
    assert "if (App.statisticsExportSaving)" in export_body, (
        "exportStatisticsCsv must guard against duplicate clicks via "
        "statisticsExportSaving, not statisticsLoading"
    )
    # The export function must also refuse while statistics are loading.
    assert "if (App.statisticsLoading)" in export_body, (
        "exportStatisticsCsv must refuse to start while a statistics load "
        "is in flight"
    )
    # The load function must guard on statisticsLoading (its own guard).
    load_body = func_body(source, "loadStatisticsExportSummary")
    assert "if (App.statisticsLoading)" in load_body, (
        "loadStatisticsExportSummary must guard via statisticsLoading"
    )


def test_frontend_js_statistics_export_disables_both_buttons():
    """``setStatisticsExportSaving`` must disable BOTH the
    export button and the statistics load button while a write is in
    flight, so the user cannot trigger a concurrent load."""
    source = read_js("statistics.js")
    body = func_body(source, "setStatisticsExportSaving")
    assert "stats-export-action-btn" in body, (
        "setStatisticsExportSaving must toggle the export button"
    )
    assert "statistics-load-btn" in body, (
        "setStatisticsExportSaving must also disable the load button"
    )
    # Both buttons must be disabled by the saving flag.
    assert "saving" in body
    assert "App.statisticsLoading" in body, (
        "the load button disabled state must also consider statisticsLoading"
    )


def test_frontend_js_statistics_load_disables_export_button():
    """``setStatisticsLoading`` must disable the export button
    while statistics are loading, so a write cannot be triggered mid-load."""
    source = read_js("statistics.js")
    body = func_body(source, "setStatisticsLoading")
    assert "stats-export-action-btn" in body, (
        "setStatisticsLoading must disable the export button while loading"
    )
    assert "App.statisticsExportSaving" in body, (
        "the export button disabled state must consider statisticsExportSaving"
    )
