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
    REPO_ROOT, WEBVIEW_UI_DIR, HISTORY_PATH,
    RELEASE_VALIDATION_PATH, README_PATH,
    read_resource, func_body,
    FRONTEND_RESOURCE_FILES, NO_STORAGE_FILES,
)


# --- existence tests -----------------------------------------------------


def test_index_html_exists():
    assert (WEBVIEW_UI_DIR / "index.html").is_file()


def test_app_js_exists():
    assert (WEBVIEW_UI_DIR / "app.js").is_file()


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
    assert 'src="app.js"' in source


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
    """Phase 1: app.js must render classified_duration and
    uncategorized_duration returned by the bridge, not just total
    duration."""
    source = read_resource("app.js")
    assert "kpi-classified" in source
    assert "kpi-uncategorized" in source
    assert "classified_duration" in source
    assert "uncategorized_duration" in source


def test_app_js_surfaces_bridge_errors_in_page():
    """Phase 1: app.js must show bridge errors in the in-page error banner
    instead of silently swallowing them."""
    source = read_resource("app.js")
    assert "overview-error" in source
    assert "showError" in source
    assert "clearError" in source


def test_app_js_does_not_expose_tracebacks():
    """The frontend must not attempt to parse or display Python tracebacks.
    It only shows the generic error string returned by the bridge."""
    source = read_resource("app.js")
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
