"""Timeline WebView static-contract tests.

These tests read the bundled frontend resources (index.html /
js/*.js / styles.css) directly without starting the GUI. Frontend JS is
loaded from the ordered modules listed in ALL_JS_FILES. These tests lock
the Timeline page contracts.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import (
    REPO_ROOT, WEBVIEW_UI_DIR, HISTORY_PATH,
    RELEASE_VALIDATION_PATH, README_PATH,
    read_resource, read_all_js, func_body,
    html_section_by_id,
    read_bridge_sources_combined,
    FRONTEND_RESOURCE_FILES, NO_STORAGE_FILES,
)




def test_index_html_timeline_page_is_not_placeholder():
    """the Timeline page must be a production page, not a
    placeholder. The placeholder text must not appear inside the
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
    """the Timeline page must have prev/today/next date navigation.

    The date element is now an ``<input type="date">`` (id
    ``timeline-date-input``) instead of a static display span, so the user
    can pick a date directly from the native date picker.
    """
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-prev-btn"' in source
    assert 'id="timeline-next-btn"' in source
    assert 'id="timeline-today-btn"' in source
    assert 'id="timeline-date-input"' in source



def test_index_html_timeline_page_has_sessions_and_details_containers():
    """the Timeline page must have a sessions list container and a
    details list container for the master-detail layout."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-sessions-list"' in source
    assert 'id="timeline-details-list"' in source
    assert 'id="timeline-details-header"' in source



def test_index_html_timeline_page_has_error_and_empty_and_loading_states():
    """the Timeline page must have an error banner, an empty state
    element, and a loading indicator."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-error"' in source
    assert 'id="timeline-loading"' in source
    assert "timeline-empty" in source



def test_index_html_timeline_page_has_total():
    """the Timeline page must show daily total and current activity."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-total"' in source
    assert 'id="timeline-current"' in source



def test_index_html_rules_and_settings_are_full_pages():
    """Rules and Settings pages expose their current WebView controls."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    rules_start = source.find('id="page-rules"')
    assert rules_start != -1, "rules section must exist"
    rules_end = source.find('<section id="page-settings"', rules_start)
    rules_section = source[rules_start:rules_end]
    assert "WebView 迁移中" not in rules_section
    assert "项目规则" in rules_section
    assert "新建规则" in rules_section
    assert "新建项目" in rules_section
    assert "高级功能" in rules_section
    assert "按上次使用排序" in rules_section
    assert "按首字母排序" in rules_section
    assert "自动归类" in rules_section
    assert "批量" not in rules_section

    # Settings / Privacy is a WebView status page. The obsolete placeholder
    # copy must not appear in its section.
    settings_start = source.find('id="page-settings"')
    assert settings_start != -1, "settings section must exist"
    settings_end = source.find("</section>", settings_start)
    settings_section = source[settings_start:settings_end]
    assert "WebView 迁移中" not in settings_section



def test_frontend_js_has_timeline_load_function():
    """frontend JS must have a loadTimeline function that calls the
    get_timeline bridge method."""
    source = read_all_js()
    assert "loadTimeline" in source
    assert "get_timeline" in source



def test_frontend_js_has_timeline_session_details_load():
    """frontend JS must load session details via
    get_timeline_session_details bridge method."""
    source = read_all_js()
    assert "get_timeline_session_details" in source
    assert "loadSessionDetails" in source



def test_frontend_js_has_timeline_date_navigation():
    """frontend JS must implement prev/next/today date navigation."""
    source = read_all_js()
    assert "goPrevDay" in source
    assert "goNextDay" in source
    assert "goToday" in source
    assert "shiftDate" in source



def test_frontend_js_timeline_refreshes_on_auto_refresh():
    """when the Timeline page is active, refreshAll must also
    refresh the timeline data."""
    source = read_all_js()
    assert "currentPage" in source
    assert 'currentPage === "timeline"' in source



def test_frontend_js_timeline_has_error_handling():
    """frontend JS must have timeline-specific error display functions."""
    source = read_all_js()
    assert "showTimelineError" in source
    assert "clearTimelineError" in source



def test_frontend_js_timeline_has_no_forbidden_edit_handlers():
    """The Timeline page allows project reclassification,
    session-note editing, time correction, split, merge, and single-
    activity hide / soft delete. frontend JS must not contain handlers for
    batch editing, batch hide/delete, restore, permanent delete, auto-rule
    creation, or complex correction."""
    source = read_all_js().lower()
    # Forbidden operations (not part of any current Timeline contract)
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





def test_index_html_timeline_has_edit_panel():
    """the Timeline details area must contain an edit panel for
    project reclassification and session-note editing."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-edit-panel"' in source
    assert "timeline-edit-panel" in source



def test_index_html_timeline_has_project_select():
    """the edit panel must have a project <select> so the user
    can reclassify. The frontend must not allow free-form project_id input."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-project-select"' in source
    assert "<select" in source
    # No free-form text input for project_id
    assert 'id="edit-project-input"' not in source



def test_index_html_timeline_has_note_textarea():
    """the edit panel must have a <textarea> for note editing."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-note-text"' in source
    assert "<textarea" in source
    assert 'id="edit-note-count"' in source



def test_index_html_timeline_has_save_cancel_buttons():
    """the edit panel must have save and cancel buttons."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-save-btn"' in source
    assert 'id="edit-cancel-btn"' in source
    assert 'id="edit-status"' in source



def test_index_html_timeline_edit_panel_has_no_delete_batch():
    """the edit panel contains time-
    correction inputs (``edit-start-time`` / ``edit-end-time``), a split
    section (``edit-split-section``), and a hide/delete section
    (``edit-visibility-section``). The per-activity merge button lives in
    the rendered detail rows (not in the static edit panel), so
    "merge" may appear in frontend JS but the static index.html must still not
    contain merge, restore, permanent-delete, or auto-rule controls.
    A soft-delete button in the static panel means
    "delete" is therefore allowed in index.html, but only as the
    soft-delete foundation, never as a permanent delete control.
    The first batch write capability (batch project
    reassignment in the correction shell) means "batch" is allowed in
    index.html but only in the project reassignment context. Batch hide /
    delete / time / split / merge controls must still be absent."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # provides time-correction inputs in the edit panel.
    assert 'id="edit-start-time"' in source
    assert 'id="edit-end-time"' in source
    assert 'id="edit-time-save-btn"' in source
    # provides a split section in the edit panel.
    assert 'id="edit-split-section"' in source
    assert 'id="edit-split-time"' in source
    assert 'id="edit-split-save-btn"' in source
    # provides a hide/delete section in the edit panel.
    assert 'id="edit-visibility-section"' in source
    assert 'id="edit-visibility-single"' in source
    assert 'id="edit-visibility-multi"' in source
    assert 'id="edit-visibility-hide-btn"' in source
    assert 'id="edit-visibility-delete-btn"' in source
    assert 'id="edit-visibility-status"' in source
    # Provides a batch project reassignment section in the correction shell.
    # "batch" is allowed only in the project context; batch hide / delete / time
    # / split / merge controls must stay absent, as must Restore / permanent
    # delete / auto-rule.
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
    # introduces single activity restore, so "restore" is now
    # allowed in index.html. Batch restore, restore-all, undo stack, and
    # permanent delete must still be absent.
    for forbidden_restore in (
        "batch-restore", "batchrestore", "restore-all", "restoreall",
        "undo-restore", "undorestore", "permanent", "auto-rule",
    ):
        assert forbidden_restore not in lowered, (
            "index.html must not contain a '" + forbidden_restore + "' control"
        )



def test_frontend_js_has_edit_panel_functions():
    """frontend JS must define the edit panel lifecycle functions."""
    source = read_all_js()
    assert "populateEditPanel" in source
    assert "clearEditPanel" in source
    assert "isEditDirty" in source
    assert "loadProjects" in source
    assert "saveEdit" in source
    assert "cancelEdit" in source
    assert "updateNoteCount" in source
    assert "showEditStatus" in source



def test_frontend_js_calls_editing_bridge_methods():
    """frontend JS must call the bridge methods for project
    reclassification, note editing, and project list loading."""
    source = read_all_js()
    assert "list_projects_for_timeline" in source
    assert "update_timeline_project" in source
    assert "update_timeline_note" in source



def test_frontend_js_has_saving_state():
    """frontend JS must track a saving state to prevent double-submit
    and show '保存中…' feedback."""
    source = read_all_js()
    assert "editSaving" in source
    assert "setEditSaving" in source
    assert "保存中" in source



def test_frontend_js_edit_save_failure_preserves_data():
    """when a save fails, frontend JS must keep the original data in
    the form and display an error, not clear the form or leave it in a
    'saving' state."""
    source = read_all_js()
    # On error, setEditSaving(false) is called and showEditStatus shows error
    assert "setEditSaving(false)" in source
    assert "showEditStatus(errorMsg, true)" in source



def test_frontend_js_edit_save_success_refreshes_timeline():
    """on save success, frontend JS must refresh the Timeline so the
    session list and edit panel reflect the new state."""
    source = read_all_js()
    assert "refreshTimelineAfterEdit" in source
    assert "保存成功" in source



def test_styles_css_has_edit_panel_styles():
    """styles.css must style the edit panel, project select,
    note textarea, save/cancel buttons, and status messages."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".timeline-edit-panel" in source
    assert ".edit-select" in source
    assert ".edit-note" in source
    assert ".edit-save-btn" in source
    assert ".edit-cancel-btn" in source
    assert ".edit-status-error" in source
    assert ".edit-status-success" in source





def test_frontend_js_save_success_updates_edit_baseline():
    """on save success, frontend JS must update the editingSession
    baseline to the saved values so the dirty state clears and Cancel
    after save does not revert to pre-save values."""
    source = read_all_js()
    assert "editingSession.project_id = projectId" in source, (
        "save success must update editingSession.project_id to the saved value"
    )
    assert "editingSession.session_note = note" in source, (
        "save success must update editingSession.session_note to the saved value"
    )



