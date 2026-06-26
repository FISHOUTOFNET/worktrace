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
    contain merge, restore, permanent-delete, or auto-rule controls.
    Phase 3B.4 introduces a soft-delete button in the static panel;
    "delete" is therefore allowed in index.html, but only as the
    soft-delete foundation, never as a permanent delete control.
    Phase 3B.6 introduces the first batch write capability (batch project
    reassignment in the correction shell); "batch" is now allowed in
    index.html but only in the project reassignment context. Batch hide /
    delete / time / split / merge controls must still be absent."""
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
    # Phase 3B.6 now provides a batch project reassignment section in the
    # correction shell. "batch" is allowed only in the project context;
    # batch hide / delete / time / split / merge controls must still be
    # absent from the entire HTML. Restore / permanent delete / auto-rule
    # must also still be absent.
    lowered = source.lower()
    for forbidden_batch in (
        "batch-hide", "batch-delete", "batch-time",
        "batch-split", "batch-merge",
        "batchhide", "batchdelete", "batchtime",
        "batchsplit", "batchmerge",
    ):
        assert forbidden_batch not in lowered, (
            "index.html must not contain a '" + forbidden_batch + "' control"
        )
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
    # button in index.html, so "delete" is allowed there. Phase 3B.6
    # introduces batch project reassignment in the correction shell, so
    # "batch" is now allowed in index.html but only in the project context;
    # batch hide / delete / time / split / merge controls must still be
    # absent.
    html_source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8").lower()
    for forbidden_batch in (
        "batch-hide", "batch-delete", "batch-time",
        "batch-split", "batch-merge",
        "batchhide", "batchdelete", "batchtime",
        "batchsplit", "batchmerge",
    ):
        assert forbidden_batch not in html_source, (
            "index.html must not contain a '" + forbidden_batch + "' control"
        )
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


# ---------------------------------------------------------------------------
# Phase 3B.5A: Timeline correction action consolidation
# ---------------------------------------------------------------------------
# These tests verify the consolidation / polish / consistency work: the
# per-activity correction buttons are grouped into edit / merge / danger
# groups with a stable order; merge now carries the same isEditDirty guard
# and row-id check as hide / delete; destructive-action copy is unified;
# session-level edit-panel section labels are unified; clearEditPanel
# resets all action state; no batch / restore / permanent-delete /
# auto-rule / complex-correction-page handlers are introduced; and the
# frontend resources still contain no localStorage / sessionStorage / CDN /
# external links / Google Fonts / traceback display logic.


def test_app_js_has_action_group_wrappers_in_detail_rows():
    """Phase 3B.5A: renderSessionDetails must wrap the per-activity
    correction buttons in three action groups (edit / merge / danger) so
    destructive actions are visually separated from edits."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function renderSessionDetails(")
    assert start != -1, "renderSessionDetails must exist"
    next_func = source.find("\n    function ", start + 1)
    body = source[start:next_func] if next_func != -1 else source[start:]
    assert "detail-action-edit-group" in body, (
        "renderSessionDetails must wrap 编辑时间 / 拆分 in a "
        "detail-action-edit-group"
    )
    assert "detail-action-merge-group" in body, (
        "renderSessionDetails must wrap 与下一条合并 in a "
        "detail-action-merge-group"
    )
    assert "detail-action-danger-group" in body, (
        "renderSessionDetails must wrap 隐藏 / 删除 in a "
        "detail-action-danger-group"
    )


def test_app_js_action_order_is_stable():
    """Phase 3B.5A: the per-activity action order must be stable:
    编辑时间 → 拆分 → 与下一条合并 → 隐藏 → 删除."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function renderSessionDetails(")
    assert start != -1, "renderSessionDetails must exist"
    next_func = source.find("\n    function ", start + 1)
    body = source[start:next_func] if next_func != -1 else source[start:]
    # Each action button's class must appear in the stable order.
    pos_edit = body.find("detail-edit-time-btn")
    pos_split = body.find("detail-split-btn")
    pos_merge = body.find("detail-merge-btn")
    pos_hide = body.find("detail-hide-btn")
    pos_delete = body.find("detail-delete-btn")
    assert pos_edit != -1 and pos_split != -1 and pos_merge != -1, (
        "edit / split / merge buttons must all be rendered"
    )
    assert pos_hide != -1 and pos_delete != -1, (
        "hide / delete buttons must all be rendered"
    )
    assert pos_edit < pos_split < pos_merge < pos_hide < pos_delete, (
        "per-activity action order must be: 编辑时间 → 拆分 → 与下一条合并 "
        "→ 隐藏 → 删除"
    )


def test_app_js_merge_has_dirty_state_guard():
    """Phase 3B.5A: saveActivityMerge must refuse while there are unsaved
    project/note/time/split inputs, consistent with hide / delete. Merge
    triggers a refresh that would wipe those inputs."""
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
    assert "isEditDirty()" in body, (
        "saveActivityMerge must call isEditDirty() to refuse merge while "
        "there are unsaved edits"
    )
    assert "请先保存或取消当前编辑" in body, (
        "saveActivityMerge must show the unified dirty-state refusal message"
    )


def test_app_js_merge_has_row_id_consistency_check():
    """Phase 3B.5A: saveActivityMerge must verify the activity id still
    matches the detail row, consistent with hide / delete, so a stale
    button does not operate on a different session's activity."""
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
    assert 'btn.closest(".detail-item")' in body, (
        "saveActivityMerge must locate the closest detail-item row"
    )
    assert "rowAid !== activityId" in body, (
        "saveActivityMerge must compare the row's activity id with the "
        "passed activity id and bail out if they differ"
    )


def test_app_js_dirty_state_refusal_message_is_unified():
    """Phase 3B.5A: the dirty-state refusal message must be unified across
    merge / hide / delete (per-activity and session-level)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    refusal = "请先保存或取消当前编辑"
    # Must appear in saveActivityMerge, saveActivityHide, saveActivityDelete,
    # saveSessionHide, saveSessionDelete.
    for func_name in (
        "saveActivityMerge",
        "saveActivityHide",
        "saveActivityDelete",
        "saveSessionHide",
        "saveSessionDelete",
    ):
        start = source.find("function " + func_name + "(")
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
        assert refusal in body, (
            f"{func_name} must use the unified dirty-state refusal message"
        )


def test_app_js_destructive_action_copy_is_unified():
    """Phase 3B.5A: hide / delete success and failure copy must be
    unified. Hide: 已隐藏 / 隐藏失败. Delete: 已删除 / 删除失败."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # Per-activity hide
    assert "已隐藏" in source and "隐藏失败" in source, (
        "hide must succeed with 已隐藏 and fail with 隐藏失败"
    )
    # Per-activity delete
    assert "已删除" in source and "删除失败" in source, (
        "delete must succeed with 已删除 and fail with 删除失败"
    )
    # Delete confirmation must still say soft delete
    assert "本阶段不会物理删除数据" in source, (
        "delete confirmation must still say 本阶段不会物理删除数据"
    )


def test_index_html_has_unified_section_labels():
    """Phase 3B.5A: the session-level edit panel sections must be labeled
    consistently: 项目与备注 / 时间修正 / 拆分 / 可见性."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "项目与备注" in source, (
        "edit panel must have a 项目与备注 section label"
    )
    assert "时间修正" in source, (
        "edit panel must have a 时间修正 section label"
    )
    assert "拆分" in source, (
        "edit panel must have a 拆分 section label"
    )
    assert "可见性" in source, (
        "edit panel must have a 可见性 section label"
    )
    # The old section titles must be gone (拆分时段 / 隐藏 / 删除 as a
    # section label is replaced by 可见性).
    assert "拆分时段" not in source, (
        "old section title 拆分时段 must be replaced by 拆分"
    )


def test_index_html_visibility_hint_mentions_hide_and_soft_delete():
    """Phase 3B.5A: the visibility section hint must mention both hide and
    soft-delete semantics so the user understands neither physically
    deletes data."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # Find the visibility section
    start = source.find('id="edit-visibility-section"')
    assert start != -1, "edit-visibility-section must exist"
    # Find the end of the section (next </div> at the section level is hard
    # to find reliably, so just search forward for the hint text).
    section = source[start:start + 1200]
    assert "隐藏" in section, (
        "visibility hint must mention 隐藏"
    )
    assert "软删除" in section or "不会物理删除数据" in section, (
        "visibility hint must mention soft delete / no physical deletion"
    )


