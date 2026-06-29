"""Statistics / Export WebView static-contract tests.

These tests read the bundled frontend resources (index.html /
js/*.js / styles.css) directly without starting the GUI. Phase R2
split the monolithic app.js into six js/ modules; JS-level contracts
use read_all_js() (concatenated split modules in load order) or
read_js("<module>.js") for module-scoped checks. They lock the
Statistics / Export page contracts for Phases 4A, 4A.1, and 4B.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import (
    REPO_ROOT, WEBVIEW_UI_DIR, HISTORY_PATH,
    RELEASE_VALIDATION_PATH, README_PATH,
    read_resource, read_all_js, read_js, func_body,
    FRONTEND_RESOURCE_FILES, NO_STORAGE_FILES,
)


# --- Phase 4A ----------------------------------------------------


def test_index_html_statistics_nav_entry_4a():
    """Phase 4A: the sidebar nav must contain the 统计与导出 entry."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-page="statistics"' in source
    assert "统计与导出" in source



def test_index_html_statistics_page_section_exists_4a():
    """Phase 4A: the page-statistics section must exist and not be a
    placeholder."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-statistics"')
    assert pos != -1
    section = source[pos:pos + 2000]
    # The migrated page must NOT show the migration placeholder.
    assert "WebView 迁移中" not in section



def test_index_html_statistics_header_subtitle_4b():
    """Phase 4B: the page header subtitle must announce CSV export is
    open (no longer the read-only / no-file-write 4A copy)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-statistics"')
    section = source[pos:pos + 600]
    assert "统计 / 导出" in section
    assert "查看统计并导出当前范围内的活动记录为 CSV 文件" in section
    # The old 4A read-only copy must be gone.
    assert "本阶段仅提供只读统计和导出预览" not in section
    assert "暂不写入文件" not in section



def test_index_html_statistics_date_range_controls_4a():
    """Phase 4A: date range controls must exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="statistics-date-from"' in source
    assert 'id="statistics-date-to"' in source
    assert 'id="statistics-load-btn"' in source
    assert "加载统计" in source



def test_index_html_statistics_quick_range_buttons_4a():
    """Phase 4A: quick range buttons (today / 7d / month) exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="statistics-today-btn"' in source
    assert 'id="statistics-7d-btn"' in source
    assert 'id="statistics-month-btn"' in source



def test_index_html_statistics_summary_cards_4a():
    """Phase 4A: the four summary cards exist (total / activity / project /
    app)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="stats-total"' in source
    assert 'id="stats-activity-count"' in source
    assert 'id="stats-project-count"' in source
    assert 'id="stats-app-count"' in source



def test_index_html_statistics_grouped_tables_4a():
    """Phase 4A: by_project / by_app / by_status tables exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="stats-by-project"' in source
    assert 'id="stats-by-app"' in source
    assert 'id="stats-by-status"' in source
    assert "按项目" in source
    assert "按应用" in source
    assert "按状态" in source



def test_index_html_statistics_empty_states_4a():
    """Phase 4A: each table has an empty-state element."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="stats-empty-project"' in source
    assert 'id="stats-empty-app"' in source
    assert 'id="stats-empty-status"' in source
    assert "暂无统计数据" in source



def test_index_html_statistics_export_preview_4a():
    """Phase 4A: the export preview card exists with range / count /
    duration / formats fields."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="statistics-export-preview"' in source
    assert 'id="stats-export-range"' in source
    assert 'id="stats-export-count"' in source
    assert 'id="stats-export-duration"' in source
    assert 'id="stats-export-formats"' in source
    assert "导出预览" in source



def test_index_html_statistics_export_action_enabled_4b():
    """Phase 4B: the export action button must be enabled and labeled
    "导出 CSV" (no longer the disabled 4A placeholder)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="stats-export-action-btn"')
    assert pos != -1
    section = source[pos:pos + 400]
    # The button must be a real action button with the CSV label.
    assert "导出 CSV" in section
    # The button itself must NOT carry a disabled attribute; the old
    # 4A copy ("导出动作将在后续阶段开放") must be gone.
    assert "导出动作将在后续阶段开放" not in section
    # A status element must exist for export progress / success / cancel.
    assert 'id="stats-export-status"' in source



def test_index_html_statistics_export_hint_csv_enabled_4b():
    """Phase 4B: the export hint must announce CSV is supported and that
    Excel / PDF / timesheet / folder-open / auto-submit remain unsupported."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find("stats-export-hint")
    assert pos != -1
    section = source[pos:pos + 600]
    # The hint must clearly state CSV is the supported format.
    assert "当前支持 CSV 导出" in section
    assert "导出范围最多 31 天" in section
    assert "已结束的非隐藏记录" in section
    assert "不含窗口标题、文件路径等敏感信息" in section
    # Excel / PDF / timesheet / folder-open / auto-submit remain unsupported.
    assert "Excel" in section
    assert "PDF" in section
    assert "timesheet" in section
    assert "打开文件夹" in section
    assert "自动提交工时" in section
    # The old 4A copy must be gone.
    assert "本阶段不支持写出" not in section