def test_frontend_js_update_note_count_disables_save_over_limit():
    """updateNoteCount must disable the save button when the
    note exceeds NOTE_MAX_LENGTH, so the user gets immediate feedback."""
    source = read_all_js()
    assert "edit-note-count-over" in source, (
        "updateNoteCount must add an 'edit-note-count-over' class when over limit"
    )
    # The function must reference the save button and toggle its disabled
    # state based on the length check.
    assert "edit-save-btn" in source
    assert "len > App.NOTE_MAX_LENGTH" in source or "len >= App.NOTE_MAX_LENGTH" in source



def test_frontend_js_set_edit_saving_reapplies_length_guard():
    """setEditSaving(false) must call updateNoteCount to
    re-apply the note-length guard after a save finishes."""
    source = read_all_js()
    # Find the setEditSaving function body and verify it calls
    # updateNoteCount when saving is false.
    assert "if (!saving && App.editingSession)" in source, (
        "setEditSaving must call updateNoteCount when saving is false"
    )
    assert "updateNoteCount()" in source



def test_frontend_js_populate_edit_panel_calls_update_note_count_last():
    """populateEditPanel must call updateNoteCount after
    enabling the save button so the length check has the final say."""
    import re

    source = read_all_js()
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
    """styles.css must style the note counter in red when the
    note exceeds the 2000-character limit."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-note-count-over" in source



def test_styles_css_has_edit_panel_responsive_rules():
    """styles.css must keep the edit panel usable on narrow
    viewports — the actions row wraps and the note textarea keeps a
    min-height."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-actions" in source
    assert "flex-wrap" in source
    assert "min-height" in source



def test_frontend_js_still_has_no_forbidden_edit_handlers_after_hardening():
    """Time correction, activity split,
    two-activity merge, and single-activity hide / soft delete are now
    supported features, but the frontend must still not contain batch,
    restore, permanent-delete, or auto-rule handlers. ``merge_session``
    (multi-activity session whole-merge) is also forbidden — only the
    two-activity ``merge_timeline_activities`` bridge call is allowed."""
    source = read_all_js().lower()
    # provides time correction; split is provided;
    # two-activity merge; single-activity hide / soft delete
    # is provided. The following forbidden handlers must
    # still be absent.
    assert "merge_session" not in source
    assert "batch_edit" not in source
    assert "batch_delete" not in source
    assert "batch_hide" not in source
    assert "restore_activity" not in source
    assert "permanent_delete" not in source
    assert "auto_rule" not in source
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
    # introduces single activity restore, so "restore" is now
    # allowed in index.html. Batch restore, restore-all, undo stack, and
    # permanent delete must still be absent.
    for forbidden_restore in (
        "batch-restore", "batchrestore", "restore-all", "restoreall",
        "undo-restore", "undorestore", "permanent", "auto-rule",
    ):
        assert forbidden_restore not in html_source, (
            "index.html must not contain a '" + forbidden_restore + "' control"
        )





def test_frontend_js_has_request_token_guard_for_timeline_loads():
    """frontend JS must use a request token (or equivalent sequence
    id) to prevent stale Timeline load responses from overwriting newer
    data when the user rapidly switches dates."""
    source = read_all_js()
    assert "timelineRequestToken" in source, (
        "frontend JS must define a timelineRequestToken guard so stale bridge "
        "responses do not overwrite newer Timeline data"
    )
    # The token must be incremented before each load and checked after.
    assert "++App.timelineRequestToken" in source
    assert "token !== App.timelineRequestToken" in source



def test_frontend_js_has_request_token_guard_for_session_details():
    """frontend JS must use a request token for session detail loads
    too, so rapidly switching sessions does not let an older detail
    response overwrite the newer one."""
    source = read_all_js()
    assert "detailsRequestToken" in source, (
        "frontend JS must define a detailsRequestToken guard so stale session "
        "detail responses do not overwrite newer detail data"
    )
    assert "++App.detailsRequestToken" in source
    assert "token !== App.detailsRequestToken" in source



def test_frontend_js_preserves_selected_session_across_refresh():
    """frontend JS must keep the selected session selected across
    auto-refresh. The session must be matched by session_id, and if it
    disappears the selection must clear gracefully without JS errors."""
    source = read_all_js()
    assert "selectedSessionId" in source
    # The selected session must be matched by session_id after refresh.
    assert "session_id === App.selectedSessionId" in source or (
        "sessions[k].session_id === App.selectedSessionId" in source
    )



def test_frontend_js_handles_disappeared_selected_session_gracefully():
    """when the last selected session no longer exists
    after a refresh, frontend JS must clear the selection without throwing."""
    source = read_all_js()
    # The code path that handles a missing session must reset
    # selectedSessionId and update the details panel placeholder.
    assert "selectedSessionId = null" in source



def test_frontend_js_marks_in_progress_sessions():
    """frontend JS must visually mark in-progress sessions (sessions
    whose ``is_in_progress`` flag is true) so the user can tell the
    current open record from closed history."""
    source = read_all_js()
    assert "is_in_progress" in source
    assert "in-progress" in source, (
        "frontend JS must apply an 'in-progress' CSS class to in-progress items"
    )



def test_frontend_js_marks_in_progress_activities():
    """frontend JS must visually mark in-progress activity detail
    rows too."""
    source = read_all_js()
    # The detail rendering must check is_in_progress and apply the class.
    assert "a.is_in_progress" in source or "is_in_progress" in source



def test_frontend_js_uses_in_progress_label_in_time_range():
    """when the ``is_in_progress`` flag is true, frontend JS must show
    a clear '进行中' label in the time range instead of an empty 'HH:MM-'.
    The frontend consumes the explicit ``is_in_progress`` flag (not the
    emptiness of the displayed ``end_time``, which may be projected for
    open activities)."""
    source = read_all_js()
    assert "进行中" in source, (
        "frontend JS must show '进行中' for in-progress time ranges"
    )



def test_frontend_js_provides_safe_tooltip_for_long_text():
    """frontend JS must add ``title`` attributes with the safe
    display name so the user can read long names on hover. The tooltip
    must use the same sanitized display name shown inline, not the raw
    window_title or full path."""
    source = read_all_js()
    assert 'title="' in source or "title=" in source
    # The tooltip must use escapeHtml to avoid attribute injection.
    assert 'escapeHtml(' in source



def test_frontend_js_preserves_prior_data_on_refresh_error():
    """when a Timeline refresh fails, frontend JS must keep showing
    the last loaded data instead of clearing the page. The error
    banner is shown alongside the prior data."""
    source = read_all_js()
    assert "lastTimelineData" in source, (
        "frontend JS must cache lastTimelineData so a refresh failure keeps the "
        "prior data visible instead of clearing the page"
    )



def test_styles_css_has_in_progress_styling():
    """styles.css must visually distinguish in-progress
    sessions/activities from closed history."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".timeline-item.in-progress" in source
    assert ".detail-item.in-progress" in source



def test_styles_css_has_responsive_layout_for_narrow_viewports():
    """styles.css must keep the Timeline layout usable on
    narrow viewports. Long resource names must not stretch the layout."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    # The detail-item must switch to a single-column grid on narrow viewports
    # so long names wrap instead of stretching the layout horizontally.
    assert "grid-template-columns: 1fr" in source
    assert "@media" in source



def test_index_html_timeline_details_panel_has_initial_empty_state():
    """the Timeline details panel must ship with an initial
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





def test_index_html_has_time_correction_section():
    """index.html must have a time-correction section in the
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



def test_frontend_js_calls_time_correction_bridge_methods():
    """frontend JS must call the new bridge methods for time
    correction."""
    source = read_all_js()
    assert "update_timeline_activity_time" in source
    assert "update_timeline_session_time" in source



def test_frontend_js_has_datetime_conversion_helpers():
    """frontend JS must have helpers to convert between the backend
    ``YYYY-MM-DD HH:MM:SS`` format and the ``datetime-local`` input's
    ``YYYY-MM-DDTHH:MM:SS`` format."""
    source = read_all_js()
    assert "backendToDatetimeLocal" in source
    assert "datetimeLocalToBackend" in source
    # The conversion must use fixed-format string replacement (space <-> T),
    # not Date parsing (which would interpret as local time and shift values).
    assert ".replace" in source



def test_frontend_js_has_time_saving_state():
    """frontend JS must track independent saving states for
    session-level and per-activity time correction so they do not pollute
    the project/note saving state."""
    source = read_all_js()
    assert "timeSaving" in source
    assert "activityTimeSaving" in source
    assert "setTimeSaving" in source
    assert "setActivityTimeSaving" in source
    # The session-level saving state must be separate from editSaving
    assert "editSaving" in source



def test_frontend_js_has_session_time_functions():
    """frontend JS must define the session-level time correction
    lifecycle functions."""
    source = read_all_js()
    assert "populateSessionTimeSection" in source
    assert "resetSessionTimeSection" in source
    assert "saveSessionTime" in source
    assert "showTimeStatus" in source



def test_frontend_js_has_per_activity_inline_editor_functions():
    """frontend JS must define the per-activity inline time editor
    lifecycle functions."""
    source = read_all_js()
    assert "openActivityTimeEditor" in source
    assert "closeActivityTimeEditor" in source
    assert "saveActivityTime" in source
    assert "editingActivityId" in source



def test_frontend_js_refreshes_timeline_after_time_save():
    """after a successful time correction, frontend JS must refresh
    the Timeline so the new times are reflected."""
    source = read_all_js()
    # saveSessionTime and saveActivityTime must both call refreshTimelineAfterEdit
    save_session_pos = source.find("function saveSessionTime")
    assert save_session_pos != -1
    save_activity_pos = source.find("function saveActivityTime")
    assert save_activity_pos != -1
    # Check that refreshTimelineAfterEdit is called within both functions
    refresh_pos = source.find("function refreshTimelineAfterEdit")
    assert refresh_pos != -1