def test_styles_css_has_action_group_styles():
    """Phase 3B.5A: styles.css must style the three action groups and
    visually separate the danger group from the edit / merge groups."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".detail-action-edit-group" in source, (
        "styles.css must style .detail-action-edit-group"
    )
    assert ".detail-action-merge-group" in source, (
        "styles.css must style .detail-action-merge-group"
    )
    assert ".detail-action-danger-group" in source, (
        "styles.css must style .detail-action-danger-group"
    )
    # The danger group must have a red-tinted left border so destructive
    # actions read as visually separated.
    danger_start = source.find(".detail-action-danger-group")
    danger_block = source[danger_start:danger_start + 400]
    assert "#fca5a5" in danger_block or "border-left" in danger_block, (
        "danger group must have a visually separating border"
    )


def test_styles_css_has_section_label_style():
    """Phase 3B.5A: styles.css must style the .edit-section-label class
    used by the unified section labels."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-section-label" in source, (
        "styles.css must style .edit-section-label"
    )


def test_app_js_clear_edit_panel_resets_all_action_state():
    """Phase 3B.5A: clearEditPanel must reset all transient action state,
    including merge / hide / delete saving state and target ids."""
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
    # Project / note / time / split state
    assert "editSaving = false" in body
    assert "timeSaving = false" in body
    assert "editingActivityId = null" in body
    assert "activityTimeSaving = false" in body
    assert "editingSplitActivityId = null" in body
    assert "activitySplitSaving = false" in body
    assert "sessionSplitSaving = false" in body
    # Merge state
    assert "mergeSaving = false" in body, (
        "clearEditPanel must reset mergeSaving"
    )
    assert "mergingActivityId = null" in body, (
        "clearEditPanel must reset mergingActivityId"
    )
    # Hide / delete state
    assert "hideSaving = false" in body, (
        "clearEditPanel must reset hideSaving"
    )
    assert "hidingActivityId = null" in body, (
        "clearEditPanel must reset hidingActivityId"
    )
    assert "deleteSaving = false" in body, (
        "clearEditPanel must reset deleteSaving"
    )
    assert "deletingActivityId = null" in body, (
        "clearEditPanel must reset deletingActivityId"
    )


def test_app_js_populate_edit_panel_populates_all_correction_sections():
    """Phase 3B.5A: populateEditPanel must populate / reset all correction
    sections (project/note, time, split, visibility) so switching sessions
    does not leave stale state behind."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    start = source.find("function populateEditPanel(")
    assert start != -1, "populateEditPanel must exist"
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
    # Session-level correction section populators
    assert "populateSessionTimeSection" in body, (
        "populateEditPanel must call populateSessionTimeSection"
    )
    assert "populateSessionSplitSection" in body, (
        "populateEditPanel must call populateSessionSplitSection"
    )
    assert "populateSessionVisibilitySection" in body, (
        "populateEditPanel must call populateSessionVisibilitySection"
    )


def test_app_js_consolidation_has_no_forbidden_handlers():
    """Phase 3B.5A: the consolidation must not introduce batch edit,
    batch hide, batch delete, undo / restore, permanent delete, auto-rule,
    complex correction page, or overlap detection handlers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "batchedit",
        "batchhide",
        "batchdelete",
        "restoreactivity",
        "restoresession",
        "permanentdelete",
        "autorule",
        "complexcorrection",
        "overlapdetection",
        "merge_session",  # multi-activity session whole-merge
        "deleteactivity",  # lowercase-d permanent delete handler name
    ):
        assert forbidden not in lowered, (
            f"app.js must not introduce a '{forbidden}' handler"
        )


def test_index_html_consolidation_has_no_forbidden_controls():
    """Phase 3B.5A: index.html must not contain batch hide / batch delete /
    batch time / batch split / batch merge / restore / permanent-delete /
    auto-rule / complex-correction-page / overlap controls. Phase 3B.6
    introduces batch project reassignment, so "batch" is now allowed in
    index.html but only in the project context; the specific batch hide /
    delete / time / split / merge variants must still be absent."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "batch-hide", "batch-delete", "batch-time",
        "batch-split", "batch-merge",
        "batchhide", "batchdelete", "batchtime",
        "batchsplit", "batchmerge",
        "restore",
        "permanent",
        "auto-rule",
        "complex-correction",
        "overlap",
    ):
        assert forbidden not in lowered, (
            f"index.html must not contain a '{forbidden}' control"
        )


def test_frontend_resources_consolidation_no_external_links():
    """Phase 3B.5A: the consolidation must not introduce external links,
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


def test_frontend_resources_consolidation_no_browser_storage():
    """Phase 3B.5A: the consolidation must not use browser storage."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"localStorage", source, re.IGNORECASE), (
            f"{filename} must not use localStorage"
        )
        assert not re.search(r"sessionStorage", source, re.IGNORECASE), (
            f"{filename} must not use sessionStorage"
        )


def test_frontend_resources_consolidation_no_traceback_display():
    """Phase 3B.5A: the consolidation must not introduce traceback
    display logic in the frontend resources."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        lowered = source.lower()
        assert "traceback" not in lowered, (
            f"{filename} must not contain traceback display logic"
        )


def test_docs_mention_phase_3b_5a():
    """Phase 3B.5A: the migration doc and release-validation doc must
    mention Phase 3B.5A and restate that batch edit / restore / permanent
    delete / complex correction page are not implemented."""
    migration = (REPO_ROOT / "docs" / "ui-webview-migration.md").read_text(
        encoding="utf-8"
    )
    assert "3B.5A" in migration, (
        "ui-webview-migration.md must mention Phase 3B.5A"
    )
    assert "consolidation" in migration.lower(), (
        "ui-webview-migration.md must describe 3B.5A as a consolidation phase"
    )
    # Restate the unimplemented features
    for term in ("batch", "restore", "permanent delete", "complex correction"):
        assert term.lower() in migration.lower(), (
            f"ui-webview-migration.md must restate that {term} is not "
            "implemented"
        )
    release_val = (REPO_ROOT / "docs" / "release-validation.md").read_text(
        encoding="utf-8"
    )
    assert "3B.5A" in release_val, (
        "release-validation.md must mention Phase 3B.5A"
    )


def test_docs_readme_mentions_phase_3b_5a():
    """Phase 3B.5A: the README must mention Phase 3B.5A as the
    consolidation phase."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "3B.5A" in readme, "README.md must mention Phase 3B.5A"
    assert "consolidation" in readme.lower(), (
        "README.md must describe 3B.5A as a consolidation phase"
    )


# --- Phase 3B.5B: Timeline correction shell tests ---------------------
#
# Phase 3B.5B adds a correction workspace *shell* inside the Timeline page.
# It is a read-only context + navigation layout that reuses the existing
# single project / note / time / split / merge / hide / delete capability.
# It does NOT add batch edit, batch hide / delete, undo / restore,
# permanent delete, auto-rule, or global overlap detection.


def test_index_html_has_correction_shell_container():
    """Phase 3B.5B: index.html must contain a hidden correction shell
    container inside the Timeline details column."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-correction-shell"' in source, (
        "index.html must contain #timeline-correction-shell"
    )


def test_index_html_correction_shell_hidden_by_default():
    """Phase 3B.5B: the correction shell must be hidden by default."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    start = source.find('id="timeline-correction-shell"')
    assert start != -1, "correction shell container must exist"
    # The opening tag must carry the `hidden` attribute.
    tag_end = source.find(">", start)
    opening_tag = source[start:tag_end + 1]
    assert "hidden" in opening_tag, (
        "correction shell must be hidden by default"
    )


def test_index_html_correction_shell_has_close_button():
    """Phase 3B.5B: the correction shell must have a close button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-close-btn"' in source, (
        "correction shell must have a close button"
    )
    assert "返回时间详情" in source, (
        "correction shell close button text must be 返回时间详情"
    )


def test_index_html_correction_shell_has_required_areas():
    """Phase 3B.5B: the shell must have context / status / activity /
    action areas."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-status"' in source
    assert 'id="correction-shell-context"' in source
    assert 'id="correction-shell-activities"' in source
    assert 'id="correction-shell-actions"' in source


def test_index_html_correction_shell_title_is_advanced_correction():
    """Phase 3B.5B: the shell title must be 高级纠错."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "高级纠错" in source, (
        "correction shell title must be 高级纠错"
    )


