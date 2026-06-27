"""Global WebView frontend resource boundary tests.

These tests read the bundled frontend resources (``index.html`` / ``app.js`` /
``styles.css``) directly without starting the GUI. They cover:

- Resource existence (index.html / app.js / styles.css / bridge.py).
- Global static boundaries (no external links / CDN / Google Fonts /
  localStorage / traceback text), expressed as parametrized tests that
  replace the per-phase duplicate checks scattered across the original
  monolithic file.
- index.html structural anchors (local resource refs, Chinese sidebar nav,
  unmigrated-page placeholder).
- Overview page production contract (KPIs, current/recent sections, error
  banner, pause toggle, classified/uncategorized durations, surfaces bridge
  errors, does not expose tracebacks).
- Startup module contracts (main entry exists, resource_path resolves,
  pywebview missing gives a clear Chinese error).
- Consolidated doc-mention regression locks for the WebView phase history.
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


def test_app_js_exists():
    """Phase R2: the monolithic app.js has been split into six js/ modules.
    The old app.js must no longer exist; each js/ module must exist."""
    assert not (WEBVIEW_UI_DIR / "app.js").is_file(), (
        "app.js must be removed after Phase R2 split"
    )
    assert JS_DIR.is_dir(), "js/ directory must exist after Phase R2 split"
    for name in ALL_JS_FILES:
        assert (JS_DIR / name).is_file(), (
            "js/" + name + " must exist after Phase R2 split"
        )


def test_styles_css_exists():
    assert (WEBVIEW_UI_DIR / "styles.css").is_file()


def test_bridge_py_exists():
    assert (WEBVIEW_UI_DIR / "bridge.py").is_file()


# --- global boundary tests (parametrized) --------------------------------
# These five parametrized tests replace the dozens of per-phase
# ``test_frontend_resources_*_still_no_external_links`` /
# ``*_no_browser_storage`` / ``*_no_traceback_display`` duplicates that
# existed in the original monolithic file. They cover every frontend
# resource file for every prohibited pattern.


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
    # Phase R2: index.html must load the six js/ modules in order and
    # must no longer reference the removed app.js.
    assert 'src="app.js"' not in source, (
        "index.html must not reference removed app.js"
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


def test_index_html_has_placeholder_for_unmigrated_pages():
    source = read_resource("index.html")
    assert "WebView 迁移中" in source


# --- Overview page production contract -----------------------------------


def test_index_html_overview_page_has_required_kpis():
    """Phase 1: the Overview page must show the production KPI set, not a
    spike placeholder. Required KPIs: date, total duration, project count,
    classified duration, uncategorized duration."""
    source = read_resource("index.html")
    assert 'id="kpi-date"' in source
    assert 'id="kpi-total"' in source
    assert 'id="kpi-projects"' in source
    assert 'id="kpi-classified"' in source
    assert 'id="kpi-uncategorized"' in source


def test_index_html_overview_page_has_current_and_recent_sections():
    """Phase 1: the Overview page must have a current-activity section and a
    recent-activities list."""
    source = read_resource("index.html")
    assert 'id="current-activity"' in source
    assert 'id="recent-list"' in source


def test_index_html_overview_page_has_error_banner():
    """Phase 1: the Overview page must have an in-page error banner so
    bridge errors are surfaced to the user without exposing tracebacks."""
    source = read_resource("index.html")
    assert 'id="overview-error"' in source


def test_index_html_overview_page_has_pause_toggle():
    """Phase 1: the Overview page must support pause/resume through the
    sidebar toggle button."""
    source = read_resource("index.html")
    assert 'id="toggle-pause-btn"' in source
    assert 'id="status-display"' in source


def test_app_js_displays_classified_and_uncategorized_durations():
    """Phase 1: the frontend must render classified_duration and
    uncategorized_duration returned by the bridge, not just total
    duration. (Phase R2: contract now checked across all js/ modules.)"""
    source = read_all_js()
    assert "kpi-classified" in source
    assert "kpi-uncategorized" in source
    assert "classified_duration" in source
    assert "uncategorized_duration" in source


def test_app_js_surfaces_bridge_errors_in_page():
    """Phase 1: the frontend must show bridge errors in the in-page error
    banner instead of silently swallowing them. (Phase R2: contract now
    checked across all js/ modules.)"""
    source = read_all_js()
    assert "overview-error" in source
    assert "showError" in source
    assert "clearError" in source


def test_app_js_does_not_expose_tracebacks():
    """The frontend must not attempt to parse or display Python tracebacks.
    It only shows the generic error string returned by the bridge.
    (Phase R2: contract now checked across all js/ modules.)"""
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
# Each phase below is locked in docs/history/webview-phases.md (the
# verbatim phase history) and docs/release-validation.md. The original
# per-phase ``test_docs_mention_phase_X`` / ``test_docs_readme_mentions_phase_X``
# pairs read ui-webview-migration.md and README.md respectively; both have
# been repointed to the single history file because the README / migration
# doc were slimmed down and their phase history moved verbatim into
# docs/history/webview-phases.md. The README tests' assertions were strict
# subsets of the migration tests' assertions after repointing, so each pair
# has been merged into a single per-phase test that preserves every
# assertion's coverage semantics.
# release-validation.md reads are unchanged.


def test_docs_history_mention_phase_3b_5a():
    """Phase 3B.5A: the history doc and release-validation doc must
    mention Phase 3B.5A and restate that batch edit / restore / permanent
    delete / complex correction page are not implemented."""
    history = HISTORY_PATH.read_text(encoding="utf-8")
    assert "3B.5A" in history, (
        "docs/history/webview-phases.md must mention Phase 3B.5A"
    )
    assert "consolidation" in history.lower(), (
        "docs/history/webview-phases.md must describe 3B.5A as a "
        "consolidation phase"
    )
    for term in ("batch", "restore", "permanent delete", "complex correction"):
        assert term.lower() in history.lower(), (
            f"docs/history/webview-phases.md must restate that {term} is "
            "not implemented"
        )
    release_val = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "3B.5A" in release_val, (
        "release-validation.md must mention Phase 3B.5A"
    )


def test_docs_history_mention_phase_3b_5b():
    """Phase 3B.5B: the history doc and release-validation doc must
    mention Phase 3B.5B and restate that batch edit / restore / permanent
    delete / auto-rule / overlap detection are not implemented."""
    history = HISTORY_PATH.read_text(encoding="utf-8")
    assert "3B.5B" in history, (
        "docs/history/webview-phases.md must mention Phase 3B.5B"
    )
    assert "correction shell" in history.lower() or "高级纠错" in history, (
        "docs/history/webview-phases.md must describe 3B.5B as a "
        "correction shell phase"
    )
    for term in ("batch", "restore", "permanent delete", "auto-rule",
                 "overlap"):
        assert term.lower() in history.lower(), (
            "docs/history/webview-phases.md must restate that " + term
            + " is not implemented"
        )
    release_val = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "3B.5B" in release_val, (
        "release-validation.md must mention Phase 3B.5B"
    )


def test_docs_history_mention_phase_3b_5b_1():
    """Phase 3B.5B.1: the history doc, release-validation doc, and (via the
    history verbatim copy) README must mention Phase 3B.5B.1 as the
    correction shell hardening phase and restate that no new backend /
    DB / bridge capability and no batch editing were added."""
    history = HISTORY_PATH.read_text(encoding="utf-8")
    release_val = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    for doc, name in ((history, "docs/history/webview-phases.md"),
                      (release_val, "release-validation.md")):
        assert "3B.5B.1" in doc, name + " must mention Phase 3B.5B.1"
        assert "hardening" in doc.lower() or "硬化" in doc, (
            name + " must describe 3B.5B.1 as a hardening phase"
        )
    # The history doc must restate the hardening points and the
    # not-implemented list.
    assert "correction shell" in history.lower() or "高级纠错" in history
    for term in ("batch", "restore", "permanent delete", "auto-rule",
                 "overlap"):
        assert term.lower() in history.lower(), (
            "docs/history/webview-phases.md must restate that " + term
            + " is not implemented"
        )


def test_docs_history_mention_phase_3b_9():
    """Phase 3B.9: the history doc must mention Phase 3B.9."""
    source = HISTORY_PATH.read_text(encoding="utf-8")
    assert "3B.9" in source, (
        "docs/history/webview-phases.md must mention Phase 3B.9"
    )
    assert "consolidation" in source.lower() or "整理" in source, (
        "docs/history/webview-phases.md must describe 3B.9 as consolidation"
    )


def test_docs_release_validation_mentions_phase_3b_9():
    """Phase 3B.9: release-validation must mention Phase 3B.9."""
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "3B.9" in source, (
        "release-validation.md must mention Phase 3B.9"
    )


def test_docs_history_mention_phase_3b9_1():
    """Phase 3B.9.1: the history doc must mention Phase 3B.9.1."""
    source = HISTORY_PATH.read_text(encoding="utf-8")
    assert "3B.9.1" in source, (
        "docs/history/webview-phases.md must mention Phase 3B.9.1"
    )


def test_docs_release_validation_mentions_phase_3b9_1():
    """Phase 3B.9.1: release-validation must mention Phase 3B.9.1."""
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "3B.9.1" in source, (
        "release-validation.md must mention Phase 3B.9.1"
    )


def test_docs_history_mention_phase_3c():
    """Phase 3C: the history doc must mention Phase 3C."""
    source = HISTORY_PATH.read_text(encoding="utf-8")
    assert "3C" in source, (
        "docs/history/webview-phases.md must mention Phase 3C"
    )
    assert "Phase 3C Implemented Scope" in source, (
        "docs/history/webview-phases.md must have a Phase 3C Implemented "
        "Scope section"
    )


def test_docs_release_validation_mentions_phase_3c():
    """Phase 3C: release-validation must mention Phase 3C."""
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "3C" in source, (
        "release-validation.md must mention Phase 3C"
    )
    assert "WebView Phase 3C Validation" in source, (
        "release-validation.md must have a WebView Phase 3C Validation section"
    )


def test_docs_release_validation_phase_3c_release_blockers_3c():
    """Phase 3C: release-validation must list the Phase 3C release
    blockers."""
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "Phase 3C Release Blockers" in source, (
        "release-validation.md must have a Phase 3C Release Blockers section"
    )
    for blocker in ("new backend write capability",
                    "new bridge", "new DB schema",
                    "new correction action",
                    "localStorage", "Tkinter fallback"):
        assert blocker in source, (
            "release-validation.md must mention release blocker: " + blocker
        )


def test_docs_history_mention_phase_3c1():
    """Phase 3C.1: the history doc must mention Phase 3C.1."""
    source = HISTORY_PATH.read_text(encoding="utf-8")
    assert "3C.1" in source, (
        "docs/history/webview-phases.md must mention Phase 3C.1"
    )


def test_docs_release_validation_mentions_phase_3c1():
    """Phase 3C.1: release-validation must mention Phase 3C.1."""
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "3C.1" in source, (
        "release-validation.md must mention Phase 3C.1"
    )
    assert "WebView Phase 3C.1 Validation" in source, (
        "release-validation.md must have a WebView Phase 3C.1 Validation "
        "section"
    )


def test_docs_release_validation_phase_3c1_release_blockers_3c1():
    """Phase 3C.1: release-validation must list the Phase 3C.1 release
    blockers."""
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "Phase 3C.1 Release Blockers" in source, (
        "release-validation.md must have a Phase 3C.1 Release Blockers "
        "section"
    )
    for blocker in ("raw exception", "traceback", "auto-refresh",
                    "saving", "dirty guard", "cross-save",
                    "stale id", "soft delete",
                    "localStorage", "new bridge"):
        assert blocker in source, (
            "release-validation.md must mention release blocker: " + blocker
        )


def test_docs_history_mention_phase_4a():
    """Phase 4A: the history doc must mention Phase 4A."""
    source = HISTORY_PATH.read_text(encoding="utf-8")
    assert "4A" in source, (
        "docs/history/webview-phases.md must mention Phase 4A"
    )
    assert "Phase 4A" in source, (
        "docs/history/webview-phases.md must mention 'Phase 4A'"
    )


def test_docs_release_validation_mentions_phase_4a():
    """Phase 4A: release-validation must mention Phase 4A."""
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "4A" in source, (
        "release-validation.md must mention Phase 4A"
    )
    assert "WebView Phase 4A Validation" in source, (
        "release-validation.md must have a WebView Phase 4A Validation section"
    )


def test_docs_release_validation_phase_4a_release_blockers_4a():
    """Phase 4A: release-validation must list the Phase 4A release
    blockers."""
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "Phase 4A Release Blockers" in source, (
        "release-validation.md must have a Phase 4A Release Blockers section"
    )
    for blocker in ("export write", "save dialog",
                    "raw title", "clipboard", "note",
                    "traceback", "SQL",
                    "DB schema", "write API",
                    "Project Rules", "Settings",
                    "legacy UI", "localStorage",
                    "Timeline", "regression"):
        assert blocker in source, (
            "release-validation.md must mention release blocker: " + blocker
        )


def test_docs_history_mention_phase_4a1():
    """Phase 4A.1: the history doc must mention Phase 4A.1 hardening."""
    source = HISTORY_PATH.read_text(encoding="utf-8")
    assert "4A.1" in source, (
        "docs/history/webview-phases.md must mention Phase 4A.1"
    )
    assert "hardening" in source.lower() or "harden" in source.lower()


def test_docs_release_validation_phase_4a1_section_4a1():
    """Phase 4A.1: release-validation must have a Phase 4A.1 section."""
    source = RELEASE_VALIDATION_PATH.read_text(encoding="utf-8")
    assert "4A.1" in source, (
        "release-validation.md must mention Phase 4A.1"
    )


# --- Phase R2: JS module split structural tests --------------------------
# Phase R2 split the monolithic app.js into six IIFE modules under
# worktrace/webview_ui/js/. These tests verify the split is structurally
# correct and behavior-preserving.


def test_phase_r2_js_directory_exists():
    """Phase R2: the js/ subdirectory must exist under webview_ui/."""
    assert JS_DIR.is_dir(), (
        "worktrace/webview_ui/js/ directory must exist after Phase R2"
    )


def test_phase_r2_each_js_file_declares_worktrace_namespace():
    """Phase R2: every js/ module must declare the shared namespace via
    ``var App = window.WorkTraceApp = window.WorkTraceApp || {};`` so all
    modules share the same namespace object."""
    for name in ALL_JS_FILES:
        source = read_js(name)
        assert "var App = window.WorkTraceApp = window.WorkTraceApp || {};" in source, (
            "js/" + name + " must declare the WorkTraceApp namespace"
        )


def test_phase_r2_each_js_file_is_iife():
    """Phase R2: every js/ module must be wrapped in an IIFE to avoid
    leaking locals into the global scope (matching the original app.js
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


def test_phase_r2_index_html_loads_js_files_in_correct_order():
    """Phase R2: index.html must load the six js/ modules in the exact
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


def test_phase_r2_no_es_module_syntax_in_js_files():
    """Phase R2: the js/ modules must NOT use ES module syntax (import /
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


def test_phase_r2_domcontentloaded_wiring_only_in_init_js():
    """Phase R2: the DOMContentLoaded wiring (the only top-level code
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


def test_phase_r2_worktrace_spec_bundles_js_modules():
    """Phase R2: the PyInstaller spec must list every js/ module in datas
    so the packaged exe includes the split frontend resources."""
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    for name in ALL_JS_FILES:
        assert ("js" in spec and name in spec), (
            "WorkTrace.spec must bundle js/" + name + " in datas"
        )
    # The old app.js reference must be gone.
    assert "app.js" not in spec, (
        "WorkTrace.spec must no longer reference the removed app.js"
    )


def test_phase_r2_no_app_js_references_remain_in_js_files():
    """Phase R2: no js/ module must reference the removed app.js file
    (e.g., via a script load or string literal)."""
    source = read_all_js()
    assert "app.js" not in source, (
        "js/ modules must not reference the removed app.js"
    )


# --- Phase R2: CRITICAL behavior-preservation guards --------------------


def test_phase_r2_all_functions_still_defined():
    """CRITICAL Phase R2 guard: every function that existed in the
    monolithic app.js must still be defined across the six js/ modules.
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
        "startAutoRefresh", "init",
    ]
    missing = []
    for name in required_functions:
        if source.find("function " + name + "(") == -1:
            missing.append(name)
    assert not missing, (
        "Phase R2 split is missing function definitions: "
        + ", ".join(missing)
        + ". These would cause ReferenceError at runtime."
    )
    # Also verify the total function count is in the expected range.
    # The original app.js had 147 function declarations. After the split,
    # we expect at least 140 top-level function declarations (some may be
    # counted as nested). This guards against accidental drops.
    all_decls = re.findall(r'\n    function \w+\s*\(', source)
    assert len(all_decls) >= 140, (
        "Expected at least 140 function declarations across js/ modules, "
        "found " + str(len(all_decls))
    )


def test_phase_r2_state_variables_only_accessed_via_app_namespace():
    """CRITICAL Phase R2 guard: every state variable declared via
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
        "lastTimelineData", "refreshTimer",
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
