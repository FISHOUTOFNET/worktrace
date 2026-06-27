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
    """Phase 2: Rules and Settings pages are not yet migrated
    and must still show the placeholder text. Statistics is migrated
    in Phase 4A."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for page_id in ["rules", "settings"]:
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
    # Phase 3B.8 introduces single activity restore, so "restore" is now
    # allowed in index.html. Batch restore, restore-all, undo stack, and
    # permanent delete must still be absent.
    for forbidden_restore in (
        "batch-restore", "batchrestore", "restore-all", "restoreall",
        "undo-restore", "undorestore", "permanent", "auto-rule",
    ):
        assert forbidden_restore not in lowered, (
            "index.html must not contain a '" + forbidden_restore + "' control"
        )


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
    # Phase 3B.8 introduces single activity restore, so "restore" is now
    # allowed in index.html. Batch restore, restore-all, undo stack, and
    # permanent delete must still be absent.
    for forbidden_restore in (
        "batch-restore", "batchrestore", "restore-all", "restoreall",
        "undo-restore", "undorestore", "permanent", "auto-rule",
    ):
        assert forbidden_restore not in html_source, (
            "index.html must not contain a '" + forbidden_restore + "' control"
        )


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
    batch time / batch split / batch merge / batch restore / restore-all /
    permanent-delete / auto-rule / complex-correction-page / overlap
    controls. Phase 3B.6 introduces batch project reassignment, so "batch"
    is now allowed in index.html but only in the project context; the
    specific batch hide / delete / time / split / merge variants must still
    be absent. Phase 3B.8 introduces single activity restore, so "restore"
    is now allowed; batch restore, restore-all, undo stack, and permanent
    delete must still be absent."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "batch-hide", "batch-delete", "batch-time",
        "batch-split", "batch-merge",
        "batchhide", "batchdelete", "batchtime",
        "batchsplit", "batchmerge",
        "batch-restore", "batchrestore",
        "restore-all", "restoreall",
        "undo-restore", "undorestore",
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
    batch time / batch split / batch merge / batch restore / restore-all /
    permanent-delete / auto-rule / overlap controls in the shell. Phase
    3B.6 introduces batch project reassignment in the correction shell, so
    "batch" is now allowed in the shell but only in the project context;
    the specific batch hide / delete / time / split / merge variants must
    still be absent. Phase 3B.8 introduces single activity restore in the
    shell, so "restore" is now allowed; batch restore, restore-all, undo
    stack, and permanent delete must still be absent."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("batch-hide", "batch-delete", "batch-time",
                      "batch-split", "batch-merge",
                      "batchhide", "batchdelete", "batchtime",
                      "batchsplit", "batchmerge",
                      "batch-restore", "batchrestore",
                      "restore-all", "restoreall",
                      "undo-restore", "undorestore",
                      "permanent", "auto-rule",
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
                      "batch-restore", "batchrestore",
                      "restore-all", "restoreall",
                      "undo-restore", "undorestore",
                      "permanent", "auto-rule", "overlap"):
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


# --- Phase 3B.7: Timeline batch note editing foundation -----------------
#
# Phase 3B.7 adds the second batch write capability: batch note overwrite
# on multiple closed activities in the correction shell. It reuses the same
# selectedBatchActivityIds selection as batch project so the user picks
# activities once and chooses either "set project" or "overwrite note".
# The service layer uses a single atomic transaction with a rowcount guard;
# the API maps service errors to stable TimelineBatchNoteError codes; the
# bridge maps those to Chinese messages. Only activity_log.note and
# updated_at are modified (source is intentionally NOT changed). Empty
# string is allowed and clears notes. No new DB schema, no batch note
# append / merge, no batch hide / delete / time / split / merge, no
# restore / permanent delete / auto-rule / overlap detection.


def test_app_js_has_batch_note_saving_state():
    """Phase 3B.7: app.js must declare the batchNoteSaving state variable."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "batchNoteSaving" in source, (
        "app.js must declare the batchNoteSaving state variable"
    )


def test_app_js_has_batch_note_save_helper():
    """Phase 3B.7: app.js must define the saveBatchNote function and
    related helpers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function saveBatchNote" in source, (
        "app.js must define the saveBatchNote function"
    )
    assert "function resetBatchNoteState" in source, (
        "app.js must define the resetBatchNoteState function"
    )
    assert "function renderBatchNoteSection" in source, (
        "app.js must define the renderBatchNoteSection function"
    )
    assert "function setBatchNoteSaving" in source, (
        "app.js must define the setBatchNoteSaving function"
    )
    assert "function updateBatchNoteCount" in source, (
        "app.js must define the updateBatchNoteCount function"
    )
    assert "function updateBatchNoteSaveButtonState" in source, (
        "app.js must define the updateBatchNoteSaveButtonState function"
    )
    assert "function showBatchNoteStatus" in source, (
        "app.js must define the showBatchNoteStatus function"
    )
    assert "function bindBatchNoteControls" in source, (
        "app.js must define the bindBatchNoteControls function"
    )


def test_app_js_calls_batch_note_update_bridge():
    """Phase 3B.7: app.js must call the batch_update_timeline_activities_note
    bridge method."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "batch_update_timeline_activities_note" in source, (
        "app.js must call the batch_update_timeline_activities_note bridge method"
    )


def test_index_html_has_batch_note_section():
    """Phase 3B.7: index.html must contain the batch note section in the
    correction shell."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "批量备注覆盖" in source, (
        "index.html must contain the 批量备注覆盖 section title"
    )
    assert 'id="correction-shell-batch-note-section"' in source, (
        "index.html must contain the batch note section container"
    )
    assert 'id="correction-shell-batch-note-text"' in source, (
        "index.html must contain the batch note textarea"
    )
    assert 'id="correction-shell-batch-note-save-btn"' in source, (
        "index.html must contain the batch note save button"
    )
    assert 'id="correction-shell-batch-note-count"' in source, (
        "index.html must contain the batch note count display"
    )
    assert 'id="correction-shell-batch-note-status"' in source, (
        "index.html must contain the batch note status display"
    )


def test_index_html_batch_note_hint_only_overwrite():
    """Phase 3B.7: the batch note hint must state that only overwrite is
    supported (no append / merge)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "覆盖" in source, (
        "batch note hint must mention overwrite (覆盖)"
    )
    assert "追加" in source or "合并" in source, (
        "batch note hint must mention unsupported append/merge operations"
    )


def test_index_html_batch_note_textarea_placeholder():
    """Phase 3B.7: the batch note textarea must have a placeholder."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "placeholder" in source, (
        "batch note textarea must have a placeholder attribute"
    )


def test_index_html_no_batch_note_append_merge_controls():
    """Phase 3B.7: index.html must not contain append / merge note mode
    controls."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "batch-note-append", "batch-note-merge",
        "batchnoteappend", "batchnotemerge",
        "append-mode", "merge-mode",
    ):
        assert forbidden not in lowered, (
            "index.html must not contain a '" + forbidden + "' control"
        )


def test_index_html_no_batch_hide_delete_time_split_merge_controls_3b7():
    """Phase 3B.7: index.html must not contain batch hide / delete / time /
    split / merge control identifiers (re-asserted for Phase 3B.7)."""
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


def test_app_js_batch_note_save_disabled_for_fewer_than_two():
    """Phase 3B.7: the batch note save button must be disabled when fewer
    than two activities are selected."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function updateBatchNoteSaveButtonState")
    assert save_start != -1
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "count < 2" in save_body, (
        "updateBatchNoteSaveButtonState must check count < 2"
    )


def test_app_js_batch_note_save_blocked_by_dirty_edit():
    """Phase 3B.7: saveBatchNote must block when isEditDirty() is true."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    assert save_start != -1
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "isEditDirty()" in save_body, (
        "saveBatchNote must call isEditDirty() and block on dirty edits"
    )
    assert "请先保存或取消当前编辑" in save_body, (
        "saveBatchNote must show the dirty-edit blocking message"
    )


def test_app_js_batch_note_success_refreshes_timeline():
    """Phase 3B.7: a successful batch note save must refresh the Timeline."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "refreshTimelineForBatchSave" in save_body or "loadTimeline" in save_body, (
        "saveBatchNote must call refresh/load on success"
    )


def test_app_js_batch_note_failure_preserves_selection():
    """Phase 3B.7: a failed batch note save must preserve the selection,
    detail list, and note textarea so the user can retry."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The error path must NOT call clearBatchSelection or resetBatchNoteState.
    assert "clearBatchSelection" not in save_body or save_body.count("clearBatchSelection") == 0, (
        "saveBatchNote failure must not clear the selection"
    )


def test_app_js_batch_note_catch_resets_saving():
    """Phase 3B.7: the .catch path in saveBatchNote must reset saving."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    catch_start = save_body.find(".catch(")
    assert catch_start != -1, (
        "saveBatchNote must have a .catch handler"
    )
    catch_body = save_body[catch_start:]
    assert "setBatchNoteSaving(false)" in catch_body, (
        "saveBatchNote .catch must call setBatchNoteSaving(false)"
    )


def test_app_js_clear_edit_panel_resets_batch_note_state():
    """Phase 3B.7: clearEditPanel must call resetBatchNoteState."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    clear_start = source.find("function clearEditPanel")
    clear_end = source.find("\n    function ", clear_start + 1)
    clear_body = source[clear_start:clear_end]
    assert "resetBatchNoteState" in clear_body, (
        "clearEditPanel must call resetBatchNoteState"
    )


def test_app_js_reset_correction_shell_resets_batch_note_state():
    """Phase 3B.7: resetCorrectionShellState must call
    resetBatchNoteState."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    reset_start = source.find("function resetCorrectionShellState")
    reset_end = source.find("\n    function ", reset_start + 1)
    reset_body = source[reset_start:reset_end]
    assert "resetBatchNoteState" in reset_body, (
        "resetCorrectionShellState must call resetBatchNoteState"
    )


def test_app_js_batch_note_rechecks_stale_ids():
    """Phase 3B.7: saveBatchNote must re-check selected ids against the
    currently rendered shell activity rows before calling the bridge."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "renderedIds" in save_body or "querySelectorAll" in save_body, (
        "saveBatchNote must re-check selected ids against rendered rows"
    )
    assert "cleanIds" in save_body, (
        "saveBatchNote must build a cleanIds list from rendered rows"
    )


def test_app_js_batch_note_empty_allowed():
    """Phase 3B.7: the batch note save must allow empty string (to clear
    notes). The save function must not reject an empty note."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The save function must NOT block on empty note (only on too-long).
    # It must use note.length > NOTE_MAX_LENGTH, not !note or note.length === 0.
    assert "NOTE_MAX_LENGTH" in save_body, (
        "saveBatchNote must reference NOTE_MAX_LENGTH"
    )


def test_app_js_batch_note_saving_disables_controls():
    """Phase 3B.7: setBatchNoteSaving must disable the textarea, save
    button, and checkboxes during save."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function setBatchNoteSaving")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "correction-shell-batch-note-save-btn" in save_body, (
        "setBatchNoteSaving must toggle the note save button"
    )
    assert "correction-shell-batch-note-text" in save_body, (
        "setBatchNoteSaving must toggle the note textarea"
    )
    assert "checkbox" in save_body.lower(), (
        "setBatchNoteSaving must toggle checkboxes"
    )


def test_app_js_batch_note_count_uses_max_length():
    """Phase 3B.7: updateBatchNoteCount must use NOTE_MAX_LENGTH."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    count_start = source.find("function updateBatchNoteCount")
    count_end = source.find("\n    function ", count_start + 1)
    count_body = source[count_start:count_end]
    assert "NOTE_MAX_LENGTH" in count_body, (
        "updateBatchNoteCount must use NOTE_MAX_LENGTH"
    )


def test_app_js_batch_note_bind_controls_called_in_init():
    """Phase 3B.7: bindBatchNoteControls must be called during init."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The bind call should be in the initButtons function (where other
    # bind calls live).
    buttons_start = source.find("function initButtons")
    buttons_end = source.find("\n    function ", buttons_start + 1)
    buttons_body = source[buttons_start:buttons_end]
    assert "bindBatchNoteControls" in buttons_body, (
        "bindBatchNoteControls must be called during initButtons"
    )


def test_app_js_batch_note_no_local_storage():
    """Phase 3B.7: the batch note code must not use browser storage
    (re-asserted for the whole app.js)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"localStorage|sessionStorage", source), (
        "app.js must not use localStorage or sessionStorage"
    )


def test_app_js_batch_note_no_external_links():
    """Phase 3B.7: the batch note code must not introduce external links
    (re-asserted for all frontend resources)."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )


def test_app_js_batch_note_no_traceback_display():
    """Phase 3B.7: the batch note code must not display tracebacks
    (re-asserted for the whole app.js)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "traceback" not in source.lower(), (
        "app.js must not contain traceback display logic"
    )


def test_app_js_batch_note_no_restore_permanent_auto_rule_overlap():
    """Phase 3B.7: the batch note code must not introduce batch restore,
    restore all, undo restore, permanent delete, auto-rule, or overlap
    handlers (re-asserted for Phase 3B.8: single ``saveActivityRestore`` is
    now implemented, but batch/undo/permanent variants remain forbidden)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("batchRestore", "batch_restore", "restoreAll",
                      "restore_all", "restoreSession", "restore_session",
                      "undoRestore", "undo_restore",
                      "permanentDelete", "permanent_delete",
                      "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap"):
        assert forbidden not in source, (
            "app.js must not contain " + forbidden + " handler"
        )


def test_styles_css_has_batch_note_section_styles():
    """Phase 3B.7: styles.css must define the batch note section styles."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell-batch-note-text" in source, (
        "styles.css must define .correction-shell-batch-note-text"
    )


def test_bridge_has_batch_note_update_method():
    """Phase 3B.7: the bridge must define the
    batch_update_timeline_activities_note method."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    assert "def batch_update_timeline_activities_note" in bridge_src, (
        "bridge must define batch_update_timeline_activities_note"
    )


def test_bridge_batch_note_error_messages_dict():
    """Phase 3B.7: the bridge must define the _BATCH_NOTE_ERROR_MESSAGES
    dict with all stable error code -> Chinese message mappings."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    assert "_BATCH_NOTE_ERROR_MESSAGES" in bridge_src, (
        "bridge must define _BATCH_NOTE_ERROR_MESSAGES"
    )
    for code in ("invalid_selection", "batch_too_large", "invalid_note",
                 "note_too_long", "in_progress", "hidden_activity",
                 "operation_failed"):
        assert code in bridge_src, (
            "bridge must map the '" + code + "' error code"
        )
    for msg in ("请选择至少两个活动", "一次最多修改 100 条活动",
                "请输入有效备注", "备注过长",
                "进行中记录暂不支持批量修改",
                "隐藏记录暂不支持批量修改", "操作失败"):
        assert msg in bridge_src, (
            "bridge must contain the Chinese message: " + msg
        )


def test_api_has_batch_note_update_function():
    """Phase 3B.7: the API must define the
    batch_update_timeline_activities_note function and
    TimelineBatchNoteError class."""
    api_src = (REPO_ROOT / "worktrace" / "api" / "timeline_api.py").read_text(
        encoding="utf-8"
    )
    assert "class TimelineBatchNoteError" in api_src, (
        "timeline_api must define TimelineBatchNoteError"
    )
    assert "def batch_update_timeline_activities_note" in api_src, (
        "timeline_api must define batch_update_timeline_activities_note"
    )


def test_service_has_batch_note_update_function():
    """Phase 3B.7: the service must define the
    batch_update_activity_note function and the
    MAX_BATCH_NOTE_EDIT_ACTIVITIES / BATCH_NOTE_MAX_LENGTH constants."""
    service_src = (REPO_ROOT / "worktrace" / "services" / "activity_service.py").read_text(
        encoding="utf-8"
    )
    assert "def batch_update_activity_note" in service_src, (
        "activity_service must define batch_update_activity_note"
    )
    assert "MAX_BATCH_NOTE_EDIT_ACTIVITIES" in service_src, (
        "activity_service must define MAX_BATCH_NOTE_EDIT_ACTIVITIES"
    )
    assert "BATCH_NOTE_MAX_LENGTH" in service_src, (
        "activity_service must define BATCH_NOTE_MAX_LENGTH"
    )


def test_app_js_batch_note_render_called_from_render_correction_shell():
    """Phase 3B.7: renderBatchNoteSection must be called from
    renderCorrectionShell so the section is always populated when the shell
    opens."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "renderBatchNoteSection" in render_body, (
        "renderCorrectionShell must call renderBatchNoteSection"
    )