def test_index_html_statistics_loading_text_4a():
    """Phase 4A: the loading text 正在加载统计… must be present."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "正在加载统计" in source



def test_index_html_statistics_error_text_4a():
    """Phase 4A: the error banner default text 加载统计失败 must be present."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="statistics-error"' in source
    assert "加载统计失败" in source



def test_index_html_statistics_only_csv_export_button_allowed_4b():
    """Phase 4B: CSV export is now supported via the bridge. index.html may
    contain the CSV export button (stats-export-action-btn / 导出 CSV), but
    must NOT contain Excel / PDF / timesheet / open-folder / auto-submit
    button controls, nor any frontend-side save-dialog / file-path input
    control. The CSV export write itself is only invoked through a bridge
    call, never via a frontend direct file-write control.

    Note: the export hint text legitimately mentions Excel / PDF / timesheet
    / 打开文件夹 / 自动提交工时 as *unsupported* features; those mentions are
    verified by test_index_html_statistics_export_hint_csv_enabled_4b. This
    test only forbids button-like ids / classes and the ``导出excel`` /
    ``导出pdf`` label tokens (with the 导出 prefix) that would indicate a
    real unsupported export button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    # CSV is the only supported export format (Phase 4B). No button id /
    # class for Excel / PDF / timesheet / folder-open / auto-submit may
    # exist, and no 导出excel / 导出pdf button label may be present.
    for forbidden in ("export-excel-btn", "export-pdf-btn",
                      "export-timesheet-btn", "save-file-btn",
                      "open-folder-btn", "auto-submit-btn",
                      "导出excel", "导出pdf"):
        assert forbidden not in lowered, (
            "index.html must not contain unsupported export button: " + forbidden
        )



def test_index_html_overview_and_timeline_nav_not_regressed_4a():
    """Phase 4A: Overview and Timeline nav entries must still exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-page="overview"' in source
    assert 'data-page="timeline"' in source



def test_frontend_js_statistics_state_variables_4a():
    """Phase 4A: frontend JS must declare the statistics state variables."""
    source = read_all_js()
    assert "statisticsLoaded" in source
    assert "statisticsLoading" in source
    assert "statisticsRequestToken" in source



def test_frontend_js_statistics_load_function_4a():
    """Phase 4A: frontend JS must define loadStatisticsExportSummary and call the
    bridge method get_statistics_export_summary."""
    source = read_all_js()
    assert "function loadStatisticsExportSummary" in source
    assert "get_statistics_export_summary" in source



def test_frontend_js_statistics_render_function_4a():
    """Phase 4A: frontend JS must define showStatistics and renderStatsTable."""
    source = read_all_js()
    assert "function showStatistics" in source
    assert "function renderStatsTable" in source
    assert "function renderExportPreview" in source



def test_frontend_js_statistics_quick_range_function_4a():
    """Phase 4A: frontend JS must define applyStatisticsQuickRange and
    initStatisticsDefaults."""
    source = read_all_js()
    assert "function applyStatisticsQuickRange" in source
    assert "function initStatisticsDefaults" in source



def test_frontend_js_statistics_lazy_load_in_switch_page_4a():
    """Phase 4A: switchPage must lazy-load the statistics summary on first
    navigation to the page."""
    source = read_all_js()
    # Find the switchPage function body and verify the statistics branch.
    pos = source.find("function switchPage")
    assert pos != -1
    body = source[pos:pos + 1500]
    assert "statistics" in body
    assert "loadStatisticsExportSummary" in body
    assert "initStatisticsDefaults" in body