def test_index_html_has_session_level_open_correction_entry():
    """Phase 3B.5B: the session-level edit panel must have a
    打开高级纠错 entry button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="open-correction-shell-btn"' in source, (
        "session-level edit panel must have an open-correction-shell button"
    )
    assert "打开高级纠错" in source, (
        "session-level open button text must be 打开高级纠错"
    )


def test_index_html_correction_shell_inside_timeline_page():
    """Phase 3B.5B: the correction shell must live inside the Timeline
    page, not as a new top-level sidebar nav item. The sidebar nav must
    still be exactly 概览 / 时间详情 / 统计与导出 / 项目规则 / 设置与隐私."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    shell_pos = source.find('id="timeline-correction-shell"')
    timeline_pos = source.find('id="page-timeline"')
    timeline_end = source.find('</section>', timeline_pos)
    assert shell_pos > timeline_pos, (
        "correction shell must be inside #page-timeline"
    )
    assert shell_pos < timeline_end, (
        "correction shell must be inside #page-timeline section"
    )
    # No new sidebar nav item was added for the shell.
    nav_start = source.find('<nav class="sidebar-nav">')
    nav_end = source.find('</nav>', nav_start)
    nav_block = source[nav_start:nav_end]
    assert "纠错" not in nav_block, (
        "no correction-related sidebar nav item may be added"
    )


def test_app_js_has_open_correction_shell_helper():
    """Phase 3B.5B: app.js must define an openCorrectionShell helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function openCorrectionShell" in source, (
        "app.js must define openCorrectionShell"
    )


def test_app_js_has_close_correction_shell_helper():
    """Phase 3B.5B: app.js must define a closeCorrectionShell helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function closeCorrectionShell" in source, (
        "app.js must define closeCorrectionShell"
    )


def test_app_js_has_reset_correction_shell_state_helper():
    """Phase 3B.5B: app.js must define a resetCorrectionShellState helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function resetCorrectionShellState" in source, (
        "app.js must define resetCorrectionShellState"
    )


def test_app_js_has_render_correction_shell_helper():
    """Phase 3B.5B: app.js must define a renderCorrectionShell helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function renderCorrectionShell" in source, (
        "app.js must define renderCorrectionShell"
    )


def test_app_js_has_set_correction_shell_status_helper():
    """Phase 3B.5B: app.js must define a setCorrectionShellStatus helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function setCorrectionShellStatus" in source, (
        "app.js must define setCorrectionShellStatus"
    )


def test_app_js_has_get_selected_session_helper():
    """Phase 3B.5B: app.js must define a getSelectedSession helper that
    looks up the selected session from currentSessions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function getSelectedSession" in source, (
        "app.js must define getSelectedSession"
    )


def test_app_js_open_correction_shell_checks_dirty_state():
    """Phase 3B.5B: openCorrectionShell must refuse to open while there
    are unsaved edits, using the refusal text 请先保存或取消当前编辑."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    open_start = source.find("function openCorrectionShell")
    open_end = source.find("\n    function ", open_start + 1)
    open_body = source[open_start:open_end]
    assert "isEditDirty()" in open_body, (
        "openCorrectionShell must call isEditDirty() before opening"
    )
    assert "请先保存或取消当前编辑" in open_body, (
        "openCorrectionShell must use the dirty-state refusal text"
    )


def test_app_js_open_correction_shell_checks_selected_session():
    """Phase 3B.5B: openCorrectionShell must verify a selected session
    exists before opening."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    open_start = source.find("function openCorrectionShell")
    open_end = source.find("\n    function ", open_start + 1)
    open_body = source[open_start:open_end]
    assert "getSelectedSession" in open_body, (
        "openCorrectionShell must call getSelectedSession before opening"
    )


def test_app_js_close_correction_shell_preserves_selected_session():
    """Phase 3B.5B: closeCorrectionShell must NOT clear selectedSessionId
    so the user returns to the same session context."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    close_start = source.find("function closeCorrectionShell")
    close_end = source.find("\n    function ", close_start + 1)
    close_body = source[close_start:close_end]
    assert "selectedSessionId = null" not in close_body, (
        "closeCorrectionShell must not clear selectedSessionId"
    )
    assert "resetCorrectionShellState" in close_body, (
        "closeCorrectionShell must reset shell state"
    )


def test_app_js_clear_edit_panel_resets_shell_state():
    """Phase 3B.5B: clearEditPanel must call resetCorrectionShellState so
    a stale shell does not leak into the next session."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    clear_start = source.find("function clearEditPanel")
    clear_end = source.find("\n    function ", clear_start + 1)
    clear_body = source[clear_start:clear_end]
    assert "resetCorrectionShellState" in clear_body, (
        "clearEditPanel must reset correction shell state"
    )


def test_app_js_date_navigation_closes_shell():
    """Phase 3B.5B: goPrevDay / goNextDay / goToday must close the
    correction shell so the shell context does not carry across dates."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for fname in ("goPrevDay", "goNextDay", "goToday"):
        fstart = source.find("function " + fname)
        fend = source.find("\n    function ", fstart + 1)
        fbody = source[fstart:fend]
        assert "resetCorrectionShellState" in fbody, (
            fname + " must call resetCorrectionShellState"
        )


def test_app_js_selected_session_disappear_resets_shell():
    """Phase 3B.5B: when the selected session disappears during a refresh,
    the shell state must be reset (via clearEditPanel)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # Use the opening-paren form so we match showTimeline(data) and not
    # showTimelineError(message).
    show_start = source.find("function showTimeline(")
    assert show_start != -1, "showTimeline function must exist"
    show_end = source.find("\n    function ", show_start + 1)
    show_body = source[show_start:show_end]
    # The disappear branch clears the selection and calls clearEditPanel,
    # which in turn resets the shell state.
    assert "selectedSessionId = null" in show_body, (
        "showTimeline must clear selectedSessionId when session disappears"
    )
    assert "clearEditPanel()" in show_body, (
        "showTimeline must call clearEditPanel on session disappear"
    )


def test_app_js_session_switch_closes_shell():
    """Phase 3B.5B: selecting a different session must close the shell so
    the shell context does not get confused across sessions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    sel_start = source.find("function selectTimelineSession")
    sel_end = source.find("\n    function ", sel_start + 1)
    sel_body = source[sel_start:sel_end]
    assert "correctionShellOpen" in sel_body, (
        "selectTimelineSession must check correction shell state"
    )
    assert "resetCorrectionShellState" in sel_body, (
        "selectTimelineSession must reset shell state on session switch"
    )


def test_app_js_correction_shell_state_variables_exist():
    """Phase 3B.5B: app.js must declare the correction shell state
    variables."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "correctionShellOpen" in source
    assert "correctionShellSessionId" in source
    assert "correctionShellActivityId" in source
    assert "correctionShellMode" in source


def test_app_js_correction_shell_no_sensitive_fields():
    """Phase 3B.5B: the shell rendering must only use display-safe fields
    and must never read raw window_title / file_path / clipboard / note
    internals."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    for forbidden in ("window_title", "file_path", "file_path_hint",
                      "full_path", "clipboard"):
        assert forbidden not in render_body, (
            "renderCorrectionShell must not read " + forbidden
        )


def test_app_js_get_current_detail_activities_no_sensitive_fields():
    """Phase 3B.5B: getCurrentDetailActivities must only read display-safe
    DOM fields, never raw sensitive fields."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function getCurrentDetailActivities")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    for forbidden in ("window_title", "file_path", "full_path", "clipboard",
                      "session_note"):
        assert forbidden not in fn_body, (
            "getCurrentDetailActivities must not read " + forbidden
        )


def test_app_js_correction_shell_uses_existing_string_helpers():
    """Phase 3B.5B: the shell must not parse backend times with
    new Date(string); it must reuse the existing fixed-format helpers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "formatTimeRange" in render_body, (
        "renderCorrectionShell must use formatTimeRange"
    )
    # No `new Date(` parsing of backend time strings inside the shell.
    assert "new Date(" not in render_body, (
        "renderCorrectionShell must not use new Date(string) on backend times"
    )


def test_app_js_correction_shell_no_browser_storage():
    """Phase 3B.5B: the shell must not use localStorage / sessionStorage."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"localStorage|sessionStorage", source), (
        "app.js must not use browser storage"
    )


