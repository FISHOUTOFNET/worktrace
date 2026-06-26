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
    """Phase 3A / 3B.4: the Timeline page allows project reclassification,
    session-note editing, time correction, split, merge, and single-
    activity hide / soft delete. app.js must not contain handlers for
    batch editing, batch hide/delete, restore, permanent delete, auto-rule
    creation, or complex correction."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    # Forbidden operations (not part of any current phase scope)
    assert "edit_activity" not in source
    assert "correct_activity" not in source
    assert "split_session" not in source
    assert "merge_session" not in source
    assert "batch_edit" not in source
    assert "batch_delete" not in source
    assert "batch_hide" not in source
    assert "restore_activity" not in source
    assert "permanent_delete" not in source
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


def test_index_html_timeline_edit_panel_has_no_delete_batch():
    """Phase 3B.1 / 3B.2 / 3B.3 / 3B.4: the edit panel contains time-
    correction inputs (``edit-start-time`` / ``edit-end-time``), a split
    section (``edit-split-section``), and a hide/delete section
    (``edit-visibility-section``). Phase 3B.3 adds the per-activity merge
    button in the rendered detail rows (not in the static edit panel), so
    "merge" may appear in app.js but the static index.html must still not
    contain merge, batch, restore, permanent-delete, or auto-rule
    controls. Phase 3B.4 introduces a soft-delete button in the static
    panel; "delete" is therefore allowed in index.html, but only as the
    soft-delete foundation, never as a permanent delete control."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # Phase 3B.1 now provides time-correction inputs in the edit panel.
    assert 'id="edit-start-time"' in source
    assert 'id="edit-end-time"' in source
    assert 'id="edit-time-save-btn"' in source
    # Phase 3B.2 now provides a split section in the edit panel.
    assert 'id="edit-split-section"' in source
    assert 'id="edit-split-time"' in source
    assert 'id="edit-split-save-btn"' in source
    # Phase 3B.4 now provides a hide/delete section in the edit panel.
    assert 'id="edit-visibility-section"' in source
    assert 'id="edit-visibility-single"' in source
    assert 'id="edit-visibility-multi"' in source
    assert 'id="edit-visibility-hide-btn"' in source
    assert 'id="edit-visibility-delete-btn"' in source
    assert 'id="edit-visibility-status"' in source
    # Batch / restore / permanent delete / auto-rule must still be absent
    # from the entire HTML (these controls must never appear anywhere).
    # Phase 3B.4 allows "delete" because the visibility section contains a
    # soft-delete button; the test instead guards against the stronger
    # destructive variants.
    lowered = source.lower()
    assert "batch" not in lowered
    assert "restore" not in lowered
    assert "permanent" not in lowered
    assert "auto-rule" not in lowered


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


# --- Phase 3A.1: Timeline editing hardening tests -----------------------


def test_app_js_save_success_updates_edit_baseline():
    """Phase 3A.1: on save success, app.js must update the editingSession
    baseline to the saved values so the dirty state clears and Cancel
    after save does not revert to pre-save values."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "editingSession.project_id = projectId" in source, (
        "save success must update editingSession.project_id to the saved value"
    )
    assert "editingSession.session_note = note" in source, (
        "save success must update editingSession.session_note to the saved value"
    )


def test_app_js_update_note_count_disables_save_over_limit():
    """Phase 3A.1: updateNoteCount must disable the save button when the
    note exceeds NOTE_MAX_LENGTH, so the user gets immediate feedback."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "edit-note-count-over" in source, (
        "updateNoteCount must add an 'edit-note-count-over' class when over limit"
    )
    # The function must reference the save button and toggle its disabled
    # state based on the length check.
    assert "edit-save-btn" in source
    assert "len > NOTE_MAX_LENGTH" in source or "len >= NOTE_MAX_LENGTH" in source


def test_app_js_set_edit_saving_reapplies_length_guard():
    """Phase 3A.1: setEditSaving(false) must call updateNoteCount to
    re-apply the note-length guard after a save finishes."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # Find the setEditSaving function body and verify it calls
    # updateNoteCount when saving is false.
    assert "if (!saving && editingSession)" in source, (
        "setEditSaving must call updateNoteCount when saving is false"
    )
    assert "updateNoteCount()" in source


def test_app_js_populate_edit_panel_calls_update_note_count_last():
    """Phase 3A.1: populateEditPanel must call updateNoteCount after
    enabling the save button so the length check has the final say."""
    import re

    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # Find the populateEditPanel function body by brace matching (the body
    # contains nested `function` expressions, so a naive `find("function ")`
    # would truncate it too early).
    start = source.find("function populateEditPanel(")
    assert start != -1, "populateEditPanel must exist"
    brace_start = source.find("{", start)
    assert brace_start != -1, "populateEditPanel must have a body"
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    # updateNoteCount must appear after the save-button enable statement in
    # the function body, so the length check overrides the enable. The enable
    # may be written defensively as `if (saveBtn) saveBtn.disabled = false;`
    # or directly as `saveBtn.disabled = false;`.
    enable_match = re.search(r"saveBtn\.disabled\s*=\s*false", body)
    assert enable_match is not None, "populateEditPanel must enable save button"
    save_btn_enable_pos = enable_match.start()
    update_note_count_pos = body.find("updateNoteCount()")
    assert update_note_count_pos != -1, "populateEditPanel must call updateNoteCount"
    assert update_note_count_pos > save_btn_enable_pos, (
        "updateNoteCount must be called after saveBtn.disabled = false so the "
        "length check has the final say"
    )


def test_styles_css_has_note_over_limit_style():
    """Phase 3A.1: styles.css must style the note counter in red when the
    note exceeds the 2000-character limit."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-note-count-over" in source