def test_frontend_js_statistics_event_binding_in_init_buttons_4a():
    """Phase 4A: initButtons must bind the statistics load + quick range
    buttons."""
    source = read_all_js()
    pos = source.find("function initButtons")
    assert pos != -1
    body = source[pos:pos + 5000]
    assert "statistics-load-btn" in body
    assert "statistics-today-btn" in body
    assert "statistics-7d-btn" in body
    assert "statistics-month-btn" in body
    assert "loadStatisticsExportSummary" in body
    assert "applyStatisticsQuickRange" in body



def test_frontend_js_statistics_uses_escape_html_4a():
    """Phase 4A: renderStatsTable must use escapeHtml for dynamic values."""
    source = read_all_js()
    pos = source.find("function renderStatsTable")
    assert pos != -1
    body = source[pos:pos + 1200]
    assert "escapeHtml" in body
    assert "safeText" in body



def test_frontend_js_statistics_export_only_via_bridge_4b():
    """Phase 4B: CSV export is now supported, but only through the bridge.
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



def test_frontend_js_statistics_no_local_storage_4a():
    """Phase 4A: the statistics page must not use localStorage /
    sessionStorage (regression lock)."""
    source = read_all_js()
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in source, (
            "frontend JS must not use " + forbidden
        )



def test_frontend_js_statistics_error_text_4a():
    """Phase 4A: the statistics error path must surface 加载统计失败."""
    source = read_all_js()
    assert "加载统计失败" in source



def test_frontend_js_statistics_loading_text_4a():
    """Phase 4A: the statistics loading path must surface 正在加载统计…."""
    source = read_all_js()
    # The loading text is in index.html; frontend JS toggles the hidden flag on
    # the statistics-loading element. Verify the element id is referenced.
    assert "statistics-loading" in source



def test_styles_css_statistics_page_classes_4a():
    """Phase 4A: styles.css must contain the statistics page classes."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (".stats-header", ".stats-controls", ".stats-summary-grid",
                ".stats-summary-card", ".stats-table", ".stats-table-card",
                ".stats-export-preview", ".stats-loading", ".stats-empty",
                ".stats-export-action-btn"):
        assert cls in source, (
            "styles.css must define class: " + cls
        )



def test_styles_css_statistics_responsive_wrap_4a():
    """Phase 4A: styles.css must include responsive wrap rules for narrow
    windows."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "flex-wrap" in source
    assert "@media" in source
    assert "overflow-x" in source



def test_styles_css_statistics_export_action_enabled_style_4b():
    """Phase 4B: the export action button must use an enabled pointer
    style (no longer the 4A ``cursor: not-allowed`` disabled style)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    pos = source.find(".stats-export-action-btn")
    assert pos != -1
    body = source[pos:pos + 400]
    # An enabled action button uses pointer cursor and a primary blue.
    assert "cursor: pointer" in body or "cursor:pointer" in body
    # The disabled not-allowed style must not appear on the default
    # (non-disabled) state. The :disabled shared style may still exist
    # elsewhere, but the default rule must not include not-allowed.
    assert "not-allowed" not in body
    # A status element style must exist for export progress / success /
    # cancel / error.
    assert ".stats-export-status" in source



def test_styles_css_no_external_assets_4a():
    """Phase 4A: styles.css must not reference external assets (regression
    lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"cdn", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)



def test_styles_css_timeline_and_correction_shell_not_removed_4a():
    """Phase 4A: Timeline and correction shell CSS must not be removed
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".timeline-date-nav" in source
    assert ".correction-shell" in source



