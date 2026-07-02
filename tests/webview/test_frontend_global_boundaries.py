"""Global WebView frontend resource boundary tests.

These tests read the bundled frontend resources (``index.html`` /
``js/*.js`` / ``styles.css``) directly without starting the GUI. The
JS-level contracts use ``read_all_js()`` (concatenated modules in load
order). They cover:

- Resource existence (index.html / js/*.js / styles.css / bridge.py).
- Global static boundaries (no external links / CDN / Google Fonts /
  localStorage / traceback text), expressed as parametrized tests over
  every frontend resource.
- index.html structural anchors (local resource refs, Chinese sidebar nav,
  no migration copy).
- Overview page production contract (KPIs, current/recent sections, error
  banner, pause toggle, classified/uncategorized durations, surfaces bridge
  errors, does not expose tracebacks).
- Startup module contracts (main entry exists, resource_path resolves,
  pywebview missing gives a clear Chinese error).
- Documentation regression locks for WebView history and release validation.
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
    REPO_ROOT, WEBVIEW_UI_DIR, JS_DIR, HISTORY_PATH,
    RELEASE_VALIDATION_PATH, README_PATH,
    read_resource, read_all_js, read_js, func_body,
    FRONTEND_RESOURCE_FILES, NO_STORAGE_FILES,
    ALL_JS_FILES,
)


# --- existence tests -----------------------------------------------------


def test_index_html_exists():
    assert (WEBVIEW_UI_DIR / "index.html").is_file()


def test_frontend_js_exists():
    """Frontend JavaScript is bundled from ordered js/ modules."""
    assert not (WEBVIEW_UI_DIR / "app.js").is_file(), (
        "frontend JS must be removed after frontend module split"
    )
    assert JS_DIR.is_dir(), "js/ directory must exist after frontend module split"
    for name in ALL_JS_FILES:
        assert (JS_DIR / name).is_file(), (
            "js/" + name + " must exist after frontend module split"
        )


def test_styles_css_exists():
    assert (WEBVIEW_UI_DIR / "styles.css").is_file()


def test_bridge_py_exists():
    assert (WEBVIEW_UI_DIR / "bridge.py").is_file()


# --- global boundary tests (parametrized) --------------------------------
# These parametrized tests cover every frontend resource file for every
# prohibited pattern.


@pytest.mark.parametrize("filename", FRONTEND_RESOURCE_FILES)
def test_frontend_resource_has_no_external_links(filename):
    source = read_resource(filename)
    assert not re.search(r"https?://", source, re.IGNORECASE), (
        f"{filename} must not contain http:// or https:// links"
    )


@pytest.mark.parametrize("filename", FRONTEND_RESOURCE_FILES)
def test_frontend_resource_has_no_cdn(filename):
    source = read_resource(filename)
    assert not re.search(r"cdn", source, re.IGNORECASE), (
        f"{filename} must not reference CDN"
    )


@pytest.mark.parametrize("filename", FRONTEND_RESOURCE_FILES)
def test_frontend_resource_has_no_google_fonts(filename):
    source = read_resource(filename)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE), (
        f"{filename} must not reference Google Fonts"
    )


@pytest.mark.parametrize("filename", NO_STORAGE_FILES)
def test_frontend_resource_has_no_local_storage(filename):
    source = read_resource(filename)
    assert not re.search(r"localStorage|sessionStorage", source), (
        f"{filename} must not use localStorage or sessionStorage"
    )


@pytest.mark.parametrize("filename", FRONTEND_RESOURCE_FILES)
def test_frontend_resource_has_no_traceback_text(filename):
    """The frontend must not embed traceback text. The bridge returns only
    a generic error string; the UI must never parse or display Python
    tracebacks."""
    source = read_resource(filename)
    assert "traceback" not in source.lower(), (
        f"{filename} must not contain traceback text"
    )


# --- index.html structural anchors ---------------------------------------


def test_index_html_references_local_resources():
    source = read_resource("index.html")
    assert 'href="styles.css"' in source
    # index.html must load the six js/ modules in order and
    # must no longer reference the removed monolithic frontend bundle.
    assert 'src="app.js"' not in source, (
        "index.html must not reference removed monolithic frontend bundle"
    )
    for name in ALL_JS_FILES:
        assert 'src="js/' + name + '"' in source, (
            "index.html must load js/" + name
        )


def test_index_html_has_chinese_text():
    source = read_resource("index.html")
    assert "概览" in source


def test_index_html_has_sidebar_nav():
    source = read_resource("index.html")
    for label in ["概览", "时间详情", "统计与导出", "项目规则", "设置与隐私"]:
        assert label in source


def test_index_html_has_no_migration_placeholder():
    """every sidebar page is a concrete WebView page.

    The removed "WebView 迁移中" placeholder copy must not appear anywhere in
    index.html.
    """
    source = read_resource("index.html")
    assert "WebView 迁移中" not in source


# --- Overview page production contract -----------------------------------


def test_index_html_overview_page_has_required_kpis():
    """the Overview page must show the production KPI set, not a
    placeholder. Required KPIs: date, total duration, project count,
    classified duration, uncategorized duration."""
    source = read_resource("index.html")
    assert 'id="kpi-date"' in source
    assert 'id="kpi-total"' in source
    assert 'id="kpi-projects"' in source
    assert 'id="kpi-classified"' in source
    assert 'id="kpi-uncategorized"' in source


def test_index_html_overview_page_has_current_and_recent_sections():
    """the Overview page must have a current-activity section and a
    recent-activities list."""
    source = read_resource("index.html")
    assert 'id="current-activity"' in source
    assert 'id="recent-list"' in source


def test_index_html_overview_page_has_error_banner():
    """the Overview page must have an in-page error banner so
    bridge errors are surfaced to the user without exposing tracebacks."""
    source = read_resource("index.html")
    assert 'id="overview-error"' in source


def test_index_html_overview_page_has_pause_toggle():
    """the Overview page must support pause/resume through the
    sidebar toggle button."""
    source = read_resource("index.html")
    assert 'id="toggle-pause-btn"' in source
    assert 'id="status-display"' in source


def test_frontend_js_displays_classified_and_uncategorized_durations():
    """the frontend must render classified_duration and
    uncategorized_duration returned by the bridge, not just total
    duration. (Contract checked across all js/ modules.)"""
    source = read_all_js()
    assert "kpi-classified" in source
    assert "kpi-uncategorized" in source
    assert "classified_duration" in source
    assert "uncategorized_duration" in source


def test_frontend_js_surfaces_bridge_errors_in_page():
    """the frontend must show bridge errors in the in-page error
    banner instead of silently swallowing them. (Contract checked
    across all js/ modules.)"""
    source = read_all_js()
    assert "overview-error" in source
    assert "showError" in source
    assert "clearError" in source


def test_frontend_js_does_not_expose_tracebacks():
    """The frontend must not attempt to parse or display Python tracebacks.
    It only shows the generic error string returned by the bridge.
    (Contract checked across all js/ modules.)"""
    source = read_all_js()
    assert "traceback" not in source.lower()


# --- startup tests -------------------------------------------------------


def test_import_webview_main_does_not_start_gui():
    """Importing the module must not start the GUI or block."""
    import importlib

    mod = importlib.import_module("worktrace.webview_main")
    assert hasattr(mod, "main")
    assert callable(mod.main)


def test_webview_main_main_exists():
    import worktrace.webview_main as mod

    assert callable(getattr(mod, "main", None))


def test_webview_main_resource_path_resolves():
    import worktrace.webview_main as mod

    path = mod.resource_path("index.html")
    assert path.name == "index.html"
    assert path.exists()


def test_webview_main_check_pywebview_missing_gives_clear_error(monkeypatch):
    """When pywebview is not installed, the error message must be clear."""
    import worktrace.webview_main as mod

    # Simulate pywebview not being installed.
    monkeypatch.setitem(sys.modules, "webview", None)
    with pytest.raises(RuntimeError) as exc_info:
        mod._check_pywebview_available()
    msg = str(exc_info.value)
    assert "pywebview" in msg
    assert "未安装" in msg


# --- doc-mention regression locks ----------------------------------------
# Documentation resources are allowed to preserve historical records, but
# frontend boundary tests should only lock current documentation surfaces.


def test_docs_history_and_release_validation_files_exist():
    assert HISTORY_PATH.is_file()
    assert RELEASE_VALIDATION_PATH.is_file()


def test_release_validation_mentions_current_webview_surface():
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "WebView" in source
    assert "release" in source.lower()

def test_frontend_module_js_directory_exists():
    """the js/ subdirectory must exist under webview_ui/."""
    assert JS_DIR.is_dir(), (
        "worktrace/webview_ui/js/ directory must exist after frontend module split"
    )


def test_frontend_module_each_js_file_declares_worktrace_namespace():
    """every js/ module must declare the shared namespace via
    ``var App = window.WorkTraceApp = window.WorkTraceApp || {};`` so all
    modules share the same namespace object."""
    for name in ALL_JS_FILES:
        source = read_js(name)
        assert "var App = window.WorkTraceApp = window.WorkTraceApp || {};" in source, (
            "js/" + name + " must declare the WorkTraceApp namespace"
        )


def test_frontend_module_each_js_file_is_iife():
    """every js/ module must be wrapped in an IIFE to avoid
    leaking locals into the global scope (matching the monolithic frontend bundle
    structure). A short leading comment header (module name / purpose)
    is permitted before the IIFE opening."""
    for name in ALL_JS_FILES:
        source = read_js(name).strip()
        # The IIFE opening must appear near the top (after optional
        # comment lines that document the module).
        assert "(function () {" in source[:400], (
            "js/" + name + " must open with an IIFE near the top"
        )
        assert source.rstrip().endswith("})();"), (
            "js/" + name + " must close with })();"
        )


def test_frontend_module_index_html_loads_js_files_in_correct_order():
    """index.html must load the six js/ modules in the exact
    dependency order (core → overview → timeline → timeline_correction →
    statistics → init). A wrong order would cause ReferenceError at load
    time because a module might call App.foo() before core.js defines it."""
    source = read_resource("index.html")
    positions = []
    for name in ALL_JS_FILES:
        tag = 'src="js/' + name + '"'
        pos = source.find(tag)
        assert pos != -1, (
            "index.html must contain script tag for js/" + name
        )
        positions.append(pos)
    for i in range(len(positions) - 1):
        assert positions[i] < positions[i + 1], (
            "index.html must load js/" + ALL_JS_FILES[i]
            + " before js/" + ALL_JS_FILES[i + 1]
        )


def test_frontend_module_no_es_module_syntax_in_js_files():
    """the js/ modules must NOT use ES module syntax (import /
    export). The project loads scripts via plain <script> tags, so ES
    modules would break the load chain.

    The patterns are scoped to actual ES module statement syntax so
    legitimate identifiers like ``exportStatisticsCsv`` and comment
    phrases like ``// CSV export`` do not produce false positives."""
    forbidden_patterns = [
        # import declarations: import x from "..."; import { x } from "..."
        r'\bimport\s+[\w{}\s,]+\s+from\s',
        r'\bimport\s*\{',
        r'\bimport\s+["\']',
        # export declarations: export default ...; export { ... };
        # export const/let/var/function ...
        r'\bexport\s+default\b',
        r'\bexport\s*\{',
        r'\bexport\s+(?:const|let|var|function)\s+\w+',
        # CommonJS require()
        r'\brequire\s*\(',
    ]
    for name in ALL_JS_FILES:
        source = read_js(name)
        for pattern in forbidden_patterns:
            assert not re.search(pattern, source), (
                "js/" + name + " must not use ES module syntax: " + pattern
            )