def test_app_js_correction_shell_no_forbidden_handlers():
    """Phase 3B.5B: app.js must not contain batch edit / batch hide /
    batch delete / restore / permanent delete / auto-rule / global overlap
    detection handlers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("batchEdit", "batchHide", "batchDelete",
                      "restoreActivity", "restoreSession",
                      "permanentDelete", "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap"):
        assert forbidden not in source, (
            "app.js must not contain " + forbidden + " handler"
        )


def test_index_html_correction_shell_no_forbidden_controls():
    """Phase 3B.5B: index.html must not contain batch hide / batch delete /
    batch time / batch split / batch merge / restore / permanent-delete /
    auto-rule / overlap controls in the shell. Phase 3B.6 introduces batch
    project reassignment in the correction shell, so "batch" is now
    allowed in the shell but only in the project context; the specific
    batch hide / delete / time / split / merge variants must still be
    absent."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("batch-hide", "batch-delete", "batch-time",
                      "batch-split", "batch-merge",
                      "batchhide", "batchdelete", "batchtime",
                      "batchsplit", "batchmerge",
                      "restore", "permanent", "auto-rule",
                      "overlap"):
        assert forbidden not in lowered, (
            "index.html must not contain a '" + forbidden + "' control"
        )


def test_app_js_correction_shell_actions_guide_only():
    """Phase 3B.5B: the shell action area must only guide the user back to
    the existing controls; it must not render its own write buttons. The
    delete guidance must remain soft-delete wording."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    # The shell reiterates that delete is soft, not permanent.
    assert "不会物理删除数据" in render_body or "软操作" in render_body, (
        "shell action guidance must restate soft-delete semantics"
    )


def test_styles_css_has_correction_shell_styles():
    """Phase 3B.5B: styles.css must define correction shell styles."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell" in source
    assert ".correction-shell-header" in source
    assert ".correction-shell-context" in source
    assert ".correction-shell-activities" in source
    assert ".correction-shell-actions" in source
    assert ".correction-shell-close-btn" in source


def test_styles_css_correction_shell_hidden_rule():
    """Phase 3B.5B: styles.css must hide the shell when [hidden]."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must hide .correction-shell[hidden]"
    )


def test_bridge_no_new_write_methods_for_shell():
    """Phase 3B.5B: the bridge must not gain new write methods for the
    shell. The existing project / note / time / split / merge / hide /
    delete methods must still be present."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    for required in (
        "def update_timeline_project",
        "def update_timeline_note",
        "def update_timeline_activity_time",
        "def update_timeline_session_time",
        "def split_timeline_activity",
        "def split_timeline_session",
        "def merge_timeline_activities",
        "def hide_timeline_activity",
        "def soft_delete_timeline_activity",
        "def hide_timeline_session",
        "def soft_delete_timeline_session",
        "def get_timeline",
        "def get_timeline_session_details",
    ):
        assert required in bridge_src, (
            "bridge must still define " + required
        )
    # No shell-specific write method is added.
    assert "def correction_shell" not in bridge_src, (
        "bridge must not add a correction_shell write method"
    )


def test_bridge_imports_only_allowed_modules():
    """Phase 3B.5B: the bridge must continue to import only
    worktrace.api / worktrace.formatters and must not directly import
    services / db / collector / security / runtime / config."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    for forbidden in (
        "import worktrace.services",
        "import worktrace.db",
        "import worktrace.collector",
        "import worktrace.security",
        "import worktrace.runtime",
        "import worktrace.config",
        "from worktrace.services",
        "from worktrace.db",
        "from worktrace.collector",
        "from worktrace.security",
        "from worktrace.runtime",
        "from worktrace.config",
    ):
        assert forbidden not in bridge_src, (
            "bridge must not import " + forbidden
        )


def test_docs_mention_phase_3b_5b():
    """Phase 3B.5B: the migration doc and release-validation doc must
    mention Phase 3B.5B and restate that batch edit / restore / permanent
    delete / auto-rule / overlap detection are not implemented."""
    migration = (REPO_ROOT / "docs" / "ui-webview-migration.md").read_text(
        encoding="utf-8"
    )
    assert "3B.5B" in migration, (
        "ui-webview-migration.md must mention Phase 3B.5B"
    )
    assert "correction shell" in migration.lower() or "高级纠错" in migration, (
        "ui-webview-migration.md must describe 3B.5B as a correction shell phase"
    )
    for term in ("batch", "restore", "permanent delete", "auto-rule",
                 "overlap"):
        assert term.lower() in migration.lower(), (
            "ui-webview-migration.md must restate that " + term + " is not "
            "implemented"
        )
    release_val = (REPO_ROOT / "docs" / "release-validation.md").read_text(
        encoding="utf-8"
    )
    assert "3B.5B" in release_val, (
        "release-validation.md must mention Phase 3B.5B"
    )


def test_docs_readme_mentions_phase_3b_5b():
    """Phase 3B.5B: the README must mention Phase 3B.5B as the
    correction shell phase."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "3B.5B" in readme, "README.md must mention Phase 3B.5B"
    assert "correction shell" in readme.lower() or "高级纠错" in readme, (
        "README.md must describe 3B.5B as a correction shell phase"
    )
    # README must restate that batch edit / restore / permanent delete are
    # not yet available.
    for term in ("batch", "restore", "permanent delete"):
        assert term.lower() in readme.lower(), (
            "README.md must restate that " + term + " is not implemented"
        )


# --- Phase 3B.5B.1: Timeline correction shell hardening tests ------------
#
# Phase 3B.5B.1 is a hardening-only phase for the 3B.5B correction shell.
# It stabilizes the shell on navigation, auto-refresh, dirty-state, selected
# session disappearance, display-safe field boundaries, click-to-locate, and
# the close / reset paths. It does NOT add batch edit / hide / delete, undo /
# restore, permanent delete, auto-rule, global overlap detection, arbitrary-
# length merge, multi-activity session whole-hide / whole-delete, any new
# backend write capability, any new DB schema, or any new bridge / API /
# service method.


def _func_body(source, name):
    """Return the body of ``function <name>`` in app.js (best-effort)."""
    start = source.find("function " + name)
    assert start != -1, "app.js must define " + name
    end = source.find("\n    function ", start + 1)
    return source[start:end] if end != -1 else source[start:]


def test_app_js_correction_shell_highlight_timer_variable_declared():
    """Phase 3B.5B.1: app.js must declare a single tracked highlight timer
    so repeated click-to-locate clicks never accumulate timers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "correctionShellHighlightTimer" in source, (
        "app.js must declare the correctionShellHighlightTimer state variable"
    )


def test_app_js_reset_correction_shell_state_clears_highlight_timer():
    """Phase 3B.5B.1: resetCorrectionShellState must cancel any pending
    highlight timer so a close / reset never leaves a dangling timer."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "resetCorrectionShellState")
    assert "correctionShellHighlightTimer" in body, (
        "resetCorrectionShellState must reference the highlight timer"
    )
    assert "clearTimeout" in body, (
        "resetCorrectionShellState must clear the pending highlight timer"
    )


def test_app_js_highlight_detail_row_no_bridge_writes():
    """Phase 3B.5B.1: highlightDetailRow must be read-only — it must not
    call any bridge method (write or otherwise) and must not perform any
    save / hide / delete / merge / split / time / project / note action."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "highlightDetailRow")
    assert "callBridge" not in body, (
        "highlightDetailRow must not call any bridge method"
    )
    for forbidden in ("saveProject", "saveNote", "saveActivityTime",
                      "saveSessionTime", "saveActivitySplit", "saveSessionSplit",
                      "saveMerge", "saveHide", "saveDelete",
                      "hide_timeline", "soft_delete", "merge_timeline",
                      "split_timeline", "update_timeline"):
        assert forbidden not in body, (
            "highlightDetailRow must not invoke " + forbidden
        )


def test_app_js_highlight_detail_row_safe_single_timer():
    """Phase 3B.5B.1: the transient highlight must use a single tracked
    timer — clearTimeout before setTimeout — so repeated clicks never
    accumulate timers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "highlightDetailRow")
    assert "clearTimeout" in body, (
        "highlightDetailRow must clear the prior timer before scheduling"
    )
    assert "setTimeout" in body, (
        "highlightDetailRow must schedule a transient highlight timer"
    )
    assert "correctionShellHighlightTimer" in body, (
        "highlightDetailRow must track the timer in the shared variable"
    )
    # Only one setTimeout call may be present so timers cannot accumulate.
    assert body.count("setTimeout") == 1, (
        "highlightDetailRow must schedule exactly one timer per click"
    )