def test_index_html_project_rules_page_migrated_after_5b():
    """Phase 5B/5C/5D: Project Rules is migrated; supports existing rule
    toggles (5B), keyword rule creation (5C), and keyword rule deletion (5D).
    The boundary copy lists the supported ops and the not-yet-open ops."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-rules"')
    assert pos != -1
    end = source.find("</section>", pos)
    section = source[pos:end]
    assert "WebView 迁移中" not in section
    assert "项目规则" in section
    # Phase 5C: boundary copy updated to mention keyword creation. The
    # supported-ops clause still references enable/disable.
    assert "启用/停用" in section
    assert "新增关键词规则" in section
    # Phase 5D: boundary copy updated to mention keyword deletion.
    assert "删除已有关键词规则" in section
    # Phase 5H: single-rule impact preview + safe backfill are now supported;
    # automatic rules / batch ops / hard delete remain not-yet-open.
    assert "编辑" in section
    assert "预览单条规则影响" in section
    assert "安全应用" in section
    assert "自动规则" in section
    assert "批量" in section
    assert "项目硬删除" in section



def test_frontend_js_no_save_dialog_or_folder_open_4a():
    """Phase 4A: frontend JS must not call any save dialog or folder open helper."""
    source = read_all_js()
    lowered = source.lower()
    for forbidden in ("saveasdialog", "save_dialog", "createfile",
                      "openfolder", "open_folder", "shell.open"):
        assert forbidden not in lowered, (
            "frontend JS must not call: " + forbidden
        )



def test_bridge_no_export_write_method_4a():
    """Phase 4A: the bridge must not expose any export write / file save
    method."""
    bridge_path = WEBVIEW_UI_DIR / "bridge.py"
    source = bridge_path.read_text(encoding="utf-8")
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



def test_schema_sql_unchanged_4a():
    """Phase 4A: schema.sql must not have been modified for this phase. We
    verify the known Phase 4A tables/columns are still present and no new
    statistics-specific table has been added."""
    schema_path = REPO_ROOT / "worktrace" / "schema.sql"
    source = schema_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS activity_log" in source
    assert "CREATE TABLE IF NOT EXISTS project" in source
    # No new statistics table should have been added.
    assert "statistics_export" not in source.lower()
    assert "statistics_summary" not in source.lower()



def test_legacy_ui_files_not_deleted_4a():
    """Phase 4A: legacy Tkinter / CustomTkinter UI files must still exist
    (regression lock)."""
    legacy_dir = REPO_ROOT / "worktrace" / "ui"
    assert legacy_dir.is_dir()
    assert (legacy_dir / "statistics_view.py").is_file()
    assert (legacy_dir / "app.py").is_file()



def test_index_html_no_react_vue_vite_node_4a():
    """Phase 4A: no React / Vue / Vite / Node references may be introduced."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("react", "vue", "vite", "node_modules"):
        assert forbidden not in lowered, (
            "index.html must not reference: " + forbidden
        )



def test_frontend_js_no_react_vue_vite_node_4a():
    """Phase 4A: frontend JS must not reference React / Vue / Vite / Node.
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



def test_frontend_js_correction_shell_no_external_links_3c():
    """Phase 3C: frontend JS must not reference external links / CDN
    (regression lock)."""
    source = read_all_js()
    lowered = source.lower()
    for forbidden in ("http://", "https://", "cdn", "google fonts",
                      "googleapis"):
        assert forbidden not in lowered, (
            "frontend JS must not reference external resource: " + forbidden
        )



def test_frontend_js_correction_shell_no_raw_sensitive_fields_3c():
    """Phase 3C: frontend JS must not render raw window_title / file_path_hint /
    full_path / clipboard fields (regression lock).

    Phase 6A exception: ``clipboard_capture_enabled`` is the JSON status
    flag returned by the Settings / Privacy read-only facade; it is the
    only allowed ``clipboard`` reference. All other uses remain forbidden.

    Phase 6B exception: the Settings / Privacy clipboard capture toggle
    introduces ``settings-clipboard-toggle`` DOM ids. These are UI element
    identifiers, not raw backend field names, so they are also whitelisted.
    """
    source = read_all_js()
    # The literal field names must not appear as rendered display values.
    # (They may appear in comments explaining what is NOT rendered, but
    # the test asserts the literals are absent from the rendering paths.)
    # Phase 6A: only the legitimate JSON status flag name is whitelisted.
    source_without_capture_flag = source.replace("clipboard_capture_enabled", "")
    # Phase 6B: whitelist the toggle DOM id prefix so it is not confused
    # with the raw "clipboard" content field.
    source_without_capture_flag = source_without_capture_flag.replace("clipboard-toggle", "")
    for forbidden in ("window_title", "file_path_hint",
                      "full_path", "clipboard"):
        assert forbidden not in source_without_capture_flag, (
            "frontend JS must not reference raw sensitive field: " + forbidden
        )



def test_bridge_no_new_methods_for_phase_3c():
    """Phase 3C: no new bridge methods beyond the known 21-method set
    (regression lock — same set as Phase 3B.9.1)."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    known_methods = (
        "get_status", "toggle_pause", "get_overview",
        "get_recent_activities", "get_timeline",
        "get_timeline_session_details", "list_projects_for_timeline",
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