def test_frontend_module_domcontentloaded_wiring_only_in_init_js():
    """the DOMContentLoaded wiring (the only top-level code
    that runs at module-load time) must exist ONLY in init.js — the last
    module loaded. Other modules must not auto-execute any code."""
    for name in ALL_JS_FILES:
        source = read_js(name)
        if name == "init.js":
            assert "DOMContentLoaded" in source, (
                "init.js must contain the DOMContentLoaded wiring"
            )
        else:
            assert "DOMContentLoaded" not in source, (
                "js/" + name + " must not contain DOMContentLoaded wiring "
                "(only init.js should auto-execute at load time)"
            )


def test_frontend_module_worktrace_spec_bundles_js_modules():
    """the PyInstaller spec must list every js/ module in datas
    so the packaged exe includes the split frontend resources."""
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    for name in ALL_JS_FILES:
        assert ("js" in spec and name in spec), (
            "WorkTrace.spec must bundle js/" + name + " in datas"
        )
    # the removed bundle reference must be gone.
    assert "app.js" not in spec, (
        "WorkTrace.spec must no longer reference the removed monolithic frontend bundle"
    )


def test_frontend_module_no_app_js_references_remain_in_js_files():
    """no js/ module must reference the removed monolithic frontend bundle file
    (e.g., via a script load or string literal)."""
    source = read_all_js()
    assert "app.js" not in source, (
        "js/ modules must not reference the removed monolithic frontend bundle"
    )