# --- Phase 3B.7.1: Timeline batch note editing hardening -----------------
#
# These static tests verify the hardening invariants in app.js: cross-save
# guard, session/date/shell switch clearing, and cross-disable of batch
# project controls when batch note is saving (and vice versa).


def test_app_js_batch_note_save_checks_batch_project_saving():
    """Phase 3B.7.1: saveBatchNote must check ``batchProjectSaving`` before
    proceeding so two batch saves cannot compete."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "batchProjectSaving" in save_body, (
        "saveBatchNote must check batchProjectSaving before proceeding"
    )


def test_app_js_select_timeline_session_resets_batch_note():
    """Phase 3B.7.1: selectTimelineSession must call
    resetCorrectionShellState (which calls resetBatchNoteState) when
    switching sessions so the note textarea does not carry over."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    select_start = source.find("function selectTimelineSession")
    select_end = source.find("\n    function ", select_start + 1)
    select_body = source[select_start:select_end]
    assert "resetCorrectionShellState" in select_body, (
        "selectTimelineSession must call resetCorrectionShellState on "
        "session switch (which resets batch note state)"
    )


def test_app_js_date_navigation_resets_batch_note():
    """Phase 3B.7.1: goPrevDay / goNextDay / goToday must all call
    resetCorrectionShellState (which calls resetBatchNoteState) so the
    note textarea does not carry over to a different day."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for func_name in ("goPrevDay", "goNextDay", "goToday"):
        func_start = source.find("function " + func_name)
        assert func_start >= 0, f"app.js must define {func_name}"
        func_end = source.find("\n    function ", func_start + 1)
        func_body = source[func_start:func_end]
        assert "resetCorrectionShellState" in func_body, (
            func_name + " must call resetCorrectionShellState (which "
            "resets batch note state)"
        )


def test_app_js_close_correction_shell_resets_batch_note():
    """Phase 3B.7.1: closeCorrectionShell must call
    resetCorrectionShellState (which calls resetBatchNoteState) so the
    note textarea is cleared when the user closes the shell."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    close_start = source.find("function closeCorrectionShell")
    close_end = source.find("\n    function ", close_start + 1)
    close_body = source[close_start:close_end]
    assert "resetCorrectionShellState" in close_body, (
        "closeCorrectionShell must call resetCorrectionShellState "
        "(which resets batch note state)"
    )


def test_app_js_set_batch_note_saving_disables_batch_project_controls():
    """Phase 3B.7.1: setBatchNoteSaving must disable the batch project
    save button (and select-all / clear / project select) so the user
    cannot start a competing project save while a note save is in flight."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    saving_start = source.find("function setBatchNoteSaving")
    saving_end = source.find("\n    function ", saving_start + 1)
    saving_body = source[saving_start:saving_end]
    assert "correction-shell-batch-save-btn" in saving_body, (
        "setBatchNoteSaving must disable the batch project save button"
    )
    assert "correction-shell-batch-select-all-btn" in saving_body, (
        "setBatchNoteSaving must disable the select-all button"
    )
    assert "correction-shell-batch-clear-btn" in saving_body, (
        "setBatchNoteSaving must disable the clear-selection button"
    )
    assert "correction-shell-batch-project-select" in saving_body, (
        "setBatchNoteSaving must disable the batch project select"
    )


def test_app_js_set_batch_project_saving_disables_batch_note_controls():
    """Phase 3B.7.1: setBatchProjectSaving must disable the batch note
    textarea so the user cannot edit the note while a project save is in
    flight."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    saving_start = source.find("function setBatchProjectSaving")
    saving_end = source.find("\n    function ", saving_start + 1)
    saving_body = source[saving_start:saving_end]
    assert "correction-shell-batch-note-text" in saving_body, (
        "setBatchProjectSaving must disable the batch note textarea"
    )


def test_app_js_reset_correction_shell_state_calls_reset_batch_note():
    """Phase 3B.7.1: resetCorrectionShellState must call
    resetBatchNoteState so every path that resets the shell also clears
    the note textarea / count / status / saving state."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    reset_start = source.find("function resetCorrectionShellState")
    reset_end = source.find("\n    function ", reset_start + 1)
    reset_body = source[reset_start:reset_end]
    assert "resetBatchNoteState" in reset_body, (
        "resetCorrectionShellState must call resetBatchNoteState"
    )


def test_app_js_reset_batch_note_state_clears_textarea_and_count():
    """Phase 3B.7.1: resetBatchNoteState must clear the note textarea
    value, reset the count, and hide the status area."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    reset_start = source.find("function resetBatchNoteState")
    reset_end = source.find("\n    function ", reset_start + 1)
    reset_body = source[reset_start:reset_end]
    assert 'noteText.value = ""' in reset_body or "noteText.value = ''" in reset_body, (
        "resetBatchNoteState must clear the note textarea value"
    )
    assert "batchNoteSaving = false" in reset_body, (
        "resetBatchNoteState must reset batchNoteSaving"
    )
    assert "correction-shell-batch-note-count" in reset_body, (
        "resetBatchNoteState must reset the note count"
    )


def test_app_js_batch_note_no_old_or_new_note_leak_in_error_handling():
    """Phase 3B.7.1: the batch note error handling code must not reference
    old_note or new_note variables — the bridge error is surfaced verbatim
    without echoing note content."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "old_note" not in save_body, (
        "saveBatchNote must not reference old_note"
    )
    assert "new_note" not in save_body, (
        "saveBatchNote must not reference new_note"
    )
    assert "oldNote" not in save_body, (
        "saveBatchNote must not reference oldNote"
    )
    assert "newNote" not in save_body, (
        "saveBatchNote must not reference newNote"
    )


def test_app_js_batch_note_failure_preserves_textarea():
    """Phase 3B.7.1: the failure path in saveBatchNote must NOT clear the
    note textarea — the user's input is preserved so they can retry."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # Find the error/failure branch (result.ok === false).
    fail_idx = save_body.find("result.ok === false")
    if fail_idx < 0:
        fail_idx = save_body.find("result.ok !== true")
    assert fail_idx >= 0, "saveBatchNote must have a failure branch"
    # Extract only the failure branch body — from the condition up to (but
    # not including) the first ``return;`` that closes the branch. Anything
    # after that return belongs to the success path.
    fail_return = save_body.find("return;", fail_idx)
    if fail_return < 0:
        fail_return = len(save_body)
    fail_branch = save_body[fail_idx:fail_return]
    # The failure branch must NOT reset the textarea value.
    assert 'noteEl.value = ""' not in fail_branch, (
        "saveBatchNote failure path must not clear the note textarea"
    )
    assert "resetBatchNoteState" not in fail_branch, (
        "saveBatchNote failure path must not call resetBatchNoteState"
    )


def test_app_js_batch_note_success_clears_selection_and_textarea():
    """Phase 3B.7.1: the success path in saveBatchNote must clear the
    selection and the note textarea."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The success path must clear selectedBatchActivityIds.
    assert "selectedBatchActivityIds = {}" in save_body, (
        "saveBatchNote success must clear selectedBatchActivityIds"
    )
    # The success path must clear the note textarea.
    assert 'noteEl.value = ""' in save_body or "noteEl.value = ''" in save_body, (
        "saveBatchNote success must clear the note textarea"
    )


# --- Phase 3B.8: Timeline single activity restore foundation -------------
#
# These static tests verify the Phase 3B.8 restore foundation in the WebView
# frontend: the restore section in index.html, the restore saving state and
# helpers in app.js, the CSS styles, and the bridge/API/service layer
# existence. They also re-assert that no batch restore / undo stack /
# permanent delete / auto-rule / overlap controls are introduced.


def test_index_html_has_restore_section():
    """Phase 3B.8: index.html must contain the restore section in the
    correction shell."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "可恢复记录" in source, (
        "index.html must contain the 可恢复记录 section title"
    )
    assert 'id="correction-shell-restore-section"' in source, (
        "index.html must contain the restore section container"
    )
    assert 'id="correction-shell-restore-list"' in source, (
        "index.html must contain the restore list container"
    )
    assert 'id="correction-shell-restore-status"' in source, (
        "index.html must contain the restore status display"
    )


def test_index_html_restore_hint_no_batch_undo_permanent():
    """Phase 3B.8: the restore hint must state that batch restore, undo
    stack, and permanent delete are not supported."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    hint_start = source.find("correction-shell-restore-hint")
    assert hint_start != -1, "index.html must contain the restore hint"
    # Extract a window around the hint to check its text.
    hint_window = source[hint_start:hint_start + 500]
    assert "批量恢复" in hint_window or "批量" in hint_window, (
        "restore hint must mention batch restore is not supported"
    )
    assert "撤销" in hint_window, (
        "restore hint must mention undo stack is not supported"
    )
    assert "永久删除" in hint_window, (
        "restore hint must mention permanent delete is not supported"
    )


def test_index_html_no_batch_restore_restore_all_permanent_undo_controls():
    """Phase 3B.8: index.html must not contain batch restore, restore all,
    permanent delete, or undo stack controls."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "batch-restore", "batchrestore",
        "restore-all", "restoreall",
        "undo-restore", "undorestore",
        "permanent-delete", "permanentdelete",
        "undo-stack", "undostack",
    ):
        assert forbidden not in lowered, (
            "index.html must not contain a '" + forbidden + "' control"
        )


def test_app_js_has_restore_saving_state():
    """Phase 3B.8: app.js must declare the restoreSaving state variable,
    independent from batchProjectSaving / batchNoteSaving."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "restoreSaving" in source, (
        "app.js must declare the restoreSaving state variable"
    )
    assert "restoreSavingActivityId" in source, (
        "app.js must declare the restoreSavingActivityId state variable"
    )


def test_app_js_has_restore_helpers():
    """Phase 3B.8: app.js must define the restore helper functions."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function resetRestoreState" in source, (
        "app.js must define the resetRestoreState function"
    )
    assert "function showRestoreStatus" in source, (
        "app.js must define the showRestoreStatus function"
    )
    assert "function setRestoreSaving" in source, (
        "app.js must define the setRestoreSaving function"
    )
    assert "function renderRestoreSection" in source, (
        "app.js must define the renderRestoreSection function"
    )
    assert "function loadRestorableActivities" in source, (
        "app.js must define the loadRestorableActivities function"
    )
    assert "function renderRestorableActivities" in source, (
        "app.js must define the renderRestorableActivities function"
    )
    assert "function saveActivityRestore" in source, (
        "app.js must define the saveActivityRestore function"
    )
    assert "function bindRestoreControls" in source, (
        "app.js must define the bindRestoreControls function"
    )


def test_app_js_calls_restore_bridge_methods():
    """Phase 3B.8: app.js must call the restore_timeline_activity and
    get_timeline_restorable_activities bridge methods."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "restore_timeline_activity" in source, (
        "app.js must call the restore_timeline_activity bridge method"
    )
    assert "get_timeline_restorable_activities" in source, (
        "app.js must call the get_timeline_restorable_activities bridge method"
    )


def test_app_js_restore_save_blocked_by_dirty_edit():
    """Phase 3B.8: saveActivityRestore must block when isEditDirty() is
    true and show the dirty-edit blocking message."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    assert save_start != -1
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "isEditDirty()" in save_body, (
        "saveActivityRestore must call isEditDirty() and block on dirty edits"
    )
    assert "请先保存或取消当前编辑" in save_body, (
        "saveActivityRestore must show the dirty-edit blocking message"
    )


def test_app_js_restore_save_checks_restore_saving():
    """Phase 3B.8: saveActivityRestore must check restoreSaving before
    proceeding so two restores cannot compete."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "restoreSaving" in save_body, (
        "saveActivityRestore must check restoreSaving before proceeding"
    )


def test_app_js_restore_success_refreshes_timeline():
    """Phase 3B.8: a successful restore must refresh the Timeline."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "refreshTimelineAfterEdit" in save_body, (
        "saveActivityRestore success must call refreshTimelineAfterEdit"
    )


def test_app_js_restore_success_shows_restored_message():
    """Phase 3B.8: a successful restore must show the 已恢复 message."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "已恢复" in save_body, (
        "saveActivityRestore success must show the 已恢复 message"
    )


def test_app_js_restore_failure_preserves_list():
    """Phase 3B.8: a failed restore must preserve the restore list so the
    user can retry."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The error path must NOT call resetRestoreState (which clears the list).
    # It should only call setRestoreSaving(false, null) + showRestoreStatus.
    error_start = save_body.find("result.ok === false")
    assert error_start != -1
    error_body = save_body[error_start:]
    assert "resetRestoreState" not in error_body, (
        "saveActivityRestore failure must not clear the restore list"
    )


def test_app_js_restore_catch_resets_saving():
    """Phase 3B.8: the .catch path in saveActivityRestore must reset
    saving."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    catch_start = save_body.find(".catch(")
    assert catch_start != -1, "saveActivityRestore must have a .catch handler"
    catch_body = save_body[catch_start:]
    assert "setRestoreSaving(false" in catch_body, (
        "saveActivityRestore .catch must call setRestoreSaving(false)"
    )
    assert "恢复失败" in catch_body, (
        "saveActivityRestore .catch must show 恢复失败"
    )


def test_app_js_restore_saving_disables_buttons():
    """Phase 3B.8: setRestoreSaving must disable all restore buttons when
    saving is true."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    set_start = source.find("function setRestoreSaving")
    set_end = source.find("\n    function ", set_start + 1)
    set_body = source[set_start:set_end]
    assert "disabled" in set_body, (
        "setRestoreSaving must disable/enable restore buttons"
    )
    assert "correction-shell-restore-btn" in set_body, (
        "setRestoreSaving must target the restore button class"
    )


def test_app_js_clear_edit_panel_resets_restore_state():
    """Phase 3B.8: clearEditPanel must call resetRestoreState."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    clear_start = source.find("function clearEditPanel")
    clear_end = source.find("\n    function ", clear_start + 1)
    clear_body = source[clear_start:clear_end]
    assert "resetRestoreState" in clear_body, (
        "clearEditPanel must call resetRestoreState"
    )


def test_app_js_reset_correction_shell_resets_restore_state():
    """Phase 3B.8: resetCorrectionShellState must call resetRestoreState."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    reset_start = source.find("function resetCorrectionShellState")
    reset_end = source.find("\n    function ", reset_start + 1)
    reset_body = source[reset_start:reset_end]
    assert "resetRestoreState" in reset_body, (
        "resetCorrectionShellState must call resetRestoreState"
    )