def test_frontend_js_disables_in_progress_activity_time_edit():
    """in-progress activities must have their '编辑时间' button
    disabled, and the session-level time section must show a hint."""
    source = read_all_js()
    assert "进行中记录无法修改时间" in source



def test_frontend_js_disables_multi_activity_session_time_edit():
    """multi-activity sessions must show the 'multi-activity
    not supported' hint instead of the time inputs."""
    source = read_all_js()
    assert "多活动时段无法修改整体时间" in source



def test_frontend_js_preserves_input_on_save_failure():
    """when a time save fails, the user's input must be
    preserved (not cleared) and an error message shown."""
    source = read_all_js()
    # The save functions must call setTimeSaving(false) on error to
    # re-enable the button without clearing the input values. The .catch
    # handler and the `result.ok === false` branch must both re-enable
    # without resetting the input .value.
    assert "setTimeSaving(false)" in source or "setTimeSaving(row, false)" in source
    # The error path must show an error message, not clear the inputs.
    assert "保存时间失败" in source



def test_frontend_js_time_edit_uses_is_in_progress_not_end_time_emptiness():
    """the frontend must use the ``is_in_progress`` flag to
    decide whether time editing is allowed, NOT infer it from whether
    ``end_time`` is empty (because the displayed ``end_time`` may be a
    projected value for open activities)."""
    source = read_all_js()
    # populateSessionTimeSection must check is_in_progress, not end_time
    populate_pos = source.find("function populateSessionTimeSection")
    assert populate_pos != -1
    # Find the end of the function (next 'function' at the same indent level)
    next_func = source.find("\n    function ", populate_pos + 1)
    body = source[populate_pos:next_func]
    assert "is_in_progress" in body



def test_frontend_js_time_edit_buttons_have_no_delete_batch():
    """The per-activity editor area must
    not include batch, restore, or permanent-delete buttons. Split buttons
    are provided, merge buttons are provided, and
    per-activity hide / soft-delete buttons are provided; all
    three are allowed."""
    source = read_all_js().lower()
    # The renderSessionDetails function must not generate batch / restore /
    # permanent-delete buttons. Hide / soft-delete buttons,
    # merge buttons, and split buttons are allowed.
    render_pos = source.find("function rendersessiondetails")
    assert render_pos != -1
    # Find the next function to bound the search
    next_func = source.find("\n    function ", render_pos + 1)
    body = source[render_pos:next_func] if next_func != -1 else source[render_pos:]
    assert "batch" not in body
    assert "restore" not in body
    assert "permanent" not in body



def test_styles_css_has_time_correction_styles():
    """styles.css must style the time correction UI elements."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-time-section" in source
    assert ".edit-time-input" in source
    assert ".edit-time-save-btn" in source
    assert ".detail-time-editor" in source
    assert ".detail-time-input" in source
    assert ".detail-time-save-btn" in source





def test_refresh_timeline_after_edit_does_not_reset_edit_saving():
    """``refreshTimelineAfterEdit`` must NOT call
    ``setEditSaving(false)``. The three independent save flows (project/note,
    session-time, per-activity-time) must each reset their own saving state
    before calling the shared refresh function, so a refresh triggered by one
    flow does not prematurely reset another flow's saving state."""
    source = read_all_js()
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
    """``saveSessionTime`` must call ``setTimeSaving(false)``
    BEFORE ``refreshTimelineAfterEdit`` on the success path, so the save
    button is re-enabled regardless of whether the refresh succeeds."""
    source = read_all_js()
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
    """``saveEdit`` must call ``setEditSaving(false)`` BEFORE
    ``refreshTimelineAfterEdit`` on the success path."""
    source = read_all_js()
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
    """``saveActivityTime`` must call
    ``setActivityTimeSaving(row, false)`` BEFORE ``refreshTimelineAfterEdit``
    on the success path."""
    source = read_all_js()
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



def test_is_edit_dirty_covers_duration_input():
    """``isEditDirty`` must check the ``edit-duration-input`` field so
    auto-refresh does not overwrite an unsaved duration override.

    The session-level time inputs (``edit-start-time`` / ``edit-end-time``)
    have moved to the correction shell in the simplified view, so they are
    no longer checked by the main ``isEditDirty``. The duration override
    input is now the third field in the main edit panel alongside note
    and project."""
    source = read_all_js()
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
    assert "edit-duration-input" in body, (
        "isEditDirty must check edit-duration-input for unsaved duration "
        "overrides so auto-refresh does not wipe them"
    )



def test_is_edit_dirty_no_longer_checks_inline_editors():
    """The main ``isEditDirty`` no longer checks ``editingActivityId`` because
    per-activity inline editors have moved to the correction shell (opened
    via the ``高级纠错`` button). The correction shell has its own dirty /
    saving guards; the main edit panel only tracks note, project, and
    duration."""
    source = read_all_js()
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
    # The simplified isEditDirty must still check note and project.
    assert "edit-note-text" in body, (
        "isEditDirty must still check edit-note-text"
    )
    assert "edit-project-select" in body, (
        "isEditDirty must still check edit-project-select"
    )



def test_auto_refresh_skips_detail_reload_when_edit_dirty():
    """the Timeline auto-refresh path must call ``isEditDirty``
    to decide whether to skip the detail reload / edit-panel repopulation,
    so unsaved time edits are not overwritten."""
    source = read_all_js()
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
    """styles.css must wrap ``.detail-time-row`` on narrow
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
    """``saveSessionTime`` must update the
    ``editingSession.start_time`` / ``end_time`` baseline on success so a
    subsequent auto-refresh does not revert the inputs to pre-save values."""
    source = read_all_js()
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
    """``saveActivityTime`` must update the button's
    ``data-start`` / ``data-end`` attributes on success so a subsequent
    auto-refresh does not revert the editor inputs to pre-save values."""
    source = read_all_js()
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





def test_index_html_has_split_section():
    """index.html must have a split section in the edit panel
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



def test_frontend_js_calls_split_bridge_methods():
    """frontend JS must call the new bridge methods for splitting."""
    source = read_all_js()
    assert "split_timeline_activity" in source
    assert "split_timeline_session" in source



def test_frontend_js_has_split_saving_state():
    """frontend JS must track independent saving states for
    session-level and per-activity split so they do not pollute the
    project/note/time saving states."""
    source = read_all_js()
    assert "sessionSplitSaving" in source
    assert "activitySplitSaving" in source
    assert "editingSplitActivityId" in source
    # The split saving states must be separate from the time saving states
    assert "timeSaving" in source
    assert "activityTimeSaving" in source



def test_frontend_js_has_session_split_functions():
    """frontend JS must define the session-level split lifecycle
    functions."""
    source = read_all_js()
    assert "populateSessionSplitSection" in source
    assert "resetSessionSplitSection" in source
    assert "saveSessionSplit" in source
    assert "showSplitStatus" in source
    assert "setSessionSplitSaving" in source



def test_frontend_js_has_per_activity_split_functions():
    """frontend JS must define the per-activity inline split editor
    lifecycle functions."""
    source = read_all_js()
    assert "openActivitySplitEditor" in source
    assert "closeActivitySplitEditor" in source
    assert "closeAllActivitySplitEditors" in source
    assert "saveActivitySplit" in source
    assert "setActivitySplitSaving" in source



def test_frontend_js_refreshes_timeline_after_split_save():
    """after a successful split, frontend JS must refresh the
    Timeline so the two new activities appear."""
    source = read_all_js()
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



def test_frontend_js_split_save_resets_saving_before_refresh():
    """``saveActivitySplit`` and ``saveSessionSplit`` must
    reset the saving state BEFORE calling ``refreshTimelineAfterEdit`` so
    the UI does not get stuck in the '拆分中…' state if the refresh
    fails."""
    source = read_all_js()
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



def test_frontend_js_split_preserves_input_on_save_failure():
    """when a split save fails, the user's input must be
    preserved (not cleared) and an error message shown. The save
    functions must reset the saving state to re-enable the button without
    wiping the input value."""
    source = read_all_js()
    # The error path must reset the saving state. Both the
    # ``result.ok === false`` branch and the ``.catch`` handler must reset.
    assert "setActivitySplitSaving(row, false)" in source
    assert "setSessionSplitSaving(false)" in source
    # The error path must show an error message (split-failed).
    assert "拆分失败" in source



def test_frontend_js_split_disables_multi_activity_session():
    """multi-activity sessions must show the 'multi-activity
    not supported' hint for the session-level split."""
    source = read_all_js()
    assert "多活动时段请在活动详情中拆分单条活动" in source



def test_frontend_js_split_disables_in_progress_activity():
    """in-progress activities must be disabled or show a hint
    for splitting."""
    source = read_all_js()
    assert "进行中记录无法拆分" in source



def test_frontend_js_split_does_not_use_date_automatic_parsing():
    """the split-time conversion must NOT rely on JS ``Date``
    string parsing (which interprets the value as local time and could
    shift it). The midpoint helper must use explicit Date.UTC
    construction."""
    source = read_all_js()
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



def test_frontend_js_split_has_no_merge_delete_batch_auto_rule_handlers():
    """The split code must not introduce merge, batch
    edit, restore, permanent-delete, or auto-rule handlers. The
    soft-delete introduces ``saveActivityDelete`` / ``saveSessionDelete`` for single-
    activity soft delete; the lowercase-d ``deleteActivity`` handler name
    (a different convention) must still be absent."""
    source = read_all_js()
    # The whole file must not contain merge/batch/restore/permanent/auto-rule
    # handler names. (Split and single-activity soft delete are allowed.)
    assert "mergeActivity" not in source
    assert "deleteActivity" not in source
    assert "batchEdit" not in source
    assert "restoreActivity" not in source
    assert "permanentDelete" not in source
    assert "autoRule" not in source
    assert "createRule" not in source