# --- CRITICAL behavior-preservation guards --------------------


def test_frontend_module_all_functions_still_defined():
    """CRITICAL guard: every function that existed in the
    frontend JS must still be defined across the ordered js/ modules.
    A missing function would cause a ReferenceError at runtime when the
    UI tries to call it — and no other test would catch this except a
    full runtime integration test. This static guard lists the critical
    entry points and lifecycle hooks from each module."""
    source = read_all_js()
    required_functions = [
        # core.js — bridge + state helpers + utilities
        "callBridge", "showError", "clearError", "showTimelineError",
        "clearTimelineError", "setTimelineLoading", "statusClassFor",
        "applyStatusType", "setTimelineStatus", "setDetailStatus",
        "setEditStatus", "setCorrectionStatus", "handleResult", "showStatus",
        "safeText", "escapeHtml", "formatTimeRange", "shiftDate",
        "localTodayStr", "formatDuration", "backendToDatetimeLocal",
        "datetimeLocalToBackend", "midpointTime", "parseBackendTimeParts",
        "formatUtcParts",
        # overview.js
        "showOverview", "showRecent",
        # timeline.js — main flow + editing
        "showTimeline", "selectTimelineSession", "loadSessionDetails",
        "renderSessionDetails", "loadTimeline", "refreshTimeline",
        "goPrevDay", "goNextDay", "goToday", "loadProjects",
        "populateEditPanel", "clearEditPanel", "isEditDirty", "saveEdit",
        "cancelEdit", "updateNoteCount", "showEditStatus", "setEditSaving",
        "saveActivityTime", "saveActivitySplit", "saveActivityMerge",
        "saveActivityHide", "saveActivityDelete",
        "saveSessionTime", "saveSessionSplit", "saveSessionHide",
        "saveSessionDelete", "refreshTimelineAfterEdit",
        # timeline_correction.js — correction shell + batch + restore
        "getSelectedSession", "getCurrentDetailActivities",
        "isAnyCorrectionWriteSaving", "renderCorrectionShell",
        "openCorrectionShell", "closeCorrectionShell",
        "saveBatchProject", "saveBatchNote", "saveActivityRestore",
        "resetCorrectionShellState", "highlightDetailRow",
        "resetBatchProjectState", "resetBatchNoteState", "resetRestoreState",
        "bindBatchProjectControls", "bindBatchNoteControls", "bindRestoreControls",
        # statistics.js
        "loadStatisticsExportSummary", "showStatistics", "renderStatsTable",
        "validateStatisticsDateRange", "applyStatisticsQuickRange",
        "initStatisticsDefaults", "exportStatisticsCsv",
        # init.js — refresh + nav + bootstrap
        "refreshAll", "togglePause", "switchPage", "initNav", "initButtons",
        "startHeartbeat", "init",
    ]
    missing = []
    for name in required_functions:
        if source.find("function " + name + "(") == -1:
            missing.append(name)
    assert not missing, (
        "frontend module split is missing function definitions: "
        + ", ".join(missing)
        + ". These would cause ReferenceError at runtime."
    )
    # Also verify the total function count is in the expected range.
    # The original monolithic frontend bundle had 147 function declarations. After the split,
    # we expect at least 140 top-level function declarations (some may be
    # counted as nested). This guards against accidental drops.
    all_decls = re.findall(r'\n    function \w+\s*\(', source)
    assert len(all_decls) >= 140, (
        "Expected at least 140 function declarations across js/ modules, "
        "found " + str(len(all_decls))
    )