def test_bridge_imports_only_allowed_modules_3c():
    """Phase 3C: the bridge must still only import worktrace.api and
    worktrace.formatters (regression lock)."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    for forbidden in ("from ..services", "from ..db",
                      "from ..collector", "from ..security",
                      "from ..runtime", "from ..config",
                      "import worktrace.services",
                      "import worktrace.db"):
        assert forbidden not in bridge_src, (
            "bridge must not import " + forbidden
        )



def test_api_has_no_new_methods_for_phase_3c():
    """Phase 3C: the timeline API must still expose the known Phase 3B.8
    method set and error classes (regression lock — no new API methods)."""
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



def test_no_new_db_schema_for_phase_3c():
    """Phase 3C: schema.sql must still define the known core tables
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



def test_default_webview_entry_preserved_3c():
    """Phase 3C: the default entry point must still delegate to
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



# --- Phase 4A.1 --------------------------------------------------


def test_frontend_js_statistics_loading_double_click_guard_4a1():
    """Phase 4A.1: loadStatisticsExportSummary must refuse concurrent loads
    by checking ``statisticsLoading`` before doing any work."""
    source = read_all_js()
    pos = source.find("function loadStatisticsExportSummary")
    assert pos != -1
    body = source[pos:pos + 600]
    assert "if (App.statisticsLoading) return" in body, (
        "loadStatisticsExportSummary must guard against concurrent loads"
    )



def test_frontend_js_statistics_client_side_range_validator_4a1():
    """Phase 4A.1: frontend JS must have a client-side date range validator that
    catches invalid_date / invalid_range / range_too_large before calling the
    bridge."""
    source = read_all_js()
    assert "function validateStatisticsDateRange" in source, (
        "frontend JS must define validateStatisticsDateRange"
    )
    pos = source.find("function validateStatisticsDateRange")
    body = source[pos:pos + 1200]
    # Must return the same Chinese messages the bridge uses.
    assert "请选择有效日期" in body
    assert "请选择有效日期范围" in body
    assert "日期范围过大" in body
    # Must check date_from > date_to.
    assert "from > to" in body
    # Must check the 31-day max (diffDays > 30 for an inclusive 31-day span).
    assert "diffDays" in body
    assert "30" in body



def test_frontend_js_statistics_load_uses_validator_4a1():
    """Phase 4A.1: loadStatisticsExportSummary must call
    validateStatisticsDateRange before calling the bridge."""
    source = read_all_js()
    pos = source.find("function loadStatisticsExportSummary")
    body = source[pos:pos + 2000]
    assert "validateStatisticsDateRange" in body
    assert "if (rangeMsg)" in body



def test_frontend_js_statistics_no_direct_file_write_in_module_4b():
    """Phase 4B: the statistics module may invoke the CSV export through the
    bridge (``App.callBridge("export_statistics_csv", ...)``), but must not
    contain any direct file write / save dialog / filesystem helper. The
    forbidden tokens below (``export_csv`` / ``exportCsv`` etc.) do not match
    the bridge-mediated ``exportStatisticsCsv`` / ``export_statistics_csv``
    identifiers, so the allowed bridge path is unaffected while direct
    handlers like ``exportCsv()`` or ``saveFile()`` would be caught.

    Phase R2: the statistics logic now lives in its own js/statistics.js
    file, so we check that file directly instead of looking for the old
    ``// --- Phase 4A: Statistics`` / ``// --- Utility`` section markers
    that existed in the monolithic app.js."""
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



def test_index_html_statistics_export_hint_csv_enabled_4a1_to_4b():
    """Phase 4B (supersedes 4A.1): the export preview area must announce
    CSV is supported; the old 4A.1 "本阶段不支持写出" copy must be gone."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="statistics-export-preview"')
    assert pos != -1
    section = source[pos:pos + 2000]
    # CSV is now supported; the hint announces it.
    assert "当前支持 CSV 导出" in section
    # Excel / PDF / timesheet remain explicitly unsupported.
    assert "Excel" in section
    assert "PDF" in section
    assert "timesheet" in section
    # The old 4A.1 read-only copy must be gone.
    assert "本阶段不支持写出" not in section
    assert "不打开保存对话框" not in section
    assert "不打开文件夹" not in section



def test_bridge_statistics_explicit_bool_rejection_comment_4a1():
    """Phase 4A.1: bridge.py must document that bool/None/non-string inputs
    are rejected by the isinstance str check."""
    bridge_path = REPO_ROOT / "worktrace" / "webview_ui" / "bridge.py"
    source = bridge_path.read_text(encoding="utf-8")
    pos = source.find("def get_statistics_export_summary")
    body = source[pos:pos + 1500]
    assert "bool" in body, (
        "bridge must document bool rejection in get_statistics_export_summary"
    )
    assert "isinstance" in body