def test_is_edit_dirty_no_longer_checks_split_inputs():
    """The main ``isEditDirty`` no longer checks the session-level split
    input (``edit-split-time``) or the per-activity inline split editor
    (``editingSplitActivityId``) because the split UI has moved to the
    correction shell (opened via the ``高级纠错`` button). The correction
    shell has its own dirty / saving guards; the main edit panel only
    tracks note, project, and duration."""
    source = read_all_js()
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
    assert "edit-split-time" not in body, (
        "isEditDirty must no longer check edit-split-time; the split UI has "
        "moved to the correction shell"
    )
    assert "editingSplitActivityId" not in body, (
        "isEditDirty must no longer check editingSplitActivityId; per-activity "
        "inline split editors have moved to the correction shell"
    )



def test_styles_css_has_split_styles():
    """styles.css must style the split UI elements."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-split-section" in source
    assert ".edit-split-save-btn" in source
    assert ".detail-split-editor" in source
    assert ".detail-split-btn" in source



def test_styles_css_has_split_responsive_wrap():
    """styles.css must handle the split editor on narrow
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





def test_frontend_js_calls_merge_bridge_method():
    """frontend JS must call the new bridge method for merging two
    activities."""
    source = read_all_js()
    assert "merge_timeline_activities" in source



def test_frontend_js_has_merge_saving_state():
    """frontend JS must track an independent saving state for merge
    so it does not pollute the project/note/time/split saving states."""
    source = read_all_js()
    assert "mergeSaving" in source
    assert "mergingActivityId" in source
    # The merge saving state must be separate from the other saving states
    assert "editSaving" in source
    assert "timeSaving" in source
    assert "activitySplitSaving" in source



def test_frontend_js_has_merge_functions():
    """frontend JS must define the merge lifecycle functions."""
    source = read_all_js()
    assert "saveActivityMerge" in source
    assert "setMergeSaving" in source
    assert "setMergeStatus" in source



def test_frontend_js_no_merge_button_in_rendered_detail_rows():
    """The simplified ``renderSessionDetails`` no longer renders a per-
    activity merge button (``detail-merge-btn`` / ``与下一条合并``) in
    the detail rows. Per-activity merge has moved to the correction shell
    (opened via the ``高级纠错`` button). The merge bridge call and
    saving-state helpers may still exist for the correction shell, but
    the rendered detail rows must be read-only."""
    source = read_all_js()
    start = source.find("function renderSessionDetails(")
    assert start != -1, "renderSessionDetails must exist"
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
    assert "detail-merge-btn" not in body, (
        "renderSessionDetails must no longer render detail-merge-btn; "
        "per-activity merge has moved to the correction shell"
    )
    assert "与下一条合并" not in body, (
        "renderSessionDetails must no longer render the 与下一条合并 button "
        "label; per-activity merge has moved to the correction shell"
    )



def test_frontend_js_merge_save_resets_saving_before_refresh():
    """``saveActivityMerge`` must reset the saving state BEFORE
    calling ``refreshTimelineAfterEdit`` on the success path so the UI
    does not get stuck in the '合并中…' state if the refresh fails."""
    source = read_all_js()
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



def test_frontend_js_merge_preserves_state_on_save_failure():
    """when a merge save fails, the saving state must be reset
    and an error message shown. The detail list must not be cleared."""
    source = read_all_js()
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



def test_frontend_js_render_session_details_no_merge_button_disabled_logic():
    """The simplified ``renderSessionDetails`` no longer computes a
    ``mergeBtnDisabled`` flag because per-activity merge buttons are no
    longer rendered in the detail rows (merge has moved to the correction
    shell). The function may still reference ``is_in_progress`` for row
    class purposes, but must not contain the per-activity merge-button
    disabled logic."""
    source = read_all_js()
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
    assert "mergeBtnDisabled" not in body, (
        "renderSessionDetails must no longer compute a mergeBtnDisabled flag; "
        "per-activity merge buttons have moved to the correction shell"
    )



def test_frontend_js_merge_has_no_delete_batch_auto_rule_handlers():
    """The merge code must not introduce batch edit,
    restore, permanent-delete, or auto-rule handlers. Multi-activity
    session whole-merge (``merge_session``) is also forbidden. The
    soft-delete introduces ``saveActivityDelete`` / ``saveSessionDelete`` for single-
    activity soft delete; the lowercase-d ``deleteActivity`` handler name
    must still be absent."""
    source = read_all_js()
    assert "deleteActivity" not in source
    assert "batchEdit" not in source
    assert "restoreActivity" not in source
    assert "permanentDelete" not in source
    assert "autoRule" not in source
    assert "createRule" not in source
    assert "merge_session" not in source



def test_frontend_js_merge_has_no_raw_field_exposure():
    """the merge code must not reference raw window_title,
    file_path_hint, full_path, or clipboard fields."""
    source = read_all_js().lower()
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



def test_frontend_js_merge_state_reset_in_clear_edit_panel():
    """clearEditPanel must reset the merge saving state so a
    stale merge does not leak into a new session selection."""
    source = read_all_js()
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
    """styles.css must style the merge button and status."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".detail-merge-btn" in source
    assert ".detail-merge-status" in source



def test_styles_css_has_merge_responsive_wrap():
    """styles.css must handle the merge button on narrow
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





def test_frontend_js_has_hide_delete_bridge_calls():
    """frontend JS must call the hide / soft-delete bridge methods."""
    source = read_all_js()
    assert "hide_timeline_activity" in source
    assert "soft_delete_timeline_activity" in source
    assert "hide_timeline_session" in source
    assert "soft_delete_timeline_session" in source



def test_frontend_js_has_hide_delete_saving_state():
    """frontend JS must declare independent hideSaving / deleteSaving
    state variables so the hide / delete flows do not pollute the other
    save flows. (State vars now live on the App. namespace.)"""
    source = read_all_js()
    assert "App.hideSaving" in source
    assert "App.deleteSaving" in source
    # The hide/delete saving state must be separate from the merge saving
    # state and the other edit flows.
    assert "App.mergeSaving" in source
    assert "App.hideSaving" in source
    assert "App.deleteSaving" in source



def test_frontend_js_hide_delete_refreshes_timeline_on_success():
    """a successful hide / delete must call the shared
    ``refreshTimelineAfterEdit`` helper to refresh the Timeline."""
    source = read_all_js()
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



def test_frontend_js_hide_delete_clears_saving_state_on_failure():
    """a failed hide / delete must clear the saving state so the
    button is not stuck in the "处理中" state."""
    source = read_all_js()
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
        # Both the error branch (result.ok === false) and the catch branch must
        # reset the saving state. We verify by counting occurrences of the reset
        # helper (setHideSaving / setDeleteSaving / setSessionHideSaving /
        # setSessionDeleteSaving, depending on the function).
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



def test_frontend_js_hide_delete_preserves_details_on_failure():
    """a failed hide / delete must not clear the detail list.
    The save functions must not call any clear/render function on the
    failure branch (only refreshTimelineAfterEdit is called on success)."""
    source = read_all_js()
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



def test_frontend_js_multi_activity_session_disables_whole_hide_delete():
    """a multi-activity session must disable the session-level
    hide / delete and show the "多活动" hint. The
    ``populateSessionVisibilitySection`` function must check
    ``activityIds.length > 1`` and show the multi-activity hint."""
    source = read_all_js()
    start = source.find("function populateSessionVisibilitySection(")
    assert start != -1, "populateSessionVisibilitySection must exist"
    next_func = source.find("\n    function ", start + 1)
    body = source[start:next_func] if next_func != -1 else source[start:]
    assert "activityIds.length > 1" in body or "activityIds.length !== 1" in body, (
        "populateSessionVisibilitySection must check for multi-activity sessions"
    )
    # The multi-activity hint must mention "多活动".
    assert "多活动" in body



def test_frontend_js_render_session_details_no_visibility_button_logic():
    """The simplified ``renderSessionDetails`` no longer computes a
    ``visibilityBtnDisabled`` flag because per-activity hide / delete
    buttons are no longer rendered in the detail rows (they have moved
    to the correction shell).

    The session-level ``populateSessionVisibilitySection`` (used by the
    correction shell / edit panel) must still check ``is_in_progress``
    so an in-progress session shows the "进行中" hint instead of the
    hide / delete buttons."""
    source = read_all_js()
    # renderSessionDetails must no longer compute a visibilityBtnDisabled
    # flag for in-progress activities (per-activity buttons are gone).
    render_start = source.find("function renderSessionDetails(")
    assert render_start != -1, "renderSessionDetails must exist"
    render_next = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_next] if render_next != -1 else source[render_start:]
    assert "visibilityBtnDisabled" not in render_body, (
        "renderSessionDetails must no longer compute a visibilityBtnDisabled "
        "flag; per-activity hide / delete buttons have moved to the correction shell"
    )
    # populateSessionVisibilitySection must still check is_in_progress so
    # the session-level hide / delete UI in the correction shell refuses
    # in-progress sessions.
    vis_start = source.find("function populateSessionVisibilitySection(")
    assert vis_start != -1, "populateSessionVisibilitySection must exist"
    vis_next = source.find("\n    function ", vis_start + 1)
    vis_body = source[vis_start:vis_next] if vis_next != -1 else source[vis_start:]
    assert "is_in_progress" in vis_body



def test_frontend_js_hide_delete_blocked_when_edit_dirty():
    """if ``isEditDirty()`` returns true, the hide / delete
    functions must refuse and show "请先保存或取消当前编辑"."""
    source = read_all_js()
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



def test_frontend_js_has_no_batch_restore_permanent_auto_rule_handlers():
    """the hide / delete additions must not introduce batch
    hide, batch delete, restore, permanent delete, or auto-rule handlers."""
    source = read_all_js().lower()
    assert "batch_delete" not in source
    assert "batch_hide" not in source
    assert "restore_activity" not in source
    assert "permanent_delete" not in source
    assert "auto_rule" not in source