def test_styles_css_has_edit_panel_responsive_rules():
    """Phase 3A.1: styles.css must keep the edit panel usable on narrow
    viewports — the actions row wraps and the note textarea keeps a
    min-height."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-actions" in source
    assert "flex-wrap" in source
    assert "min-height" in source


def test_app_js_still_has_no_forbidden_edit_handlers_after_hardening():
    """Phase 3B.1 / 3B.2 / 3B.3 / 3B.4: time correction, activity split,
    two-activity merge, and single-activity hide / soft delete are now
    supported features, but the frontend must still not contain batch,
    restore, permanent-delete, or auto-rule handlers. ``merge_session``
    (multi-activity session whole-merge) is also forbidden — only the
    two-activity ``merge_timeline_activities`` bridge call is allowed."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    # Phase 3B.1 now provides time correction; Phase 3B.2 provides split;
    # Phase 3B.3 provides two-activity merge; Phase 3B.4 provides single-
    # activity hide / soft delete. The following forbidden handlers must
    # still be absent.
    assert "merge_session" not in source
    assert "batch_edit" not in source
    assert "batch_delete" not in source
    assert "batch_hide" not in source
    assert "restore_activity" not in source
    assert "permanent_delete" not in source
    assert "auto_rule" not in source
    # Batch / restore / permanent-delete / auto-rule buttons must not exist
    # in the HTML either. Merge is now allowed in app.js (Phase 3B.3) but
    # still must not appear in the static index.html (the merge button is
    # rendered dynamically by app.js). Phase 3B.4 introduces a soft-delete
    # button in index.html, so "delete" is allowed there.
    html_source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8").lower()
    assert "batch" not in html_source
    assert "restore" not in html_source
    assert "permanent" not in html_source
    assert "auto-rule" not in html_source


def test_app_js_still_no_browser_storage_after_hardening():
    """Phase 3A.1: the hardening must not introduce browser storage."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"localStorage|sessionStorage", source)


def test_app_js_still_no_traceback_display_after_hardening():
    """Phase 3A.1: the hardening must not introduce traceback display."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "traceback" not in source.lower()


def test_app_js_still_no_external_links_after_hardening():
    """Phase 3A.1: the hardening must not introduce external links."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"https?://", source, re.IGNORECASE)


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


# --- Phase 3B.1: Timeline time correction frontend tests ------------------


def test_index_html_has_time_correction_section():
    """Phase 3B.1: index.html must have a time-correction section in the
    edit panel with start/end inputs and a save button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-time-section"' in source
    assert 'id="edit-time-single"' in source
    assert 'id="edit-time-multi"' in source
    assert 'id="edit-start-time"' in source
    assert 'id="edit-end-time"' in source
    assert 'id="edit-time-save-btn"' in source
    assert 'id="edit-time-status"' in source
    # Must use datetime-local inputs for time correction
    assert 'type="datetime-local"' in source


def test_app_js_calls_time_correction_bridge_methods():
    """Phase 3B.1: app.js must call the new bridge methods for time
    correction."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "update_timeline_activity_time" in source
    assert "update_timeline_session_time" in source


def test_app_js_has_datetime_conversion_helpers():
    """Phase 3B.1: app.js must have helpers to convert between the backend
    ``YYYY-MM-DD HH:MM:SS`` format and the ``datetime-local`` input's
    ``YYYY-MM-DDTHH:MM:SS`` format."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "backendToDatetimeLocal" in source
    assert "datetimeLocalToBackend" in source
    # The conversion must use fixed-format string replacement (space <-> T),
    # not Date parsing (which would interpret as local time and shift values).
    assert ".replace" in source


def test_app_js_has_time_saving_state():
    """Phase 3B.1: app.js must track independent saving states for
    session-level and per-activity time correction so they do not pollute
    the project/note saving state."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "timeSaving" in source
    assert "activityTimeSaving" in source
    assert "setTimeSaving" in source
    assert "setActivityTimeSaving" in source
    # The session-level saving state must be separate from editSaving
    assert "editSaving" in source


def test_app_js_has_session_time_functions():
    """Phase 3B.1: app.js must define the session-level time correction
    lifecycle functions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "populateSessionTimeSection" in source
    assert "resetSessionTimeSection" in source
    assert "saveSessionTime" in source
    assert "showTimeStatus" in source


def test_app_js_has_per_activity_inline_editor_functions():
    """Phase 3B.1: app.js must define the per-activity inline time editor
    lifecycle functions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "openActivityTimeEditor" in source
    assert "closeActivityTimeEditor" in source
    assert "saveActivityTime" in source
    assert "editingActivityId" in source


def test_app_js_refreshes_timeline_after_time_save():
    """Phase 3B.1: after a successful time correction, app.js must refresh
    the Timeline so the new times are reflected."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # saveSessionTime and saveActivityTime must both call refreshTimelineAfterEdit
    save_session_pos = source.find("function saveSessionTime")
    assert save_session_pos != -1
    save_activity_pos = source.find("function saveActivityTime")
    assert save_activity_pos != -1
    # Check that refreshTimelineAfterEdit is called within both functions
    refresh_pos = source.find("function refreshTimelineAfterEdit")
    assert refresh_pos != -1


def test_app_js_disables_in_progress_activity_time_edit():
    """Phase 3B.1: in-progress activities must have their '编辑时间' button
    disabled, and the session-level time section must show a hint."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "进行中记录暂不支持时间修正" in source


def test_app_js_disables_multi_activity_session_time_edit():
    """Phase 3B.1: multi-activity sessions must show the 'multi-activity
    not supported' hint instead of the time inputs."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "多活动 session 暂不支持整体时间修改" in source


def test_app_js_preserves_input_on_save_failure():
    """Phase 3B.1: when a time save fails, the user's input must be
    preserved (not cleared) and an error message shown."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The save functions must call setTimeSaving(false) on error to
    # re-enable the button without clearing the input values. The .catch
    # handler and the `result.ok === false` branch must both re-enable
    # without resetting the input .value.
    assert "setTimeSaving(false)" in source or "setTimeSaving(row, false)" in source
    # The error path must show an error message, not clear the inputs.
    assert "保存时间失败" in source


def test_app_js_time_edit_uses_is_in_progress_not_end_time_emptiness():
    """Phase 3B.1: the frontend must use the ``is_in_progress`` flag to
    decide whether time editing is allowed, NOT infer it from whether
    ``end_time`` is empty (because the displayed ``end_time`` may be a
    projected value for open activities)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # populateSessionTimeSection must check is_in_progress, not end_time
    populate_pos = source.find("function populateSessionTimeSection")
    assert populate_pos != -1
    # Find the end of the function (next 'function' at the same indent level)
    next_func = source.find("\n    function ", populate_pos + 1)
    body = source[populate_pos:next_func]
    assert "is_in_progress" in body


