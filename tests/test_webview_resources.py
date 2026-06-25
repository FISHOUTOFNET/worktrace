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


# --- Phase 2: Timeline read-only page tests -----------------------------


def test_index_html_timeline_page_is_not_placeholder():
    """Phase 2: the Timeline page must be a production page, not a
    migration placeholder. The placeholder text must not appear inside the
    timeline section."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # Extract the timeline section
    start = source.find('id="page-timeline"')
    end = source.find('</section>', start)
    assert start != -1, "timeline section must exist"
    timeline_section = source[start:end]
    assert "WebView 迁移中" not in timeline_section, (
        "Timeline page must not be a placeholder"
    )


def test_index_html_timeline_page_has_date_navigation():
    """Phase 2: the Timeline page must have prev/today/next date navigation."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-prev-btn"' in source
    assert 'id="timeline-next-btn"' in source
    assert 'id="timeline-today-btn"' in source
    assert 'id="timeline-date-display"' in source


def test_index_html_timeline_page_has_sessions_and_details_containers():
    """Phase 2: the Timeline page must have a sessions list container and a
    details list container for the master-detail layout."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-sessions-list"' in source
    assert 'id="timeline-details-list"' in source
    assert 'id="timeline-details-header"' in source


def test_index_html_timeline_page_has_error_and_empty_and_loading_states():
    """Phase 2: the Timeline page must have an error banner, an empty state
    element, and a loading indicator."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-error"' in source
    assert 'id="timeline-loading"' in source
    assert "timeline-empty" in source


def test_index_html_timeline_page_has_total_and_current():
    """Phase 2: the Timeline page must show the daily total duration and a
    current activity summary."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-total"' in source
    assert 'id="timeline-current"' in source


def test_index_html_unmigrated_pages_still_have_placeholders():
    """Phase 2: Statistics, Rules, and Settings pages are not yet migrated
    and must still show the placeholder text."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for page_id in ["statistics", "rules", "settings"]:
        start = source.find('id="page-{}"'.format(page_id))
        assert start != -1, f"{page_id} section must exist"
        end = source.find('</section>', start)
        section = source[start:end]
        assert "WebView 迁移中" in section, (
            f"{page_id} page should still be a placeholder in Phase 2"
        )


def test_app_js_has_timeline_load_function():
    """Phase 2: app.js must have a loadTimeline function that calls the
    get_timeline bridge method."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "loadTimeline" in source
    assert "get_timeline" in source


def test_app_js_has_timeline_session_details_load():
    """Phase 2: app.js must load session details via
    get_timeline_session_details bridge method."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "get_timeline_session_details" in source
    assert "loadSessionDetails" in source


def test_app_js_has_timeline_date_navigation():
    """Phase 2: app.js must implement prev/next/today date navigation."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "goPrevDay" in source
    assert "goNextDay" in source
    assert "goToday" in source
    assert "shiftDate" in source


def test_app_js_timeline_refreshes_on_auto_refresh():
    """Phase 2: when the Timeline page is active, refreshAll must also
    refresh the timeline data."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "currentPage" in source
    assert 'currentPage === "timeline"' in source


def test_app_js_timeline_has_error_handling():
    """Phase 2: app.js must have timeline-specific error display functions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "showTimelineError" in source
    assert "clearTimelineError" in source


def test_app_js_timeline_has_no_forbidden_edit_handlers():
    """Phase 3A: the Timeline page allows project reclassification and
    session-note editing only. app.js must not contain handlers for time
    editing, session split/merge, deletion, batch editing, auto-rule
    creation, or complex correction."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    # Forbidden operations (not part of Phase 3A scope)
    assert "edit_activity" not in source
    assert "delete_activity" not in source
    assert "correct_activity" not in source
    assert "split_session" not in source
    assert "merge_session" not in source
    assert "batch_edit" not in source
    assert "auto_rule" not in source
    assert "edit_start_time" not in source
    assert "edit_end_time" not in source


# --- Phase 3A: Timeline editing UI tests -------------------------------


def test_index_html_timeline_has_edit_panel():
    """Phase 3A: the Timeline details area must contain an edit panel for
    project reclassification and session-note editing."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-edit-panel"' in source
    assert "timeline-edit-panel" in source


def test_index_html_timeline_has_project_select():
    """Phase 3A: the edit panel must have a project <select> so the user
    can reclassify. The frontend must not allow free-form project_id input."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-project-select"' in source
    assert "<select" in source
    # No free-form text input for project_id
    assert 'id="edit-project-input"' not in source