def test_app_js_restore_render_called_from_render_correction_shell():
    """Phase 3B.8: renderRestoreSection must be called from
    renderCorrectionShell so the section is always populated when the shell
    opens."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "renderRestoreSection" in render_body, (
        "renderCorrectionShell must call renderRestoreSection"
    )


def test_app_js_restore_bind_called_in_init():
    """Phase 3B.8: bindRestoreControls must be called during initButtons."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    buttons_start = source.find("function initButtons")
    buttons_end = source.find("\n    function ", buttons_start + 1)
    buttons_body = source[buttons_start:buttons_end]
    assert "bindRestoreControls" in buttons_body, (
        "bindRestoreControls must be called during initButtons"
    )


def test_app_js_restore_uses_escape_html():
    """Phase 3B.8: renderRestorableActivities must escape dynamic values
    using escapeHtml."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderRestorableActivities")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "escapeHtml" in render_body, (
        "renderRestorableActivities must use escapeHtml for dynamic values"
    )


def test_app_js_restore_no_local_storage():
    """Phase 3B.8: the restore code must not use browser storage
    (re-asserted for the whole app.js)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"localStorage|sessionStorage", source), (
        "app.js must not use localStorage or sessionStorage"
    )


def test_app_js_restore_no_external_links():
    """Phase 3B.8: the restore code must not introduce external links
    (re-asserted for all frontend resources)."""
    for filename in ["index.html", "app.js", "styles.css"]:
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )


def test_app_js_restore_no_traceback_display():
    """Phase 3B.8: the restore code must not display tracebacks
    (re-asserted for the whole app.js)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "traceback" not in source.lower(), (
        "app.js must not contain traceback display logic"
    )


def test_app_js_restore_no_raw_field_display():
    """Phase 3B.8: the restore code must not display raw window_title /
    file_path / clipboard / note fields."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderRestorableActivities")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    for forbidden in ("window_title", "file_path_hint", "full_path",
                       "clipboard", "raw_note", "traceback"):
        assert forbidden not in render_body.lower(), (
            "renderRestorableActivities must not reference " + forbidden
        )


def test_styles_css_has_restore_section_styles():
    """Phase 3B.8: styles.css must define the restore section styles."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell-restore-section" in source, (
        "styles.css must define .correction-shell-restore-section"
    )
    assert ".correction-shell-restore-list" in source, (
        "styles.css must define .correction-shell-restore-list"
    )
    assert ".correction-shell-restore-row" in source, (
        "styles.css must define .correction-shell-restore-row"
    )
    assert ".correction-shell-restore-btn" in source, (
        "styles.css must define .correction-shell-restore-btn"
    )
    assert ".correction-shell-restore-badge" in source, (
        "styles.css must define .correction-shell-restore-badge"
    )


def test_bridge_has_restore_method():
    """Phase 3B.8: the bridge must define the restore_timeline_activity
    and get_timeline_restorable_activities methods."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    assert "def restore_timeline_activity" in bridge_src, (
        "bridge must define restore_timeline_activity"
    )
    assert "def get_timeline_restorable_activities" in bridge_src, (
        "bridge must define get_timeline_restorable_activities"
    )


def test_bridge_restore_error_messages_dict():
    """Phase 3B.8: the bridge must define the _RESTORE_ERROR_MESSAGES
    dict with all stable error code -> Chinese message mappings."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    assert "_RESTORE_ERROR_MESSAGES" in bridge_src, (
        "bridge must define _RESTORE_ERROR_MESSAGES"
    )
    for code in ("invalid_activity", "not_found", "not_restorable",
                 "in_progress", "invalid_date", "operation_failed"):
        assert code in bridge_src, (
            "bridge must map the '" + code + "' error code"
        )
    for msg in ("请选择有效的活动", "活动不存在", "该活动无需恢复",
                "进行中记录暂不支持恢复", "日期无效", "恢复失败",
                "加载可恢复记录失败"):
        assert msg in bridge_src, (
            "bridge must contain the Chinese message: " + msg
        )


def test_api_has_restore_function():
    """Phase 3B.8: the API must define the restore_timeline_activity and
    get_timeline_restorable_activities functions and the
    TimelineRestoreActivityError class."""
    api_src = (REPO_ROOT / "worktrace" / "api" / "timeline_api.py").read_text(
        encoding="utf-8"
    )
    assert "class TimelineRestoreActivityError" in api_src, (
        "timeline_api must define TimelineRestoreActivityError"
    )
    assert "def restore_timeline_activity" in api_src, (
        "timeline_api must define restore_timeline_activity"
    )
    assert "def get_timeline_restorable_activities" in api_src, (
        "timeline_api must define get_timeline_restorable_activities"
    )


def test_service_has_restore_function():
    """Phase 3B.8: the service must define the restore_activity and
    list_restorable_activities_for_date functions."""
    service_src = (
        REPO_ROOT / "worktrace" / "services" / "activity_service.py"
    ).read_text(encoding="utf-8")
    assert "def restore_activity" in service_src, (
        "activity_service must define restore_activity"
    )
    assert "def list_restorable_activities_for_date" in service_src, (
        "activity_service must define list_restorable_activities_for_date"
    )


def test_app_js_restore_state_independent_from_batch_states():
    """Phase 3B.8 / 3B.9: the restore saving STATE VARIABLE must be
    independent from batchProjectSaving / batchNoteSaving (declared as a
    separate variable). Phase 3B.9 adds a cross-save guard so
    saveActivityRestore refuses when a batch save is in flight; that guard
    is covered by the Phase 3B.9 cross-save tests and does not violate the
    state-variable independence."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The restore saving variable must be declared separately.
    assert "var restoreSaving" in source, (
        "app.js must declare restoreSaving as a separate variable"
    )
    assert "var restoreSavingActivityId" in source, (
        "app.js must declare restoreSavingActivityId as a separate variable"
    )
    # The setRestoreSaving helper must still set the independent
    # restoreSaving variable (not batchProjectSaving / batchNoteSaving).
    set_start = source.find("function setRestoreSaving")
    set_end = source.find("\n    function ", set_start + 1)
    set_body = source[set_start:set_end]
    assert "restoreSaving = saving" in set_body, (
        "setRestoreSaving must set the independent restoreSaving variable"
    )


def test_app_js_restore_does_not_reload_during_save():
    """Phase 3B.8: renderRestoreSection must not reload the recovery list
    while a restore save is in flight."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderRestoreSection")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "restoreSaving" in render_body, (
        "renderRestoreSection must check restoreSaving before reloading"
    )


def test_app_js_restore_load_shows_loading_placeholder():
    """Phase 3B.8: loadRestorableActivities must show a loading placeholder
    while the list loads."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    load_start = source.find("function loadRestorableActivities")
    load_end = source.find("\n    function ", load_start + 1)
    load_body = source[load_start:load_end]
    assert "加载中" in load_body, (
        "loadRestorableActivities must show a 加载中 placeholder"
    )


def test_app_js_restore_load_failure_shows_error():
    """Phase 3B.8: loadRestorableActivities must show 加载可恢复记录失败 on
    failure."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    load_start = source.find("function loadRestorableActivities")
    load_end = source.find("\n    function ", load_start + 1)
    load_body = source[load_start:load_end]
    assert "加载可恢复记录失败" in load_body, (
        "loadRestorableActivities must show 加载可恢复记录失败 on failure"
    )


def test_app_js_restore_empty_list_css_fallback():
    """Phase 3B.8: an empty restore list must rely on the CSS :empty
    rule (no explicit 'no records' text in JS)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderRestorableActivities")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    # The empty-state comment must reference the CSS :empty rule.
    assert ":empty" in render_body or "暂无可恢复记录" not in render_body, (
        "renderRestorableActivities must rely on CSS :empty for empty state"
    )


def test_styles_css_restore_empty_state():
    """Phase 3B.8: styles.css must define the empty-state fallback for the
    restore list."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "暂无可恢复记录" in source or ":empty" in source, (
        "styles.css must define the restore list empty-state fallback"
    )


# --- Phase 3B.8.1: restore hardening tests -------------------------------


def test_app_js_restore_stale_row_guard():
    """Phase 3B.8.1: saveActivityRestore must confirm the activity row
    still exists in the current restore list before calling the bridge.
    If the row is stale (e.g. the list was reloaded by an auto-refresh and
    the activity is no longer present), a safe message must be shown and
    the bridge must NOT be called."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    assert save_start != -1, "saveActivityRestore must exist"
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The stale-row guard must query the DOM for a matching restore row.
    assert "correction-shell-restore-list" in save_body, (
        "saveActivityRestore must query the restore list container"
    )
    assert "correction-shell-restore-row" in save_body, (
        "saveActivityRestore must query for restore row elements"
    )
    assert "data-activity-id" in save_body, (
        "saveActivityRestore must match rows by data-activity-id"
    )
    # The stale-row guard must show a safe message when the row is gone.
    assert "该活动已不在可恢复列表中" in save_body, (
        "saveActivityRestore must show a stale-row safe message"
    )
    # The stale-row guard must return early (not fall through to the
    # bridge call). The bridge call ("callBridge") must appear AFTER the
    # stale-row guard's return, so extract the guard body and verify
    # callBridge is not referenced before the guard's return.
    guard_start = save_body.find("correction-shell-restore-list")
    guard_return = save_body.find("return", guard_start)
    call_bridge_pos = save_body.find('callBridge("restore_timeline_activity"')
    assert call_bridge_pos != -1, (
        "saveActivityRestore must call the restore bridge method"
    )
    assert guard_return != -1 and guard_return < call_bridge_pos, (
        "saveActivityRestore stale-row guard must return before the "
        "bridge call (stale rows must not call the bridge)"
    )


def test_app_js_restore_stale_row_guard_before_dirty_check():
    """Phase 3B.8.1: the stale-row guard must run before the dirty-edit
    check so that a stale row is surfaced even when the user has unsaved
    edits (the stale row message is more specific than the dirty-edit
    block message)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    stale_guard_pos = save_body.find("correction-shell-restore-list")
    dirty_check_pos = save_body.find("isEditDirty()")
    assert stale_guard_pos != -1 and dirty_check_pos != -1, (
        "saveActivityRestore must contain both the stale-row guard and "
        "the isEditDirty() check"
    )
    assert stale_guard_pos < dirty_check_pos, (
        "saveActivityRestore stale-row guard must precede the isEditDirty() "
        "check so stale rows are surfaced before the generic dirty block"
    )


def test_app_js_restore_auto_refresh_reload_guard():
    """Phase 3B.8.1: the auto-refresh path that re-renders the correction
    shell (and thus the restore section) must be guarded by:
      1. shell open (correctionShellOpen),
      2. session match (correctionShellSessionId === found.session_id),
      3. no dirty edit (!isEditDirty()),
      4. not restore saving (restoreSaving check in renderRestoreSection).
    This test verifies the complete guard chain exists in the auto-refresh
    path of showTimeline and the renderRestoreSection function."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # 1. showTimeline auto-refresh path must guard the shell re-render.
    show_start = source.find("function showTimeline(")
    assert show_start != -1, "showTimeline must exist"
    show_end = source.find("\n    function ", show_start + 1)
    show_body = source[show_start:show_end]
    assert "correctionShellOpen" in show_body, (
        "showTimeline auto-refresh must check correctionShellOpen before "
        "re-rendering the shell (which contains the restore section)"
    )
    assert "isEditDirty()" in show_body, (
        "showTimeline auto-refresh must guard with isEditDirty() before "
        "re-rendering the shell"
    )
    assert "renderCorrectionShell" in show_body, (
        "showTimeline auto-refresh must call renderCorrectionShell (which "
        "in turn calls renderRestoreSection)"
    )
    # 2. renderRestoreSection must independently guard against an in-flight
    #    restore save (the final layer of the guard chain).
    render_start = source.find("function renderRestoreSection")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "restoreSaving" in render_body, (
        "renderRestoreSection must check restoreSaving before reloading the "
        "restore list (auto-refresh must not overwrite an in-flight save)"
    )
    # The restoreSaving guard must return early before calling
    # loadRestorableActivities so a save in flight is not clobbered.
    load_pos = render_body.find("loadRestorableActivities")
    saving_pos = render_body.find("restoreSaving")
    assert load_pos != -1, (
        "renderRestoreSection must call loadRestorableActivities"
    )
    assert saving_pos < load_pos, (
        "renderRestoreSection must check restoreSaving before calling "
        "loadRestorableActivities"
    )


def test_app_js_restore_saving_guard_in_render_returns_early():
    """Phase 3B.8.1: when restoreSaving is true, renderRestoreSection must
    return immediately (skip the loadRestorableActivities call) so the
    in-flight save's success/failure handler can complete the reload
    itself. This prevents an auto-refresh from overwriting the list while
    a restore save response is pending."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_start = source.find("function renderRestoreSection")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    # The guard must be an early return: "if (restoreSaving) return;"
    assert re.search(r"if\s*\(\s*restoreSaving\s*\)\s*return", render_body), (
        "renderRestoreSection must early-return when restoreSaving is true"
    )


def test_app_js_restore_stale_guard_does_not_change_selected_session():
    """Phase 3B.8.1: the stale-row refusal path must not change the
    selected session (only show a safe message and return). This mirrors
    the dirty-state refusal semantics."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # Extract the stale-row guard body: from the list query to the guard's
    # return statement.
    stale_guard_start = save_body.find("correction-shell-restore-list")
    # The stale-row guard block ends at the "return;" after the safe message.
    guard_return = save_body.find("return", stale_guard_start)
    assert guard_return != -1, (
        "saveActivityRestore stale-row guard must return early"
    )
    guard_body = save_body[stale_guard_start:guard_return]
    # The stale-row guard must not touch selectedSessionId.
    assert "selectedSessionId" not in guard_body, (
        "saveActivityRestore stale-row guard must not change the selected "
        "session"
    )


def test_app_js_restore_stale_guard_no_bridge_call():
    """Phase 3B.8.1: the stale-row guard path must not call callBridge.
    Only the path after the dirty-edit check (the actual restore path) may
    call the bridge."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The stale-row guard runs from the list query to its return.
    stale_guard_start = save_body.find("correction-shell-restore-list")
    stale_guard_end = save_body.find("return", stale_guard_start)
    assert stale_guard_end != -1, (
        "saveActivityRestore stale-row guard must return early"
    )
    guard_body = save_body[stale_guard_start:stale_guard_end]
    assert "callBridge" not in guard_body, (
        "saveActivityRestore stale-row guard must not call the bridge "
        "(stale rows must not trigger a restore)"
    )


# ====================================================================
# Phase 3B.9: Timeline correction shell consolidation
# ====================================================================
#
# This phase only consolidates the correction shell's internal UI
# structure, state, copy, render helpers, and CSS. It does NOT add any
# backend write capability, bridge/API/service method, DB schema, or new
# correction action. The tests below verify the consolidation is present
# and that no forbidden capability was introduced.


def test_index_html_correction_shell_has_context_card_3b9():
    """Phase 3B.9: index.html must wrap the context block in a
    correction-shell-context-card."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-context-card"' in source, (
        "index.html must contain #correction-shell-context-card"
    )
    assert "correction-shell-context-card" in source, (
        "index.html must define the .correction-shell-context-card class"
    )


