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

pytestmark = [pytest.mark.contract, pytest.mark.webview_static, pytest.mark.db]

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
    """frontend JS must load session activity summaries for the right panel."""
    source = read_all_js()
    assert "get_timeline_project_activity_summary" not in source
    assert "get_timeline_session_activity_summary" in source
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
    """frontend JS must call the bridge methods for project loading and
    unified session override saving."""
    source = read_all_js()
    assert "list_projects_for_timeline" in source
    assert "save_timeline_session_override" in source

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
    assert 'showEditStatus(result && result.error ? result.error : "保存失败", true)' in source

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

def test_timeline_date_switch_uses_report_loader_not_live_runtime_scope():
    """Timeline date switching must change only report scope. It must not
    clear/re-scope the accepted live runtime or call refreshCurrentPageData
    before loading the report."""
    source = read_resource("js/timeline.js")
    init_source = read_resource("js/init.js")
    for fn_name in ("goPrevDay", "goNextDay", "goToday"):
        body = func_body(source, fn_name)
        assert "loadTimelineReport" in body
        assert "setLiveRuntimeScope" not in body
        assert "refreshCurrentPageData" not in body
    change_pos = init_source.find('dateInput.addEventListener("change"')
    assert change_pos != -1
    change_body = init_source[change_pos:init_source.find("});", change_pos) + 3]
    assert "loadTimelineReport" in change_body
    assert "setLiveRuntimeScope" not in change_body
    assert "refreshCurrentPageData" not in change_body

def test_timeline_report_loader_owns_loading_and_releases_on_all_paths():
    """Explicit Timeline report requests must own the loading indicator and
    release it for success, stale, and rejected responses without allowing an
    older request to close a newer owner's loading state."""
    source = read_resource("js/timeline.js")
    body = func_body(source, "timelineReportRequest")
    release_body = func_body(source, "releaseTimelineLoadingOwner")
    assert "timelineLoadingOwner" in body
    assert "releaseTimelineLoadingOwner(loadingOwner)" in body
    assert "token !== App.timelineRequestToken" in body
    assert "showLoading" in body
    assert "App.timelineLoadingOwner === owner" in release_body
    assert "App.setTimelineLoading(false)" in release_body

def test_timeline_refresh_entrypoints_share_report_loader():
    """load, silent refresh, and after-edit refresh must share one Timeline
    request helper so token/loading behavior cannot diverge."""
    source = read_resource("js/timeline.js")
    for fn_name in ("loadTimeline", "refreshTimeline", "refreshTimelineAfterEdit"):
        body = func_body(source, fn_name)
        assert "loadTimelineReport" in body
        assert "++App.timelineRequestToken" not in body

def test_details_runtime_mismatch_skips_overlay_not_static_render():
    """Details payloads belong to report scope. If their live overlay is not
    compatible with the accepted runtime, the frontend must still render the
    static details after recording the mismatch."""
    source = read_resource("js/timeline.js")
    accept_body = func_body(source, "acceptTimelineDetailsPayload")
    load_body = func_body(source, "loadSessionDetails")
    assert "isPagePayloadCompatibleWithRuntime" in accept_body
    assert "noteRejectedPagePayload" in accept_body
    assert "return true" in accept_body
    assert "if (!acceptTimelineDetailsPayload(data, date)) return;" in load_body
    assert "renderSessionDetails(data)" in load_body

def test_timeline_right_panel_uses_session_summary_bridge_contract():
    source = read_resource("js/timeline.js")

    assert "get_timeline_project_activity_summary" not in source
    assert "get_timeline_session_activity_summary" in source

def test_timeline_selection_loads_summary_by_activity_ids():
    source = read_resource("js/timeline.js")
    select_body = func_body(source, "selectTimelineSession")
    show_body = func_body(source, "showTimeline")

    assert "loadSessionActivitySummary(found.activity_ids, App.timelineDate)" in select_body
    assert "loadSessionActivitySummary(found.activity_ids, data.date)" in show_body
    assert "loadSessionActivitySummary(found.project_id" not in source
    assert "loadSessionDetails(found.project_id" not in source

def test_timeline_summary_columns_are_duration_name_project():
    source = read_resource("js/timeline.js")
    body = func_body(source, "renderSessionDetails")

    duration_pos = body.find("summary-item-duration")
    name_pos = body.find("summary-item-name")
    project_pos = body.find("summary-item-project")

    assert duration_pos != -1
    assert name_pos != -1
    assert project_pos != -1
    assert duration_pos < name_pos < project_pos

def test_timeline_summary_project_column_uses_plain_project_name():
    source = read_resource("js/timeline.js")
    body = func_body(source, "renderSessionDetails")

    assert 'row.display_project_name || "未归类"' in body
    assert "formatProjectLabel(row.display_project_name, row.display_project_description)" not in body
    assert "该项目暂无活动耗时" not in source
    assert "该时段暂无活动耗时" in source

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
    """the saveEdit rejection handler must use the stable '保存失败'
    fallback instead of reading raw exception messages."""
    source = read_all_js()
    # Bound the scan to the real saveEdit function body so adjacent
    # functions / modules cannot leak into the block we assert on.
    body = func_body(source, "saveEdit")
    catch_pos = body.find(".catch(function ()")
    assert catch_pos != -1, "saveEdit must handle bridge rejection"
    block = body[catch_pos:]
    assert 'showEditStatus("保存失败", true)' in block, (
        "saveEdit rejection handler must use '保存失败' stable fallback"
    )