def test_index_html_timeline_has_note_textarea():
    """Phase 3A: the edit panel must have a <textarea> for note editing."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-note-text"' in source
    assert "<textarea" in source
    assert 'id="edit-note-count"' in source


def test_index_html_timeline_has_save_cancel_buttons():
    """Phase 3A: the edit panel must have save and cancel buttons."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-save-btn"' in source
    assert 'id="edit-cancel-btn"' in source
    assert 'id="edit-status"' in source


def test_index_html_timeline_edit_panel_has_no_time_edit_inputs():
    """Phase 3A: the edit panel must not contain time editing inputs
    (start time, end time). Only project and note are editable."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # Extract the edit panel section
    start = source.find('id="timeline-edit-panel"')
    assert start != -1, "edit panel must exist"
    end = source.find("</div>", source.find("</div>", source.find("</div>", source.find("</div>", source.find("</div>", start) + 1) + 1) + 1) + 1)
    panel = source[start:end]
    assert "edit-start-time" not in panel
    assert "edit-end-time" not in panel
    assert "split" not in panel.lower()
    assert "merge" not in panel.lower()
    assert "delete" not in panel.lower()
    assert "batch" not in panel.lower()


def test_app_js_has_edit_panel_functions():
    """Phase 3A: app.js must define the edit panel lifecycle functions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "populateEditPanel" in source
    assert "clearEditPanel" in source
    assert "isEditDirty" in source
    assert "loadProjects" in source
    assert "saveEdit" in source
    assert "cancelEdit" in source
    assert "updateNoteCount" in source
    assert "showEditStatus" in source


def test_app_js_calls_editing_bridge_methods():
    """Phase 3A: app.js must call the Phase 3A bridge methods for project
    reclassification, note editing, and project list loading."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "list_projects_for_timeline" in source
    assert "update_timeline_project" in source
    assert "update_timeline_note" in source


def test_app_js_has_saving_state():
    """Phase 3A: app.js must track a saving state to prevent double-submit
    and show '保存中…' feedback."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "editSaving" in source
    assert "setEditSaving" in source
    assert "保存中" in source


def test_app_js_edit_save_failure_preserves_data():
    """Phase 3A: when a save fails, app.js must keep the original data in
    the form and display an error, not clear the form or leave it in a
    'saving' state."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # On error, setEditSaving(false) is called and showEditStatus shows error
    assert "setEditSaving(false)" in source
    assert "showEditStatus(errorMsg, true)" in source


def test_app_js_edit_save_success_refreshes_timeline():
    """Phase 3A: on save success, app.js must refresh the Timeline so the
    session list and edit panel reflect the new state."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "refreshTimelineAfterEdit" in source
    assert "保存成功" in source


def test_styles_css_has_edit_panel_styles():
    """Phase 3A: styles.css must style the edit panel, project select,
    note textarea, save/cancel buttons, and status messages."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".timeline-edit-panel" in source
    assert ".edit-select" in source
    assert ".edit-note" in source
    assert ".edit-save-btn" in source
    assert ".edit-cancel-btn" in source
    assert ".edit-status-error" in source
    assert ".edit-status-success" in source


def test_app_js_timeline_does_not_expose_tracebacks():
    """Phase 2: timeline error handling must not expose tracebacks."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "traceback" not in source.lower()


# --- Phase 2.1: Timeline read-only validation hardening tests ------------


def test_app_js_has_request_token_guard_for_timeline_loads():
    """Phase 2.1: app.js must use a request token (or equivalent sequence
    id) to prevent stale Timeline load responses from overwriting newer
    data when the user rapidly switches dates."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "timelineRequestToken" in source, (
        "app.js must define a timelineRequestToken guard so stale bridge "
        "responses do not overwrite newer Timeline data"
    )
    # The token must be incremented before each load and checked after.
    assert "++timelineRequestToken" in source
    assert "token !== timelineRequestToken" in source


def test_app_js_has_request_token_guard_for_session_details():
    """Phase 2.1: app.js must use a request token for session detail loads
    too, so rapidly switching sessions does not let an older detail
    response overwrite the newer one."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "detailsRequestToken" in source, (
        "app.js must define a detailsRequestToken guard so stale session "
        "detail responses do not overwrite newer detail data"
    )
    assert "++detailsRequestToken" in source
    assert "token !== detailsRequestToken" in source