def test_frontend_module_state_variables_only_accessed_via_app_namespace():
    """CRITICAL guard: every state variable declared via
    ``App.<name>`` in core.js must be accessed ONLY via the App.
    namespace in all js/ modules. A bare reference (e.g.
    ``timelineDate = shiftDate(...)`` without ``App.``) would be a
    runtime ReferenceError because the variable is not declared with
    ``var`` in any module's IIFE scope.

    This test strips line comments to avoid false positives from
    comments that mention state variable names, then searches for
    bare (non-dot-prefixed) references."""
    source = read_all_js()
    # Strip // line comments to avoid false positives.
    cleaned_lines = []
    for line in source.split("\n"):
        idx = line.find("//")
        if idx != -1:
            line = line[:idx]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    # State variable names declared in core.js via App.<name> = ...
    # These are the module-level state variables that must NEVER be
    # accessed without the App. prefix.
    state_vars = [
        "timelineDate", "timelineLoaded", "timelineLoading",
        "selectedSessionId", "timelineRequestToken", "detailsRequestToken",
        "projectsCache", "projectsLoading", "currentSessions",
        "editingSession", "editSaving",
        "timeSaving", "editingActivityId", "activityTimeSaving",
        "sessionSplitSaving", "editingSplitActivityId", "activitySplitSaving",
        "mergeSaving", "mergingActivityId",
        "hideSaving", "hidingActivityId", "deleteSaving", "deletingActivityId",
        "correctionShellOpen", "correctionShellSessionId",
        "correctionShellActivityId", "correctionShellMode",
        "correctionShellHighlightTimer",
        "selectedBatchActivityIds", "batchProjectSaving",
        "batchProjectTargetId", "batchNoteSaving",
        "restoreSaving", "restoreSavingActivityId",
        "statisticsLoaded", "statisticsLoading",
        "statisticsRequestToken", "statisticsExportSaving",
        "lastTimelineData",
    ]
    errors = []
    for varname in state_vars:
        # Match VARNAME not preceded by a word char or dot, and not
        # followed by a word char. This catches bare references like
        # `timelineDate = ...` or `if (timelineDate)` while skipping
        # `App.timelineDate` (preceded by dot).
        pattern = re.compile(
            r'(?<![\w.])' + re.escape(varname) + r'(?!\w)'
        )
        matches = pattern.findall(cleaned)
        if matches:
            errors.append(
                varname + " (" + str(len(matches)) + " bare reference(s))"
            )
    assert not errors, (
        "State variables accessed without App. prefix (would cause "
        "ReferenceError at runtime): " + "; ".join(errors)
    )