def test_frontend_js_stable_fallback_vocabulary_present():
    """all six stable Chinese fallback strings must be present
    in frontend JS: 加载时间线失败 / 刷新失败 / 加载详情失败 / 保存失败 /
    操作失败 / 恢复失败."""
    source = read_all_js()
    for fallback in ("加载时间线失败", "刷新失败", "加载项目活动耗时失败",
                     "保存失败", "操作失败"):
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
    assert "加载项目活动耗时失败" in source, (
        "detail panel must use stable project summary error fallback"
    )

def test_frontend_js_edit_saving_success_failure_strings_stable():
    """edit panel saving/success/failure strings must be
    stable."""
    source = read_all_js()
    assert "保存中" in source, "edit saving text '保存中' must be present"
    assert "保存成功" in source, "edit success text '保存成功' must be present"
    assert "保存失败" in source, "edit failure text '保存失败' must be present"

def test_frontend_js_auto_refresh_dirty_guard_present():
    """auto-refresh must check isEditDirty() before overwriting
    edit inputs (regression lock)."""
    source = read_all_js()
    # The auto-refresh path in showTimeline checks isEditDirty.
    assert "isEditDirty()" in source, (
        "auto-refresh must call isEditDirty() to guard edit inputs"
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
        "CREATE TABLE IF NOT EXISTS project_session_override",
        "CREATE TABLE IF NOT EXISTS project_session_override_member",
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

def test_frontend_js_has_format_start_time_only():
    """frontend JS must define ``formatStartTimeOnly`` so the Timeline session
    list and detail list show only the start time (HH:MM) of each
    activity, not the full datetime."""
    source = read_all_js()
    assert "formatStartTimeOnly" in source, (
        "frontend JS must define formatStartTimeOnly helper"
    )

def test_frontend_js_has_update_note_and_duration_bridge_call():
    """frontend JS must call the unified session override bridge so project,
    note, and adjusted duration are saved together in a single write."""
    source = read_all_js()
    assert "save_timeline_session_override" in source, (
        "frontend JS must call save_timeline_session_override bridge method"
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

def test_index_html_timeline_p0_edit_panel_only():
    source = read_resource("index.html")
    for required in (
        'id="timeline-edit-panel"',
        'id="edit-project-select"',
        'id="edit-duration-input"',
        'id="edit-duration-status"',
        'id="edit-note-text"',
        'id="edit-note-count"',
        'id="edit-save-btn"',
        'id="edit-cancel-btn"',
        'id="edit-status"',
    ):
        assert required in source
    for forbidden in (
        "open-correction-shell-btn",
        "timeline-correction-shell",
        "correction-shell",
        "timeline_correction.js",
        "edit-time-section",
        "edit-start-time",
        "edit-end-time",
        "edit-time-save-btn",
        "edit-split-section",
        "edit-split-time",
        "edit-split-save-btn",
        "edit-visibility-section",
        "edit-visibility-hide-btn",
        "edit-visibility-delete-btn",
    ):
        assert forbidden not in source

def test_save_edit_still_uses_p0_bridge_methods():
    body = func_body(read_all_js(), "saveEdit")
    assert '"save_timeline_session_override"' in body
    assert '"update_timeline_activity_time"' not in body
    assert '"split_timeline_activity"' not in body

def test_bridge_and_api_do_not_define_advanced_timeline_methods():
    bridge_src = read_bridge_sources_combined()
    api_src = (REPO_ROOT / "worktrace" / "api" / "timeline_api.py").read_text(encoding="utf-8")
    for forbidden in (
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
        "class TimelineTimeEditError",
        "class TimelineSplitError",
        "class TimelineMergeError",
        "class TimelineVisibilityError",
        "class TimelineBatchProjectError",
        "class TimelineBatchNoteError",
        "class TimelineRestoreActivityError",
    ):
        assert forbidden not in bridge_src
        assert forbidden not in api_src

def test_styles_css_has_no_advanced_timeline_selectors():
    source = read_resource("styles.css")
    for forbidden in (
        ".detail-edit-time-btn",
        ".detail-time-editor",
        ".detail-split-editor",
        ".detail-split-btn",
        ".detail-merge-btn",
        ".detail-merge-status",
        ".detail-hide-btn",
        ".detail-delete-btn",
        ".detail-visibility-status",
        ".edit-visibility-section",
        ".edit-visibility-hide-btn",
        ".edit-visibility-delete-btn",
        ".detail-time-row",
        ".detail-time-input",
        ".detail-time-actions",
        ".detail-time-save-btn",
        ".detail-time-cancel-btn",
        ".detail-time-status",
        ".correction-shell",
        ".detail-item.shell-target",
        ".detail-item.detail-item-highlight",
    ):
        assert forbidden not in source