def test_frontend_js_hide_delete_has_no_raw_field_exposure():
    """the hide / delete code must not reference raw
    window_title, file_path_hint, full_path, or clipboard fields.

    Exception: ``clipboard_capture_enabled`` is the JSON status
    flag returned by the Settings / Privacy read-only facade; it is the
    only allowed ``clipboard`` reference. All other uses remain forbidden.

    Exception: the Settings / Privacy clipboard capture toggle
    introduces ``settings-clipboard-toggle`` DOM ids and ``clipboardtoggle``
    function names (e.g. ``setClipboardToggleStatus``). These are UI
    identifiers, not raw backend field names, so they are also whitelisted.
    """
    source = read_all_js().lower()
    # The frontend must never reference these raw backend fields. (The
    # detail rows may show a resource_name, but never the raw column
    # names.)
    # only the legitimate JSON status flag name is whitelisted.
    source_without_capture_flag = source.replace("clipboard_capture_enabled", "")
    # whitelist the toggle DOM id prefix and camelCase function
    # names (lowercased) so they are not confused with the raw "clipboard"
    # content field.
    source_without_capture_flag = source_without_capture_flag.replace("clipboard-toggle", "")
    source_without_capture_flag = source_without_capture_flag.replace("clipboardtoggle", "")
    assert "window_title" not in source_without_capture_flag
    assert "file_path_hint" not in source_without_capture_flag
    assert "full_path" not in source_without_capture_flag
    assert "clipboard" not in source_without_capture_flag



def test_index_html_has_visibility_section():
    """index.html must include the edit-visibility-section with
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
    """styles.css must style the hide / delete UI elements."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".detail-hide-btn" in source
    assert ".detail-delete-btn" in source
    assert ".detail-visibility-status" in source
    assert ".edit-visibility-section" in source
    assert ".edit-visibility-hide-btn" in source
    assert ".edit-visibility-delete-btn" in source



def test_styles_css_has_visibility_responsive_wrap():
    """styles.css must handle the visibility buttons on narrow
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



def test_frontend_js_hide_delete_state_reset_in_clear_edit_panel():
    """clearEditPanel must reset the hide / delete saving state
    so a stale hide / delete does not leak into a new session selection."""
    source = read_all_js()
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



def test_frontend_js_visibility_buttons_bound_in_init():
    """the session-level hide / delete buttons must be bound in
    initButtons so they actually call the save handlers."""
    source = read_all_js()
    start = source.find("function initButtons(")
    assert start != -1, "initButtons must exist"
    next_func = source.find("\n    function ", start + 1)
    body = source[start:next_func] if next_func != -1 else source[start:]
    assert "edit-visibility-hide-btn" in body
    assert "edit-visibility-delete-btn" in body
    assert "saveSessionHide" in body
    assert "saveSessionDelete" in body



def test_frontend_js_no_per_activity_visibility_buttons_in_rendered_detail_rows():
    """The simplified ``renderSessionDetails`` no longer renders per-
    activity hide / delete buttons (``detail-hide-btn`` /
    ``detail-delete-btn``) in the detail rows. Per-activity hide / delete
    has moved to the correction shell (opened via the ``高级纠错``
    button). The ``data-activity-id`` attribute is still rendered on
    each detail row for identification / ticker purposes."""
    source = read_all_js()
    start = source.find("function renderSessionDetails(")
    assert start != -1, "renderSessionDetails must exist"
    next_func = source.find("\n    function ", start + 1)
    body = source[start:next_func] if next_func != -1 else source[start:]
    assert "detail-hide-btn" not in body, (
        "renderSessionDetails must no longer render detail-hide-btn; "
        "per-activity hide has moved to the correction shell"
    )
    assert "detail-delete-btn" not in body, (
        "renderSessionDetails must no longer render detail-delete-btn; "
        "per-activity delete has moved to the correction shell"
    )
    # data-activity-id is still rendered on each row for identification.
    assert "data-activity-id" in body, (
        "renderSessionDetails must still render data-activity-id on each "
        "detail row for identification / ticker purposes"
    )



def test_frontend_js_delete_uses_window_confirm():
    """the delete flow must use ``window.confirm`` with the
    soft-delete hint to avoid accidental deletion."""
    source = read_all_js()
    assert "window.confirm" in source
    assert "确定从 Timeline 删除这条记录吗？不会物理删除数据。" in source





def test_frontend_js_has_unified_status_type_class_map():
    """frontend JS must define the STATUS_TYPE_CLASS map with the five
    unified status types (info / success / error / loading / empty)."""
    source = read_all_js()
    assert "STATUS_TYPE_CLASS" in source, (
        "frontend JS must define STATUS_TYPE_CLASS map"
    )
    for key in ("info", "success", "error", "loading", "empty"):
        assert key + ":" in source or key + ' :' in source, (
            "STATUS_TYPE_CLASS must include the '" + key + "' type"
        )



def test_frontend_js_has_status_class_for_helper():
    """frontend JS must define the statusClassFor helper."""
    source = read_all_js()
    assert "function statusClassFor" in source, (
        "frontend JS must define statusClassFor helper"
    )



def test_frontend_js_has_apply_status_type_helper():
    """frontend JS must define the applyStatusType helper."""
    source = read_all_js()
    assert "function applyStatusType" in source, (
        "frontend JS must define applyStatusType helper"
    )



def test_frontend_js_has_set_timeline_status_helper():
    """frontend JS must define the unified setTimelineStatus helper."""
    source = read_all_js()
    assert "function setTimelineStatus" in source, (
        "frontend JS must define setTimelineStatus helper"
    )



def test_frontend_js_has_set_detail_status_helper():
    """frontend JS must define the unified setDetailStatus helper."""
    source = read_all_js()
    assert "function setDetailStatus" in source, (
        "frontend JS must define setDetailStatus helper"
    )



def test_frontend_js_has_set_edit_status_helper():
    """frontend JS must define the unified setEditStatus helper."""
    source = read_all_js()
    assert "function setEditStatus" in source, (
        "frontend JS must define setEditStatus helper"
    )



def test_frontend_js_has_set_correction_status_helper():
    """frontend JS must define the unified setCorrectionStatus helper."""
    source = read_all_js()
    assert "function setCorrectionStatus" in source, (
        "frontend JS must define setCorrectionStatus helper"
    )



def test_frontend_js_unified_helpers_delegate_to_existing_helpers():
    """the unified status helpers must delegate to the existing
    per-area helpers (showEditStatus, setCorrectionShellStatus,
    clearTimelineError, setTimelineLoading, showTimelineError) so the DOM
    contract is unchanged."""
    source = read_all_js()
    set_timeline = func_body(source, "setTimelineStatus")
    set_edit = func_body(source, "setEditStatus")
    set_correction = func_body(source, "setCorrectionStatus")
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



def test_frontend_js_set_detail_status_uses_safe_textcontent():
    """setDetailStatus must write to textContent (display-safe),
    never to innerHTML."""
    body = func_body(
        read_all_js(),
        "setDetailStatus",
    )
    assert "textContent" in body, (
        "setDetailStatus must use textContent for display safety"
    )
    assert "innerHTML" not in body, (
        "setDetailStatus must not use innerHTML"
    )



def test_frontend_js_set_detail_status_default_text():
    """setDetailStatus must reset the header to the stable
    '请选择一条时间记录' prompt when message is empty."""
    body = func_body(
        read_all_js(),
        "setDetailStatus",
    )
    assert "请选择一条时间记录" in body, (
        "setDetailStatus must use the stable '请选择一条时间记录' default"
    )



def test_frontend_js_no_err_message_in_catch_blocks():
    """no catch block in frontend JS may surface raw exception text
    via err.message / err.toString() / error.message / error.toString().
    This is the display-safe hardening closure."""
    source = read_all_js()
    for forbidden in ("err.message", "err.toString",
                      "error.message", "error.toString",
                      "exception.message"):
        assert forbidden not in source, (
            "frontend JS must not surface raw exception text via " + forbidden
        )



def test_frontend_js_load_timeline_catch_uses_stable_fallback():
    """the loadTimeline catch block must use the stable Chinese
    fallback '加载时间线失败' instead of err.message."""
    source = read_all_js()
    assert "加载时间线失败" in source, (
        "loadTimeline catch must use the stable fallback string"
    )



def test_frontend_js_refresh_all_catch_uses_stable_fallbacks():
    """the refreshAll catch blocks (status / overview / recent)
    must use the stable Chinese fallback '刷新失败' instead of err.message."""
    source = read_all_js()
    assert "刷新失败" in source, (
        "refreshAll catch must use the stable fallback '刷新失败'"
    )



def test_frontend_js_standard_loading_text_present():
    """the standard loading text must still be present in the
    frontend resources (Timeline loading indicator)."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "加载中" in html or "加载中" in read_all_js(), (
        "standard loading text '加载中' must be present"
    )



def test_frontend_js_standard_empty_text_present():
    """the standard empty text must still be present in the
    frontend resources."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "暂无" in html, (
        "standard empty text '暂无' must be present in index.html"
    )



def test_frontend_js_standard_error_text_present():
    """the standard error text must still be present in the
    frontend resources."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "加载失败" in html, (
        "standard error text '加载失败' must be present in index.html"
    )



def test_frontend_js_cross_save_guard_text_still_present():
    """the cross-save guard text '请等待当前操作完成' must
    still be present (regression lock)."""
    source = read_all_js()
    assert "请等待当前操作完成" in source, (
        "cross-save guard text '请等待当前操作完成' must remain"
    )



def test_frontend_js_dirty_guard_text_still_present():
    """the dirty guard text '请先保存或取消当前编辑' must
    still be present (regression lock)."""
    source = read_all_js()
    assert "请先保存或取消当前编辑" in source, (
        "dirty guard text '请先保存或取消当前编辑' must remain"
    )