def test_index_html_correction_shell_has_activity_card_3b9():
    """Phase 3B.9: index.html must wrap the activities block in a
    correction-shell-activity-card."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-activity-card"' in source, (
        "index.html must contain #correction-shell-activity-card"
    )
    assert "correction-shell-activity-card" in source


def test_index_html_correction_shell_has_single_action_card_3b9():
    """Phase 3B.9: index.html must wrap the actions block in a
    correction-shell-single-action-card."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-single-action-card"' in source, (
        "index.html must contain #correction-shell-single-action-card"
    )
    assert "correction-shell-single-action-card" in source


def test_index_html_correction_shell_has_batch_action_card_3b9():
    """Phase 3B.9: index.html must wrap the batch project + batch note
    sections in a single correction-shell-batch-action-card."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-batch-action-card"' in source, (
        "index.html must contain #correction-shell-batch-action-card"
    )
    assert "correction-shell-batch-action-card" in source
    # The batch action card must contain both batch project and batch note
    # sections.
    card_start = source.find('id="correction-shell-batch-action-card"')
    card_end = source.find("</div>", source.find(
        'id="correction-shell-batch-note-status"', card_start))
    assert card_start != -1 and card_end != -1, (
        "batch action card must contain both batch sections"
    )
    card_block = source[card_start:card_end]
    assert 'id="correction-shell-batch-project-section"' in card_block, (
        "batch action card must contain the batch project section"
    )
    assert 'id="correction-shell-batch-note-section"' in card_block, (
        "batch action card must contain the batch note section"
    )


def test_index_html_correction_shell_has_restore_card_3b9():
    """Phase 3B.9: index.html must wrap the restore section in a
    correction-shell-restore-card."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-restore-card"' in source, (
        "index.html must contain #correction-shell-restore-card"
    )
    assert "correction-shell-restore-card" in source
    # The restore card must contain the restore list and status, but no
    # batch restore / restore all / permanent delete / undo UI.
    card_start = source.find('id="correction-shell-restore-card"')
    card_end = source.find("</div>", source.find(
        'id="correction-shell-restore-status"', card_start))
    card_block = source[card_start:card_end]
    assert 'id="correction-shell-restore-list"' in card_block, (
        "restore card must contain the restore list"
    )
    assert 'id="correction-shell-restore-status"' in card_block, (
        "restore card must contain the restore status"
    )
    forbidden = ("batch-restore", "restore-all", "permanent-delete",
                 "undo-stack", "batch-undo")
    for token in forbidden:
        assert token not in card_block, (
            "restore card must not contain " + token + " UI"
        )


def test_index_html_correction_shell_has_not_implemented_card_3b9():
    """Phase 3B.9: index.html must contain a not-implemented hint card
    that explicitly lists the unsupported batch / undo / permanent delete
    capabilities."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-not-implemented-card"' in source, (
        "index.html must contain #correction-shell-not-implemented-card"
    )
    card_start = source.find('id="correction-shell-not-implemented-card"')
    card_end = source.find("</div>", source.find(
        "correction-shell-card-hint", card_start))
    card_block = source[card_start:card_end]
    # The hint must mention each forbidden capability family.
    for keyword in ("批量隐藏", "批量删除", "批量恢复", "撤销栈",
                    "永久删除", "批量时间", "批量拆分", "批量合并"):
        assert keyword in card_block, (
            "not-implemented card must mention " + keyword
        )


def test_index_html_correction_shell_card_headers_present_3b9():
    """Phase 3B.9: each card must have a .correction-shell-card-header."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "correction-shell-card-header" in source, (
        "index.html must define .correction-shell-card-header elements"
    )
    # Count occurrences: context / activity / single-action / batch /
    # restore / not-implemented = 6 headers.
    assert source.count("correction-shell-card-header") >= 6, (
        "index.html must contain at least 6 card headers"
    )


def test_index_html_correction_shell_preserves_existing_ids_3b9():
    """Phase 3B.9: consolidation must not remove any existing IDs that
    prior-phase tests depend on."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for required_id in (
        "timeline-correction-shell",
        "correction-shell-close-btn",
        "correction-shell-status",
        "correction-shell-context",
        "correction-shell-activities",
        "correction-shell-actions",
        "correction-shell-batch-project-section",
        "correction-shell-batch-save-btn",
        "correction-shell-batch-project-select",
        "correction-shell-batch-count",
        "correction-shell-batch-select-all-btn",
        "correction-shell-batch-clear-btn",
        "correction-shell-batch-status",
        "correction-shell-batch-note-section",
        "correction-shell-batch-note-text",
        "correction-shell-batch-note-save-btn",
        "correction-shell-batch-note-count",
        "correction-shell-batch-note-status",
        "correction-shell-restore-section",
        "correction-shell-restore-list",
        "correction-shell-restore-status",
        "open-correction-shell-btn",
    ):
        assert 'id="' + required_id + '"' in source, (
            "index.html must preserve id=" + required_id
        )


def test_index_html_correction_shell_no_new_forbidden_controls_3b9():
    """Phase 3B.9: the consolidation must not introduce batch hide /
    delete / restore, restore-all, undo stack, permanent delete, batch
    time / split / merge UI controls."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    forbidden_ids = (
        "batch-hide-btn",
        "batch-delete-btn",
        "batch-restore-btn",
        "restore-all-btn",
        "permanent-delete-btn",
        "undo-stack-btn",
        "batch-time-btn",
        "batch-split-btn",
        "batch-merge-btn",
        "batch-note-append-btn",
        "batch-note-merge-btn",
        "auto-rule-btn",
        "overlap-detection-btn",
    )
    for forbidden_id in forbidden_ids:
        assert 'id="' + forbidden_id + '"' not in source, (
            "index.html must not contain id=" + forbidden_id
        )


def test_index_html_correction_shell_no_external_resources_3b9():
    """Phase 3B.9: the correction shell region must not introduce
    external links, CDN, Google Fonts, or browser storage."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    shell_start = source.find('id="timeline-correction-shell"')
    shell_end = source.find("</section>", shell_start)
    shell_block = source[shell_start:shell_end]
    for forbidden in ("http://", "https://", "cdn.", "googleapis.com",
                      "fonts.googleapis", "localStorage",
                      "sessionStorage"):
        assert forbidden not in shell_block, (
            "correction shell must not reference " + forbidden
        )


def test_app_js_has_safe_text_helper_3b9():
    """Phase 3B.9: app.js must define a safeText display-safe helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function safeText" in source, (
        "app.js must define the safeText helper"
    )


def test_app_js_safe_text_returns_fallback_3b9():
    """Phase 3B.9: safeText must return the fallback for null / undefined /
    empty values, and stringify non-empty values."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "safeText")
    assert "null" in body, "safeText must handle null"
    assert "undefined" in body, "safeText must handle undefined"
    assert "fallback" in body, "safeText must accept a fallback"
    assert "String(" in body, "safeText must stringify non-empty values"


def test_app_js_has_is_any_correction_write_saving_helper_3b9():
    """Phase 3B.9: app.js must define an isAnyCorrectionWriteSaving
    cross-save guard helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function isAnyCorrectionWriteSaving" in source, (
        "app.js must define the isAnyCorrectionWriteSaving helper"
    )
    body = _func_body(source, "isAnyCorrectionWriteSaving")
    assert "batchProjectSaving" in body, (
        "isAnyCorrectionWriteSaving must consult batchProjectSaving"
    )
    assert "batchNoteSaving" in body, (
        "isAnyCorrectionWriteSaving must consult batchNoteSaving"
    )
    assert "restoreSaving" in body, (
        "isAnyCorrectionWriteSaving must consult restoreSaving"
    )


def test_app_js_has_reset_correction_action_status_helper_3b9():
    """Phase 3B.9: app.js must define a resetCorrectionActionStatus helper
    that clears every shell status area."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function resetCorrectionActionStatus" in source, (
        "app.js must define the resetCorrectionActionStatus helper"
    )
    body = _func_body(source, "resetCorrectionActionStatus")
    assert "setCorrectionShellStatus" in body, (
        "resetCorrectionActionStatus must clear the shell status"
    )
    assert "showBatchProjectStatus" in body, (
        "resetCorrectionActionStatus must clear the batch project status"
    )
    assert "showBatchNoteStatus" in body, (
        "resetCorrectionActionStatus must clear the batch note status"
    )
    assert "showRestoreStatus" in body, (
        "resetCorrectionActionStatus must clear the restore status"
    )


def test_app_js_open_correction_shell_calls_reset_action_status_3b9():
    """Phase 3B.9: openCorrectionShell must call resetCorrectionActionStatus
    so stale messages from a previous shell session do not linger."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "openCorrectionShell")
    assert "resetCorrectionActionStatus" in body, (
        "openCorrectionShell must call resetCorrectionActionStatus"
    )


def test_app_js_render_correction_shell_uses_safe_text_3b9():
    """Phase 3B.9: renderCorrectionShell must pass dynamic values through
    safeText so the shell never renders undefined / null."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderCorrectionShell")
    assert "safeText" in body, (
        "renderCorrectionShell must use safeText for dynamic values"
    )


def test_app_js_render_restorable_activities_uses_safe_text_3b9():
    """Phase 3B.9: renderRestorableActivities must pass dynamic values
    through safeText so the restore list never renders undefined / null."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderRestorableActivities")
    assert "safeText" in body, (
        "renderRestorableActivities must use safeText for dynamic values"
    )


def test_app_js_render_correction_shell_still_uses_escape_html_3b9():
    """Phase 3B.9: renderCorrectionShell must still escapeHtml every
    dynamic value before inserting into innerHTML."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderCorrectionShell")
    assert "escapeHtml" in body, (
        "renderCorrectionShell must still use escapeHtml"
    )


def test_app_js_correction_shell_no_raw_sensitive_fields_3b9():
    """Phase 3B.9: the correction shell render path must not read raw
    window_title / file_path_hint / full_path / clipboard / note internals
    / traceback / SQL / exception text."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderCorrectionShell")
    for forbidden in ("window_title", "file_path_hint", "file_path",
                      "full_path", "clipboard", "session_note",
                      "traceback", "SQL", "Exception"):
        assert forbidden not in body, (
            "renderCorrectionShell must not read " + forbidden
        )


def test_app_js_render_restorable_activities_no_raw_sensitive_fields_3b9():
    """Phase 3B.9: the restore list render path must not read raw
    window_title / file_path_hint / full_path / clipboard / note internals
    / traceback / SQL / exception text."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderRestorableActivities")
    for forbidden in ("window_title", "file_path_hint", "file_path",
                      "full_path", "clipboard", "session_note",
                      "traceback", "SQL", "Exception"):
        assert forbidden not in body, (
            "renderRestorableActivities must not read " + forbidden
        )


def test_app_js_save_batch_project_has_cross_save_guard_3b9():
    """Phase 3B.9: saveBatchProject must refuse when a batch note save or
    single restore is in flight (cross-save guard)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "saveBatchProject")
    assert "restoreSaving" in body, (
        "saveBatchProject must guard against restoreSaving"
    )
    assert "batchNoteSaving" in body, (
        "saveBatchProject must guard against batchNoteSaving"
    )
    assert "请等待当前操作完成" in body, (
        "saveBatchProject cross-save guard must use the unified message"
    )


def test_app_js_save_batch_note_has_cross_save_guard_3b9():
    """Phase 3B.9: saveBatchNote must refuse when a single restore is in
    flight (cross-save guard)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "saveBatchNote")
    assert "restoreSaving" in body, (
        "saveBatchNote must guard against restoreSaving"
    )
    assert "请等待当前操作完成" in body, (
        "saveBatchNote cross-save guard must use the unified message"
    )


def test_app_js_save_activity_restore_has_cross_save_guard_3b9():
    """Phase 3B.9: saveActivityRestore must refuse when a batch project or
    batch note save is in flight (cross-save guard)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "saveActivityRestore")
    assert "batchProjectSaving" in body, (
        "saveActivityRestore must guard against batchProjectSaving"
    )
    assert "batchNoteSaving" in body, (
        "saveActivityRestore must guard against batchNoteSaving"
    )
    assert "请等待当前操作完成" in body, (
        "saveActivityRestore cross-save guard must use the unified message"
    )


def test_app_js_save_activity_restore_cross_save_after_dirty_check_3b9():
    """Phase 3B.9: the cross-save guard in saveActivityRestore must come
    AFTER the dirty-edit check (the stale-row guard must still come before
    the dirty-edit check, per Phase 3B.8.1)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "saveActivityRestore")
    stale_pos = body.find("correction-shell-restore-list")
    dirty_pos = body.find("isEditDirty()")
    cross_pos = body.find("batchProjectSaving || batchNoteSaving")
    assert stale_pos != -1 and dirty_pos != -1 and cross_pos != -1, (
        "saveActivityRestore must contain all three guards"
    )
    assert stale_pos < dirty_pos, (
        "stale-row guard must precede the dirty-edit check"
    )
    assert dirty_pos < cross_pos, (
        "cross-save guard must come after the dirty-edit check"
    )


def test_app_js_save_activity_restore_cross_save_no_bridge_call_3b9():
    """Phase 3B.9: the cross-save guard path in saveActivityRestore must
    not call callBridge."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "saveActivityRestore")
    cross_start = body.find("batchProjectSaving || batchNoteSaving")
    cross_end = body.find("return", cross_start)
    assert cross_end != -1, (
        "saveActivityRestore cross-save guard must return early"
    )
    guard_body = body[cross_start:cross_end]
    assert "callBridge" not in guard_body, (
        "saveActivityRestore cross-save guard must not call the bridge"
    )


def test_app_js_reset_correction_shell_state_still_resets_all_3b9():
    """Phase 3B.9: resetCorrectionShellState must still call the three
    sub-reset helpers (batch project / batch note / restore)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "resetCorrectionShellState")
    assert "resetBatchProjectState" in body, (
        "resetCorrectionShellState must still call resetBatchProjectState"
    )
    assert "resetBatchNoteState" in body, (
        "resetCorrectionShellState must still call resetBatchNoteState"
    )
    assert "resetRestoreState" in body, (
        "resetCorrectionShellState must still call resetRestoreState"
    )


def test_app_js_reset_correction_shell_state_independent_of_edit_saving_3b9():
    """Phase 3B.9: resetCorrectionShellState must not reset the edit /
    time / split / merge / hide / delete saving states (those are owned by
    clearEditPanel)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "resetCorrectionShellState")
    for saving in ("editSaving", "timeSaving", "activityTimeSaving",
                   "sessionSplitSaving", "activitySplitSaving", "mergeSaving",
                   "hideSaving", "deleteSaving", "editingSession"):
        assert saving not in body, (
            "resetCorrectionShellState must not reset " + saving
        )


def test_app_js_close_correction_shell_no_write_3b9():
    """Phase 3B.9: closeCorrectionShell must not trigger a refresh or any
    write action."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "closeCorrectionShell")
    for forbidden in ("loadTimeline", "refreshAll", "callBridge",
                      "saveProject", "saveNote", "saveActivityTime",
                      "saveSessionTime", "saveActivitySplit", "saveSessionSplit",
                      "saveMerge", "saveHide", "saveDelete",
                      "saveBatchProject", "saveBatchNote",
                      "saveActivityRestore"):
        assert forbidden not in body, (
            "closeCorrectionShell must not call " + forbidden
        )


def test_app_js_correction_shell_no_local_storage_3b9():
    """Phase 3B.9: the correction shell must not use localStorage or
    sessionStorage."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in source, (
            "app.js must not use " + forbidden
        )