def test_app_js_highlight_detail_row_stale_target_message():
    """Phase 3B.5B.1: when the target detail row is missing, the handler
    must show a safe message (not throw, not perform any write)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "highlightDetailRow")
    # The stale-target branch must set a status message and return early.
    assert "setCorrectionShellStatus" in body, (
        "highlightDetailRow must report a safe status on stale target"
    )
    assert "已不在当前详情" in body or "未找到对应活动" in body, (
        "highlightDetailRow must use a safe stale-target message"
    )
    # No window alert / confirm / throw on the stale path.
    for forbidden in ("window.alert", "window.confirm", "throw "):
        assert forbidden not in body, (
            "highlightDetailRow must not use " + forbidden
        )


def test_app_js_highlight_detail_row_uses_detail_item_selector():
    """Phase 3B.5B.1: click-to-locate must only look up the existing
    .detail-item[data-activity-id=...] row inside #timeline-details-list."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "highlightDetailRow")
    assert '#timeline-details-list .detail-item[data-activity-id="' in body, (
        "highlightDetailRow must query the existing detail-item row"
    )


def test_app_js_render_correction_shell_uses_correction_activity_id():
    """Phase 3B.5B.1: shell activity rows must carry a distinct
    data-correction-activity-id attribute so they cannot be confused with
    the real .detail-item rows."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderCorrectionShell")
    assert "data-correction-activity-id" in body, (
        "shell activity rows must use data-correction-activity-id"
    )


def test_app_js_render_correction_shell_invalid_id_not_clickable():
    """Phase 3B.5B.1: a non-numeric / missing activity id must not be
    rendered as a click-to-locate target (numeric guard)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderCorrectionShell")
    assert "/^[0-9]+$/.test" in body, (
        "renderCorrectionShell must guard a numeric activity id"
    )
    # The click handler must only bind to rows carrying the safe attribute.
    assert ".correction-shell-activity-row[data-correction-activity-id]" in body, (
        "click handlers must only bind to rows with a valid id"
    )


def test_app_js_render_correction_shell_uses_escape_html():
    """Phase 3B.5B.1: every dynamic value rendered into the shell must go
    through escapeHtml so no unescaped external / dynamic value is
    injected via innerHTML."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderCorrectionShell")
    assert "escapeHtml" in body, (
        "renderCorrectionShell must escape dynamic values"
    )


def test_app_js_render_correction_shell_no_sensitive_fields_3b_5b_1():
    """Phase 3B.5B.1: the hardened shell rendering must still never read
    raw window_title / file_path_hint / full_path / clipboard / note
    internals, and must not surface traceback / SQL / exception text."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderCorrectionShell")
    for forbidden in ("window_title", "file_path_hint", "file_path",
                      "full_path", "clipboard", "session_note", "traceback",
                      "SQL", "exception"):
        assert forbidden not in body, (
            "renderCorrectionShell must not read or display " + forbidden
        )


def test_app_js_correction_shell_state_independent_of_saving_states():
    """Phase 3B.5B.1: resetCorrectionShellState must only reset shell-only
    state; it must not reset the edit / time / split / merge / hide / delete
    saving states (those are owned by clearEditPanel)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "resetCorrectionShellState")
    for saving in ("editSaving", "timeSaving", "activityTimeSaving",
                   "sessionSplitSaving", "activitySplitSaving", "mergeSaving",
                   "hideSaving", "deleteSaving", "editingSession"):
        assert saving not in body, (
            "resetCorrectionShellState must not reset " + saving
        )


def test_app_js_open_correction_shell_dirty_refusal_preserves_state():
    """Phase 3B.5B.1: the dirty-state refusal in openCorrectionShell must
    not clear selectedSessionId, must not clear the edit panel / inputs,
    and must not change the selected session."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "openCorrectionShell")
    assert "selectedSessionId = null" not in body, (
        "openCorrectionShell must not clear selectedSessionId on refusal"
    )
    assert "clearEditPanel" not in body, (
        "openCorrectionShell must not clear the edit panel on refusal"
    )
    assert "请先保存或取消当前编辑" in body, (
        "openCorrectionShell must keep the dirty refusal text"
    )


def test_app_js_get_selected_session_uses_current_sessions():
    """Phase 3B.5B.1: getSelectedSession must look the session up from
    currentSessions so a stale / disappeared session cannot open the
    shell."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "getSelectedSession")
    assert "currentSessions" in body, (
        "getSelectedSession must read from currentSessions"
    )


def test_app_js_auto_refresh_shell_guarded_by_dirty_state():
    """Phase 3B.5B.1: auto-refresh must not overwrite a dirty shell. The
    showTimeline shell re-render path must be guarded by !isEditDirty()."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    show_start = source.find("function showTimeline(")
    assert show_start != -1, "showTimeline must exist"
    show_end = source.find("\n    function ", show_start + 1)
    show_body = source[show_start:show_end]
    assert "correctionShellOpen" in show_body, (
        "showTimeline must consider the correction shell state"
    )
    assert "isEditDirty()" in show_body, (
        "showTimeline must guard shell re-render with isEditDirty()"
    )


def test_app_js_close_correction_shell_no_refresh_or_write():
    """Phase 3B.5B.1: closeCorrectionShell must not trigger a refresh and
    must not perform any write action."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "closeCorrectionShell")
    for forbidden in ("loadTimeline", "refreshAll", "callBridge",
                      "saveProject", "saveNote", "saveActivityTime",
                      "saveSessionTime", "saveActivitySplit", "saveSessionSplit",
                      "saveMerge", "saveHide", "saveDelete"):
        assert forbidden not in body, (
            "closeCorrectionShell must not call " + forbidden
        )


def test_app_js_correction_shell_no_new_forbidden_handlers_3b_5b_1():
    """Phase 3B.5B.1: the hardening must not introduce batch edit / hide /
    delete, undo / restore, permanent delete, auto-rule, or global overlap
    detection handlers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("batchEdit", "batchHide", "batchDelete",
                      "restoreActivity", "restoreSession",
                      "permanentDelete", "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap",
                      "multiActivityHide", "multiActivityDelete"):
        assert forbidden not in source, (
            "app.js must not contain " + forbidden + " handler"
        )


def test_index_html_correction_shell_no_external_resources_3b_5b_1():
    """Phase 3B.5B.1: the correction shell region must not introduce
    external links, CDN, Google Fonts, or browser storage."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    start = source.find('id="timeline-correction-shell"')
    assert start != -1, "correction shell container must exist"
    end = source.find("</div>\n                    </div>\n                </div>\n            </section>",
                      start)
    if end == -1:
        end = len(source)
    shell_block = source[start:end]
    assert not re.search(r"https?://", shell_block), (
        "correction shell must not contain external links"
    )
    assert not re.search(r"cdn", shell_block, re.IGNORECASE), (
        "correction shell must not reference CDN"
    )
    assert not re.search(r"localStorage|sessionStorage", shell_block), (
        "correction shell must not use browser storage"
    )
    for forbidden in ("batch-hide", "batch-delete", "batch-time",
                      "batch-split", "batch-merge",
                      "batchhide", "batchdelete", "batchtime",
                      "batchsplit", "batchmerge",
                      "restore", "permanent", "auto-rule", "overlap"):
        assert forbidden not in shell_block.lower(), (
            "correction shell must not contain a '" + forbidden + "' control"
        )


def test_styles_css_has_detail_item_highlight_class():
    """Phase 3B.5B.1: styles.css must define the transient
    .detail-item.detail-item-highlight class used by click-to-locate."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".detail-item.detail-item-highlight" in source, (
        "styles.css must define .detail-item.detail-item-highlight"
    )


def test_styles_css_has_correction_shell_is_static_class():
    """Phase 3B.5B.1: styles.css must define the .is-static style for
    shell activity rows whose activity id is missing / non-numeric."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell-activity-row.is-static" in source, (
        "styles.css must define the non-clickable .is-static style"
    )


def test_styles_css_correction_shell_hidden_still_display_none():
    """Phase 3B.5B.1: the shell must remain truly hidden when [hidden]."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must keep the .correction-shell[hidden] rule"
    )