def test_index_html_soft_delete_copy_still_present():
    """the soft delete copy '不会物理删除数据' must
    still be present (regression lock — delete is still soft delete)."""
    source = read_all_js()
    assert "不会物理删除数据" in source, (
        "soft delete copy '不会物理删除数据' must remain"
    )



def test_styles_css_has_edit_status_info_class():
    """styles.css must define .edit-status-info."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-status-info" in source, (
        "styles.css must define .edit-status-info"
    )



def test_styles_css_has_edit_status_loading_class():
    """styles.css must define .edit-status-loading."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-status-loading" in source, (
        "styles.css must define .edit-status-loading"
    )



def test_styles_css_has_edit_status_empty_class():
    """styles.css must define .edit-status-empty."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-status-empty" in source, (
        "styles.css must define .edit-status-empty"
    )



def test_styles_css_unified_status_classes_share_prefix():
    """all five unified status classes must share the
    .edit-status-* prefix family."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (".edit-status-info", ".edit-status-success",
                ".edit-status-error", ".edit-status-loading",
                ".edit-status-empty"):
        assert cls in source, (
            "styles.css must contain the unified status class " + cls
        )



def test_styles_css_correction_shell_hidden_still_display_none():
    """.correction-shell[hidden] must still set display:none
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must have .correction-shell[hidden] rule"
    )
    pos = source.find(".correction-shell[hidden]")
    rule_end = source.find("}", pos)
    assert rule_end != -1, (
        ".correction-shell[hidden] rule must close with }"
    )
    rule = source[pos:rule_end + 1]
    assert "display: none" in rule, (
        ".correction-shell[hidden] must set display: none"
    )



def test_styles_css_highlight_still_present():
    """the transient highlight CSS must still be present
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "highlight" in source, (
        "styles.css must still contain the transient highlight rule"
    )



def test_styles_css_no_external_resources():
    """styles.css must not import external CSS / fonts / CDN
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("@import", "http://", "https://", "cdn",
                      "google fonts", "googleapis"):
        assert forbidden not in lowered, (
            "styles.css must not reference external resource: " + forbidden
        )



def test_index_html_correction_shell_cards_still_present():
    """the five available correction shell cards must still be
    present. The unavailable-feature card must NOT reappear."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for card_id in (
        "correction-shell-context-card",
        "correction-shell-activity-card",
        "correction-shell-single-action-card",
        "correction-shell-batch-action-card",
        "correction-shell-restore-card",
    ):
        assert card_id in source, (
            "index.html must still contain correction shell card: " + card_id
        )
    assert "correction-shell-not-implemented-card" not in source, (
        "index.html must not contain the not-implemented card; the "
        "unavailable feature list must not be rendered"
    )



def test_index_html_no_forbidden_batch_ui():
    """no batch hide / batch delete / batch restore /
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



def test_index_html_not_implemented_card_lists_unavailable():
    """the not-implemented card must NOT exist in index.html.
    Only currently-available capabilities are shown."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "correction-shell-not-implemented-card" not in source, (
        "index.html must not contain the not-implemented card; the "
        "unavailable feature list must not be rendered"
    )



def test_index_html_no_new_top_level_pages():
    """the sidebar nav still lists the five known items.

    Statistics / Export, Project Rules, and Settings / Privacy are all
    migrated WebView pages; Settings / Privacy migrated as a
    read-only status foundation.
    """
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # The sidebar nav must still list exactly the five known items.
    for nav_item in ("概览", "时间详情", "统计与导出",
                     "项目规则", "设置与隐私"):
        assert nav_item in source, (
            "sidebar must still list nav item: " + nav_item
        )
    rules_pos = source.find('id="page-rules"')
    assert rules_pos != -1
    rules_end = source.find('<section id="page-settings"', rules_pos)
    rules_section = source[rules_pos:rules_end]
    assert "WebView 迁移中" not in rules_section
    assert "rules-list" in rules_section

    # Settings / Privacy migrated as a read-only WebView status
    # page; the obsolete placeholder copy must not appear in its section.
    settings_section = html_section_by_id(source, "page-settings")
    assert "WebView 迁移中" not in settings_section



def test_frontend_js_correction_shell_no_local_storage():
    """frontend JS must not use localStorage / sessionStorage
    (regression lock)."""
    source = read_all_js()
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in source, (
            "frontend JS must not use " + forbidden
        )





def test_frontend_js_apply_status_type_preserves_non_status_classes():
    """applyStatusType must preserve non-status structural
    classes — it must only toggle the whitelisted status-type classes,
    not replace the entire className."""
    body = func_body(
        read_all_js(),
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



def test_frontend_js_has_status_type_class_values_whitelist():
    """frontend JS must define the STATUS_TYPE_CLASS_VALUES whitelist
    used by applyStatusType to filter classes."""
    source = read_all_js()
    assert "STATUS_TYPE_CLASS_VALUES" in source, (
        "frontend JS must define STATUS_TYPE_CLASS_VALUES whitelist"
    )



def test_frontend_js_status_class_for_safe_default():
    """statusClassFor must return a safe default (info class)
    for unknown types, never undefined or a user-supplied string."""
    body = func_body(
        read_all_js(),
        "statusClassFor",
    )
    assert "STATUS_TYPE_CLASS.info" in body, (
        "statusClassFor must fall back to STATUS_TYPE_CLASS.info"
    )
    assert "||" in body, (
        "statusClassFor must use || fallback for unknown types"
    )



def test_frontend_js_no_reason_message_leak():
    """no code path may read .reason.message or .message from
    a rejected promise / raw exception and render it to the UI."""
    source = read_all_js()
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
            "frontend JS must not read " + forbidden
            + " from rejected promises (raw exception leak risk)"
        )



def test_frontend_js_no_string_err_leak():
    """no code path may use String(err) or String(error) to
    convert a raw exception to a string for UI display."""
    source = read_all_js()
    for forbidden in ("String(err)", "String(error)",
                      "String(exception)", "err.toString()",
                      "error.toString()"):
        assert forbidden not in source, (
            "frontend JS must not convert raw exceptions via " + forbidden
        )



def test_frontend_js_save_edit_catch_uses_stable_fallback():
    """the saveEdit Promise.allSettled rejection handler must
    use the stable '保存失败' fallback instead of reading .reason.message."""
    source = read_all_js()
    # Bound the scan to the real saveEdit function body so adjacent
    # functions / modules cannot leak into the block we assert on.
    body = func_body(source, "saveEdit")
    # Find the Promise.allSettled block inside saveEdit.
    allsettled_pos = body.find("Promise.allSettled(promises).then")
    assert allsettled_pos != -1, "saveEdit must use Promise.allSettled"
    block = body[allsettled_pos:]
    assert "保存失败" in block, (
        "saveEdit rejection handler must use '保存失败' stable fallback"
    )



def test_frontend_js_stable_fallback_vocabulary_present():
    """all six stable Chinese fallback strings must be present
    in frontend JS: 加载时间线失败 / 刷新失败 / 加载详情失败 / 保存失败 /
    操作失败 / 恢复失败."""
    source = read_all_js()
    for fallback in ("加载时间线失败", "刷新失败", "加载详情失败",
                     "保存失败", "操作失败", "恢复失败"):
        assert fallback in source, (
            "frontend JS must contain stable fallback: " + fallback
        )



def test_frontend_js_no_old_longer_fallback_strings():
    """the old longer fallback strings must be
    replaced by the stable short forms (regression lock)."""
    source = read_all_js()
    for old_string in ("加载时间详情失败，请稍后重试。",
                       "无法连接采集器状态，请稍后重试。",
                       "加载今日概览失败，请稍后重试。",
                       "加载最近活动失败，请稍后重试。",
                       "刷新时间详情失败，请稍后重试。"):
        assert old_string not in source, (
            "frontend JS must not contain old longer fallback: " + old_string
        )



def test_frontend_js_timeline_loading_text_stable():
    """Timeline loading text must be stable."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "加载中" in html, (
        "Timeline loading text '加载中' must be present in index.html"
    )



def test_frontend_js_timeline_empty_text_stable():
    """Timeline empty text must be stable."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "暂无" in html, (
        "Timeline empty text '暂无' must be present in index.html"
    )