# --- init.js does not start refresh before notice loaded -----


def test_init_js_does_not_start_refresh_before_notice_loaded() -> None:
    """in ``init()``, the call to ``App.loadFirstRunNotice()``
    must appear before the main UI refresh / heartbeat-start calls in
    source order, AND those calls must be inside a ``.then(...)``
    callback (or after an ``await``), not at the top level of ``init``.
    This eliminates the frontend race where refresh could fire before
    the gate overlay was up.

    The unified heartbeat rewrite: the ``refreshAll()`` /
    ``startAutoRefresh()`` / ``startLocalTicker()`` calls were replaced
    by ``refreshCurrentPageData()`` + ``startHeartbeat()``; this test
    verifies the new contract."""
    source = read_js("init.js")
    # Match ``function init()`` exactly so we do not collide with
    # ``function initNav`` or ``function initButtons``.
    pos = source.find("function init()")
    assert pos != -1, "init.js must define function init()"
    # Slice to the next sibling function so we capture the whole init()
    # body.
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 2500]
    load_pos = body.find("App.loadFirstRunNotice()")
    refresh_pos = body.find("refreshCurrentPageData()")
    heartbeat_pos = body.find("startHeartbeat()")
    assert load_pos != -1, "init() must call App.loadFirstRunNotice()"
    assert refresh_pos != -1, "init() must call refreshCurrentPageData()"
    assert heartbeat_pos != -1, "init() must call startHeartbeat()"
    # loadFirstRunNotice must appear before refresh / heartbeat in
    # source order within init.
    assert load_pos < refresh_pos, (
        "init() must call loadFirstRunNotice before refreshCurrentPageData"
    )
    assert load_pos < heartbeat_pos, (
        "init() must call loadFirstRunNotice before startHeartbeat"
    )
    # The refresh calls must be inside a .then(...) callback on the
    # loadFirstRunNotice promise, not at the top level of init.
    between = body[load_pos:refresh_pos]
    assert ".then(function" in between, (
        "init() must call refreshCurrentPageData / startHeartbeat inside a "
        ".then(...) callback on the loadFirstRunNotice promise, not at "
        "the top level of init"
    )


# --- local ticker (1-second DOM-only refresh) ----------------