def test_app_js_preserves_selected_session_across_refresh():
    """Phase 2.1: app.js must keep the selected session selected across
    auto-refresh. The session must be matched by session_id, and if it
    disappears the selection must clear gracefully without JS errors."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "selectedSessionId" in source
    # The selected session must be matched by session_id after refresh.
    assert "session_id === selectedSessionId" in source or (
        "sessions[k].session_id === selectedSessionId" in source
    )


def test_app_js_handles_disappeared_selected_session_gracefully():
    """Phase 2.1: when the previously selected session no longer exists
    after a refresh, app.js must clear the selection without throwing."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The code path that handles a missing session must reset
    # selectedSessionId and update the details panel placeholder.
    assert "selectedSessionId = null" in source


def test_app_js_marks_in_progress_sessions():
    """Phase 2.1: app.js must visually mark in-progress sessions (sessions
    whose ``is_in_progress`` flag is true) so the user can tell the
    current open record from closed history."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "is_in_progress" in source
    assert "in-progress" in source, (
        "app.js must apply an 'in-progress' CSS class to in-progress items"
    )


def test_app_js_marks_in_progress_activities():
    """Phase 2.1: app.js must visually mark in-progress activity detail
    rows too."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The detail rendering must check is_in_progress and apply the class.
    assert "a.is_in_progress" in source or "is_in_progress" in source


def test_app_js_uses_in_progress_label_in_time_range():
    """Phase 2.1: when the ``is_in_progress`` flag is true, app.js must show
    a clear '进行中' label in the time range instead of an empty 'HH:MM-'.
    The frontend consumes the explicit ``is_in_progress`` flag (not the
    emptiness of the displayed ``end_time``, which may be projected for
    open activities)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "进行中" in source, (
        "app.js must show '进行中' for in-progress time ranges"
    )


def test_app_js_provides_safe_tooltip_for_long_text():
    """Phase 2.1: app.js must add ``title`` attributes with the safe
    display name so the user can read long names on hover. The tooltip
    must use the same sanitized display name shown inline, not the raw
    window_title or full path."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert 'title="' in source or "title=" in source
    # The tooltip must use escapeHtml to avoid attribute injection.
    assert 'escapeHtml(' in source


def test_app_js_preserves_prior_data_on_refresh_error():
    """Phase 2.1: when a Timeline refresh fails, app.js must keep showing
    the previously loaded data instead of clearing the page. The error
    banner is shown alongside the prior data."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "lastTimelineData" in source, (
        "app.js must cache lastTimelineData so a refresh failure keeps the "
        "prior data visible instead of clearing the page"
    )


def test_app_js_does_not_use_local_storage_or_session_storage():
    """Phase 2.1: re-asserted explicitly because Phase 2.1 added new
    state-tracking variables. The frontend must not store sensitive data
    in browser storage APIs; the request tokens and lastTimelineData are
    in-memory only."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"localStorage|sessionStorage", source), (
        "app.js must not use localStorage or sessionStorage"
    )


def test_styles_css_has_in_progress_styling():
    """Phase 2.1: styles.css must visually distinguish in-progress
    sessions/activities from closed history."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".timeline-item.in-progress" in source
    assert ".detail-item.in-progress" in source


def test_styles_css_has_responsive_layout_for_narrow_viewports():
    """Phase 2.1: styles.css must keep the Timeline layout usable on
    narrow viewports. Long resource names must not stretch the layout."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    # The detail-item must switch to a single-column grid on narrow viewports
    # so long names wrap instead of stretching the layout horizontally.
    assert "grid-template-columns: 1fr" in source
    assert "@media" in source


def test_index_html_timeline_details_panel_has_initial_empty_state():
    """Phase 2.1: the Timeline details panel must ship with an initial
    empty-state message so the panel is never visually empty on first
    load."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # Find the timeline-details-list element and confirm it contains an
    # initial empty-state child.
    start = source.find('id="timeline-details-list"')
    assert start != -1
    end = source.find("</div>", start)
    panel = source[start:end]
    assert "timeline-empty" in panel
    assert "暂无详情" in panel


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