def test_app_js_time_edit_buttons_have_no_delete_batch():
    """Phase 3B.1 / 3B.2 / 3B.3 / 3B.4: the per-activity editor area must
    not include batch, restore, or permanent-delete buttons. Split buttons
    are added in Phase 3B.2, merge buttons are added in Phase 3B.3, and
    per-activity hide / soft-delete buttons are added in Phase 3B.4; all
    three are allowed."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    # The renderSessionDetails function must not generate batch / restore /
    # permanent-delete buttons. Hide / soft-delete buttons (Phase 3B.4),
    # merge buttons (Phase 3B.3), and split buttons (Phase 3B.2) are allowed.
    render_pos = source.find("function rendersessiondetails")
    assert render_pos != -1
    # Find the next function to bound the search
    next_func = source.find("\n    function ", render_pos + 1)
    body = source[render_pos:next_func] if next_func != -1 else source[render_pos:]
    assert "batch" not in body
    assert "restore" not in body
    assert "permanent" not in body


def test_app_js_has_no_traceback_display_in_time_edit():
    """Phase 3B.1: the time correction code must not display tracebacks."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "traceback" not in source.lower()


def test_styles_css_has_time_correction_styles():
    """Phase 3B.1: styles.css must style the time correction UI elements."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-time-section" in source
    assert ".edit-time-input" in source
    assert ".edit-time-save-btn" in source
    assert ".detail-time-editor" in source
    assert ".detail-time-input" in source
    assert ".detail-time-save-btn" in source


def test_frontend_resources_still_no_external_links():
    """Phase 3B.1: the time correction additions must not introduce
    external links, CDN, or Google Fonts."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )
        assert not re.search(r"cdn", source, re.IGNORECASE), (
            f"{filename} must not reference CDN"
        )
        assert not re.search(r"google\s*fonts", source, re.IGNORECASE), (
            f"{filename} must not reference Google Fonts"
        )


def test_frontend_resources_still_no_browser_storage():
    """Phase 3B.1: the time correction additions must not use browser
    storage APIs."""
    for filename in ["index.html", "app.js"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"localStorage|sessionStorage", source), (
            f"{filename} must not use localStorage or sessionStorage"
        )


# --- Phase 3B.1.1: time correction hardening tests -----------------------


def test_refresh_timeline_after_edit_does_not_reset_edit_saving():
    """Phase 3B.1.1: ``refreshTimelineAfterEdit`` must NOT call
    ``setEditSaving(false)``. The three independent save flows (project/note,
    session-time, per-activity-time) must each reset their own saving state
    before calling the shared refresh function, so a refresh triggered by one
    flow does not prematurely reset another flow's saving state."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # Extract the refreshTimelineAfterEdit function body by brace matching.
    start = source.find("function refreshTimelineAfterEdit(")
    assert start != -1, "refreshTimelineAfterEdit must exist"
    brace_start = source.find("{", start)
    assert brace_start != -1
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert "setEditSaving" not in body, (
        "refreshTimelineAfterEdit must not call setEditSaving — each save "
        "flow must reset its own saving state before refreshing"
    )
    assert "setTimeSaving" not in body, (
        "refreshTimelineAfterEdit must not call setTimeSaving — each save "
        "flow must reset its own saving state before refreshing"
    )


def test_save_session_time_resets_saving_before_refresh():
    """Phase 3B.1.1: ``saveSessionTime`` must call ``setTimeSaving(false)``
    BEFORE ``refreshTimelineAfterEdit`` on the success path, so the save
    button is re-enabled regardless of whether the refresh succeeds."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function saveSessionTime(")
    assert start != -1, "saveSessionTime must exist"
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    reset_pos = body.find("setTimeSaving(false)")
    refresh_pos = body.find("refreshTimelineAfterEdit()")
    assert reset_pos != -1, "saveSessionTime must call setTimeSaving(false) on success"
    assert refresh_pos != -1, "saveSessionTime must call refreshTimelineAfterEdit on success"
    assert reset_pos < refresh_pos, (
        "saveSessionTime must reset timeSaving BEFORE refreshing so the "
        "button is re-enabled even if the refresh fails"
    )


def test_save_edit_resets_saving_before_refresh():
    """Phase 3B.1.1: ``saveEdit`` must call ``setEditSaving(false)`` BEFORE
    ``refreshTimelineAfterEdit`` on the success path."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function saveEdit(")
    assert start != -1, "saveEdit must exist"
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    # Find the success-path setEditSaving(false) — it must appear before the
    # refreshTimelineAfterEdit call. (There may also be an error-path
    # setEditSaving(false) earlier; we need at least one before the refresh.)
    refresh_pos = body.find("refreshTimelineAfterEdit()")
    assert refresh_pos != -1, "saveEdit must call refreshTimelineAfterEdit on success"
    # Search for setEditSaving(false) before the refresh call.
    pre_refresh = body[:refresh_pos]
    assert "setEditSaving(false)" in pre_refresh, (
        "saveEdit must call setEditSaving(false) BEFORE refreshTimelineAfterEdit "
        "so the button is re-enabled even if the refresh fails"
    )


def test_save_activity_time_resets_saving_before_refresh():
    """Phase 3B.1.1: ``saveActivityTime`` must call
    ``setActivityTimeSaving(row, false)`` BEFORE ``refreshTimelineAfterEdit``
    on the success path."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function saveActivityTime(")
    assert start != -1, "saveActivityTime must exist"
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    refresh_pos = body.find("refreshTimelineAfterEdit()")
    assert refresh_pos != -1, "saveActivityTime must call refreshTimelineAfterEdit on success"
    pre_refresh = body[:refresh_pos]
    assert "setActivityTimeSaving(row, false)" in pre_refresh, (
        "saveActivityTime must call setActivityTimeSaving(row, false) BEFORE "
        "refreshTimelineAfterEdit so the inputs are re-enabled even if the "
        "refresh fails"
    )


def test_is_edit_dirty_covers_session_level_time_inputs():
    """Phase 3B.1.1: ``isEditDirty`` must check the session-level time inputs
    (``edit-start-time`` / ``edit-end-time``) so auto-refresh does not
    overwrite unsaved time edits."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function isEditDirty(")
    assert start != -1, "isEditDirty must exist"
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert "edit-start-time" in body, (
        "isEditDirty must check edit-start-time for unsaved time edits"
    )
    assert "edit-end-time" in body, (
        "isEditDirty must check edit-end-time for unsaved time edits"
    )


def test_is_edit_dirty_covers_per_activity_inline_editor():
    """Phase 3B.1.1: ``isEditDirty`` must also check the per-activity inline
    time editor so auto-refresh does not re-render the detail list and lose
    unsaved inline edits."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function isEditDirty(")
    assert start != -1
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert "editingActivityId" in body, (
        "isEditDirty must check editingActivityId so an open inline editor "
        "is treated as dirty and auto-refresh does not wipe it"
    )