def test_core_js_does_not_define_removed_ticker_interval() -> None:
    """Static boundary test: core.js must NOT define the removed
    ``LOCAL_TICKER_INTERVAL_MS`` / ``REFRESH_INTERVAL_MS`` constants.
    The unified heartbeat (``App.HEARTBEAT_INTERVAL_MS = 1000``) owns
    the single 1-second timer; the parallel-timer constants have
    been removed entirely and must not regress."""
    source = read_js("core.js")
    assert "App.LOCAL_TICKER_INTERVAL_MS" not in source, (
        "core.js must not define the removed App.LOCAL_TICKER_INTERVAL_MS "
        "constant; the unified heartbeat owns the single timer"
    )
    assert "App.REFRESH_INTERVAL_MS" not in source, (
        "core.js must not define the removed App.REFRESH_INTERVAL_MS "
        "constant; the unified heartbeat owns the single timer"
    )


def test_core_js_defines_apply_local_ticker_function() -> None:
    """core.js must define the ``applyLocalTicker`` function
    and expose it on the App namespace so the timer in init.js can
    invoke it once per second."""
    source = read_js("core.js")
    assert "function applyLocalTicker" in source, (
        "core.js must define function applyLocalTicker for live startup contract"
    )
    assert "App.applyLocalTicker" in source, (
        "core.js must expose App.applyLocalTicker for live startup contract"
    )


def test_core_js_ticker_does_not_call_bridge_methods() -> None:
    """the ``applyLocalTicker`` function body must NOT contain
    ``callBridge`` or ``App.callBridge``. The ticker is cosmetic: it only
    updates DOM text with a locally-computed elapsed increment. It must
    never trigger a backend round-trip, never write the database, and
    never start / stop the collector."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1, "core.js must define function applyLocalTicker"
    # Slice to the next sibling function declaration or the IIFE close,
    # whichever comes first (matching the func_body pattern).
    end_func = source.find("\n    function ", pos + 1)
    end_iife = source.find("\n})();", pos + 1)
    candidates = [e for e in (end_func, end_iife) if e != -1]
    end = min(candidates) if candidates else -1
    body = source[pos:end] if end != -1 else source[pos:]
    assert "callBridge" not in body, (
        "applyLocalTicker must not call callBridge; the ticker only "
        "updates DOM text and must never trigger a backend round-trip"
    )
    assert "App.callBridge" not in body, (
        "applyLocalTicker must not call App.callBridge; the ticker only "
        "updates DOM text and must never trigger a backend round-trip"
    )


def test_core_js_ticker_uses_raw_seconds_not_string_parsing() -> None:
    """The ticker must use numeric ``classified_seconds`` /
    ``uncategorized_seconds`` baseline fields. It must NOT parse
    ``classified_duration`` / ``uncategorized_duration`` HH:MM:SS strings
    to compute the ticker delta."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1, "core.js must define function applyLocalTicker"
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    # Must use the raw numeric fields.
    assert "classified_seconds" in body, (
        "applyLocalTicker must read classified_seconds (numeric baseline)"
    )
    assert "uncategorized_seconds" in body, (
        "applyLocalTicker must read uncategorized_seconds (numeric baseline)"
    )
    # Must NOT parse the string duration fields to compute the ticker.
    assert "classified_duration" not in body, (
        "applyLocalTicker must NOT parse classified_duration strings"
    )
    assert "uncategorized_duration" not in body, (
        "applyLocalTicker must NOT parse uncategorized_duration strings"
    )


def test_core_js_ticker_updates_classified_and_uncategorized_kpis() -> None:
    """The ticker must update kpi-classified and kpi-uncategorized DOM
    elements along with kpi-total, so all three KPIs stay on the same
   口径 (same basis)."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1, "core.js must define function applyLocalTicker"
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    assert "kpi-classified" in body, (
        "applyLocalTicker must update kpi-classified DOM element"
    )
    assert "kpi-uncategorized" in body, (
        "applyLocalTicker must update kpi-uncategorized DOM element"
    )
    assert "kpi-total" in body, (
        "applyLocalTicker must update kpi-total DOM element"
    )


def test_core_js_ticker_uses_is_classified_is_uncategorized_flags() -> None:
    """The ticker must use ``is_classified`` / ``is_uncategorized`` flags
    from ``current_activity`` to decide which KPI gets the delta. Only
    one of the two may be incremented (never both)."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1, "core.js must define function applyLocalTicker"
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    assert "is_classified" in body, (
        "applyLocalTicker must check current.is_classified to decide "
        "whether to increment kpi-classified"
    )
    assert "is_uncategorized" in body, (
        "applyLocalTicker must check current.is_uncategorized to decide "
        "whether to increment kpi-uncategorized"
    )