def test_service_statistics_status_inclusion_semantics_documented_4a1():
    """Phase 4A.1: statistics_service.py must document the status inclusion
    semantics (normal/idle/paused/excluded/error all included)."""
    service_path = REPO_ROOT / "worktrace" / "services" / "statistics_service.py"
    source = service_path.read_text(encoding="utf-8")
    # The documented semantics block.
    assert "normal" in source and "idle" in source and "paused" in source
    assert "excluded" in source and "error" in source
    assert "included" in source



def test_service_statistics_bool_input_rejected_4a1(temp_db):
    """Phase 4A.1: bool inputs must be rejected as invalid_date."""
    from worktrace.services import statistics_service
    import pytest
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary(True, "2026-06-25")
    assert "invalid_date" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary("2026-06-25", False)
    assert "invalid_date" in str(exc.value)



def test_service_statistics_none_input_rejected_4a1(temp_db):
    """Phase 4A.1: None inputs must be rejected as invalid_date."""
    from worktrace.services import statistics_service
    import pytest
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary(None, "2026-06-25")
    assert "invalid_date" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        statistics_service.get_statistics_export_summary("2026-06-25", None)
    assert "invalid_date" in str(exc.value)



def test_service_statistics_tie_breaker_stable_4a1(temp_db):
    """Phase 4A.1: groups with equal duration must tie-break by display_name
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



def test_service_statistics_all_known_statuses_included_4a1(temp_db):
    """Phase 4A.1: all known statuses (normal/idle/paused/excluded/error)
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



def test_api_statistics_delegates_validation_to_service_4a1(temp_db, monkeypatch):
    """Phase 4A.1: the API layer delegates date validation to the service
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



def test_api_statistics_unknown_value_error_collapses_to_operation_failed_4a1(
    temp_db, monkeypatch
):
    """Phase 4A.1: a ValueError without a known code token must collapse to
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



def test_bridge_statistics_bool_input_rejected_4a1(temp_db):
    """Phase 4A.1: bool inputs must be rejected with 请选择有效日期."""
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



def test_bridge_statistics_none_input_rejected_4a1(temp_db):
    """Phase 4A.1: None inputs must be rejected with 请选择有效日期."""
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



def test_bridge_statistics_empty_string_input_rejected_4a1(temp_db):
    """Phase 4A.1: empty string inputs must be rejected with 请选择有效日期."""
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



def test_schema_sql_unchanged_4a1():
    """Phase 4A.1: no DB schema changes."""
    schema_path = REPO_ROOT / "worktrace" / "schema.sql"
    source = schema_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS activity_log" in source
    assert "CREATE TABLE IF NOT EXISTS project" in source
    # No new statistics table.
    assert "statistics_export" not in source.lower()
    assert "stats_summary" not in source.lower()



def test_legacy_ui_files_not_deleted_4a1():
    """Phase 4A.1: legacy Tkinter UI files must not be deleted."""
    ui_dir = REPO_ROOT / "worktrace" / "ui"
    assert ui_dir.exists(), "worktrace/ui must still exist (legacy pending removal)"
    # At least one legacy UI module must remain.
    py_files = list(ui_dir.glob("*.py"))
    assert len(py_files) > 0, "legacy UI .py files must not be deleted"



# --- Phase 4B ----------------------------------------------------


def test_frontend_js_statistics_export_calls_bridge_export_statistics_csv_4b():
    """Phase 4B: frontend JS must call the bridge ``export_statistics_csv``
    method to perform the CSV write. The frontend never writes a file
    itself; it only invokes the bridge."""
    source = read_all_js()
    assert 'callBridge("export_statistics_csv"' in source, (
        "frontend JS must call bridge export_statistics_csv for the CSV write"
    )