def test_app_js_correction_shell_no_external_links_3b9():
    """Phase 3B.9: app.js must not reference external links, CDN, or
    Google Fonts."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("http://", "https://", "cdn.", "googleapis.com",
                      "fonts.googleapis"):
        assert forbidden not in source, (
            "app.js must not reference " + forbidden
        )


def test_app_js_correction_shell_no_traceback_display_3b9():
    """Phase 3B.9: app.js must not display tracebacks / SQL / raw exception
    text in the correction shell."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("traceback", "Traceback", "SQL", "Exception"):
        assert forbidden not in source, (
            "app.js must not display " + forbidden
        )


def test_app_js_correction_shell_no_new_forbidden_handlers_3b9():
    """Phase 3B.9: the consolidation must not introduce batch hide /
    delete, batch restore, restore all, undo stack, permanent delete,
    auto-rule, or global overlap detection handlers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("batchHide", "batchDelete", "batchRestore",
                      "restoreAll", "restore_all",
                      "permanentDelete", "permanent_delete",
                      "undoStack", "undo_stack",
                      "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap",
                      "batchTimeCorrection", "batchSplit", "batchMerge",
                      "batchNoteAppend", "batchNoteMerge"):
        assert forbidden not in source, (
            "app.js must not contain " + forbidden + " handler"
        )


def test_app_js_batch_project_and_note_share_selection_3b9():
    """Phase 3B.9: batch project and batch note must share the same
    selectedBatchActivityIds selection (single source of truth)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    project_body = _func_body(source, "saveBatchProject")
    note_body = _func_body(source, "saveBatchNote")
    assert "selectedBatchActivityIds" in project_body, (
        "saveBatchProject must read from the shared selection"
    )
    assert "selectedBatchActivityIds" in note_body, (
        "saveBatchNote must read from the shared selection"
    )


def test_styles_css_has_correction_shell_card_styles_3b9():
    """Phase 3B.9: styles.css must define the unified .correction-shell-card
    style and its variants."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell-card" in source, (
        "styles.css must define .correction-shell-card"
    )
    assert ".correction-shell-card-header" in source, (
        "styles.css must define .correction-shell-card-header"
    )
    assert ".correction-shell-card-hint" in source, (
        "styles.css must define .correction-shell-card-hint"
    )
    assert ".correction-shell-card[hidden]" in source, (
        "styles.css must hide .correction-shell-card[hidden]"
    )


def test_styles_css_correction_shell_hidden_still_display_none_3b9():
    """Phase 3B.9: .correction-shell[hidden] must still be display:none."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must keep the .correction-shell[hidden] rule"
    )


def test_styles_css_has_card_responsive_rules_3b9():
    """Phase 3B.9: styles.css must keep the correction shell cards stable
    on narrow viewports."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    # The responsive block must reference the card class.
    assert ".correction-shell-card" in source, (
        "styles.css responsive block must reference .correction-shell-card"
    )


def test_styles_css_no_external_resources_3b9():
    """Phase 3B.9: styles.css must not reference external resources."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for forbidden in ("http://", "https://", "cdn.", "googleapis.com",
                      "fonts.googleapis", "@import"):
        assert forbidden not in source, (
            "styles.css must not reference " + forbidden
        )


def test_bridge_no_new_methods_for_phase_3b_9():
    """Phase 3B.9: the bridge must not gain new methods. The existing
    project / note / time / split / merge / hide / delete / batch project /
    batch note / restore methods must still be present."""
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
        "def batch_update_timeline_activities_project",
        "def batch_update_timeline_activities_note",
        "def restore_timeline_activity",
        "def get_timeline_restorable_activities",
    ):
        assert required in bridge_src, (
            "bridge must still define " + required
        )


def test_bridge_imports_only_allowed_modules_3b_9():
    """Phase 3B.9: the bridge must still only import worktrace.api and
    worktrace.formatters; no direct service / db / collector / security /
    runtime / config imports."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    for forbidden in ("from ..services", "from ..db",
                      "from ..collector", "from ..security",
                      "from ..runtime", "from ..config",
                      "import worktrace.services",
                      "import worktrace.db"):
        assert forbidden not in bridge_src, (
            "bridge must not import " + forbidden
        )


def test_docs_mention_phase_3b_9():
    """Phase 3B.9: the migration doc must mention Phase 3B.9."""
    doc_path = REPO_ROOT / "docs" / "ui-webview-migration.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3B.9" in source, (
        "ui-webview-migration.md must mention Phase 3B.9"
    )
    assert "consolidation" in source.lower() or "整理" in source, (
        "ui-webview-migration.md must describe 3B.9 as consolidation"
    )


def test_docs_readme_mentions_phase_3b_9():
    """Phase 3B.9: README must mention Phase 3B.9."""
    doc_path = REPO_ROOT / "README.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3B.9" in source, (
        "README.md must mention Phase 3B.9"
    )


def test_docs_release_validation_mentions_phase_3b_9():
    """Phase 3B.9: release-validation must mention Phase 3B.9."""
    doc_path = REPO_ROOT / "docs" / "release-validation.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3B.9" in source, (
        "release-validation.md must mention Phase 3B.9"
    )


# ======================================================================
# Phase 3B.9.1 — Timeline correction shell consolidation hardening
# ======================================================================
# These tests lock the hardening contracts introduced by Phase 3B.9.1:
#   1. saveBatchNote cross-save guard uses the unified message for
#      batchProjectSaving (not "操作失败").
#   2. The auto-refresh re-render path checks isAnyCorrectionWriteSaving()
#      so a save in flight is never overwritten.
#   3. renderBatchProjectSection / renderBatchNoteSection do not clear
#      their status area while a save is in flight.
#   4. Existing Phase 3B.9 contracts (cards, helpers, guards, reset
#      paths, display-safe, CSS, boundary) continue to hold.


def test_app_js_save_batch_note_cross_save_uses_unified_message_3b9_1():
    """Phase 3B.9.1: saveBatchNote must use the unified cross-save message
    '请等待当前操作完成' for BOTH batchProjectSaving and restoreSaving, not
    '操作失败' for batchProjectSaving."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "saveBatchNote")
    # The consolidated cross-save guard checks both flags together.
    assert "batchProjectSaving || restoreSaving" in body, (
        "saveBatchNote must consolidate the cross-save guard into a single "
        "check covering batchProjectSaving and restoreSaving"
    )
    # The unified message must appear in the cross-save guard section.
    cross_pos = body.find("batchProjectSaving || restoreSaving")
    assert cross_pos != -1, "cross-save guard must exist"
    guard_section = body[cross_pos:cross_pos + 200]
    assert "请等待当前操作完成" in guard_section, (
        "saveBatchNote cross-save guard must use the unified message"
    )


def test_app_js_save_batch_note_no_legacy_failure_message_for_cross_save_3b9_1():
    """Phase 3B.9.1: saveBatchNote must NOT use '操作失败' for the
    batchProjectSaving cross-save (that was the pre-hardening behavior)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "saveBatchNote")
    # The cross-save guard section must not contain '操作失败'.
    cross_pos = body.find("batchProjectSaving || restoreSaving")
    assert cross_pos != -1
    # Look at the guard block up to the next 'return'.
    ret_pos = body.find("return", cross_pos)
    guard_block = body[cross_pos:ret_pos] if ret_pos != -1 else body[cross_pos:]
    assert "操作失败" not in guard_block, (
        "saveBatchNote cross-save guard must not use '操作失败'"
    )


def test_app_js_auto_refresh_checks_correction_write_saving_3b9_1():
    """Phase 3B.9.1: the auto-refresh re-render path must check
    isAnyCorrectionWriteSaving() so a save in flight is not overwritten."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The auto-refresh guard is in the session-found branch of the
    # timeline render path. It must include isAnyCorrectionWriteSaving().
    # We search for the combined condition.
    assert "isAnyCorrectionWriteSaving()" in source, (
        "app.js must call isAnyCorrectionWriteSaving()"
    )
    # The auto-refresh block must combine the four conditions.
    assert "correctionShellOpen" in source
    assert "correctionShellSessionId === found.session_id" in source
    # The isAnyCorrectionWriteSaving check must appear near the
    # renderCorrectionShell call in the auto-refresh path.
    render_pos = source.find("renderCorrectionShell(")
    assert render_pos != -1
    # Find the auto-refresh renderCorrectionShell call (not the one in
    # openCorrectionShell). The auto-refresh path is preceded by the
    # isAnyCorrectionWriteSaving guard.
    auto_refresh_section = source[max(0, render_pos - 600):render_pos]
    assert "isAnyCorrectionWriteSaving()" in auto_refresh_section, (
        "auto-refresh path must guard renderCorrectionShell with "
        "isAnyCorrectionWriteSaving()"
    )


def test_app_js_render_batch_project_section_status_guard_3b9_1():
    """Phase 3B.9.1: renderBatchProjectSection must not clear the batch
    project status while a batch project save is in flight."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderBatchProjectSection")
    # The showBatchProjectStatus("", false) call must be wrapped in a
    # !batchProjectSaving guard.
    status_pos = body.find('showBatchProjectStatus("", false)')
    assert status_pos != -1, (
        "renderBatchProjectSection must call showBatchProjectStatus"
    )
    # Look backwards from the status call for the guard.
    preceding = body[max(0, status_pos - 200):status_pos]
    assert "batchProjectSaving" in preceding, (
        "renderBatchProjectSection must guard showBatchProjectStatus with "
        "batchProjectSaving"
    )
    assert "if (!batchProjectSaving)" in body, (
        "renderBatchProjectSection must wrap status clear in "
        "if (!batchProjectSaving)"
    )


def test_app_js_render_batch_note_section_status_guard_3b9_1():
    """Phase 3B.9.1: renderBatchNoteSection must not clear the batch note
    status while a batch note save is in flight."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "renderBatchNoteSection")
    status_pos = body.find('showBatchNoteStatus("", false)')
    assert status_pos != -1, (
        "renderBatchNoteSection must call showBatchNoteStatus"
    )
    preceding = body[max(0, status_pos - 200):status_pos]
    assert "batchNoteSaving" in preceding, (
        "renderBatchNoteSection must guard showBatchNoteStatus with "
        "batchNoteSaving"
    )
    assert "if (!batchNoteSaving)" in body, (
        "renderBatchNoteSection must wrap status clear in "
        "if (!batchNoteSaving)"
    )


def test_app_js_cross_save_guard_order_dirty_before_cross_save_3b9_1():
    """Phase 3B.9.1: in all three consolidated write paths, the dirty guard
    (isEditDirty) must come BEFORE the cross-save guard."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for func_name, cross_marker in [
        ("saveBatchProject", "batchNoteSaving || restoreSaving"),
        ("saveBatchNote", "batchProjectSaving || restoreSaving"),
        ("saveActivityRestore", "batchProjectSaving || batchNoteSaving"),
    ]:
        body = _func_body(source, func_name)
        dirty_pos = body.find("isEditDirty()")
        cross_pos = body.find(cross_marker)
        assert dirty_pos != -1, (
            func_name + " must contain isEditDirty check"
        )
        assert cross_pos != -1, (
            func_name + " must contain cross-save guard"
        )
        assert dirty_pos < cross_pos, (
            func_name + ": dirty guard must precede cross-save guard"
        )


def test_app_js_cross_save_guard_no_bridge_call_3b9_1():
    """Phase 3B.9.1: none of the three cross-save guard paths may call
    callBridge before returning."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for func_name, cross_marker in [
        ("saveBatchProject", "batchNoteSaving || restoreSaving"),
        ("saveBatchNote", "batchProjectSaving || restoreSaving"),
        ("saveActivityRestore", "batchProjectSaving || batchNoteSaving"),
    ]:
        body = _func_body(source, func_name)
        cross_pos = body.find(cross_marker)
        assert cross_pos != -1
        ret_pos = body.find("return", cross_pos)
        assert ret_pos != -1, (
            func_name + " cross-save guard must return early"
        )
        guard_block = body[cross_pos:ret_pos]
        assert "callBridge" not in guard_block, (
            func_name + " cross-save guard must not call the bridge"
        )


def test_app_js_cross_save_guard_preserves_state_3b9_1():
    """Phase 3B.9.1: the cross-save guard paths must not clear selection,
    textarea, or restore list (they only show a status and return)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for func_name, cross_marker in [
        ("saveBatchProject", "batchNoteSaving || restoreSaving"),
        ("saveBatchNote", "batchProjectSaving || restoreSaving"),
        ("saveActivityRestore", "batchProjectSaving || batchNoteSaving"),
    ]:
        body = _func_body(source, func_name)
        cross_pos = body.find(cross_marker)
        assert cross_pos != -1
        ret_pos = body.find("return", cross_pos)
        guard_block = body[cross_pos:ret_pos]
        # The guard block must not clear selection or textarea.
        assert "selectedBatchActivityIds = {}" not in guard_block, (
            func_name + " cross-save guard must not clear selection"
        )
        assert ".value = ''" not in guard_block, (
            func_name + " cross-save guard must not clear textarea"
        )


def test_app_js_is_any_correction_write_saving_covers_three_states_3b9_1():
    """Phase 3B.9.1: isAnyCorrectionWriteSaving must cover batchProjectSaving,
    batchNoteSaving, and restoreSaving."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "isAnyCorrectionWriteSaving")
    assert "batchProjectSaving" in body, (
        "isAnyCorrectionWriteSaving must check batchProjectSaving"
    )
    assert "batchNoteSaving" in body, (
        "isAnyCorrectionWriteSaving must check batchNoteSaving"
    )
    assert "restoreSaving" in body, (
        "isAnyCorrectionWriteSaving must check restoreSaving"
    )


def test_app_js_reset_correction_shell_state_calls_sub_resets_3b9_1():
    """Phase 3B.9.1: resetCorrectionShellState must still call all three
    sub-reset helpers."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "resetCorrectionShellState")
    assert "resetBatchProjectState()" in body, (
        "resetCorrectionShellState must call resetBatchProjectState"
    )
    assert "resetBatchNoteState()" in body, (
        "resetCorrectionShellState must call resetBatchNoteState"
    )
    assert "resetRestoreState()" in body, (
        "resetCorrectionShellState must call resetRestoreState"
    )


def test_app_js_reset_paths_cover_all_contexts_3b9_1():
    """Phase 3B.9.1: resetCorrectionShellState must be called on close,
    date switch, session switch, and session disappear paths."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # closeCorrectionShell must call resetCorrectionShellState.
    close_body = _func_body(source, "closeCorrectionShell")
    assert "resetCorrectionShellState()" in close_body, (
        "closeCorrectionShell must call resetCorrectionShellState"
    )
    # goPrevDay / goNextDay / goToday must call resetCorrectionShellState.
    for fn in ("goPrevDay", "goNextDay", "goToday"):
        body = _func_body(source, fn)
        assert "resetCorrectionShellState()" in body, (
            fn + " must call resetCorrectionShellState"
        )
    # selectTimelineSession must call resetCorrectionShellState when
    # switching sessions.
    sel_body = _func_body(source, "selectTimelineSession")
    assert "resetCorrectionShellState()" in sel_body, (
        "selectTimelineSession must call resetCorrectionShellState"
    )


def test_app_js_close_correction_shell_preserves_selected_session_3b9_1():
    """Phase 3B.9.1: closeCorrectionShell must NOT clear selectedSessionId
    (the user returns to the same session context)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    body = _func_body(source, "closeCorrectionShell")
    # The comment documenting the preserve semantics must be present.
    assert "selectedSessionId" in body, (
        "closeCorrectionShell must reference selectedSessionId"
    )
    # It must not assign null to selectedSessionId.
    assert "selectedSessionId = null" not in body, (
        "closeCorrectionShell must not clear selectedSessionId"
    )


def test_app_js_safe_text_still_used_in_correction_shell_3b9_1():
    """Phase 3B.9.1: renderCorrectionShell and renderRestorableActivities
    must still use safeText for dynamic values."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_body = _func_body(source, "renderCorrectionShell")
    assert "safeText(" in render_body, (
        "renderCorrectionShell must use safeText"
    )
    restore_body = _func_body(source, "renderRestorableActivities")
    assert "safeText(" in restore_body, (
        "renderRestorableActivities must use safeText"
    )