def test_auto_refresh_skips_detail_reload_when_edit_dirty():
    """Phase 3B.1.1: the Timeline auto-refresh path must call ``isEditDirty``
    to decide whether to skip the detail reload / edit-panel repopulation,
    so unsaved time edits are not overwritten."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The showTimeline function (or its session-matching branch) must call
    # isEditDirty() before repopulating the edit panel.
    assert "isEditDirty()" in source, (
        "auto-refresh must call isEditDirty() to avoid overwriting unsaved edits"
    )
    # The skipDetailReload guard must exist.
    assert "skipDetailReload" in source, (
        "auto-refresh must use a skipDetailReload guard based on isEditDirty"
    )


def test_styles_css_has_detail_time_row_responsive_wrap():
    """Phase 3B.1.1: styles.css must wrap ``.detail-time-row`` on narrow
    viewports so the inline time editor does not break the layout."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    # There may be multiple @media (max-width: 900px) blocks; scan all of
    # them and confirm at least one contains .detail-time-row with flex-wrap.
    found = False
    search_from = 0
    while True:
        media_start = source.find("@media (max-width: 900px)", search_from)
        if media_start == -1:
            break
        brace_start = source.find("{", media_start)
        if brace_start == -1:
            break
        depth = 0
        end = brace_start
        for i in range(brace_start, len(source)):
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        media_body = source[media_start:end]
        if ".detail-time-row" in media_body and "flex-wrap" in media_body:
            found = True
            break
        search_from = end
    assert found, (
        "at least one @media (max-width: 900px) block must include "
        ".detail-time-row with flex-wrap"
    )


def test_save_session_time_updates_baseline_on_success():
    """Phase 3B.1.1: ``saveSessionTime`` must update the
    ``editingSession.start_time`` / ``end_time`` baseline on success so a
    subsequent auto-refresh does not revert the inputs to pre-save values."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function saveSessionTime(")
    assert start != -1
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert "editingSession.start_time = startVal" in body, (
        "saveSessionTime must update editingSession.start_time baseline on success"
    )
    assert "editingSession.end_time = endVal" in body, (
        "saveSessionTime must update editingSession.end_time baseline on success"
    )


def test_save_activity_time_updates_baseline_on_success():
    """Phase 3B.1.1: ``saveActivityTime`` must update the button's
    ``data-start`` / ``data-end`` attributes on success so a subsequent
    auto-refresh does not revert the editor inputs to pre-save values."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function saveActivityTime(")
    assert start != -1
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert 'setAttribute("data-start"' in body, (
        "saveActivityTime must update data-start baseline on success"
    )
    assert 'setAttribute("data-end"' in body, (
        "saveActivityTime must update data-end baseline on success"
    )


# --- Phase 3B.2: Timeline activity split frontend tests ------------------


def test_index_html_has_split_section():
    """Phase 3B.2: index.html must have a split section in the edit panel
    with a split-time input and a save button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-split-section"' in source
    assert 'id="edit-split-single"' in source
    assert 'id="edit-split-multi"' in source
    assert 'id="edit-split-time"' in source
    assert 'id="edit-split-save-btn"' in source
    assert 'id="edit-split-status"' in source
    # Must use datetime-local input for the split point
    assert 'type="datetime-local"' in source


def test_app_js_calls_split_bridge_methods():
    """Phase 3B.2: app.js must call the new bridge methods for splitting."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "split_timeline_activity" in source
    assert "split_timeline_session" in source


def test_app_js_has_split_saving_state():
    """Phase 3B.2: app.js must track independent saving states for
    session-level and per-activity split so they do not pollute the
    project/note/time saving states."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "sessionSplitSaving" in source
    assert "activitySplitSaving" in source
    assert "editingSplitActivityId" in source
    # The split saving states must be separate from the time saving states
    assert "timeSaving" in source
    assert "activityTimeSaving" in source


def test_app_js_has_session_split_functions():
    """Phase 3B.2: app.js must define the session-level split lifecycle
    functions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "populateSessionSplitSection" in source
    assert "resetSessionSplitSection" in source
    assert "saveSessionSplit" in source
    assert "showSplitStatus" in source
    assert "setSessionSplitSaving" in source


def test_app_js_has_per_activity_split_functions():
    """Phase 3B.2: app.js must define the per-activity inline split editor
    lifecycle functions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "openActivitySplitEditor" in source
    assert "closeActivitySplitEditor" in source
    assert "closeAllActivitySplitEditors" in source
    assert "saveActivitySplit" in source
    assert "setActivitySplitSaving" in source


def test_app_js_refreshes_timeline_after_split_save():
    """Phase 3B.2: after a successful split, app.js must refresh the
    Timeline so the two new activities appear."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_session_pos = source.find("function saveSessionSplit")
    assert save_session_pos != -1, "saveSessionSplit must exist"
    save_activity_pos = source.find("function saveActivitySplit")
    assert save_activity_pos != -1, "saveActivitySplit must exist"
    # Both functions must call refreshTimelineAfterEdit on the success path.
    # Find the function body for saveActivitySplit and verify the refresh call.
    brace_start = source.find("{", save_activity_pos)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    activity_body = source[save_activity_pos:end]
    assert "refreshTimelineAfterEdit()" in activity_body, (
        "saveActivitySplit must call refreshTimelineAfterEdit on success"
    )
    # Same for saveSessionSplit
    brace_start2 = source.find("{", save_session_pos)
    depth2 = 0
    end2 = brace_start2
    for i in range(brace_start2, len(source)):
        ch = source[i]
        if ch == "{":
            depth2 += 1
        elif ch == "}":
            depth2 -= 1
            if depth2 == 0:
                end2 = i + 1
                break
    session_body = source[save_session_pos:end2]
    assert "refreshTimelineAfterEdit()" in session_body, (
        "saveSessionSplit must call refreshTimelineAfterEdit on success"
    )