def test_frontend_js_statistics_export_saving_guard_present_4b():
    """Phase 4B: frontend JS must define a separate ``statisticsExportSaving``
    guard so the CSV write cannot be double-triggered or overlap a
    statistics load. The guard must NOT reuse ``statisticsLoading``."""
    source = read_all_js()
    assert "statisticsExportSaving" in source, (
        "frontend JS must define statisticsExportSaving guard"
    )
    # The guard variable must be declared as a separate boolean state.
    # Phase R2: state vars now live on the App. namespace.
    assert "App.statisticsExportSaving = false" in source, (
        "statisticsExportSaving must start as a separate false boolean"
    )
    # The export function must check the guard on entry.
    pos = source.find("function exportStatisticsCsv")
    assert pos != -1, "frontend JS must define exportStatisticsCsv function"
    body = source[pos:pos + 1500]
    assert "if (App.statisticsExportSaving)" in body, (
        "exportStatisticsCsv must guard against duplicate clicks"
    )
    # The statistics load path must also block while a write is in flight.
    # ``setStatisticsLoading`` must consider ``statisticsExportSaving``.
    set_load_pos = source.find("function setStatisticsLoading")
    assert set_load_pos != -1
    set_load_body = source[set_load_pos:set_load_pos + 800]
    assert "statisticsExportSaving" in set_load_body, (
        "setStatisticsLoading must disable export btn while a write is in flight"
    )



def test_frontend_js_statistics_export_uses_validate_statistics_date_range_4b():
    """Phase 4B: exportStatisticsCsv must call
    validateStatisticsDateRange before calling the bridge, so the user
    gets an immediate clear message without a bridge round-trip."""
    source = read_all_js()
    pos = source.find("function exportStatisticsCsv")
    assert pos != -1
    body = source[pos:pos + 1500]
    assert "validateStatisticsDateRange" in body, (
        "exportStatisticsCsv must call validateStatisticsDateRange"
    )



def test_frontend_js_statistics_export_catch_never_surfaces_raw_exception_4b():
    """Phase 4B: the exportStatisticsCsv promise catch must collapse to
    a stable Chinese message and never read raw exception text."""
    source = read_all_js()
    pos = source.find("function exportStatisticsCsv")
    assert pos != -1
    # The catch block is somewhere after the export function. Find the
    # next ``.catch`` after the export function start.
    catch_pos = source.find(".catch", pos)
    assert catch_pos != -1
    # The catch block extends to the next ``;`` after the closing ``}``.
    catch_body = source[catch_pos:catch_pos + 400]
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



def test_frontend_js_statistics_export_cancel_is_clean_result_4b():
    """Phase 4B: a cancelled export must be handled as a clean info
    result (``已取消导出``), not as a Python exception or ``导出失败``."""
    source = read_all_js()
    pos = source.find("function exportStatisticsCsv")
    assert pos != -1
    body = source[pos:pos + 2000]
    assert "result.cancelled" in body or "cancelled" in body, (
        "exportStatisticsCsv must handle a cancelled result explicitly"
    )
    assert "已取消导出" in body, (
        "cancel result must show the stable 已取消导出 message"
    )



def test_frontend_js_statistics_export_success_shows_filename_count_duration_4b():
    """Phase 4B: a successful export must surface the basename, activity
    count, and total duration — never the full local path."""
    source = read_all_js()
    pos = source.find("function exportStatisticsCsv")
    assert pos != -1
    body = source[pos:pos + 2000]
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



def test_frontend_js_no_export_excel_pdf_timesheet_open_folder_methods_4b():
    """Phase 4B: frontend JS must not define any export_excel / export_pdf /
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



def test_bridge_export_statistics_csv_method_present_4b():
    """Phase 4B: bridge.py must define ``export_statistics_csv`` (the
    controlled write path for the CSV export)."""
    source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
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



def test_bridge_set_window_method_present_4b():
    """Phase 4B: bridge.py must define ``set_window`` so webview_main.py
    can inject the pywebview window for the native save dialog."""
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
    pos = source.find("def set_window")
    body = source[pos:pos + 800]
    assert "webview.start()" not in body, (
        "set_window must not call webview.start()"
    )
    assert "webview.create_window(" not in body, (
        "set_window must not call webview.create_window()"
    )



def test_bridge_export_statistics_csv_returns_basename_only_4b():
    """Phase 4B: the docstring of export_statistics_csv must state that
    only the basename is returned (never the full local path)."""
    source = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    pos = source.find("def export_statistics_csv")
    body = source[pos:pos + 2500]
    assert "basename" in body.lower() or "filename" in body.lower(), (
        "export_statistics_csv docstring must document basename-only return"
    )
    # The success payload must include filename / activity_count / duration.
    assert "filename" in body
    assert "activity_count" in body
    assert "duration" in body
    # The cancel payload must include cancelled: True.
    assert "cancelled" in body



def test_webview_main_injects_window_into_bridge_4b():
    """Phase 4B: webview_main.py must call bridge.set_window(window) so
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