def test_app_js_correction_shell_no_raw_sensitive_fields_3b9_1():
    """Phase 3B.9.1: app.js must not reference raw sensitive backend column
    names anywhere (window_title, file_path_hint, full_path, clipboard)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    for forbidden in ("window_title", "file_path_hint", "full_path",
                      "clipboard"):
        assert forbidden not in source, (
            "app.js must not reference raw sensitive field: " + forbidden
        )


def test_app_js_correction_shell_escape_html_still_used_3b9_1():
    """Phase 3B.9.1: escapeHtml must still be used in correction shell
    rendering paths."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    render_body = _func_body(source, "renderCorrectionShell")
    assert "escapeHtml(" in render_body, (
        "renderCorrectionShell must use escapeHtml"
    )
    restore_body = _func_body(source, "renderRestorableActivities")
    assert "escapeHtml(" in restore_body, (
        "renderRestorableActivities must use escapeHtml"
    )


def test_app_js_correction_shell_no_local_storage_3b9_1():
    """Phase 3B.9.1: app.js must not use localStorage or sessionStorage."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    assert "localstorage" not in source, (
        "app.js must not use localStorage"
    )
    assert "sessionstorage" not in source, (
        "app.js must not use sessionStorage"
    )


def test_app_js_correction_shell_no_external_links_3b9_1():
    """Phase 3B.9.1: app.js must not reference external http/https/CDN
    resources."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("http://", "https://", "//cdn", "googleapis"):
        assert forbidden not in source, (
            "app.js must not reference external resource: " + forbidden
        )


def test_app_js_correction_shell_no_traceback_display_3b9_1():
    """Phase 3B.9.1: app.js must not display traceback or raw exception
    text in correction shell status areas."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8").lower()
    assert "traceback" not in source, (
        "app.js must not display traceback"
    )


def test_index_html_correction_shell_cards_still_present_3b9_1():
    """Phase 3B.9.1: all six correction shell cards must still be present
    in index.html."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for card_id in (
        "correction-shell-context-card",
        "correction-shell-activity-card",
        "correction-shell-single-action-card",
        "correction-shell-batch-action-card",
        "correction-shell-restore-card",
        "correction-shell-not-implemented-card",
    ):
        assert card_id in source, (
            "index.html must contain " + card_id
        )


def test_index_html_correction_shell_existing_ids_preserved_3b9_1():
    """Phase 3B.9.1: all existing JS-dependent ids must still be present."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "timeline-correction-shell",
        "correction-shell-close-btn",
        "correction-shell-status",
        "correction-shell-context",
        "correction-shell-activities",
        "correction-shell-actions",
        "correction-shell-batch-project-section",
        "correction-shell-batch-save-btn",
        "correction-shell-batch-project-select",
        "correction-shell-batch-count",
        "correction-shell-batch-select-all-btn",
        "correction-shell-batch-clear-btn",
        "correction-shell-batch-status",
        "correction-shell-batch-note-section",
        "correction-shell-batch-note-text",
        "correction-shell-batch-note-save-btn",
        "correction-shell-batch-note-count",
        "correction-shell-batch-note-status",
        "correction-shell-restore-section",
        "correction-shell-restore-list",
        "correction-shell-restore-status",
        "open-correction-shell-btn",
    ):
        assert element_id in source, (
            "index.html must preserve existing id: " + element_id
        )


def test_index_html_no_forbidden_batch_ui_3b9_1():
    """Phase 3B.9.1: index.html must not contain batch hide / batch delete /
    batch restore / undo stack / permanent delete UI controls."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for forbidden in (
        "batch-hide",
        "batch-delete",
        "batch-restore",
        "restore-all",
        "undo-stack",
        "permanent-delete",
    ):
        # The not-implemented card may mention these as "暂不开放" text;
        # that is allowed. Forbidden UI controls (buttons / checkboxes with
        # these ids) are what we check for.
        assert ('id="' + forbidden + '"') not in source, (
            "index.html must not contain forbidden UI control id: "
            + forbidden
        )


def test_index_html_not_implemented_card_lists_unavailable_3b9_1():
    """Phase 3B.9.1: the not-implemented card must list all unavailable
    capabilities."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    not_impl_pos = source.find("correction-shell-not-implemented-card")
    assert not_impl_pos != -1
    not_impl_section = source[not_impl_pos:not_impl_pos + 600]
    for keyword in ("批量隐藏", "批量删除", "批量恢复", "撤销栈",
                    "永久删除", "批量时间", "批量拆分", "批量合并",
                    "自动规则", "重叠检测"):
        assert keyword in not_impl_section, (
            "not-implemented card must list: " + keyword
        )


def test_styles_css_correction_shell_hidden_display_none_3b9_1():
    """Phase 3B.9.1: .correction-shell[hidden] must remain display:none."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must have .correction-shell[hidden] rule"
    )
    pos = source.find(".correction-shell[hidden]")
    rule = source[pos:pos + 80]
    assert "display: none" in rule, (
        ".correction-shell[hidden] must set display: none"
    )


def test_styles_css_card_classes_present_3b9_1():
    """Phase 3B.9.1: unified card CSS classes must still be present."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (
        ".correction-shell-card",
        ".correction-shell-card-header",
        ".correction-shell-card-hint",
        ".correction-shell-status",
    ):
        assert cls in source, (
            "styles.css must contain " + cls
        )


def test_styles_css_no_external_resources_3b9_1():
    """Phase 3B.9.1: styles.css must not reference external resources."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8").lower()
    for forbidden in ("http://", "https://", "@import", "googleapis",
                      "cdn"):
        assert forbidden not in source, (
            "styles.css must not reference external resource: " + forbidden
        )


def test_styles_css_highlight_still_present_3b9_1():
    """Phase 3B.9.1: the transient highlight CSS must still be present."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "detail-item-highlight" in source, (
        "styles.css must retain .detail-item-highlight"
    )
    assert "shell-target" in source, (
        "styles.css must retain .shell-target"
    )


def test_bridge_no_new_methods_for_phase_3b9_1():
    """Phase 3B.9.1: no new bridge methods beyond the known set."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    known_methods = (
        "get_status",
        "toggle_pause",
        "get_overview",
        "get_recent_activities",
        "get_timeline",
        "get_timeline_session_details",
        "list_projects_for_timeline",
        "update_timeline_project",
        "update_timeline_note",
        "update_timeline_activity_time",
        "update_timeline_session_time",
        "split_timeline_activity",
        "split_timeline_session",
        "merge_timeline_activities",
        "hide_timeline_activity",
        "soft_delete_timeline_activity",
        "hide_timeline_session",
        "soft_delete_timeline_session",
        "batch_update_timeline_activities_project",
        "batch_update_timeline_activities_note",
        "get_timeline_restorable_activities",
        "restore_timeline_activity",
    )
    for method in known_methods:
        assert method in bridge_src, (
            "bridge must still expose " + method
        )


def test_bridge_imports_only_allowed_modules_3b9_1():
    """Phase 3B.9.1: the bridge must still only import worktrace.api and
    worktrace.formatters."""
    bridge_src = (WEBVIEW_UI_DIR / "bridge.py").read_text(encoding="utf-8")
    for forbidden in ("from ..services", "from ..db",
                      "from ..collector", "from ..security",
                      "from ..runtime", "from ..config",
                      "import worktrace.services",
                      "import worktrace.db"):
        assert forbidden not in bridge_src, (
            "bridge must not import " + forbidden
        )


def test_docs_mention_phase_3b9_1():
    """Phase 3B.9.1: the migration doc must mention Phase 3B.9.1."""
    doc_path = REPO_ROOT / "docs" / "ui-webview-migration.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3B.9.1" in source, (
        "ui-webview-migration.md must mention Phase 3B.9.1"
    )


def test_docs_readme_mentions_phase_3b9_1():
    """Phase 3B.9.1: README must mention Phase 3B.9.1."""
    doc_path = REPO_ROOT / "README.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3B.9.1" in source, (
        "README.md must mention Phase 3B.9.1"
    )


def test_docs_release_validation_mentions_phase_3b9_1():
    """Phase 3B.9.1: release-validation must mention Phase 3B.9.1."""
    doc_path = REPO_ROOT / "docs" / "release-validation.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3B.9.1" in source, (
        "release-validation.md must mention Phase 3B.9.1"
    )


# ---------------------------------------------------------------------------
# Phase 3C: Timeline UI release stabilization
#
# Phase 3C is a stabilization-only phase. It does NOT add any backend write
# capability, bridge / API / service method, DB schema, correction action,
# or UI control. The tests below lock the Phase 3C contract: the unified
# status helpers, the unified status-type CSS classes, the err.message leak
# closure, the stable Chinese fallback strings, and the regression locks
# for every prior-phase invariant that must survive the stabilization.
# ---------------------------------------------------------------------------


def test_app_js_has_unified_status_type_class_map_3c():
    """Phase 3C: app.js must define the STATUS_TYPE_CLASS map with the five
    unified status types (info / success / error / loading / empty)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "STATUS_TYPE_CLASS" in source, (
        "app.js must define STATUS_TYPE_CLASS map"
    )
    for key in ("info", "success", "error", "loading", "empty"):
        assert key + ":" in source or key + ' :' in source, (
            "STATUS_TYPE_CLASS must include the '" + key + "' type"
        )


def test_app_js_has_status_class_for_helper_3c():
    """Phase 3C: app.js must define the statusClassFor helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function statusClassFor" in source, (
        "app.js must define statusClassFor helper"
    )


def test_app_js_has_apply_status_type_helper_3c():
    """Phase 3C: app.js must define the applyStatusType helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function applyStatusType" in source, (
        "app.js must define applyStatusType helper"
    )


def test_app_js_has_set_timeline_status_helper_3c():
    """Phase 3C: app.js must define the unified setTimelineStatus helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function setTimelineStatus" in source, (
        "app.js must define setTimelineStatus helper"
    )


def test_app_js_has_set_detail_status_helper_3c():
    """Phase 3C: app.js must define the unified setDetailStatus helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function setDetailStatus" in source, (
        "app.js must define setDetailStatus helper"
    )


def test_app_js_has_set_edit_status_helper_3c():
    """Phase 3C: app.js must define the unified setEditStatus helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function setEditStatus" in source, (
        "app.js must define setEditStatus helper"
    )


def test_app_js_has_set_correction_status_helper_3c():
    """Phase 3C: app.js must define the unified setCorrectionStatus helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function setCorrectionStatus" in source, (
        "app.js must define setCorrectionStatus helper"
    )


def test_app_js_unified_helpers_delegate_to_existing_helpers_3c():
    """Phase 3C: the unified status helpers must delegate to the existing
    per-area helpers (showEditStatus, setCorrectionShellStatus,
    clearTimelineError, setTimelineLoading, showTimelineError) so the DOM
    contract is unchanged."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    set_timeline = _func_body(source, "setTimelineStatus")
    set_edit = _func_body(source, "setEditStatus")
    set_correction = _func_body(source, "setCorrectionStatus")
    assert "clearTimelineError" in set_timeline, (
        "setTimelineStatus must delegate to clearTimelineError"
    )
    assert "setTimelineLoading" in set_timeline, (
        "setTimelineStatus must delegate to setTimelineLoading"
    )
    assert "showTimelineError" in set_timeline, (
        "setTimelineStatus must delegate to showTimelineError"
    )
    assert "showEditStatus" in set_edit, (
        "setEditStatus must delegate to showEditStatus"
    )
    assert "setCorrectionShellStatus" in set_correction, (
        "setCorrectionStatus must delegate to setCorrectionShellStatus"
    )


def test_app_js_set_detail_status_uses_safe_textcontent_3c():
    """Phase 3C: setDetailStatus must write to textContent (display-safe),
    never to innerHTML."""
    body = _func_body(
        (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8"),
        "setDetailStatus",
    )
    assert "textContent" in body, (
        "setDetailStatus must use textContent for display safety"
    )
    assert "innerHTML" not in body, (
        "setDetailStatus must not use innerHTML"
    )


def test_app_js_set_detail_status_default_text_3c():
    """Phase 3C: setDetailStatus must reset the header to the stable
    '请选择一条时间记录' prompt when message is empty."""
    body = _func_body(
        (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8"),
        "setDetailStatus",
    )
    assert "请选择一条时间记录" in body, (
        "setDetailStatus must use the stable '请选择一条时间记录' default"
    )


def test_app_js_no_err_message_in_catch_blocks_3c():
    """Phase 3C: no catch block in app.js may surface raw exception text
    via err.message / err.toString() / error.message / error.toString().
    This is the display-safe hardening closure."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("err.message", "err.toString",
                      "error.message", "error.toString",
                      "exception.message"):
        assert forbidden not in source, (
            "app.js must not surface raw exception text via " + forbidden
        )


def test_app_js_load_timeline_catch_uses_stable_fallback_3c():
    """Phase 3C: the loadTimeline catch block must use the stable Chinese
    fallback '加载时间线失败' instead of err.message."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "加载时间线失败" in source, (
        "loadTimeline catch must use the stable fallback string"
    )


def test_app_js_refresh_all_catch_uses_stable_fallbacks_3c():
    """Phase 3C: the refreshAll catch blocks (status / overview / recent)
    must use the stable Chinese fallback '刷新失败' instead of err.message."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "刷新失败" in source, (
        "refreshAll catch must use the stable fallback '刷新失败'"
    )


def test_app_js_standard_loading_text_present_3c():
    """Phase 3C: the standard loading text must still be present in the
    frontend resources (Timeline loading indicator)."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "加载中" in html or "加载中" in (
        WEBVIEW_UI_DIR / "app.js"
    ).read_text(encoding="utf-8"), (
        "standard loading text '加载中' must be present"
    )


def test_app_js_standard_empty_text_present_3c():
    """Phase 3C: the standard empty text must still be present in the
    frontend resources."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "暂无" in html, (
        "standard empty text '暂无' must be present in index.html"
    )


def test_app_js_standard_error_text_present_3c():
    """Phase 3C: the standard error text must still be present in the
    frontend resources."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "加载失败" in html, (
        "standard error text '加载失败' must be present in index.html"
    )