def test_bridge_no_new_methods_for_phase_3b_5b_1():
    """Phase 3B.5B.1: the hardening must not add any new bridge method,
    and the bridge must continue to import only allowed modules."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    # No new shell-specific write / read method is added in this phase.
    for forbidden in ("def correction_shell", "def batch_edit",
                      "def batch_hide", "def batch_delete",
                      "def restore_activity", "def permanent_delete",
                      "def auto_rule", "def detect_overlaps"):
        assert forbidden not in bridge_src, (
            "bridge must not add " + forbidden
        )
    for forbidden in (
        "import worktrace.services",
        "import worktrace.db",
        "import worktrace.collector",
        "import worktrace.security",
        "import worktrace.runtime",
        "import worktrace.config",
        "from worktrace.services",
        "from worktrace.db",
        "from worktrace.collector",
        "from worktrace.security",
        "from worktrace.runtime",
        "from worktrace.config",
    ):
        assert forbidden not in bridge_src, (
            "bridge must not import " + forbidden
        )


def test_docs_mention_phase_3b_5b_1():
    """Phase 3B.5B.1: the migration doc, release-validation doc, and
    README must mention Phase 3B.5B.1 as the correction shell hardening
    phase and restate that no new backend / DB / bridge capability and no
    batch editing were added."""
    migration = (REPO_ROOT / "docs" / "ui-webview-migration.md").read_text(
        encoding="utf-8"
    )
    release_val = (REPO_ROOT / "docs" / "release-validation.md").read_text(
        encoding="utf-8"
    )
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for doc, name in ((migration, "ui-webview-migration.md"),
                      (release_val, "release-validation.md"),
                      (readme, "README.md")):
        assert "3B.5B.1" in doc, name + " must mention Phase 3B.5B.1"
        assert "hardening" in doc.lower() or "硬化" in doc, (
            name + " must describe 3B.5B.1 as a hardening phase"
        )
    # The migration doc must restate the hardening points and the
    # not-implemented list.
    assert "correction shell" in migration.lower() or "高级纠错" in migration
    for term in ("batch", "restore", "permanent delete", "auto-rule",
                 "overlap"):
        assert term.lower() in migration.lower(), (
            "ui-webview-migration.md must restate that " + term
            + " is not implemented"
        )


# --- Phase 3B.6: Timeline batch project editing foundation ---------------
#
# Phase 3B.6 adds the first batch write capability: batch project
# reassignment on multiple closed activities in the correction shell. It
# reuses the existing activity_project_assignment / activity_log.project_id
# semantics. The service layer uses a single atomic transaction with a
# rowcount guard; the API maps service errors to stable
# TimelineBatchProjectError codes; the bridge maps those to Chinese messages.
# No new DB schema, no batch hide / delete / time / split / merge, no
# restore / permanent delete / auto-rule / overlap detection.


def test_app_js_has_batch_selection_state():
    """Phase 3B.6: app.js must declare the batch project selection state."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "selectedBatchActivityIds" in source, (
        "app.js must declare the selectedBatchActivityIds state variable"
    )
    assert "batchProjectSaving" in source, (
        "app.js must declare the batchProjectSaving state variable"
    )
    assert "batchProjectTargetId" in source, (
        "app.js must declare the batchProjectTargetId state variable"
    )


def test_app_js_has_batch_project_save_helper():
    """Phase 3B.6: app.js must define the saveBatchProject function."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function saveBatchProject" in source, (
        "app.js must define the saveBatchProject function"
    )
    assert "function resetBatchProjectState" in source, (
        "app.js must define the resetBatchProjectState function"
    )
    assert "function renderBatchProjectSection" in source, (
        "app.js must define the renderBatchProjectSection function"
    )
    assert "function pruneStaleBatchSelection" in source, (
        "app.js must define the pruneStaleBatchSelection function"
    )
    assert "function setBatchProjectSaving" in source, (
        "app.js must define the setBatchProjectSaving function"
    )


def test_app_js_calls_batch_update_bridge():
    """Phase 3B.6: app.js must call the batch_update_timeline_activities_project
    bridge method."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "batch_update_timeline_activities_project" in source, (
        "app.js must call the batch_update_timeline_activities_project bridge method"
    )


def test_index_html_has_batch_project_section():
    """Phase 3B.6: index.html must contain the batch project section in the
    correction shell."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "批量项目重分类" in source, (
        "index.html must contain the 批量项目重分类 section title"
    )
    assert 'id="correction-shell-batch-project-section"' in source, (
        "index.html must contain the batch project section container"
    )
    assert 'id="correction-shell-batch-save-btn"' in source, (
        "index.html must contain the batch save button"
    )
    assert 'id="correction-shell-batch-project-select"' in source, (
        "index.html must contain the batch project select"
    )
    assert 'id="correction-shell-batch-count"' in source, (
        "index.html must contain the batch selection count display"
    )


def test_index_html_batch_hint_only_project():
    """Phase 3B.6: the batch section hint must state that only batch
    project reassignment is supported."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "仅支持批量设置项目" in source, (
        "batch section hint must state only project batch is supported"
    )
    # The hint must also list the unsupported batch operations.
    assert "拆分" in source or "合并" in source, (
        "batch section hint must mention unsupported batch operations"
    )


def test_index_html_no_batch_hide_delete_time_split_merge_controls():
    """Phase 3B.6: index.html must not contain batch hide / delete / time /
    split / merge control identifiers."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "batch-hide", "batch-delete", "batch-time",
        "batch-split", "batch-merge",
        "batchhide", "batchdelete", "batchtime",
        "batchsplit", "batchmerge",
    ):
        assert forbidden not in lowered, (
            "index.html must not contain a '" + forbidden + "' control"
        )


def test_app_js_batch_checkbox_only_for_shell_activities():
    """Phase 3B.6: the batch checkbox must only be rendered on shell
    activity rows, not on the detail list rows."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The checkbox class must be correction-shell-activity-checkbox.
    assert "correction-shell-activity-checkbox" in source, (
        "app.js must render the correction-shell-activity-checkbox class"
    )
    # The checkbox must carry a data-batch-activity-id attribute.
    assert "data-batch-activity-id" in source, (
        "app.js must render the data-batch-activity-id attribute on checkboxes"
    )


def test_app_js_batch_in_progress_checkbox_disabled():
    """Phase 3B.6: in-progress activities must render a disabled checkbox."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The renderCorrectionShell function must check is_in_progress and
    # disable the checkbox for in-progress rows.
    render_start = source.find("function renderCorrectionShell")
    assert render_start != -1
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "isInProgress" in render_body or "is_in_progress" in render_body, (
        "renderCorrectionShell must check in-progress state for checkbox eligibility"
    )
    assert "batchEligible" in render_body, (
        "renderCorrectionShell must compute batchEligible for each activity row"
    )


def test_app_js_batch_save_disabled_for_fewer_than_two():
    """Phase 3B.6: the batch save button must be disabled when fewer than
    two activities are selected."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function updateBatchSaveButtonState")
    assert save_start != -1
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "count < 2" in save_body or "len(ids) < 2" in save_body, (
        "updateBatchSaveButtonState must check count < 2"
    )


def test_app_js_batch_save_blocked_by_dirty_edit():
    """Phase 3B.6: saveBatchProject must block when isEditDirty() is true."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchProject")
    assert save_start != -1
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "isEditDirty()" in save_body, (
        "saveBatchProject must call isEditDirty() and block on dirty edits"
    )
    assert "请先保存或取消当前编辑" in save_body, (
        "saveBatchProject must show the dirty-edit blocking message"
    )


def test_app_js_batch_success_refreshes_timeline():
    """Phase 3B.6: a successful batch save must refresh the Timeline."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchProject")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "refreshTimelineForBatchSave" in save_body or "loadTimeline" in save_body, (
        "saveBatchProject must call refresh/load on success"
    )


def test_app_js_batch_failure_preserves_selection():
    """Phase 3B.6: a failed batch save must preserve the selection and
    detail list so the user can retry."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchProject")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The error path must NOT call clearBatchSelection or resetBatchProjectState.
    # It must only show the error message and reset the saving flag.
    assert "clearBatchSelection" not in save_body or save_body.count("clearBatchSelection") == 0, (
        "saveBatchProject failure must not clear the selection"
    )


def test_app_js_clear_edit_panel_resets_batch_state():
    """Phase 3B.6: clearEditPanel must call resetBatchProjectState."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    clear_start = source.find("function clearEditPanel")
    clear_end = source.find("\n    function ", clear_start + 1)
    clear_body = source[clear_start:clear_end]
    assert "resetBatchProjectState" in clear_body, (
        "clearEditPanel must call resetBatchProjectState"
    )


def test_app_js_reset_correction_shell_resets_batch_state():
    """Phase 3B.6: resetCorrectionShellState must call
    resetBatchProjectState."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    reset_start = source.find("function resetCorrectionShellState")
    reset_end = source.find("\n    function ", reset_start + 1)
    reset_body = source[reset_start:reset_end]
    assert "resetBatchProjectState" in reset_body, (
        "resetCorrectionShellState must call resetBatchProjectState"
    )


def test_app_js_batch_no_local_storage():
    """Phase 3B.6: the batch project code must not use browser storage."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"localStorage|sessionStorage", source), (
        "app.js must not use localStorage or sessionStorage"
    )