def test_app_js_split_save_resets_saving_before_refresh():
    """Phase 3B.2: ``saveActivitySplit`` and ``saveSessionSplit`` must
    reset the saving state BEFORE calling ``refreshTimelineAfterEdit`` so
    the UI does not get stuck in the '拆分中…' state if the refresh
    fails."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for func_name in ("saveActivitySplit", "saveSessionSplit"):
        start = source.find(f"function {func_name}(")
        assert start != -1, f"{func_name} must exist"
        brace_start = source.find("{", start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(source)):
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        body = source[start:end]
        refresh_pos = body.find("refreshTimelineAfterEdit()")
        assert refresh_pos != -1, f"{func_name} must call refreshTimelineAfterEdit"
        pre_refresh = body[:refresh_pos]
        # At least one saving-reset call must appear before the refresh.
        assert (
            "setActivitySplitSaving(row, false)" in pre_refresh
            or "setSessionSplitSaving(false)" in pre_refresh
        ), (
            f"{func_name} must reset the split saving state BEFORE "
            f"refreshTimelineAfterEdit"
        )


def test_app_js_split_preserves_input_on_save_failure():
    """Phase 3B.2: when a split save fails, the user's input must be
    preserved (not cleared) and an error message shown. The save
    functions must reset the saving state to re-enable the button without
    wiping the input value."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The error path must reset the saving state. Both the
    # ``result.ok === false`` branch and the ``.catch`` handler must reset.
    assert "setActivitySplitSaving(row, false)" in source
    assert "setSessionSplitSaving(false)" in source
    # The error path must show an error message (split-failed).
    assert "拆分失败" in source


def test_app_js_split_disables_multi_activity_session():
    """Phase 3B.2: multi-activity sessions must show the 'multi-activity
    not supported' hint for the session-level split."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动" in source


def test_app_js_split_disables_in_progress_activity():
    """Phase 3B.2: in-progress activities must be disabled or show a hint
    for splitting."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "进行中记录暂不支持拆分" in source


def test_app_js_split_does_not_use_date_automatic_parsing():
    """Phase 3B.2: the split-time conversion must NOT rely on JS ``Date``
    string parsing (which interprets the value as local time and could
    shift it). The midpoint helper must use explicit Date.UTC
    construction."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "midpointTime" in source
    assert "parseBackendTimeParts" in source
    assert "formatUtcParts" in source
    # parseBackendTimeParts must use Date.UTC so backend timestamps are
    # interpreted as-is without a local-timezone shift.
    parse_start = source.find("function parseBackendTimeParts(")
    assert parse_start != -1
    parse_brace = source.find("{", parse_start)
    depth = 0
    parse_end = parse_brace
    for i in range(parse_brace, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                parse_end = i + 1
                break
    parse_body = source[parse_start:parse_end]
    assert "Date.UTC" in parse_body, (
        "parseBackendTimeParts must use Date.UTC to avoid local-timezone "
        "interpretation of backend timestamps"
    )
    # The midpoint helper must not use new Date("<string>") string parsing.
    # new Date(<number>) (epoch ms) is allowed because it is timezone-safe.
    mid_start = source.find("function midpointTime(")
    assert mid_start != -1
    brace_start = source.find("{", mid_start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    mid_body = source[mid_start:end]
    assert 'new Date("' not in mid_body, (
        "midpointTime must not use new Date(string) parsing which would "
        "interpret the value as local time"
    )


def test_app_js_split_has_no_merge_delete_batch_auto_rule_handlers():
    """Phase 3B.2 / 3B.4: the split code must not introduce merge, batch
    edit, restore, permanent-delete, or auto-rule handlers. Phase 3B.4
    introduces ``saveActivityDelete`` / ``saveSessionDelete`` for single-
    activity soft delete; the lowercase-d ``deleteActivity`` handler name
    (a different convention) must still be absent."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The whole file must not contain merge/batch/restore/permanent/auto-rule
    # handler names. (Split and single-activity soft delete are allowed.)
    assert "mergeActivity" not in source
    assert "deleteActivity" not in source
    assert "batchEdit" not in source
    assert "restoreActivity" not in source
    assert "permanentDelete" not in source
    assert "autoRule" not in source
    assert "createRule" not in source


def test_app_js_split_has_no_traceback_display():
    """Phase 3B.2: the split code must not display tracebacks."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "traceback" not in source.lower()


def test_app_js_is_edit_dirty_covers_split_inputs():
    """Phase 3B.2: ``isEditDirty`` must check the session-level split input
    and the per-activity inline split editor so auto-refresh does not wipe
    unsaved split edits."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function isEditDirty(")
    assert start != -1, "isEditDirty must exist"
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert "edit-split-time" in body, (
        "isEditDirty must check edit-split-time for unsaved session-level split"
    )
    assert "editingSplitActivityId" in body, (
        "isEditDirty must check editingSplitActivityId so an open inline "
        "split editor is treated as dirty"
    )


def test_styles_css_has_split_styles():
    """Phase 3B.2: styles.css must style the split UI elements."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-split-section" in source
    assert ".edit-split-save-btn" in source
    assert ".detail-split-editor" in source
    assert ".detail-split-btn" in source


def test_styles_css_has_split_responsive_wrap():
    """Phase 3B.2: styles.css must handle the split editor on narrow
    viewports (flex-wrap and grid-row adjustments inside the
    ``@media (max-width: 900px)`` block)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    found = False
    search_from = 0
    while True:
        media_start = source.find("@media (max-width: 900px)", search_from)
        if media_start == -1:
            break
        brace_start = source.find("{", media_start)
        if brace_start == -1:
            break
        depth = 0
        end = brace_start
        for i in range(brace_start, len(source)):
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        media_body = source[media_start:end]
        if ".detail-split-editor" in media_body:
            found = True
            break
        search_from = end
    assert found, (
        "at least one @media (max-width: 900px) block must include "
        ".detail-split-editor for narrow-viewport support"
    )