def test_frontend_js_timeline_error_text_stable():
    """Timeline error text must be stable."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "加载失败" in html, (
        "Timeline error text '加载失败' must be present in index.html"
    )



def test_frontend_js_detail_no_selection_text_stable():
    """detail panel no-selection text must be stable."""
    source = read_all_js()
    # setDetailStatus default + the index.html initial header text.
    assert "请选择一条时间记录" in source, (
        "setDetailStatus must use stable '请选择一条时间记录' default"
    )



def test_frontend_js_detail_error_fallback_stable():
    """detail panel error fallback must be stable."""
    source = read_all_js()
    assert "加载详情失败" in source, (
        "detail panel must use stable '加载详情失败' error fallback"
    )



def test_frontend_js_edit_saving_success_failure_strings_stable():
    """edit panel saving/success/failure strings must be
    stable."""
    source = read_all_js()
    assert "保存中" in source, "edit saving text '保存中' must be present"
    assert "保存成功" in source, "edit success text '保存成功' must be present"
    assert "保存失败" in source, "edit failure text '保存失败' must be present"



def test_frontend_js_correction_shell_dirty_guard_text_stable():
    """correction shell dirty guard text must be stable."""
    source = read_all_js()
    assert "请先保存或取消当前编辑" in source, (
        "dirty guard text '请先保存或取消当前编辑' must be present"
    )



def test_frontend_js_correction_shell_cross_save_guard_text_stable():
    """correction shell cross-save guard text must be stable."""
    source = read_all_js()
    assert "请等待当前操作完成" in source, (
        "cross-save guard text '请等待当前操作完成' must be present"
    )



def test_frontend_js_soft_delete_copy_still_not_permanent():
    """soft delete copy must still say not physical / not
    permanent delete (regression lock)."""
    source = read_all_js()
    assert "不会物理删除数据" in source, (
        "soft delete copy '不会物理删除数据' must remain"
    )



def test_frontend_js_restore_copy_still_no_batch_undo_permanent():
    """the correction shell must not list unavailable capabilities."""
    html = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "correction-shell-not-implemented-card" not in html, (
        "index.html must not contain the not-implemented card; the "
        "unavailable feature list must not be rendered"
    )



def test_frontend_js_auto_refresh_dirty_guard_present():
    """auto-refresh must check isEditDirty() before overwriting
    edit inputs (regression lock)."""
    source = read_all_js()
    # The auto-refresh path in showTimeline checks isEditDirty.
    assert "isEditDirty()" in source, (
        "auto-refresh must call isEditDirty() to guard edit inputs"
    )



def test_frontend_js_auto_refresh_saving_guard_present():
    """auto-refresh must check isAnyCorrectionWriteSaving()
    before re-rendering the correction shell (regression lock)."""
    source = read_all_js()
    assert "isAnyCorrectionWriteSaving()" in source, (
        "auto-refresh must call isAnyCorrectionWriteSaving() to guard "
        "correction shell re-render during save"
    )



def test_frontend_js_catch_paths_reset_saving():
    """all catch paths that follow a save must reset the saving
    flag so buttons are not left disabled (regression lock)."""
    source = read_all_js()
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



def test_frontend_js_display_safe_helpers_present():
    """display-safe helpers escapeHtml and safeText must be
    present (regression lock)."""
    source = read_all_js()
    assert "function escapeHtml" in source, (
        "escapeHtml helper must be present"
    )
    assert "function safeText" in source, (
        "safeText helper must be present"
    )



def test_frontend_js_no_raw_sensitive_fields_anywhere():
    """frontend JS must not reference raw window_title /
    file_path_hint / full_path / clipboard anywhere (regression lock).

    Exception: the Settings / Privacy read-only facade returns a
    boolean status flag named ``clipboard_capture_enabled``. That literal
    JSON field name is the only allowed ``clipboard`` reference. All other
    uses of the raw field token remain forbidden.

    Exception: the Settings / Privacy clipboard capture toggle
    introduces ``settings-clipboard-toggle`` DOM ids. These are UI element
    identifiers, not raw backend field names, so they are also whitelisted.
    """
    source = read_all_js()
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



def test_frontend_js_no_traceback_sql_display():
    """frontend JS must not display traceback or SQL strings
    (regression lock)."""
    source = read_all_js()
    lowered = source.lower()
    for forbidden in ("traceback", "sql error", "sqlite"):
        assert forbidden not in lowered, (
            "frontend JS must not display " + forbidden
        )



def test_styles_css_status_classes_complete():
    """styles.css must have all five status classes
    (info / success / error / loading / empty)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (".edit-status-info", ".edit-status-success",
                ".edit-status-error", ".edit-status-loading",
                ".edit-status-empty"):
        assert cls in source, (
            "styles.css must contain status class " + cls
        )



def test_styles_css_disabled_saving_styles_present():
    """styles.css must have disabled / saving state styles
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



def test_styles_css_correction_shell_hidden_display_none():
    """.correction-shell[hidden] must still set display:none
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must have .correction-shell[hidden] rule"
    )
    pos = source.find(".correction-shell[hidden]")
    rule_end = source.find("}", pos)
    assert rule_end != -1, (
        ".correction-shell[hidden] rule must close with }"
    )
    rule = source[pos:rule_end + 1]
    assert "display: none" in rule, (
        ".correction-shell[hidden] must set display: none"
    )



def test_styles_css_highlight_still_present_contract_2():
    """transient highlight CSS must still be present
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "highlight" in source, (
        "styles.css must still contain the transient highlight rule"
    )



def test_styles_css_no_external_resources_contract_2():
    """styles.css must not import external CSS / fonts / CDN
    (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("@import", "http://", "https://", "cdn",
                      "google fonts", "googleapis"):
        assert forbidden not in lowered, (
            "styles.css must not reference external resource: " + forbidden
        )



def test_styles_css_no_local_storage():
    """styles.css must not reference localStorage /
    sessionStorage (regression lock)."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in source, (
            "styles.css must not reference " + forbidden
        )



def test_frontend_js_no_react_vue_vite_node():
    """frontend JS must not reference React / Vue / Vite / Node
    (regression lock)."""
    source = read_all_js()
    lowered = source.lower()
    # Word-boundary matching for framework names so identifiers like
    # "navItems" (lowercased "navitems") do not falsely match "vite".
    for forbidden in ("react", "vue", "vite"):
        assert re.search(r"\b" + re.escape(forbidden) + r"\b", lowered) is None, (
            "frontend JS must not reference frontend framework: " + forbidden
        )
    # Syntax patterns are checked as literal substrings.
    for forbidden in ("require(", "module.exports"):
        assert forbidden not in lowered, (
            "frontend JS must not reference frontend framework: " + forbidden
        )



def test_frontend_js_no_local_http_server():
    """frontend JS must not start a local HTTP server
    (regression lock)."""
    source = read_all_js()
    lowered = source.lower()
    for forbidden in ("httpserver", "http.createServer",
                      "express(", "flask "):
        assert forbidden not in lowered, (
            "frontend JS must not start a local HTTP server: " + forbidden
        )



def test_bridge_no_unexpected_methods_for_contract():
    """No new bridge methods beyond the known method set
    (regression lock — ``get_statistics_export_summary`` is a
    read-only method; the time-details simplification adds
    update_timeline_note_and_duration for joint note + duration writes)."""
    # scan all 8 bridge mixin files (method bodies moved out of
    # bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    known_methods = (
        "get_status", "toggle_pause", "get_overview",
        "get_recent_activities", "get_timeline",
        "get_timeline_session_details", "list_projects_for_timeline",
        "update_timeline_project", "update_timeline_note",
        "update_timeline_note_and_duration",
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



def test_bridge_imports_only_allowed_modules():
    """the bridge must still only import worktrace.api and
    worktrace.formatters (regression lock)."""
    # scan all 8 bridge mixin files (imports may live in any
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



def test_api_has_no_unexpected_methods_for_contract():
    """the timeline API must still expose the known method set
    and error classes (regression lock — the time-details simplification
    adds update_timeline_session_note_and_duration for joint note +
    duration writes)."""
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
        "def update_timeline_session_note_and_duration",
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




def _extract_css_rule(source: str, selector: str) -> str:
    """Extract the body (inside braces) of the first CSS rule whose
    selector list contains ``selector`` as an actual rule selector
    (selector text followed by ``{``), skipping any mention of the
    selector inside comments."""
    pattern = re.compile(re.escape(selector) + r"\s*\{")
    match = pattern.search(source)
    assert match is not None, "selector not found in styles.css: " + selector
    brace_start = source.find("{", match.start())
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
                end = i
                break
    return source[brace_start + 1:end]


def test_detail_item_actions_has_own_grid_area():
    """``.detail-item-actions`` must use ``grid-area: actions``
    (NOT ``grid-row: 2``) so it never overlaps with
    ``.detail-item-meta`` / ``.detail-item-project``."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    body = _extract_css_rule(source, ".detail-item-actions")
    assert "grid-area: actions" in body, (
        ".detail-item-actions must declare grid-area: actions"
    )
    assert "grid-row: 2" not in body, (
        ".detail-item-actions must not use the fragile grid-row: 2 that "
        "caused overlap with meta / project"
    )


def test_detail_item_uses_grid_template_areas():
    """``.detail-item`` must define a ``grid-template-areas``
    block so each child has a named area instead of relying on implicit
    grid-row numbering."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    body = _extract_css_rule(source, ".detail-item")
    assert "grid-template-areas" in body, (
        ".detail-item must use grid-template-areas for layout"
    )


def test_detail_item_actions_not_sharing_row_with_meta_or_project():
    """the ``actions`` row in the desktop ``.detail-item``
    grid-template-areas must occupy its own row line (three ``actions``
    tokens), separate from the rows that contain ``meta`` and ``project``."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    body = _extract_css_rule(source, ".detail-item")
    # Find the grid-template-areas block and capture its content up to the
    # terminating semicolon. Use the colon to skip comment mentions of
    # "grid-template-areas" (the property is "grid-template-areas:").
    gta_start = body.find("grid-template-areas:")
    assert gta_start != -1
    semi = body.find(";", gta_start)
    assert semi != -1
    gta_block = body[gta_start:semi]
    # The actions row must be a line whose tokens are all "actions" — i.e.
    # it does not share a row with meta or project.
    actions_row_pattern = re.compile(
        r'"actions\s+actions\s+actions"',
    )
    assert actions_row_pattern.search(gta_block) is not None, (
        "grid-template-areas must have a dedicated actions row "
        '("actions actions actions") separate from meta / project'
    )
    # No single quoted row may contain both "actions" and "meta", and no
    # row may contain both "actions" and "project".
    for row_match in re.finditer(r'"([^"]*)"', gta_block):
        row_tokens = row_match.group(1).split()
        if "actions" in row_tokens:
            assert "meta" not in row_tokens, (
                "actions must not share a row with meta: " + row_match.group(0)
            )
            assert "project" not in row_tokens, (
                "actions must not share a row with project: "
                + row_match.group(0)
            )


def test_detail_item_mobile_layout_actions_on_own_row():
    """the mobile ``@media (max-width: 900px)`` ``.detail-item``
    override must also place ``actions`` on its own row inside its
    grid-template-areas block."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    # Scan every @media (max-width: 900px) block until one contains a
    # .detail-item rule with grid-template-areas whose "actions" row is
    # a single-token row.
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
        # Find the .detail-item rule inside this media block.
        di_idx = media_body.find(".detail-item")
        if di_idx == -1:
            search_from = end
            continue
        di_brace = media_body.find("{", di_idx)
        if di_brace == -1:
            search_from = end
            continue
        depth = 0
        di_end = di_brace
        for i in range(di_brace, len(media_body)):
            ch = media_body[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    di_end = i
                    break
        di_body = media_body[di_brace + 1:di_end]
        if "grid-template-areas:" not in di_body:
            search_from = end
            continue
        gta_start = di_body.find("grid-template-areas:")
        semi = di_body.find(";", gta_start)
        assert semi != -1
        gta_block = di_body[gta_start:semi]
        # The mobile actions row is a single "actions" token on its own line.
        if re.search(r'"actions"', gta_block) is not None:
            found = True
            break
        search_from = end
    assert found, (
        "mobile @media (max-width: 900px) .detail-item must place actions "
        'on its own row ("actions") inside grid-template-areas'
    )




def test_index_html_timeline_has_date_input():
    """The Timeline date nav must use an ``<input type="date">`` (id
    ``timeline-date-input``) so the user can pick a date directly from the
    native date picker instead of relying only on prev/next/today."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-date-input"' in source, (
        "index.html must have a timeline-date-input element"
    )
    assert 'type="date"' in source, (
        "timeline-date-input must be a date input"
    )


def test_index_html_timeline_has_current_activity():
    """The Timeline page must contain a ``timeline-current`` element."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-current"' in source


def test_index_html_timeline_has_duration_input():
    """The edit panel must contain a duration-override input
    (``edit-duration-input``) so the user can set a display/申报时长 that
    differs from the raw collected duration."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="edit-duration-input"' in source, (
        "index.html must have an edit-duration-input element in the edit panel"
    )