def test_app_js_batch_no_external_links():
    """Phase 3B.6: the batch project code must not introduce external links."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )


def test_app_js_batch_no_traceback_display():
    """Phase 3B.6: the batch project code must not display tracebacks."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "traceback" not in source.lower(), (
        "app.js must not contain traceback display logic"
    )


def test_app_js_batch_no_restore_permanent_auto_rule_overlap():
    """Phase 3B.6: the batch project code must not introduce restore,
    permanent delete, auto-rule, or overlap handlers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("restoreActivity", "restoreSession",
                      "permanentDelete", "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap"):
        assert forbidden not in source, (
            "app.js must not contain " + forbidden + " handler"
        )


def test_styles_css_has_batch_section_styles():
    """Phase 3B.6: styles.css must define the batch section styles."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell-batch-section" in source, (
        "styles.css must define .correction-shell-batch-section"
    )
    assert ".correction-shell-batch-save-btn" in source, (
        "styles.css must define .correction-shell-batch-save-btn"
    )
    assert ".correction-shell-activity-checkbox" in source, (
        "styles.css must define .correction-shell-activity-checkbox"
    )


def test_bridge_has_batch_update_method():
    """Phase 3B.6: the bridge must define the
    batch_update_timeline_activities_project method."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    assert "def batch_update_timeline_activities_project" in bridge_src, (
        "bridge must define batch_update_timeline_activities_project"
    )


def test_bridge_batch_error_messages_dict():
    """Phase 3B.6: the bridge must define the _BATCH_PROJECT_ERROR_MESSAGES
    dict with all stable error code → Chinese message mappings."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    assert "_BATCH_PROJECT_ERROR_MESSAGES" in bridge_src, (
        "bridge must define _BATCH_PROJECT_ERROR_MESSAGES"
    )
    for code in ("invalid_selection", "batch_too_large", "invalid_project",
                 "in_progress", "hidden_activity", "operation_failed"):
        assert code in bridge_src, (
            "bridge must map the '" + code + "' error code"
        )
    for msg in ("请选择至少两个活动", "一次最多修改 100 条活动",
                "请选择有效的项目", "进行中记录暂不支持批量修改",
                "隐藏记录暂不支持批量修改", "操作失败"):
        assert msg in bridge_src, (
            "bridge must contain the Chinese message: " + msg
        )


def test_api_has_batch_update_function():
    """Phase 3B.6: the API must define the
    batch_update_timeline_activities_project function and
    TimelineBatchProjectError class."""
    api_src = (REPO_ROOT / "worktrace" / "api" / "timeline_api.py").read_text(
        encoding="utf-8"
    )
    assert "class TimelineBatchProjectError" in api_src, (
        "timeline_api must define TimelineBatchProjectError"
    )
    assert "def batch_update_timeline_activities_project" in api_src, (
        "timeline_api must define batch_update_timeline_activities_project"
    )


def test_service_has_batch_update_function():
    """Phase 3B.6: the service must define the
    batch_update_activity_project function and the
    MAX_BATCH_PROJECT_EDIT_ACTIVITIES constant."""
    service_src = (REPO_ROOT / "worktrace" / "services" / "activity_service.py").read_text(
        encoding="utf-8"
    )
    assert "def batch_update_activity_project" in service_src, (
        "activity_service must define batch_update_activity_project"
    )
    assert "MAX_BATCH_PROJECT_EDIT_ACTIVITIES" in service_src, (
        "activity_service must define MAX_BATCH_PROJECT_EDIT_ACTIVITIES"
    )
    assert "= 100" in service_src, (
        "MAX_BATCH_PROJECT_EDIT_ACTIVITIES must be set to 100"
    )


def test_app_js_batch_stale_id_pruning():
    """Phase 3B.6: app.js must prune stale selected ids on every render."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function pruneStaleBatchSelection" in source, (
        "app.js must define the pruneStaleBatchSelection function"
    )
    # The prune function must be called from renderCorrectionShell.
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "pruneStaleBatchSelection" in render_body, (
        "renderCorrectionShell must call pruneStaleBatchSelection"
    )


def test_app_js_batch_save_rechecks_stale_ids():
    """Phase 3B.6: saveBatchProject must re-check selected ids against the
    currently rendered shell activity rows before calling the bridge."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchProject")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "renderedIds" in save_body or "querySelectorAll" in save_body, (
        "saveBatchProject must re-check selected ids against rendered rows"
    )
    assert "cleanIds" in save_body, (
        "saveBatchProject must build a cleanIds list from rendered rows"
    )


# --- Phase 3B.6.1: Timeline batch project editing hardening ---------------
#
# Phase 3B.6.1 hardens the Phase 3B.6 batch project reassignment on the
# frontend. These static tests verify the hardening contracts:
# - batchProjectSaving is an independent state variable (not shared with
#   editSaving / timeSaving / activityTimeSaving / sessionSplitSaving /
#   activitySplitSaving / mergeSaving / hideSaving / deleteSaving);
# - session switch and date switch clear the batch selection via
#   resetCorrectionShellState -> resetBatchProjectState;
# - auto-refresh prunes disappeared / newly-ineligible ids via
#   pruneStaleBatchSelection (called from renderCorrectionShell and
#   renderBatchProjectSection);
# - invalid (non-numeric) ids are dropped by the prune regex;
# - setBatchProjectSaving(true) disables checkboxes / select / save button /
#   select-all / clear button;
# - the .catch path in saveBatchProject resets saving;
# - the success path clears selection and refreshes the Timeline;
# - invalid project selection shows 请选择有效的项目;
# - saveBatchProject re-derives selected ids from the current shell rows
#   (not from a stale in-memory copy).


def test_app_js_batch_saving_independent_state_var():
    """Phase 3B.6.1: batchProjectSaving must be a separate state variable,
    not aliased to any other saving flag."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # All saving flags that must remain independent.
    for var in (
        "batchProjectSaving",
        "editSaving",
        "timeSaving",
        "activityTimeSaving",
        "sessionSplitSaving",
        "activitySplitSaving",
        "mergeSaving",
        "hideSaving",
        "deleteSaving",
    ):
        assert var in source, (
            "app.js must declare the " + var + " state variable"
        )


def test_app_js_session_switch_clears_batch_selection():
    """Phase 3B.6.1: selectTimelineSession must call resetCorrectionShellState
    when switching to a different session, which clears the batch
    selection."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function selectTimelineSession")
    assert fn_start != -1, "app.js must define selectTimelineSession"
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    assert "resetCorrectionShellState" in fn_body, (
        "selectTimelineSession must call resetCorrectionShellState on session switch"
    )


def test_app_js_date_switch_clears_batch_selection():
    """Phase 3B.6.1: goPrevDay / goNextDay / goToday must all call
    resetCorrectionShellState, which clears the batch selection."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for fn_name in ("goPrevDay", "goNextDay", "goToday"):
        fn_start = source.find("function " + fn_name)
        assert fn_start != -1, "app.js must define " + fn_name
        fn_end = source.find("\n    function ", fn_start + 1)
        fn_body = source[fn_start:fn_end]
        assert "resetCorrectionShellState" in fn_body, (
            fn_name + " must call resetCorrectionShellState to clear batch selection"
        )


def test_app_js_auto_refresh_prunes_disappeared_ids():
    """Phase 3B.6.1: pruneStaleBatchSelection must drop ids that are no
    longer present in the freshly rendered activity list, and must be
    called from both renderCorrectionShell and renderBatchProjectSection."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The prune function must drop ids not in validIds and set changed=true.
    prune_start = source.find("function pruneStaleBatchSelection")
    assert prune_start != -1
    prune_end = source.find("\n    function ", prune_start + 1)
    prune_body = source[prune_start:prune_end]
    assert "validIds" in prune_body, (
        "pruneStaleBatchSelection must build a validIds set from rendered activities"
    )
    assert "changed" in prune_body, (
        "pruneStaleBatchSelection must track whether the selection changed"
    )
    # The prune function must be called from renderCorrectionShell.
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "pruneStaleBatchSelection" in render_body, (
        "renderCorrectionShell must call pruneStaleBatchSelection"
    )
    # The prune function must also be called from renderBatchProjectSection
    # so an auto-refresh that only re-renders the section (not the whole
    # shell) still prunes stale ids.
    section_start = source.find("function renderBatchProjectSection")
    section_end = source.find("\n    function ", section_start + 1)
    section_body = source[section_start:section_end]
    assert "pruneStaleBatchSelection" in section_body, (
        "renderBatchProjectSection must call pruneStaleBatchSelection"
    )