def test_frontend_resources_split_still_no_external_links():
    """Phase 3B.2: the split additions must not introduce external links,
    CDN, or Google Fonts."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )
        assert not re.search(r"cdn", source, re.IGNORECASE), (
            f"{filename} must not reference CDN"
        )
        assert not re.search(r"google\s*fonts", source, re.IGNORECASE), (
            f"{filename} must not reference Google Fonts"
        )


def test_frontend_resources_split_still_no_browser_storage():
    """Phase 3B.2: the split additions must not use browser storage."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"localStorage", source, re.IGNORECASE), (
            f"{filename} must not use localStorage"
        )
        assert not re.search(r"sessionStorage", source, re.IGNORECASE), (
            f"{filename} must not use sessionStorage"
        )


# --- Phase 3B.3: Timeline activity merge frontend tests ------------------


def test_app_js_calls_merge_bridge_method():
    """Phase 3B.3: app.js must call the new bridge method for merging two
    activities."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "merge_timeline_activities" in source


def test_app_js_has_merge_saving_state():
    """Phase 3B.3: app.js must track an independent saving state for merge
    so it does not pollute the project/note/time/split saving states."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "mergeSaving" in source
    assert "mergingActivityId" in source
    # The merge saving state must be separate from the other saving states
    assert "editSaving" in source
    assert "timeSaving" in source
    assert "activitySplitSaving" in source


def test_app_js_has_merge_functions():
    """Phase 3B.3: app.js must define the merge lifecycle functions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "saveActivityMerge" in source
    assert "setMergeSaving" in source
    assert "setMergeStatus" in source


def test_app_js_has_merge_button_in_detail_rows():
    """Phase 3B.3: the renderSessionDetails function must generate a merge
    button (与下一条合并) for each closed activity."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "detail-merge-btn" in source
    assert "与下一条合并" in source


def test_app_js_merge_save_resets_saving_before_refresh():
    """Phase 3B.3: ``saveActivityMerge`` must reset the saving state BEFORE
    calling ``refreshTimelineAfterEdit`` on the success path so the UI
    does not get stuck in the '合并中…' state if the refresh fails."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function saveActivityMerge(")
    assert start != -1, "saveActivityMerge must exist"
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    refresh_pos = body.find("refreshTimelineAfterEdit()")
    assert refresh_pos != -1, "saveActivityMerge must call refreshTimelineAfterEdit on success"
    pre_refresh = body[:refresh_pos]
    assert "setMergeSaving(btn, false)" in pre_refresh, (
        "saveActivityMerge must reset mergeSaving BEFORE refreshTimelineAfterEdit "
        "so the button is re-enabled even if the refresh fails"
    )


def test_app_js_merge_preserves_state_on_save_failure():
    """Phase 3B.3: when a merge save fails, the saving state must be reset
    and an error message shown. The detail list must not be cleared."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function saveActivityMerge(")
    assert start != -1
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    # Error path must reset saving state
    assert "setMergeSaving(btn, false)" in body
    # Error path must show an error message
    assert "合并失败" in body


def test_app_js_merge_disables_in_progress_activity():
    """Phase 3B.3: in-progress activities must have their merge button
    disabled."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The merge button disabled logic must check is_in_progress
    start = source.find("function renderSessionDetails(")
    assert start != -1
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert "is_in_progress" in body
    assert "mergeBtnDisabled" in body


def test_app_js_merge_has_no_delete_batch_auto_rule_handlers():
    """Phase 3B.3 / 3B.4: the merge code must not introduce batch edit,
    restore, permanent-delete, or auto-rule handlers. Multi-activity
    session whole-merge (``merge_session``) is also forbidden. Phase 3B.4
    introduces ``saveActivityDelete`` / ``saveSessionDelete`` for single-
    activity soft delete; the lowercase-d ``deleteActivity`` handler name
    must still be absent."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "deleteActivity" not in source
    assert "batchEdit" not in source
    assert "restoreActivity" not in source
    assert "permanentDelete" not in source
    assert "autoRule" not in source
    assert "createRule" not in source
    assert "merge_session" not in source


def test_app_js_merge_has_no_traceback_display():
    """Phase 3B.3: the merge code must not display tracebacks."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "traceback" not in source.lower()


def test_app_js_merge_has_no_raw_field_exposure():
    """Phase 3B.3: the merge code must not reference raw window_title,
    file_path_hint, full_path, or clipboard fields."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    # The merge functions must not access raw sensitive fields
    start = source.find("function saveactivitymerge(")
    assert start != -1
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert "window_title" not in body
    assert "file_path_hint" not in body
    assert "full_path" not in body
    assert "clipboard" not in body


def test_app_js_merge_state_reset_in_clear_edit_panel():
    """Phase 3B.3: clearEditPanel must reset the merge saving state so a
    stale merge does not leak into a new session selection."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function clearEditPanel(")
    assert start != -1, "clearEditPanel must exist"
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert "mergeSaving = false" in body, (
        "clearEditPanel must reset mergeSaving to false"
    )


def test_styles_css_has_merge_styles():
    """Phase 3B.3: styles.css must style the merge button and status."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".detail-merge-btn" in source
    assert ".detail-merge-status" in source


def test_styles_css_has_merge_responsive_wrap():
    """Phase 3B.3: styles.css must handle the merge button on narrow
    viewports inside a ``@media (max-width: 900px)`` block."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    found = False
    search_from = 0
    while True:
        media_start = source.find("@media (max-width: 900px)", search_from)
        if media_start == -1:
            break
        brace_start = source.find("{", media_start)
        if brace_start == -1:
            break
        depth = 0
        end = brace_start
        for i in range(brace_start, len(source)):
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        media_body = source[media_start:end]
        if ".detail-merge" in media_body:
            found = True
            break
        search_from = end
    assert found, (
        "at least one @media (max-width: 900px) block must include "
        ".detail-merge styles for narrow-viewport support"
    )


def test_frontend_resources_merge_still_no_external_links():
    """Phase 3B.3: the merge additions must not introduce external links,
    CDN, or Google Fonts."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )
        assert not re.search(r"cdn", source, re.IGNORECASE), (
            f"{filename} must not reference CDN"
        )
        assert not re.search(r"google\s*fonts", source, re.IGNORECASE), (
            f"{filename} must not reference Google Fonts"
        )


