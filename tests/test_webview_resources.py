"""Tests for WebView frontend resources and startup module.

Phase 1: the WebView UI is the default and only shipping UI. These tests
verify:

- index.html, app.js, styles.css exist;
- the Overview page is a production page (KPIs, current activity, recent
  activities, error banner, pause toggle), not a spike placeholder;
- frontend resources contain no external links, CDN, or localStorage;
- importing worktrace.webview_main does not start the GUI;
- worktrace.webview_main.main exists;
- pywebview missing produces a clear error.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_DIR = REPO_ROOT / "worktrace" / "webview_ui"


def test_index_html_exists():
    assert (WEBVIEW_UI_DIR / "index.html").is_file()


def test_app_js_exists():
    assert (WEBVIEW_UI_DIR / "app.js").is_file()


def test_styles_css_exists():
    assert (WEBVIEW_UI_DIR / "styles.css").is_file()


def test_bridge_py_exists():
    assert (WEBVIEW_UI_DIR / "bridge.py").is_file()


@pytest.mark.parametrize(
    "filename",
    ["index.html", "app.js", "styles.css"],
)
def test_frontend_resource_has_no_external_links(filename):
    source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
    assert not re.search(r"https?://", source, re.IGNORECASE), (
        f"{filename} must not contain http:// or https:// links"
    )


@pytest.mark.parametrize(
    "filename",
    ["index.html", "app.js", "styles.css"],
)
def test_frontend_resource_has_no_cdn(filename):
    source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
    assert not re.search(r"cdn", source, re.IGNORECASE), (
        f"{filename} must not reference CDN"
    )


@pytest.mark.parametrize(
    "filename",
    ["index.html", "app.js", "styles.css"],
)
def test_frontend_resource_has_no_google_fonts(filename):
    source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE), (
        f"{filename} must not reference Google Fonts"
    )


@pytest.mark.parametrize(
    "filename",
    ["index.html", "app.js"],
)
def test_frontend_resource_has_no_local_storage(filename):
    source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
    assert not re.search(r"localStorage|sessionStorage", source), (
        f"{filename} must not use localStorage or sessionStorage"
    )


def test_index_html_references_local_resources():
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'href="styles.css"' in source
    assert 'src="app.js"' in source


def test_index_html_has_chinese_text():
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "概览" in source


def test_index_html_has_sidebar_nav():
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for label in ["概览", "时间详情", "统计与导出", "项目规则", "设置与隐私"]:
        assert label in source


def test_index_html_has_placeholder_for_unmigrated_pages():
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "WebView 迁移中" in source


def test_index_html_overview_page_has_required_kpis():
    """Phase 1: the Overview page must show the production KPI set, not a
    spike placeholder. Required KPIs: date, total duration, project count,
    classified duration, uncategorized duration."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="kpi-date"' in source
    assert 'id="kpi-total"' in source
    assert 'id="kpi-projects"' in source
    assert 'id="kpi-classified"' in source
    assert 'id="kpi-uncategorized"' in source


def test_index_html_overview_page_has_current_and_recent_sections():
    """Phase 1: the Overview page must have a current-activity section and a
    recent-activities list."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="current-activity"' in source
    assert 'id="recent-list"' in source


def test_index_html_overview_page_has_error_banner():
    """Phase 1: the Overview page must have an in-page error banner so bridge
    errors are surfaced to the user without exposing tracebacks."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="overview-error"' in source


def test_index_html_overview_page_has_pause_toggle():
    """Phase 1: the Overview page must support pause/resume through the
    sidebar toggle button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="toggle-pause-btn"' in source
    assert 'id="status-display"' in source


def test_app_js_displays_classified_and_uncategorized_durations():
    """Phase 1: app.js must render classified_duration and
    uncategorized_duration returned by the bridge, not just total duration."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "kpi-classified" in source
    assert "kpi-uncategorized" in source
    assert "classified_duration" in source
    assert "uncategorized_duration" in source


def test_app_js_surfaces_bridge_errors_in_page():
    """Phase 1: app.js must show bridge errors in the in-page error banner
    instead of silently swallowing them."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "overview-error" in source
    assert "showError" in source
    assert "clearError" in source


def test_app_js_does_not_expose_tracebacks():
    """The frontend must not attempt to parse or display Python tracebacks.
    It only shows the generic error string returned by the bridge."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
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