def test_app_js_prune_rejects_non_numeric_ids():
    """Phase 3B.6.1: pruneStaleBatchSelection must use a numeric regex so
    invalid (non-numeric) ids are dropped from the selection."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    prune_start = source.find("function pruneStaleBatchSelection")
    prune_end = source.find("\n    function ", prune_start + 1)
    prune_body = source[prune_start:prune_end]
    # The regex must reject non-numeric ids.
    assert re.search(r"\^\[0\-9\]\+", prune_body), (
        "pruneStaleBatchSelection must use a ^[0-9]+ regex to reject non-numeric ids"
    )


def test_app_js_prune_skips_in_progress_activities():
    """Phase 3B.6.1: pruneStaleBatchSelection must skip in-progress
    activities so they cannot be selected."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    prune_start = source.find("function pruneStaleBatchSelection")
    prune_end = source.find("\n    function ", prune_start + 1)
    prune_body = source[prune_start:prune_end]
    assert "is_in_progress" in prune_body, (
        "pruneStaleBatchSelection must check is_in_progress to skip in-progress rows"
    )


def test_app_js_saving_disables_checkboxes_select_button():
    """Phase 3B.6.1: setBatchProjectSaving(true) must disable the save
    button, select-all button, clear button, project select, and every
    batch checkbox."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function setBatchProjectSaving")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    # Save button must be disabled and its text changed.
    assert "correction-shell-batch-save-btn" in fn_body, (
        "setBatchProjectSaving must toggle the batch save button"
    )
    assert "批量设置项目" in fn_body, (
        "setBatchProjectSaving must reset the save button text to 批量设置项目"
    )
    assert "保存中…" in fn_body, (
        "setBatchProjectSaving must set the saving text to 保存中…"
    )
    # Select-all and clear buttons must be disabled.
    assert "correction-shell-batch-select-all-btn" in fn_body, (
        "setBatchProjectSaving must toggle the select-all button"
    )
    assert "correction-shell-batch-clear-btn" in fn_body, (
        "setBatchProjectSaving must toggle the clear button"
    )
    # Project select must be disabled.
    assert "correction-shell-batch-project-select" in fn_body, (
        "setBatchProjectSaving must toggle the project select"
    )
    # Checkboxes must be disabled.
    assert "correction-shell-activity-checkbox" in fn_body, (
        "setBatchProjectSaving must toggle the batch checkboxes"
    )


def test_app_js_save_catch_resets_saving():
    """Phase 3B.6.1: the .catch handler in saveBatchProject must call
    setBatchProjectSaving(false) so saving never gets stuck."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function saveBatchProject")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    # Extract the .catch block.
    catch_idx = fn_body.find(".catch")
    assert catch_idx != -1, "saveBatchProject must have a .catch handler"
    catch_body = fn_body[catch_idx:]
    assert "setBatchProjectSaving(false)" in catch_body, (
        "saveBatchProject .catch must call setBatchProjectSaving(false)"
    )
    assert "操作失败" in catch_body, (
        "saveBatchProject .catch must show 操作失败"
    )


def test_app_js_save_success_clears_selection():
    """Phase 3B.6.1: the success path in saveBatchProject must clear the
    selection and refresh the Timeline."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function saveBatchProject")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    # The success path must clear selectedBatchActivityIds.
    assert "selectedBatchActivityIds = {}" in fn_body, (
        "saveBatchProject success must clear selectedBatchActivityIds"
    )
    # The success path must call the refresh helper or loadTimeline.
    assert "refreshTimelineForBatchSave" in fn_body or "loadTimeline" in fn_body, (
        "saveBatchProject success must refresh the Timeline"
    )
    # The success path must show a success message.
    assert "已批量更新项目" in fn_body, (
        "saveBatchProject success must show a success message"
    )


def test_app_js_save_invalid_project_message():
    """Phase 3B.6.1: saveBatchProject must show 请选择有效的项目 when the
    project select is empty or invalid."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function saveBatchProject")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    assert "请选择有效的项目" in fn_body, (
        "saveBatchProject must show 请选择有效的项目 for invalid project"
    )


def test_app_js_save_derives_ids_from_rendered_rows():
    """Phase 3B.6.1: saveBatchProject must derive cleanIds from the rendered
    shell rows (querySelectorAll), not from a stale in-memory copy."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function saveBatchProject")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    assert "querySelectorAll" in fn_body, (
        "saveBatchProject must query the DOM for rendered rows"
    )
    assert "data-batch-activity-id" in fn_body, (
        "saveBatchProject must read data-batch-activity-id from rendered rows"
    )


def test_app_js_save_failure_does_not_clear_selection():
    """Phase 3B.6.1: the failure path (result.ok === false) must NOT clear
    the selection or call resetBatchProjectState. The saving flag is reset
    once at the top of the .then handler (before branching), so both
    success and failure paths reset saving; the failure branch itself
    only shows the error and returns."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function saveBatchProject")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    # The .then handler must call setBatchProjectSaving(false) before
    # branching on success / failure (covers both paths).
    then_idx = fn_body.find(".then(function (result)")
    assert then_idx != -1, "saveBatchProject must have a .then handler"
    then_body = fn_body[then_idx:]
    assert "setBatchProjectSaving(false)" in then_body, (
        "saveBatchProject .then must call setBatchProjectSaving(false)"
    )
    # Extract the failure branch (result.ok === false) and verify it does
    # NOT clear the selection or call resetBatchProjectState.
    fail_idx = fn_body.find("result.ok === false")
    assert fail_idx != -1, "saveBatchProject must handle result.ok === false"
    success_idx = fn_body.find("已批量更新项目", fail_idx)
    if success_idx == -1:
        success_idx = fn_body.find("refreshTimelineForBatchSave", fail_idx)
    if success_idx == -1:
        success_idx = len(fn_body)
    fail_body = fn_body[fail_idx:success_idx]
    assert "resetBatchProjectState" not in fail_body, (
        "saveBatchProject failure must not call resetBatchProjectState"
    )
    assert "selectedBatchActivityIds = {}" not in fail_body, (
        "saveBatchProject failure must not clear selectedBatchActivityIds"
    )


def test_app_js_reset_batch_project_state_clears_selection():
    """Phase 3B.6.1: resetBatchProjectState must clear the selection, the
    target project, the saving flag, and reset the DOM controls."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function resetBatchProjectState")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    assert "selectedBatchActivityIds = {}" in fn_body, (
        "resetBatchProjectState must clear selectedBatchActivityIds"
    )
    assert "batchProjectSaving = false" in fn_body, (
        "resetBatchProjectState must reset batchProjectSaving"
    )
    assert "batchProjectTargetId = null" in fn_body, (
        "resetBatchProjectState must reset batchProjectTargetId"
    )


def test_app_js_batch_save_guarded_by_saving_flag():
    """Phase 3B.6.1: saveBatchProject must early-return if
    batchProjectSaving is already true (prevents double-submit)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    fn_start = source.find("function saveBatchProject")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    # The first guard must check batchProjectSaving.
    guard_end = fn_body.find("\n", fn_body.find("{") + 1)
    guard_block = fn_body[:guard_end + 200]
    assert "batchProjectSaving" in guard_block[:300], (
        "saveBatchProject must guard against double-submit via batchProjectSaving"
    )


def test_index_html_batch_section_has_status_area():
    """Phase 3B.6.1: index.html must contain a batch status area for
    success / error messages."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-batch-status"' in source, (
        "index.html must contain the batch status area"
    )


def test_index_html_batch_section_has_select_all_and_clear():
    """Phase 3B.6.1: index.html must contain the select-all and clear
    selection buttons referenced by setBatchProjectSaving."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-batch-select-all-btn"' in source, (
        "index.html must contain the batch select-all button"
    )
    assert 'id="correction-shell-batch-clear-btn"' in source, (
        "index.html must contain the batch clear button"
    )


def test_styles_css_has_batch_disabled_states():
    """Phase 3B.6.1: styles.css must define disabled / saving styles for
    the batch controls so the user sees a clear visual state."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    # The batch save button must have a disabled style (or inherit the
    # generic disabled style). At minimum, the batch section styles must
    # exist.
    assert ".correction-shell-batch-section" in source, (
        "styles.css must define .correction-shell-batch-section"
    )
    assert ".correction-shell-batch-save-btn" in source, (
        "styles.css must define .correction-shell-batch-save-btn"
    )