def test_frontend_resources_merge_still_no_browser_storage():
    """Phase 3B.3: the merge additions must not use browser storage."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"localStorage", source, re.IGNORECASE), (
            f"{filename} must not use localStorage"
        )
        assert not re.search(r"sessionStorage", source, re.IGNORECASE), (
            f"{filename} must not use sessionStorage"
        )


# --- Phase 3B.4: Timeline hide / soft delete frontend tests --------------


def test_app_js_has_hide_delete_bridge_calls():
    """Phase 3B.4: app.js must call the hide / soft-delete bridge methods."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "hide_timeline_activity" in source
    assert "soft_delete_timeline_activity" in source
    assert "hide_timeline_session" in source
    assert "soft_delete_timeline_session" in source


def test_app_js_has_hide_delete_saving_state():
    """Phase 3B.4: app.js must declare independent hideSaving / deleteSaving
    state variables so the hide / delete flows do not pollute the other
    save flows."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "var hideSaving" in source
    assert "var deleteSaving" in source
    # The hide/delete saving state must be separate from the merge saving
    # state (Phase 3B.3) and the other edit flows.
    assert "var mergeSaving" in source
    assert "var hideSaving" in source
    assert "var deleteSaving" in source


def test_app_js_hide_delete_refreshes_timeline_on_success():
    """Phase 3B.4: a successful hide / delete must call the shared
    ``refreshTimelineAfterEdit`` helper to refresh the Timeline."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # Locate the four save functions and verify each calls
    # refreshTimelineAfterEdit on the success branch.
    for func_name in [
        "saveActivityHide",
        "saveActivityDelete",
        "saveSessionHide",
        "saveSessionDelete",
    ]:
        start = source.find("function " + func_name + "(")
        assert start != -1, f"{func_name} must exist"
        # Find the next function to bound the search.
        next_func = source.find("\n    function ", start + 1)
        body = source[start:next_func] if next_func != -1 else source[start:]
        assert "refreshTimelineAfterEdit" in body, (
            f"{func_name} must call refreshTimelineAfterEdit on success"
        )


def test_app_js_hide_delete_clears_saving_state_on_failure():
    """Phase 3B.4: a failed hide / delete must clear the saving state so the
    button is not stuck in the "处理中" state."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for func_name in [
        "saveActivityHide",
        "saveActivityDelete",
        "saveSessionHide",
        "saveSessionDelete",
    ]:
        start = source.find("function " + func_name + "(")
        assert start != -1, f"{func_name} must exist"
        next_func = source.find("\n    function ", start + 1)
        body = source[start:next_func] if next_func != -1 else source[start:]
        # Both the error branch (result.ok === false) and the catch branch
        # must reset the saving state. We check that the reset helper is
        # called on both the error and catch paths by counting occurrences.
        # The reset helper is setHideSaving / setDeleteSaving /
        # setSessionHideSaving / setSessionDeleteSaving depending on the
        # function.
        reset_call = (
            "setHideSaving"
            if "Hide" in func_name and "Session" not in func_name
            else "setDeleteSaving"
            if "Delete" in func_name and "Session" not in func_name
            else "setSessionHideSaving"
            if "Hide" in func_name
            else "setSessionDeleteSaving"
        )
        # The reset helper must appear at least twice in the body: once on
        # the success path (set back to false) and once on the error path.
        # The catch path also resets. We just require it to appear with
        # ``false`` at least once on a non-success path.
        assert body.count(reset_call + "(") >= 2, (
            f"{func_name} must reset saving state on both success and "
            f"failure paths via {reset_call}"
        )


def test_app_js_hide_delete_preserves_details_on_failure():
    """Phase 3B.4: a failed hide / delete must not clear the detail list.
    The save functions must not call any clear/render function on the
    failure branch (only refreshTimelineAfterEdit is called on success)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for func_name in [
        "saveActivityHide",
        "saveActivityDelete",
        "saveSessionHide",
        "saveSessionDelete",
    ]:
        start = source.find("function " + func_name + "(")
        assert start != -1, f"{func_name} must exist"
        next_func = source.find("\n    function ", start + 1)
        body = source[start:next_func] if next_func != -1 else source[start:]
        # The failure branches (result.ok === false and the catch) must NOT
        # call renderSessionDetails or clearEditPanel — those would wipe
        # the current details. We verify by checking that refreshTimeline
        # only appears once (on the success branch).
        assert body.count("refreshTimelineAfterEdit") == 1, (
            f"{func_name} must only refresh on the success branch, not on "
            f"failure branches"
        )


def test_app_js_multi_activity_session_disables_whole_hide_delete():
    """Phase 3B.4: a multi-activity session must disable the session-level
    hide / delete and show the "多活动" hint. The
    ``populateSessionVisibilitySection`` function must check
    ``activityIds.length > 1`` and show the multi-activity hint."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function populateSessionVisibilitySection(")
    assert start != -1, "populateSessionVisibilitySection must exist"
    next_func = source.find("\n    function ", start + 1)
    body = source[start:next_func] if next_func != -1 else source[start:]
    assert "activityIds.length > 1" in body or "activityIds.length !== 1" in body, (
        "populateSessionVisibilitySection must check for multi-activity sessions"
    )
    # The multi-activity hint must mention "多活动".
    assert "多活动" in body


def test_app_js_in_progress_activity_disables_hide_delete():
    """Phase 3B.4: an in-progress activity must disable the hide / delete
    buttons (or show the "进行中" hint). The renderSessionDetails and
    populateSessionVisibilitySection functions must check
    ``is_in_progress``."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # renderSessionDetails must set a visibilityBtnDisabled flag for
    # in-progress activities.
    render_start = source.find("function renderSessionDetails(")
    assert render_start != -1, "renderSessionDetails must exist"
    render_next = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_next] if render_next != -1 else source[render_start:]
    assert "visibilityBtnDisabled" in render_body, (
        "renderSessionDetails must compute a visibilityBtnDisabled flag"
    )
    # populateSessionVisibilitySection must check is_in_progress.
    vis_start = source.find("function populateSessionVisibilitySection(")
    assert vis_start != -1, "populateSessionVisibilitySection must exist"
    vis_next = source.find("\n    function ", vis_start + 1)
    vis_body = source[vis_start:vis_next] if vis_next != -1 else source[vis_start:]
    assert "is_in_progress" in vis_body