def test_index_html_statistics_export_status_element_present_4b():
    """Phase 4B: index.html must contain a dedicated export status
    element (``stats-export-status``) so the frontend can surface
    export progress / success / cancel / error without alert()."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="stats-export-status"' in source, (
        "index.html must define stats-export-status element"
    )



def test_styles_css_statistics_export_status_classes_4b():
    """Phase 4B: styles.css must define the export status base class and
    the info / success / error variants."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".stats-export-status" in source
    # At least the success and error variants must exist.
    assert ".stats-export-status.success" in source or ".success" in source
    assert ".stats-export-status.error" in source or ".error" in source



def test_frontend_js_statistics_export_no_local_storage_session_storage_4b():
    """Phase 4B: the export action must not use localStorage or
    sessionStorage (regression lock for the new write path)."""
    source = read_all_js()
    pos = source.find("function exportStatisticsCsv")
    assert pos != -1
    # Scan a generous body so the catch / status helpers are included.
    body = source[pos:pos + 2500]
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in body, (
            "exportStatisticsCsv must not use " + forbidden
        )



def test_index_html_statistics_export_no_external_links_4b():
    """Phase 4B: the statistics export section must not reference any
    external link / CDN / Google Fonts (regression lock)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-statistics"')
    assert pos != -1
    end = source.find("</section>", pos)
    section = source[pos:end] if end != -1 else source[pos:pos + 4000]
    assert not re.search(r"https?://", section), (
        "statistics section must not reference external links"
    )
    assert not re.search(r"cdn", section, re.IGNORECASE), (
        "statistics section must not reference CDN"
    )
    assert not re.search(r"google\s*fonts", section, re.IGNORECASE), (
        "statistics section must not reference Google Fonts"
    )



# --- Phase R2.1: wording regression lock --------------------------------
# Phase R2 split the monolithic app.js into js/ modules. This tiny test
# prevents the old monolithic-file "must" phrasing from creeping back
# into this file's docstrings / assertion messages and misleading readers.


def test_no_stale_app_js_must_wording_in_this_file_r21():
    """Phase R2.1: this statistics contract file must no longer phrase
    requirements as ``app.js`` followed by ``must`` (the monolithic file
    was split into js/ modules in Phase R2). Use ``frontend JS must``
    instead. The only allowed ``app.js`` mentions are the historical
    ``monolithic app.js`` references explaining the Phase R2 split."""
    own_source = open(__file__, encoding="utf-8").read()
    stale = "app.js" + " must"
    assert stale not in own_source, (
        "statistics contract must not revive stale monolithic-file wording; "
        "use 'frontend JS must' instead"
    )


# --- Phase 4B.1: independent state variable hardening ------------------
# The statistics load and the CSV export must use SEPARATE state variables
# (``statisticsLoading`` vs ``statisticsExportSaving``) and each must
# cross-disable the other's button so a load and a write can never overlap.


def test_frontend_js_statistics_load_and_export_use_independent_state_4b1():
    """Phase 4B.1: ``statisticsLoading`` and ``statisticsExportSaving`` must
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
    export_pos = source.find("function exportStatisticsCsv")
    assert export_pos != -1
    export_body = source[export_pos:export_pos + 400]
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
    load_pos = source.find("function loadStatisticsExportSummary")
    assert load_pos != -1
    load_body = source[load_pos:load_pos + 400]
    assert "if (App.statisticsLoading)" in load_body, (
        "loadStatisticsExportSummary must guard via statisticsLoading"
    )


def test_frontend_js_statistics_export_disables_both_buttons_4b1():
    """Phase 4B.1: ``setStatisticsExportSaving`` must disable BOTH the
    export button and the statistics load button while a write is in
    flight, so the user cannot trigger a concurrent load."""
    source = read_js("statistics.js")
    pos = source.find("function setStatisticsExportSaving")
    assert pos != -1
    body = source[pos:pos + 800]
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


def test_frontend_js_statistics_load_disables_export_button_4b1():
    """Phase 4B.1: ``setStatisticsLoading`` must disable the export button
    while statistics are loading, so a write cannot be triggered mid-load."""
    source = read_js("statistics.js")
    pos = source.find("function setStatisticsLoading")
    assert pos != -1
    body = source[pos:pos + 800]
    assert "stats-export-action-btn" in body, (
        "setStatisticsLoading must disable the export button while loading"
    )
    assert "App.statisticsExportSaving" in body, (
        "the export button disabled state must consider statisticsExportSaving"
    )