def test_app_js_cross_save_guard_text_still_present_3c():
    """Phase 3C: the cross-save guard text '请等待当前操作完成' must
    still be present (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "请等待当前操作完成" in source, (
        "cross-save guard text '请等待当前操作完成' must remain"
    )


def test_app_js_dirty_guard_text_still_present_3c():
    """Phase 3C: the dirty guard text '请先保存或取消当前编辑' must
    still be present (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "请先保存或取消当前编辑" in source, (
        "dirty guard text '请先保存或取消当前编辑' must remain"
    )


def test_index_html_soft_delete_copy_still_present_3c():
    """Phase 3C: the soft delete copy '本阶段不会物理删除数据' must
    still be present (regression lock — delete is still soft delete)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "本阶段不会物理删除数据" in source, (
        "soft delete copy '本阶段不会物理删除数据' must remain"
    )


def test_styles_css_has_edit_status_info_class_3c():
    """Phase 3C: styles.css must define .edit-status-info."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-status-info" in source, (
        "styles.css must define .edit-status-info"
    )


def test_styles_css_has_edit_status_loading_class_3c():
    """Phase 3C: styles.css must define .edit-status-loading."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-status-loading" in source, (
        "styles.css must define .edit-status-loading"
    )


def test_styles_css_has_edit_status_empty_class_3c():
    """Phase 3C: styles.css must define .edit-status-empty."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-status-empty" in source, (
        "styles.css must define .edit-status-empty"
    )


def test_styles_css_unified_status_classes_share_prefix_3c():
    """Phase 3C: all five unified status classes must share the
    .edit-status-* prefix family."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (".edit-status-info", ".edit-status-success",
                ".edit-status-error", ".edit-status-loading",
                ".edit-status-empty"):
        assert cls in source, (
            "styles.css must contain the unified status class " + cls
        )


def test_styles_css_correction_shell_hidden_still_display_none_3c():
    """Phase 3C: .correction-shell[hidden] must still set display:none
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must have .correction-shell[hidden] rule"
    )
    pos = source.find(".correction-shell[hidden]")
    rule = source[pos:pos + 80]
    assert "display: none" in rule, (
        ".correction-shell[hidden] must set display: none"
    )


def test_styles_css_highlight_still_present_3c():
    """Phase 3C: the transient highlight CSS must still be present
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "highlight" in source, (
        "styles.css must still contain the transient highlight rule"
    )


def test_styles_css_no_external_resources_3c():
    """Phase 3C: styles.css must not import external CSS / fonts / CDN
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("@import", "http://", "https://", "cdn",
                      "google fonts", "googleapis"):
        assert forbidden not in lowered, (
            "styles.css must not reference external resource: " + forbidden
        )


def test_index_html_correction_shell_cards_still_present_3c():
    """Phase 3C: all six correction shell cards must still be present
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for card_id in (
        "correction-shell-context-card",
        "correction-shell-activity-card",
        "correction-shell-single-action-card",
        "correction-shell-batch-action-card",
        "correction-shell-restore-card",
        "correction-shell-not-implemented-card",
    ):
        assert card_id in source, (
            "index.html must still contain correction shell card: " + card_id
        )


def test_index_html_no_forbidden_batch_ui_3c():
    """Phase 3C: no batch hide / batch delete / batch restore /
    permanent delete / undo stack UI controls may be present
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("batch-hide", "batch-delete", "batch-restore",
                      "permanent-delete", "undo-stack",
                      "restore-all", "批量隐藏按钮", "批量删除按钮"):
        assert forbidden not in lowered, (
            "index.html must not contain forbidden batch UI: " + forbidden
        )


def test_index_html_not_implemented_card_lists_unavailable_3c():
    """Phase 3C: the not-implemented card must still list all unavailable
    capabilities (regression lock)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    not_impl_pos = source.find("correction-shell-not-implemented-card")
    assert not_impl_pos != -1
    not_impl_section = source[not_impl_pos:not_impl_pos + 600]
    for keyword in ("批量隐藏", "批量删除", "批量恢复", "撤销栈",
                    "永久删除", "批量时间", "批量拆分", "批量合并",
                    "自动规则", "重叠检测"):
        assert keyword in not_impl_section, (
            "not-implemented card must list: " + keyword
        )


def test_index_html_no_new_top_level_pages_3c():
    """Phase 3C / 4A: the sidebar nav must still list exactly the five known
    items. As of Phase 4A the Statistics / Export page is migrated to a real
    read-only WebView page; Project Rules and Settings / Privacy must remain
    placeholders (regression lock)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # The sidebar nav must still list exactly the five known items.
    for nav_item in ("概览", "时间详情", "统计与导出",
                     "项目规则", "设置与隐私"):
        assert nav_item in source, (
            "sidebar must still list nav item: " + nav_item
        )
    # The Project Rules / Settings pages must remain placeholders, not
    # migrated WebView pages. The Statistics / Export page is now a real
    # read-only page (Phase 4A) and is no longer a placeholder.
    for placeholder_id in ("page-rules", "page-settings"):
        pos = source.find('id="' + placeholder_id + '"')
        assert pos != -1, (
            "index.html must still contain the placeholder: " + placeholder_id
        )
        # The placeholder section must still contain the migration notice.
        section = source[pos:pos + 400]
        assert "WebView 迁移中" in section, (
            "placeholder " + placeholder_id + " must still show the migration notice"
        )


def test_app_js_correction_shell_no_local_storage_3c():
    """Phase 3C: app.js must not use localStorage / sessionStorage
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in source, (
            "app.js must not use " + forbidden
        )


# ---------------------------------------------------------------------------
# Phase 4A: Statistics / Export read-only WebView migration
#
# Phase 4A migrates the Statistics / Export page from the legacy Tkinter
# placeholder to a read-only WebView page. The tests below lock the Phase 4A
# contract: the page exists, the navigation entry exists, the date range
# controls exist, the summary cards / grouped tables / export preview exist,
# the export action is disabled, the frontend calls the read-only bridge
# method, the loading / empty / error strings are present, no export write
# button handler is wired, no localStorage / sessionStorage / CDN / external
# resources are introduced, and the Overview / Timeline pages are not
# regressed.
# ---------------------------------------------------------------------------


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


def test_index_html_statistics_header_read_only_subtitle_4a():
    """Phase 4A: the page header must say read-only / no file write."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-statistics"')
    section = source[pos:pos + 600]
    assert "统计 / 导出" in section
    assert "本阶段仅提供只读统计和导出预览" in section
    assert "暂不写入文件" in section


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


def test_index_html_statistics_export_action_disabled_4a():
    """Phase 4A: the export action button must be disabled and say the
    action will be available in a later phase."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="stats-export-action-btn"' in source
    assert "disabled" in source
    assert "导出动作将在后续阶段开放" in source


def test_index_html_statistics_export_hint_no_file_write_4a():
    """Phase 4A: the export hint must explicitly say no CSV / Excel / PDF /
    timesheet file write, no save dialog, no folder open, no auto-submit."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find("stats-export-hint")
    assert pos != -1
    section = source[pos:pos + 400]
    for keyword in ("CSV", "Excel", "PDF", "timesheet", "保存对话框", "文件夹"):
        assert keyword in section, (
            "export hint must mention: " + keyword
        )


def test_index_html_statistics_loading_text_4a():
    """Phase 4A: the loading text 正在加载统计… must be present."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "正在加载统计" in source


def test_index_html_statistics_error_text_4a():
    """Phase 4A: the error banner default text 加载统计失败 must be present."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="statistics-error"' in source
    assert "加载统计失败" in source


def test_index_html_statistics_no_real_export_button_4a():
    """Phase 4A: no real export write button may be present. The only
    export-related button must be the disabled placeholder."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("export-csv-btn", "export-excel-btn", "export-pdf-btn",
                      "export-timesheet-btn", "save-file-btn",
                      "open-folder-btn", "导出csv", "导出excel",
                      "导出pdf"):
        assert forbidden not in lowered, (
            "index.html must not contain real export button: " + forbidden
        )


def test_index_html_overview_and_timeline_nav_not_regressed_4a():
    """Phase 4A: Overview and Timeline nav entries must still exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-page="overview"' in source
    assert 'data-page="timeline"' in source


# --- app.js Phase 4A --------------------------------------------------


def test_app_js_statistics_state_variables_4a():
    """Phase 4A: app.js must declare the statistics state variables."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "statisticsLoaded" in source
    assert "statisticsLoading" in source
    assert "statisticsRequestToken" in source


def test_app_js_statistics_load_function_4a():
    """Phase 4A: app.js must define loadStatisticsExportSummary and call the
    bridge method get_statistics_export_summary."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function loadStatisticsExportSummary" in source
    assert "get_statistics_export_summary" in source


def test_app_js_statistics_render_function_4a():
    """Phase 4A: app.js must define showStatistics and renderStatsTable."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function showStatistics" in source
    assert "function renderStatsTable" in source
    assert "function renderExportPreview" in source


def test_app_js_statistics_quick_range_function_4a():
    """Phase 4A: app.js must define applyStatisticsQuickRange and
    initStatisticsDefaults."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function applyStatisticsQuickRange" in source
    assert "function initStatisticsDefaults" in source


def test_app_js_statistics_lazy_load_in_switch_page_4a():
    """Phase 4A: switchPage must lazy-load the statistics summary on first
    navigation to the page."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # Find the switchPage function body and verify the statistics branch.
    pos = source.find("function switchPage")
    assert pos != -1
    body = source[pos:pos + 1500]
    assert "statistics" in body
    assert "loadStatisticsExportSummary" in body
    assert "initStatisticsDefaults" in body


def test_app_js_statistics_event_binding_in_init_buttons_4a():
    """Phase 4A: initButtons must bind the statistics load + quick range
    buttons."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    pos = source.find("function initButtons")
    assert pos != -1
    body = source[pos:pos + 5000]
    assert "statistics-load-btn" in body
    assert "statistics-today-btn" in body
    assert "statistics-7d-btn" in body
    assert "statistics-month-btn" in body
    assert "loadStatisticsExportSummary" in body
    assert "applyStatisticsQuickRange" in body


def test_app_js_statistics_uses_escape_html_4a():
    """Phase 4A: renderStatsTable must use escapeHtml for dynamic values."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    pos = source.find("function renderStatsTable")
    assert pos != -1
    body = source[pos:pos + 1200]
    assert "escapeHtml" in body
    assert "safeText" in body


def test_app_js_statistics_no_export_write_handler_4a():
    """Phase 4A: app.js must not wire any export write / save dialog / file
    creation handler for the statistics page."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("exportcsv", "exportexcel", "exportpdf",
                      "exporttimesheet", "savefile", "saveas",
                      "opensavefile", "window.pywebview.api.export"):
        assert forbidden not in lowered, (
            "app.js must not wire export write handler: " + forbidden
        )


def test_app_js_statistics_no_local_storage_4a():
    """Phase 4A: the statistics page must not use localStorage /
    sessionStorage (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in source, (
            "app.js must not use " + forbidden
        )


def test_app_js_statistics_error_text_4a():
    """Phase 4A: the statistics error path must surface 加载统计失败."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "加载统计失败" in source


def test_app_js_statistics_loading_text_4a():
    """Phase 4A: the statistics loading path must surface 正在加载统计…."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The loading text is in index.html; app.js toggles the hidden flag on
    # the statistics-loading element. Verify the element id is referenced.
    assert "statistics-loading" in source


# --- styles.css Phase 4A ----------------------------------------------


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


def test_styles_css_statistics_export_action_disabled_style_4a():
    """Phase 4A: the disabled export action button must have a
    cursor: not-allowed style."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    pos = source.find(".stats-export-action-btn")
    assert pos != -1
    body = source[pos:pos + 300]
    assert "not-allowed" in body


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


# --- Boundary: no export write / no DB schema / no premature migration -


def test_index_html_no_project_rules_page_4a():
    """Phase 4A: the Project Rules page must remain a placeholder, not a
    migrated WebView page."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-rules"')
    assert pos != -1
    section = source[pos:pos + 400]
    assert "WebView 迁移中" in section


def test_index_html_no_settings_privacy_page_4a():
    """Phase 4A: the Settings / Privacy page must remain a placeholder, not
    a migrated WebView page."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-settings"')
    assert pos != -1
    section = source[pos:pos + 400]
    assert "WebView 迁移中" in section


def test_app_js_no_save_dialog_or_folder_open_4a():
    """Phase 4A: app.js must not call any save dialog or folder open helper."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("saveasdialog", "save_dialog", "createfile",
                      "openfolder", "open_folder", "shell.open"):
        assert forbidden not in lowered, (
            "app.js must not call: " + forbidden
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


def test_app_js_no_react_vue_vite_node_4a():
    """Phase 4A: app.js must not reference React / Vue / Vite / Node.
    Uses word-boundary matching to avoid false positives on substrings
    like ``navItems`` containing ``vite``."""
    import re
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("react", "vue", "vite", "node_modules"):
        pattern = r'\b' + re.escape(forbidden) + r'\b'
        assert not re.search(pattern, lowered), (
            "app.js must not reference: " + forbidden
        )


def test_app_js_correction_shell_no_external_links_3c():
    """Phase 3C: app.js must not reference external links / CDN
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("http://", "https://", "cdn", "google fonts",
                      "googleapis"):
        assert forbidden not in lowered, (
            "app.js must not reference external resource: " + forbidden
        )