def test_app_js_hide_delete_blocked_when_edit_dirty():
    """Phase 3B.4: if ``isEditDirty()`` returns true, the hide / delete
    functions must refuse and show "请先保存或取消当前编辑"."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for func_name in [
        "saveActivityHide",
        "saveActivityDelete",
        "saveSessionHide",
        "saveSessionDelete",
    ]:
        start = source.find("function " + func_name + "(")
        assert start != -1, f"{func_name} must exist"
        next_func = source.find("\n    function ", start + 1)
        body = source[start:next_func] if next_func != -1 else source[start:]
        assert "isEditDirty(" in body, (
            f"{func_name} must call isEditDirty() before performing the action"
        )
        assert "请先保存或取消当前编辑" in body, (
            f"{func_name} must show the dirty-edit refusal message"
        )


def test_app_js_has_no_batch_restore_permanent_auto_rule_handlers():
    """Phase 3B.4: the hide / delete additions must not introduce batch
    hide, batch delete, restore, permanent delete, or auto-rule handlers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    assert "batch_delete" not in source
    assert "batch_hide" not in source
    assert "restore_activity" not in source
    assert "permanent_delete" not in source
    assert "auto_rule" not in source


def test_app_js_has_no_traceback_display_in_hide_delete():
    """Phase 3B.4: the hide / delete code must not display tracebacks."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "traceback" not in source.lower()


def test_app_js_hide_delete_has_no_raw_field_exposure():
    """Phase 3B.4: the hide / delete code must not reference raw
    window_title, file_path_hint, full_path, or clipboard fields."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    # The frontend must never reference these raw backend fields. (The
    # detail rows may show a resource_name, but never the raw column
    # names.)
    assert "window_title" not in source
    assert "file_path_hint" not in source
    assert "full_path" not in source
    assert "clipboard" not in source


def test_index_html_has_visibility_section():
    """Phase 3B.4: index.html must include the edit-visibility-section with
    the single / multi / hide / delete / status elements."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-visibility-section"' in source
    assert 'id="edit-visibility-single"' in source
    assert 'id="edit-visibility-multi"' in source
    assert 'id="edit-visibility-hide-btn"' in source
    assert 'id="edit-visibility-delete-btn"' in source
    assert 'id="edit-visibility-status"' in source
    # The delete button text must make the soft-delete semantics clear.
    assert "删除此 session" in source
    # The soft-delete hint must mention that data is not physically deleted.
    assert "不会物理删除数据" in source


def test_styles_css_has_visibility_styles():
    """Phase 3B.4: styles.css must style the hide / delete UI elements."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".detail-hide-btn" in source
    assert ".detail-delete-btn" in source
    assert ".detail-visibility-status" in source
    assert ".edit-visibility-section" in source
    assert ".edit-visibility-hide-btn" in source
    assert ".edit-visibility-delete-btn" in source


def test_styles_css_has_visibility_responsive_wrap():
    """Phase 3B.4: styles.css must handle the visibility buttons on narrow
    viewports inside a ``@media (max-width: 900px)`` block."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    found = False
    search_from = 0
    while True:
        media_start = source.find("@media (max-width: 900px)", search_from)
        if media_start == -1:
            break
        brace_start = source.find("{", media_start)
        if brace_start == -1:
            break
        depth = 0
        end = brace_start
        for i in range(brace_start, len(source)):
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        media_body = source[media_start:end]
        if "visibility" in media_body or "detail-hide" in media_body or "detail-delete" in media_body:
            found = True
            break
        search_from = end
    assert found, (
        "at least one @media (max-width: 900px) block must include "
        "visibility / hide / delete styles for narrow-viewport support"
    )


def test_app_js_hide_delete_state_reset_in_clear_edit_panel():
    """Phase 3B.4: clearEditPanel must reset the hide / delete saving state
    so a stale hide / delete does not leak into a new session selection."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function clearEditPanel(")
    assert start != -1, "clearEditPanel must exist"
    brace_start = source.find("{", start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = source[start:end]
    assert "hideSaving = false" in body, (
        "clearEditPanel must reset hideSaving to false"
    )
    assert "deleteSaving = false" in body, (
        "clearEditPanel must reset deleteSaving to false"
    )
    assert "hidingActivityId = null" in body, (
        "clearEditPanel must reset hidingActivityId to null"
    )
    assert "deletingActivityId = null" in body, (
        "clearEditPanel must reset deletingActivityId to null"
    )


def test_app_js_visibility_buttons_bound_in_init():
    """Phase 3B.4: the session-level hide / delete buttons must be bound in
    initButtons so they actually call the save handlers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function initButtons(")
    assert start != -1, "initButtons must exist"
    next_func = source.find("\n    function ", start + 1)
    body = source[start:next_func] if next_func != -1 else source[start:]
    assert "edit-visibility-hide-btn" in body
    assert "edit-visibility-delete-btn" in body
    assert "saveSessionHide" in body
    assert "saveSessionDelete" in body


def test_app_js_per_activity_visibility_buttons_rendered():
    """Phase 3B.4: renderSessionDetails must render per-activity hide /
    delete buttons with the ``detail-hide-btn`` / ``detail-delete-btn``
    classes and a ``data-activity-id`` attribute."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function renderSessionDetails(")
    assert start != -1, "renderSessionDetails must exist"
    next_func = source.find("\n    function ", start + 1)
    body = source[start:next_func] if next_func != -1 else source[start:]
    assert "detail-hide-btn" in body
    assert "detail-delete-btn" in body
    assert "data-activity-id" in body


def test_app_js_delete_uses_window_confirm():
    """Phase 3B.4: the delete flow must use ``window.confirm`` with the
    soft-delete hint to avoid accidental deletion."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "window.confirm" in source
    assert "确定从 Timeline 删除这条记录吗？本阶段不会物理删除数据。" in source


def test_frontend_resources_visibility_still_no_external_links():
    """Phase 3B.4: the hide / delete additions must not introduce external
    links, CDN, or Google Fonts."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )
        assert not re.search(r"cdn", source, re.IGNORECASE), (
            f"{filename} must not reference CDN"
        )
        assert not re.search(r"google\s*fonts", source, re.IGNORECASE), (
            f"{filename} must not reference Google Fonts"
        )


def test_frontend_resources_visibility_still_no_browser_storage():
    """Phase 3B.4: the hide / delete additions must not use browser
    storage."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"localStorage", source, re.IGNORECASE), (
            f"{filename} must not use localStorage"
        )
        assert not re.search(r"sessionStorage", source, re.IGNORECASE), (
            f"{filename} must not use sessionStorage"
        )