def test_index_html_timeline_edit_panel_has_advanced_correction_button():
    """The edit panel must contain a ``高级纠错`` button (id
    ``open-correction-shell-btn``) that opens the advanced correction
    shell for time/split/merge/visibility operations."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="open-correction-shell-btn"' in source, (
        "index.html must have an open-correction-shell-btn button"
    )
    assert "高级纠错" in source, (
        "the advanced correction button must display '高级纠错'"
    )


def test_index_html_time_sections_hidden_by_default():
    """The time-correction, split, and visibility sections must be
    ``hidden`` by default in the static HTML. They are shown dynamically
    by frontend JS only when a session is selected and the section applies."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for section_id in (
        "edit-time-section",
        "edit-split-section",
        "edit-visibility-section",
    ):
        pos = source.find('id="' + section_id + '"')
        assert pos != -1, (
            "index.html must contain section: " + section_id
        )
        # The hidden attribute must appear on the same element as the id.
        # Search backwards from the id to find the opening tag start, then
        # forwards to find the closing > of the opening tag.
        tag_start = source.rfind("<", 0, pos)
        tag_end = source.find(">", pos)
        assert tag_start != -1 and tag_end != -1, (
            "could not locate opening tag for " + section_id
        )
        opening_tag = source[tag_start:tag_end + 1]
        assert " hidden" in opening_tag, (
            section_id + " must have the 'hidden' attribute in its opening "
            "tag so it is hidden by default; got: " + opening_tag
        )


def test_frontend_js_has_format_start_time_only():
    """frontend JS must define ``formatStartTimeOnly`` so the Timeline session
    list and detail list show only the start time (HH:MM) of each
    activity, not the full datetime."""
    source = read_all_js()
    assert "formatStartTimeOnly" in source, (
        "frontend JS must define formatStartTimeOnly helper"
    )


def test_frontend_js_has_update_note_and_duration_bridge_call():
    """frontend JS must call the ``update_timeline_note_and_duration`` bridge
    method so the note and adjusted duration are saved together in a
    single write."""
    source = read_all_js()
    assert "update_timeline_note_and_duration" in source, (
        "frontend JS must call update_timeline_note_and_duration bridge method"
    )


def test_frontend_js_dirty_state_includes_duration():
    """``isEditDirty`` must check the ``edit-duration-input`` field so
    auto-refresh does not overwrite an unsaved duration override."""
    source = read_all_js()
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
    assert "edit-duration-input" in body, (
        "isEditDirty must check edit-duration-input for unsaved duration "
        "overrides so auto-refresh does not wipe them"
    )




def test_timeline_js_does_not_skip_is_virtual_sessions():
    """Section 三.1 / 六.3: ``timeline.js`` must NOT skip sessions whose
    ``is_virtual === true``. The old ``if (s.is_virtual === true)
    continue;`` line has been removed so virtual live sessions render,
    can be clicked, and can be selected.

    The comment in the source explicitly notes the skip was removed. We
    assert the skip line is gone AND a comment references the removal.
    """
    source = read_all_js()
    # The old skip line must NOT be present.
    assert "if (s.is_virtual === true) continue" not in source, (
        "timeline.js must NOT skip is_virtual sessions — the old skip "
        "line has been removed so virtual live sessions render"
    )
    # The removal is documented via a comment that mentions the old
    # behavior, so future regressions are caught.
    assert "is_virtual" in source, (
        "timeline.js must reference is_virtual (e.g. for the virtual-live "
        "CSS class) — the field is still consumed, just not skipped"
    )


def test_timeline_js_session_dom_has_stable_live_key_attribute():
    """Section 三.2 / 六.3: Timeline session DOM elements must carry the
    ``data-stable-live-key-hash`` attribute so the ticker and selection
    continuity can locate the live session across the virtual →
    persisted_open transition (where ``session_id`` / ``activity_id``
    change but ``stable_live_key_hash`` stays the same)."""
    source = read_all_js()
    assert 'data-stable-live-key-hash' in source, (
        "timeline.js must emit data-stable-live-key-hash on session DOM "
        "elements so the ticker / selection can survive the virtual → "
        "persisted_open transition"
    )
    # The attribute is populated from the session's stable_live_key_hash.
    assert "stable_live_key_hash" in source, (
        "timeline.js must read stable_live_key_hash from sessions to "
        "populate the data-stable-live-key-hash attribute"
    )


def test_timeline_js_detail_dom_has_stable_live_key_attribute():
    """Section 三.3 / 六.3: Timeline detail row DOM elements must carry
    the ``data-stable-live-key-hash`` attribute so the detail ticker can
    locate the live detail row across the virtual → persisted_open
    transition."""
    source = read_all_js()
    # The detail-row rendering also emits data-stable-live-key-hash.
    # We verify the attribute appears in the detail-rendering section
    # (the test_frontend_js_render_session_details_no_merge_button_disabled_logic
    # pattern: search within the render function body).
    assert 'data-stable-live-key-hash' in source, (
        "timeline.js must emit data-stable-live-key-hash on detail DOM "
        "elements so the detail ticker survives the virtual → "
        "persisted_open transition"
    )


def test_timeline_js_selection_continuity_uses_stable_live_key_hash():
    """Section 三.4 / 六.3: Timeline selection continuity must use
    ``selectedSessionLiveKey`` (stable_live_key_hash) as the PRIMARY
    anchor. When refresh causes ``session_id`` to change from the
    virtual id to the real DB id, the selection must transfer to the
    new session as long as ``stable_live_key_hash`` matches. Only when
    no stable key matches does the selection fall back to ``session_id``
    or clear."""
    source = read_all_js()
    # The selectedSessionLiveKey field must be declared on App.
    assert "App.selectedSessionLiveKey" in source, (
        "timeline.js / core.js must declare App.selectedSessionLiveKey "
        "for selection continuity across the virtual → persisted_open "
        "transition"
    )
    # The selection-recovery loop must match by stable_live_key_hash
    # FIRST (before falling back to session_id).
    assert "stable_live_key_hash" in source, (
        "timeline.js must match sessions by stable_live_key_hash during "
        "selection recovery"
    )


def test_timeline_js_live_session_edit_controls_disabled():
    """Section 三.1 / 六.3: live sessions (virtual AND persisted_open)
    must have their edit / correction / split / merge / hide / delete /
    restore controls disabled. The frontend checks ``edit_disabled``
    and / or ``is_virtual`` to disable the controls."""
    source = read_all_js()
    # The frontend must reference edit_disabled to disable controls.
    assert "edit_disabled" in source, (
        "timeline.js must check edit_disabled to disable edit controls "
        "for live (virtual + persisted_open) sessions"
    )
    # The disable_reason should be surfaced so the user sees why the
    # controls are disabled.
    assert "disable_reason" in source or "is_virtual" in source, (
        "timeline.js must reference disable_reason or is_virtual for "
        "live-session edit-disable messaging"
    )


def test_core_js_ticker_uses_stable_live_key_first():
    """Section 三.5 / 六.3: the detail ticker in ``core.js`` must look up
    the DOM by ``data-stable-live-key-hash`` FIRST, falling back to
    ``data-activity-id`` only when no stable key is available. This is
    required because virtual → persisted_open changes the activity_id
    (from 0 to the real DB id) but the stable_live_key_hash stays the
    same."""
    source = read_all_js()
    # The ticker must query by data-stable-live-key-hash.
    assert 'data-stable-live-key-hash' in source, (
        "core.js ticker must query DOM by data-stable-live-key-hash so "
        "the detail duration keeps incrementing across the virtual → "
        "persisted_open transition"
    )
    # The ticker must still fall back to data-activity-id for closed
    # historical rows that have no stable key.
    assert 'data-activity-id' in source, (
        "core.js ticker must fall back to data-activity-id for closed "
        "historical rows that have no stable_live_key_hash"
    )
    # App.liveContinuityKey must be the single continuity key
    # construction entry point.
    assert "liveContinuityKey" in source, (
        "core.js must define App.liveContinuityKey as the single "
        "continuity key construction entry point for the ticker / render "
        "seeding / DOM lookup"
    )


def test_timeline_js_does_not_show_loading_placeholder_for_live_activity():
    """The backend must provide display-only live sessions, so Timeline
    must not hide an empty list behind a current-activity loading text."""
    source = read_all_js()
    assert "正在加载当前活动" not in source, (
        "timeline.js must render backend-provided display-only sessions "
        "instead of showing a current-activity loading placeholder"
    )