def test_app_js_correction_shell_no_traceback_display_3c():
    """Phase 3C: app.js must not display tracebacks (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "traceback" not in lowered, (
        "app.js must not display tracebacks"
    )


def test_app_js_correction_shell_no_raw_sensitive_fields_3c():
    """Phase 3C: app.js must not render raw window_title / file_path_hint /
    full_path / clipboard fields (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The literal field names must not appear as rendered display values.
    # (They may appear in comments explaining what is NOT rendered, but
    # the test asserts the literals are absent from the rendering paths.)
    for forbidden in ("window_title", "file_path_hint",
                      "full_path", "clipboard"):
        assert forbidden not in source, (
            "app.js must not reference raw sensitive field: " + forbidden
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


def test_docs_mention_phase_3c():
    """Phase 3C: the migration doc must mention Phase 3C."""
    doc_path = REPO_ROOT / "docs" / "ui-webview-migration.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3C" in source, (
        "ui-webview-migration.md must mention Phase 3C"
    )
    assert "Phase 3C Implemented Scope" in source, (
        "ui-webview-migration.md must have a Phase 3C Implemented Scope section"
    )


def test_docs_readme_mentions_phase_3c():
    """Phase 3C: README must mention Phase 3C."""
    doc_path = REPO_ROOT / "README.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3C" in source, (
        "README.md must mention Phase 3C"
    )


def test_docs_release_validation_mentions_phase_3c():
    """Phase 3C: release-validation must mention Phase 3C."""
    doc_path = REPO_ROOT / "docs" / "release-validation.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3C" in source, (
        "release-validation.md must mention Phase 3C"
    )
    assert "WebView Phase 3C Validation" in source, (
        "release-validation.md must have a WebView Phase 3C Validation section"
    )


def test_docs_release_validation_phase_3c_release_blockers_3c():
    """Phase 3C: release-validation must list the Phase 3C release blockers."""
    doc_path = REPO_ROOT / "docs" / "release-validation.md"
    source = doc_path.read_text(encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Phase 3C.1: Timeline UI release hardening / regression
#
# Phase 3C.1 is a hardening-only / regression-only phase. It does NOT add any
# backend write capability, bridge / API / service method, DB schema,
# correction action, or UI control. The tests below lock the Phase 3C.1
# contract: status helper hardening, raw exception leak prevention, stable
# Chinese fallback vocabulary, auto-refresh dirty/saving guards, display-safe
# rendering, CSS state hardening, and boundary regression locks.
# ---------------------------------------------------------------------------


def test_app_js_apply_status_type_preserves_non_status_classes_3c1():
    """Phase 3C.1: applyStatusType must preserve non-status structural
    classes — it must only toggle the whitelisted status-type classes,
    not replace the entire className."""
    body = _func_body(
        (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8"),
        "applyStatusType",
    )
    # The hardened implementation must filter classes, not replace wholesale.
    assert "filter" in body, (
        "applyStatusType must filter classes to preserve non-status classes"
    )
    assert "STATUS_TYPE_CLASS_VALUES" in body, (
        "applyStatusType must use the STATUS_TYPE_CLASS_VALUES whitelist"
    )
    # Must NOT do a simple className replacement.
    assert 'el.className = "edit-status "' not in body, (
        "applyStatusType must not replace className wholesale"
    )


def test_app_js_has_status_type_class_values_whitelist_3c1():
    """Phase 3C.1: app.js must define the STATUS_TYPE_CLASS_VALUES whitelist
    used by applyStatusType to filter classes."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "STATUS_TYPE_CLASS_VALUES" in source, (
        "app.js must define STATUS_TYPE_CLASS_VALUES whitelist"
    )


def test_app_js_status_class_for_safe_default_3c1():
    """Phase 3C.1: statusClassFor must return a safe default (info class)
    for unknown types, never undefined or a user-supplied string."""
    body = _func_body(
        (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8"),
        "statusClassFor",
    )
    assert "STATUS_TYPE_CLASS.info" in body, (
        "statusClassFor must fall back to STATUS_TYPE_CLASS.info"
    )
    assert "||" in body, (
        "statusClassFor must use || fallback for unknown types"
    )


def test_app_js_no_reason_message_leak_3c1():
    """Phase 3C.1: no code path may read .reason.message or .message from
    a rejected promise / raw exception and render it to the UI."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # .reason.message is the pattern used by Promise.allSettled rejection
    # handlers — it must not appear in executable code (comments are OK).
    for forbidden in ("reason.message", "reason && reason.message"):
        # Remove comment lines before checking.
        code_lines = [
            line for line in source.split("\n")
            if not line.strip().startswith("//")
        ]
        code = "\n".join(code_lines)
        assert forbidden not in code, (
            "app.js must not read " + forbidden
            + " from rejected promises (raw exception leak risk)"
        )


def test_app_js_no_string_err_leak_3c1():
    """Phase 3C.1: no code path may use String(err) or String(error) to
    convert a raw exception to a string for UI display."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("String(err)", "String(error)",
                      "String(exception)", "err.toString()",
                      "error.toString()"):
        assert forbidden not in source, (
            "app.js must not convert raw exceptions via " + forbidden
        )


def test_app_js_save_edit_catch_uses_stable_fallback_3c1():
    """Phase 3C.1: the saveEdit Promise.allSettled rejection handler must
    use the stable '保存失败' fallback instead of reading .reason.message."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # Find the Promise.allSettled block inside saveEdit.
    allsettled_pos = source.find("Promise.allSettled(promises).then")
    assert allsettled_pos != -1, "saveEdit must use Promise.allSettled"
    block = source[allsettled_pos:allsettled_pos + 800]
    assert "保存失败" in block, (
        "saveEdit rejection handler must use '保存失败' stable fallback"
    )


def test_app_js_stable_fallback_vocabulary_present_3c1():
    """Phase 3C.1: all six stable Chinese fallback strings must be present
    in app.js: 加载时间线失败 / 刷新失败 / 加载详情失败 / 保存失败 /
    操作失败 / 恢复失败."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for fallback in ("加载时间线失败", "刷新失败", "加载详情失败",
                     "保存失败", "操作失败", "恢复失败"):
        assert fallback in source, (
            "app.js must contain stable fallback: " + fallback
        )


def test_app_js_no_old_longer_fallback_strings_3c1():
    """Phase 3C.1: the old longer fallback strings from Phase 3C must be
    replaced by the stable short forms (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for old_string in ("加载时间详情失败，请稍后重试。",
                       "无法连接采集器状态，请稍后重试。",
                       "加载今日概览失败，请稍后重试。",
                       "加载最近活动失败，请稍后重试。",
                       "刷新时间详情失败，请稍后重试。"):
        assert old_string not in source, (
            "app.js must not contain old longer fallback: " + old_string
        )


def test_app_js_timeline_loading_text_stable_3c1():
    """Phase 3C.1: Timeline loading text must be stable."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "加载中" in html, (
        "Timeline loading text '加载中' must be present in index.html"
    )


def test_app_js_timeline_empty_text_stable_3c1():
    """Phase 3C.1: Timeline empty text must be stable."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "暂无" in html, (
        "Timeline empty text '暂无' must be present in index.html"
    )


def test_app_js_timeline_error_text_stable_3c1():
    """Phase 3C.1: Timeline error text must be stable."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "加载失败" in html, (
        "Timeline error text '加载失败' must be present in index.html"
    )


def test_app_js_detail_no_selection_text_stable_3c1():
    """Phase 3C.1: detail panel no-selection text must be stable."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # setDetailStatus default + the index.html initial header text.
    assert "请选择一条时间记录" in source, (
        "setDetailStatus must use stable '请选择一条时间记录' default"
    )


def test_app_js_detail_error_fallback_stable_3c1():
    """Phase 3C.1: detail panel error fallback must be stable."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "加载详情失败" in source, (
        "detail panel must use stable '加载详情失败' error fallback"
    )


def test_app_js_edit_saving_success_failure_strings_stable_3c1():
    """Phase 3C.1: edit panel saving/success/failure strings must be
    stable."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "保存中" in source, "edit saving text '保存中' must be present"
    assert "保存成功" in source, "edit success text '保存成功' must be present"
    assert "保存失败" in source, "edit failure text '保存失败' must be present"


def test_app_js_correction_shell_dirty_guard_text_stable_3c1():
    """Phase 3C.1: correction shell dirty guard text must be stable."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "请先保存或取消当前编辑" in source, (
        "dirty guard text '请先保存或取消当前编辑' must be present"
    )


def test_app_js_correction_shell_cross_save_guard_text_stable_3c1():
    """Phase 3C.1: correction shell cross-save guard text must be stable."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "请等待当前操作完成" in source, (
        "cross-save guard text '请等待当前操作完成' must be present"
    )


def test_app_js_soft_delete_copy_still_not_permanent_3c1():
    """Phase 3C.1: soft delete copy must still say not physical / not
    permanent delete (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "本阶段不会物理删除数据" in source, (
        "soft delete copy '本阶段不会物理删除数据' must remain"
    )


def test_app_js_restore_copy_still_no_batch_undo_permanent_3c1():
    """Phase 3C.1: restore copy must still say no batch restore / no undo
    stack / no permanent delete (regression lock)."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # The not-implemented card lists the unavailable capabilities.
    not_impl_pos = html.find("correction-shell-not-implemented-card")
    assert not_impl_pos != -1
    not_impl_section = html[not_impl_pos:not_impl_pos + 600]
    for keyword in ("批量恢复", "撤销栈", "永久删除"):
        assert keyword in not_impl_section, (
            "not-implemented card must still list: " + keyword
        )


def test_app_js_auto_refresh_dirty_guard_present_3c1():
    """Phase 3C.1: auto-refresh must check isEditDirty() before overwriting
    edit inputs (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # The auto-refresh path in showTimeline checks isEditDirty.
    assert "isEditDirty()" in source, (
        "auto-refresh must call isEditDirty() to guard edit inputs"
    )


def test_app_js_auto_refresh_saving_guard_present_3c1():
    """Phase 3C.1: auto-refresh must check isAnyCorrectionWriteSaving()
    before re-rendering the correction shell (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "isAnyCorrectionWriteSaving()" in source, (
        "auto-refresh must call isAnyCorrectionWriteSaving() to guard "
        "correction shell re-render during save"
    )


def test_app_js_catch_paths_reset_saving_3c1():
    """Phase 3C.1: all catch paths that follow a save must reset the saving
    flag so buttons are not left disabled (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    # Each save function has a catch that calls setXxxSaving(false).
    for reset_call in ("setEditSaving(false)", "setActivityTimeSaving(row, false)",
                       "setActivitySplitSaving(row, false)",
                       "setMergeSaving(btn, false)",
                       "setHideSaving(btn, false)",
                       "setDeleteSaving(btn, false)",
                       "setBatchProjectSaving(false)",
                       "setBatchNoteSaving(false)",
                       "setRestoreSaving(false, null)"):
        assert reset_call in source, (
            "catch path must reset saving via " + reset_call
        )


def test_app_js_display_safe_helpers_present_3c1():
    """Phase 3C.1: display-safe helpers escapeHtml and safeText must be
    present (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function escapeHtml" in source, (
        "escapeHtml helper must be present"
    )
    assert "function safeText" in source, (
        "safeText helper must be present"
    )


def test_app_js_no_raw_sensitive_fields_anywhere_3c1():
    """Phase 3C.1: app.js must not reference raw window_title /
    file_path_hint / full_path / clipboard anywhere (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    for forbidden in ("window_title", "file_path_hint",
                      "full_path", "clipboard"):
        assert forbidden not in source, (
            "app.js must not reference raw sensitive field: " + forbidden
        )


def test_app_js_no_traceback_sql_display_3c1():
    """Phase 3C.1: app.js must not display traceback or SQL strings
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("traceback", "sql error", "sqlite"):
        assert forbidden not in lowered, (
            "app.js must not display " + forbidden
        )


def test_styles_css_status_classes_complete_3c1():
    """Phase 3C.1: styles.css must have all five status classes
    (info / success / error / loading / empty)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (".edit-status-info", ".edit-status-success",
                ".edit-status-error", ".edit-status-loading",
                ".edit-status-empty"):
        assert cls in source, (
            "styles.css must contain status class " + cls
        )


def test_styles_css_disabled_saving_styles_present_3c1():
    """Phase 3C.1: styles.css must have disabled / saving state styles
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "disabled" in lowered or ":disabled" in source, (
        "styles.css must have disabled state styles"
    )
    # Saving state is expressed via disabled + button text change; the
    # disabled style is the CSS-side anchor.
    assert "disabled" in lowered, (
        "styles.css must reference disabled state"
    )


def test_styles_css_correction_shell_hidden_display_none_3c1():
    """Phase 3C.1: .correction-shell[hidden] must still set display:none
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must have .correction-shell[hidden] rule"
    )
    pos = source.find(".correction-shell[hidden]")
    rule = source[pos:pos + 80]
    assert "display: none" in rule, (
        ".correction-shell[hidden] must set display: none"
    )


def test_styles_css_highlight_still_present_3c1():
    """Phase 3C.1: transient highlight CSS must still be present
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "highlight" in source, (
        "styles.css must still contain the transient highlight rule"
    )


def test_styles_css_no_external_resources_3c1():
    """Phase 3C.1: styles.css must not import external CSS / fonts / CDN
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("@import", "http://", "https://", "cdn",
                      "google fonts", "googleapis"):
        assert forbidden not in lowered, (
            "styles.css must not reference external resource: " + forbidden
        )


def test_styles_css_no_local_storage_3c1():
    """Phase 3C.1: styles.css must not reference localStorage /
    sessionStorage (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in source, (
            "styles.css must not reference " + forbidden
        )


def test_app_js_no_react_vue_vite_node_3c1():
    """Phase 3C.1: app.js must not reference React / Vue / Vite / Node
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    lowered = source.lower()
    # Word-boundary matching for framework names so identifiers like
    # "navItems" (lowercased "navitems") do not falsely match "vite".
    for forbidden in ("react", "vue", "vite"):
        assert re.search(r"\b" + re.escape(forbidden) + r"\b", lowered) is None, (
            "app.js must not reference frontend framework: " + forbidden
        )
    # Syntax patterns are checked as literal substrings.
    for forbidden in ("require(", "module.exports"):
        assert forbidden not in lowered, (
            "app.js must not reference frontend framework: " + forbidden
        )


def test_app_js_no_local_http_server_3c1():
    """Phase 3C.1: app.js must not start a local HTTP server
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "app.js").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("httpserver", "http.createServer",
                      "express(", "flask "):
        assert forbidden not in lowered, (
            "app.js must not start a local HTTP server: " + forbidden
        )


def test_bridge_no_new_methods_for_phase_3c1():
    """Phase 3C.1 / 4A: no new bridge methods beyond the known 22-method set
    (regression lock — Phase 4A adds get_statistics_export_summary as a
    read-only method; no other methods may be added)."""
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
        "get_statistics_export_summary",
    )
    for method in known_methods:
        assert method in bridge_src, (
            "bridge must still expose " + method
        )


def test_bridge_imports_only_allowed_modules_3c1():
    """Phase 3C.1: the bridge must still only import worktrace.api and
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


def test_api_has_no_new_methods_for_phase_3c1():
    """Phase 3C.1: the timeline API must still expose the known method set
    and error classes (regression lock — no new API methods)."""
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


def test_no_new_db_schema_for_phase_3c1():
    """Phase 3C.1: schema.sql must still define the known core tables
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


def test_default_webview_entry_preserved_3c1():
    """Phase 3C.1: the default entry point must still delegate to
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


def test_docs_mention_phase_3c1():
    """Phase 3C.1: the migration doc must mention Phase 3C.1."""
    doc_path = REPO_ROOT / "docs" / "ui-webview-migration.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3C.1" in source, (
        "ui-webview-migration.md must mention Phase 3C.1"
    )


def test_docs_readme_mentions_phase_3c1():
    """Phase 3C.1: README must mention Phase 3C.1."""
    doc_path = REPO_ROOT / "README.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3C.1" in source, (
        "README.md must mention Phase 3C.1"
    )


def test_docs_release_validation_mentions_phase_3c1():
    """Phase 3C.1: release-validation must mention Phase 3C.1."""
    doc_path = REPO_ROOT / "docs" / "release-validation.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "3C.1" in source, (
        "release-validation.md must mention Phase 3C.1"
    )
    assert "WebView Phase 3C.1 Validation" in source, (
        "release-validation.md must have a WebView Phase 3C.1 Validation section"
    )


def test_docs_release_validation_phase_3c1_release_blockers_3c1():
    """Phase 3C.1: release-validation must list the Phase 3C.1 release
    blockers."""
    doc_path = REPO_ROOT / "docs" / "release-validation.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "Phase 3C.1 Release Blockers" in source, (
        "release-validation.md must have a Phase 3C.1 Release Blockers section"
    )
    for blocker in ("raw exception", "traceback", "auto-refresh",
                    "saving", "dirty guard", "cross-save",
                    "stale id", "soft delete",
                    "localStorage", "new bridge"):
        assert blocker in source, (
            "release-validation.md must mention release blocker: " + blocker
        )


# ---------------------------------------------------------------------------
# Phase 4A: documentation regression locks
# ---------------------------------------------------------------------------


def test_docs_mention_phase_4a():
    """Phase 4A: the migration doc must mention Phase 4A."""
    doc_path = REPO_ROOT / "docs" / "ui-webview-migration.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "4A" in source, (
        "ui-webview-migration.md must mention Phase 4A"
    )
    assert "Phase 4A" in source, (
        "ui-webview-migration.md must mention 'Phase 4A'"
    )


def test_docs_readme_mentions_phase_4a():
    """Phase 4A: README must mention Phase 4A."""
    doc_path = REPO_ROOT / "README.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "4A" in source, (
        "README.md must mention Phase 4A"
    )


def test_docs_release_validation_mentions_phase_4a():
    """Phase 4A: release-validation must mention Phase 4A."""
    doc_path = REPO_ROOT / "docs" / "release-validation.md"
    source = doc_path.read_text(encoding="utf-8")
    assert "4A" in source, (
        "release-validation.md must mention Phase 4A"
    )
    assert "WebView Phase 4A Validation" in source, (
        "release-validation.md must have a WebView Phase 4A Validation section"
    )


def test_docs_release_validation_phase_4a_release_blockers_4a():
    """Phase 4A: release-validation must list the Phase 4A release blockers."""
    doc_path = REPO_ROOT / "docs" / "release-validation.md"
    source = doc_path.read_text(encoding="utf-8")
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
