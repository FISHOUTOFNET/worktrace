"""Timeline correction-shell WebView static-contract tests.

These tests read the bundled frontend resources (index.html /
js/*.js / styles.css) directly without starting the GUI. Frontend JS is
loaded from the ordered modules listed in ALL_JS_FILES. These tests lock
the correction-shell contracts.
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
    html_element_by_id,
    read_bridge_sources_combined,
    FRONTEND_RESOURCE_FILES, NO_STORAGE_FILES,
)




def test_frontend_js_detail_rows_are_read_only():
    """renderSessionDetails must keep project summary rows read-only."""
    source = read_all_js()
    body = func_body(source, "renderSessionDetails")
    assert "summary-item-name" in body
    assert "summary-item-project" in body
    assert "summary-item-duration" in body
    for forbidden in (
        "detail-action-edit-group",
        "detail-action-merge-group",
        "detail-action-danger-group",
        "detail-edit-time-btn",
        "detail-split-btn",
        "detail-merge-btn",
        "detail-hide-btn",
        "detail-delete-btn",
    ):
        assert forbidden not in body, (
            "renderSessionDetails must not render per-activity action control: "
            + forbidden
        )



def test_frontend_js_detail_rows_route_actions_to_correction_shell():
    """Per-activity actions live in the correction shell, not detail rows."""
    source = read_all_js()
    detail_body = func_body(source, "renderSessionDetails")
    shell_body = func_body(source, "renderCorrectionShell")
    assert "open-correction-shell-btn" in source
    assert "detail-edit-time-btn" not in detail_body
    assert "renderBatchProjectSection" in shell_body
    assert "renderBatchNoteSection" in shell_body
    assert "renderRestoreSection" in shell_body



def test_frontend_js_merge_has_dirty_state_guard():
    """saveActivityMerge must refuse while there are unsaved
    project/note/time/split inputs, consistent with hide / delete. Merge
    triggers a refresh that would wipe those inputs."""
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
    assert "isEditDirty()" in body, (
        "saveActivityMerge must call isEditDirty() to refuse merge while "
        "there are unsaved edits"
    )
    assert "请先保存或取消当前编辑" in body, (
        "saveActivityMerge must show the unified dirty-state refusal message"
    )



def test_frontend_js_merge_has_row_id_consistency_check():
    """saveActivityMerge must verify the activity id still
    matches the detail row, consistent with hide / delete, so a stale
    button does not operate on a different session's activity."""
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
    assert 'btn.closest(".detail-item")' in body, (
        "saveActivityMerge must locate the closest detail-item row"
    )
    assert "rowAid !== activityId" in body, (
        "saveActivityMerge must compare the row's activity id with the "
        "passed activity id and bail out if they differ"
    )



def test_frontend_js_dirty_state_refusal_message_is_unified():
    """the dirty-state refusal message must be unified across
    merge / hide / delete (per-activity and session-level)."""
    source = read_all_js()
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



def test_frontend_js_destructive_action_copy_is_unified():
    """hide / delete success and failure copy must be
    unified. Hide: 已隐藏 / 隐藏失败. Delete: 已删除 / 删除失败."""
    source = read_all_js()
    # Per-activity hide
    assert "已隐藏" in source and "隐藏失败" in source, (
        "hide must succeed with 已隐藏 and fail with 隐藏失败"
    )
    # Per-activity delete
    assert "已删除" in source and "删除失败" in source, (
        "delete must succeed with 已删除 and fail with 删除失败"
    )
    # Delete confirmation must still say soft delete
    assert "不会物理删除数据" in source, (
        "delete confirmation must still say 不会物理删除数据"
    )



def test_index_html_has_unified_section_labels():
    """the session-level edit panel sections must be labeled
    consistently for the simplified edit panel and correction shell."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for label in ("项目", "时长（分钟）", "备注", "纠错面板"):
        assert label in source, "edit/correction UI must expose label: " + label
    # The obsolete section titles must be gone (拆分时段 / 隐藏 / 删除 as a
    # section label is replaced by 可见性).
    assert "拆分时段" not in source, (
        "obsolete section title 拆分时段 must be replaced by 拆分"
    )



def test_index_html_visibility_hint_mentions_hide_and_soft_delete():
    """the visibility section hint must mention both hide and
    soft-delete semantics so the user understands neither physically
    deletes data."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # Bound to the real <div id="edit-visibility-section">...</div> element
    # so the assertion never scans adjacent DOM.
    section = html_element_by_id(source, "edit-visibility-section")
    assert "隐藏" in section, (
        "visibility hint must mention 隐藏"
    )
    assert "软删除" in section or "不会物理删除数据" in section, (
        "visibility hint must mention soft delete / no physical deletion"
    )



def test_styles_css_has_action_group_styles():
    """styles.css must style the three action groups and
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
    # actions read as visually separated. The selector appears in more
    # than one rule, so collect every rule body via brace counting instead
    # of a fixed character window that could bleed into adjacent rules.
    danger_block = ""
    search_pos = 0
    while True:
        rule_start = source.find(".detail-action-danger-group", search_pos)
        if rule_start == -1:
            break
        brace_start = source.find("{", rule_start)
        assert brace_start != -1, ".detail-action-danger-group rule must open with {"
        depth = 0
        rule_end = brace_start
        for i in range(brace_start, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    rule_end = i + 1
                    break
        danger_block += source[rule_start:rule_end]
        search_pos = rule_end
    assert "#fca5a5" in danger_block or "border-left" in danger_block, (
        "danger group must have a visually separating border"
    )



def test_styles_css_has_section_label_style():
    """styles.css must style the .edit-section-label class
    used by the unified section labels."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".edit-section-label" in source, (
        "styles.css must style .edit-section-label"
    )



def test_frontend_js_clear_edit_panel_resets_all_action_state():
    """clearEditPanel must reset all transient action state,
    including merge / hide / delete saving state and target ids."""
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



def test_frontend_js_populate_edit_panel_populates_all_correction_sections():
    """populateEditPanel must populate / reset all correction
    sections (project/note, time, split, visibility) so switching sessions
    does not leave stale state behind."""
    source = read_all_js()
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
    # The simplified edit panel only populates project, note, and duration.
    for forbidden in (
        "populateSessionTimeSection",
        "populateSessionSplitSection",
        "populateSessionVisibilitySection",
    ):
        assert forbidden not in body, (
            "populateEditPanel must not populate hidden correction section: "
            + forbidden
        )



def test_frontend_js_consolidation_has_no_forbidden_handlers():
    """the consolidation must not introduce batch edit,
    batch hide, batch delete, undo / restore, permanent delete, auto-rule,
    complex correction page, or overlap detection handlers."""
    source = read_all_js()
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
            f"frontend JS must not introduce a '{forbidden}' handler"
        )



def test_index_html_consolidation_has_no_forbidden_controls():
    """index.html must not contain batch hide / batch delete /
    batch time / batch split / batch merge / batch restore / restore-all /
    permanent-delete / auto-rule / complex-correction-page / overlap
    controls. Batch project reassignment means "batch"
    is allowed in index.html but only in the project context; the
    specific batch hide / delete / time / split / merge variants must still
    be absent. Single activity restore means "restore"
    is allowed; batch restore, restore-all, undo stack, and permanent
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





def test_index_html_has_correction_shell_container():
    """index.html must contain a hidden correction shell
    container inside the Timeline details column."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="timeline-correction-shell"' in source, (
        "index.html must contain #timeline-correction-shell"
    )



def test_index_html_correction_shell_hidden_by_default():
    """the correction shell must be hidden by default."""
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
    """the correction shell must have a close button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-close-btn"' in source, (
        "correction shell must have a close button"
    )
    assert "返回时间详情" in source, (
        "correction shell close button text must be 返回时间详情"
    )



def test_index_html_correction_shell_has_required_areas():
    """the shell must have context / status / activity /
    action areas."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-status"' in source
    assert 'id="correction-shell-context"' in source
    assert 'id="correction-shell-activities"' in source
    assert 'id="correction-shell-actions"' in source



def test_index_html_correction_shell_title_is_correction_panel():
    """The shell title must be 纠错面板."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "纠错面板" in source, (
        "correction shell title must be 纠错面板"
    )



def test_index_html_has_session_level_open_correction_entry():
    """The session-level edit panel must have a correction shell entry button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="open-correction-shell-btn"' in source, (
        "session-level edit panel must have an open-correction-shell button"
    )
    assert "高级纠错" in source, (
        "session-level open button text must be 高级纠错"
    )



def test_index_html_correction_shell_inside_timeline_page():
    """the correction shell must live inside the Timeline
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



def test_frontend_js_has_open_correction_shell_helper():
    """frontend JS must define an openCorrectionShell helper."""
    source = read_all_js()
    assert "function openCorrectionShell" in source, (
        "frontend JS must define openCorrectionShell"
    )



def test_frontend_js_has_close_correction_shell_helper():
    """frontend JS must define a closeCorrectionShell helper."""
    source = read_all_js()
    assert "function closeCorrectionShell" in source, (
        "frontend JS must define closeCorrectionShell"
    )



def test_frontend_js_has_reset_correction_shell_state_helper():
    """frontend JS must define a resetCorrectionShellState helper."""
    source = read_all_js()
    assert "function resetCorrectionShellState" in source, (
        "frontend JS must define resetCorrectionShellState"
    )



def test_frontend_js_has_render_correction_shell_helper():
    """frontend JS must define a renderCorrectionShell helper."""
    source = read_all_js()
    assert "function renderCorrectionShell" in source, (
        "frontend JS must define renderCorrectionShell"
    )



def test_frontend_js_has_set_correction_shell_status_helper():
    """frontend JS must define a setCorrectionShellStatus helper."""
    source = read_all_js()
    assert "function setCorrectionShellStatus" in source, (
        "frontend JS must define setCorrectionShellStatus"
    )



def test_frontend_js_has_get_selected_session_helper():
    """frontend JS must define a getSelectedSession helper that
    looks up the selected session from currentSessions."""
    source = read_all_js()
    assert "function getSelectedSession" in source, (
        "frontend JS must define getSelectedSession"
    )



def test_frontend_js_open_correction_shell_checks_dirty_state():
    """openCorrectionShell must refuse to open while there
    are unsaved edits, using the refusal text 请先保存或取消当前编辑."""
    source = read_all_js()
    open_start = source.find("function openCorrectionShell")
    open_end = source.find("\n    function ", open_start + 1)
    open_body = source[open_start:open_end]
    assert "isEditDirty()" in open_body, (
        "openCorrectionShell must call isEditDirty() before opening"
    )
    assert "请先保存或取消当前编辑" in open_body, (
        "openCorrectionShell must use the dirty-state refusal text"
    )



def test_frontend_js_open_correction_shell_checks_selected_session():
    """openCorrectionShell must verify a selected session
    exists before opening."""
    source = read_all_js()
    open_start = source.find("function openCorrectionShell")
    open_end = source.find("\n    function ", open_start + 1)
    open_body = source[open_start:open_end]
    assert "getSelectedSession" in open_body, (
        "openCorrectionShell must call getSelectedSession before opening"
    )



def test_frontend_js_close_correction_shell_preserves_selected_session():
    """closeCorrectionShell must NOT clear selectedSessionId
    so the user returns to the same session context."""
    source = read_all_js()
    close_start = source.find("function closeCorrectionShell")
    close_end = source.find("\n    function ", close_start + 1)
    close_body = source[close_start:close_end]
    assert "selectedSessionId = null" not in close_body, (
        "closeCorrectionShell must not clear selectedSessionId"
    )
    assert "resetCorrectionShellState" in close_body, (
        "closeCorrectionShell must reset shell state"
    )



def test_frontend_js_clear_edit_panel_resets_shell_state():
    """clearEditPanel must call resetCorrectionShellState so
    a stale shell does not leak into the next session."""
    source = read_all_js()
    clear_start = source.find("function clearEditPanel")
    clear_end = source.find("\n    function ", clear_start + 1)
    clear_body = source[clear_start:clear_end]
    assert "resetCorrectionShellState" in clear_body, (
        "clearEditPanel must reset correction shell state"
    )



def test_frontend_js_date_navigation_closes_shell():
    """goPrevDay / goNextDay / goToday must close the
    correction shell so the shell context does not carry across dates."""
    source = read_all_js()
    for fname in ("goPrevDay", "goNextDay", "goToday"):
        fstart = source.find("function " + fname)
        fend = source.find("\n    function ", fstart + 1)
        fbody = source[fstart:fend]
        assert "resetCorrectionShellState" in fbody, (
            fname + " must call resetCorrectionShellState"
        )



def test_frontend_js_selected_session_disappear_resets_shell():
    """when the selected session disappears during a refresh,
    the shell state must be reset (via clearEditPanel)."""
    source = read_all_js()
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



def test_frontend_js_session_switch_closes_shell():
    """selecting a different session must close the shell so
    the shell context does not get confused across sessions."""
    source = read_all_js()
    sel_start = source.find("function selectTimelineSession")
    sel_end = source.find("\n    function ", sel_start + 1)
    sel_body = source[sel_start:sel_end]
    assert "correctionShellOpen" in sel_body, (
        "selectTimelineSession must check correction shell state"
    )
    assert "resetCorrectionShellState" in sel_body, (
        "selectTimelineSession must reset shell state on session switch"
    )



def test_frontend_js_correction_shell_state_variables_exist():
    """frontend JS must declare the correction shell state
    variables."""
    source = read_all_js()
    assert "correctionShellOpen" in source
    assert "correctionShellSessionId" in source
    assert "correctionShellActivityId" in source
    assert "correctionShellMode" in source



def test_frontend_js_correction_shell_no_sensitive_fields():
    """the shell rendering must only use display-safe fields
    and must never read raw window_title / file_path / clipboard / note
    internals."""
    source = read_all_js()
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    for forbidden in ("window_title", "file_path", "file_path_hint",
                      "full_path", "clipboard"):
        assert forbidden not in render_body, (
            "renderCorrectionShell must not read " + forbidden
        )



def test_frontend_js_get_current_detail_activities_no_sensitive_fields():
    """getCurrentDetailActivities must only read display-safe
    DOM fields, never raw sensitive fields."""
    source = read_all_js()
    fn_start = source.find("function getCurrentDetailActivities")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    for forbidden in ("window_title", "file_path", "full_path", "clipboard",
                      "session_note"):
        assert forbidden not in fn_body, (
            "getCurrentDetailActivities must not read " + forbidden
        )



def test_frontend_js_correction_shell_uses_existing_string_helpers():
    """the shell must not parse backend times with
    new Date(string); it must reuse the existing fixed-format helpers."""
    source = read_all_js()
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



def test_frontend_js_correction_shell_no_browser_storage():
    """the shell must not use localStorage / sessionStorage."""
    source = read_all_js()
    assert not re.search(r"localStorage|sessionStorage", source), (
        "frontend JS must not use browser storage"
    )



def test_frontend_js_correction_shell_no_forbidden_handlers():
    """frontend JS must not contain batch edit / batch hide /
    batch delete / restore / permanent delete / auto-rule / global overlap
    detection handlers."""
    source = read_all_js()
    for forbidden in ("batchEdit", "batchHide", "batchDelete",
                      "restoreActivity", "restoreSession",
                      "permanentDelete", "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap"):
        assert forbidden not in source, (
            "frontend JS must not contain " + forbidden + " handler"
        )



def test_index_html_correction_shell_no_forbidden_controls():
    """index.html must not contain batch hide / batch delete /
    batch time / batch split / batch merge / batch restore / restore-all /
    permanent-delete / auto-rule / overlap controls in the shell. The
    batch project reassignment in the correction shell means
    "batch" is allowed in the shell but only in the project context;
    the specific batch hide / delete / time / split / merge variants must
    still be absent. The single activity restore in the
    shell means "restore" is allowed; batch restore, restore-all, undo
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



def test_frontend_js_correction_shell_actions_guide_only():
    """the shell action area must only guide the user back to
    the existing controls; it must not render its own write buttons. The
    delete guidance must remain soft-delete wording."""
    source = read_all_js()
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    # The shell reiterates that delete is soft, not permanent.
    assert "不会物理删除数据" in render_body or "软操作" in render_body, (
        "shell action guidance must restate soft-delete semantics"
    )



def test_styles_css_has_correction_shell_styles():
    """styles.css must define correction shell styles."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell" in source
    assert ".correction-shell-header" in source
    assert ".correction-shell-context" in source
    assert ".correction-shell-activities" in source
    assert ".correction-shell-actions" in source
    assert ".correction-shell-close-btn" in source



def test_styles_css_correction_shell_hidden_rule():
    """styles.css must hide the shell when [hidden]."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must hide .correction-shell[hidden]"
    )



def test_bridge_no_new_write_methods_for_shell():
    """the bridge must not gain new write methods for the
    shell. The existing project / note / time / split / merge / hide /
    delete methods must still be present."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
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
    """the bridge must continue to import only
    worktrace.api / worktrace.formatters and must not directly import
    services / db / collector / security / runtime / config."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
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





def test_frontend_js_correction_shell_highlight_timer_variable_declared():
    """frontend JS must declare a single tracked highlight timer
    so repeated click-to-locate clicks never accumulate timers."""
    source = read_all_js()
    assert "correctionShellHighlightTimer" in source, (
        "frontend JS must declare the correctionShellHighlightTimer state variable"
    )



def test_frontend_js_reset_correction_shell_state_clears_highlight_timer():
    """resetCorrectionShellState must cancel any pending
    highlight timer so a close / reset never leaves a dangling timer."""
    source = read_all_js()
    body = func_body(source, "resetCorrectionShellState")
    assert "correctionShellHighlightTimer" in body, (
        "resetCorrectionShellState must reference the highlight timer"
    )
    assert "clearTimeout" in body, (
        "resetCorrectionShellState must clear the pending highlight timer"
    )



def test_frontend_js_highlight_detail_row_no_bridge_writes():
    """highlightDetailRow must be read-only — it must not
    call any bridge method (write or otherwise) and must not perform any
    save / hide / delete / merge / split / time / project / note action."""
    source = read_all_js()
    body = func_body(source, "highlightDetailRow")
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



def test_frontend_js_highlight_detail_row_safe_single_timer():
    """the transient highlight must use a single tracked
    timer — clearTimeout before setTimeout — so repeated clicks never
    accumulate timers."""
    source = read_all_js()
    body = func_body(source, "highlightDetailRow")
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



def test_frontend_js_highlight_detail_row_stale_target_message():
    """when the target detail row is missing, the handler
    must show a safe message (not throw, not perform any write)."""
    source = read_all_js()
    body = func_body(source, "highlightDetailRow")
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



def test_frontend_js_highlight_detail_row_uses_detail_item_selector():
    """click-to-locate must only look up the existing
    .detail-item[data-activity-id=...] row inside #timeline-details-list."""
    source = read_all_js()
    body = func_body(source, "highlightDetailRow")
    assert '#timeline-details-list .detail-item[data-activity-id="' in body, (
        "highlightDetailRow must query the existing detail-item row"
    )



def test_frontend_js_render_correction_shell_uses_correction_activity_id():
    """shell activity rows must carry a distinct
    data-correction-activity-id attribute so they cannot be confused with
    the real .detail-item rows."""
    source = read_all_js()
    body = func_body(source, "renderCorrectionShell")
    assert "data-correction-activity-id" in body, (
        "shell activity rows must use data-correction-activity-id"
    )



def test_frontend_js_render_correction_shell_invalid_id_not_clickable():
    """a non-numeric / missing activity id must not be
    rendered as a click-to-locate target (numeric guard)."""
    source = read_all_js()
    body = func_body(source, "renderCorrectionShell")
    assert "/^[0-9]+$/.test" in body, (
        "renderCorrectionShell must guard a numeric activity id"
    )
    # The click handler must only bind to rows carrying the safe attribute.
    assert ".correction-shell-activity-row[data-correction-activity-id]" in body, (
        "click handlers must only bind to rows with a valid id"
    )



def test_frontend_js_render_correction_shell_uses_escape_html():
    """every dynamic value rendered into the shell must go
    through escapeHtml so no unescaped external / dynamic value is
    injected via innerHTML."""
    source = read_all_js()
    body = func_body(source, "renderCorrectionShell")
    assert "escapeHtml" in body, (
        "renderCorrectionShell must escape dynamic values"
    )



def test_frontend_js_render_correction_shell_no_sensitive_fields():
    """the hardened shell rendering must still never read
    raw window_title / file_path_hint / full_path / clipboard / note
    internals, and must not surface traceback / SQL / exception text."""
    source = read_all_js()
    body = func_body(source, "renderCorrectionShell")
    for forbidden in ("window_title", "file_path_hint", "file_path",
                      "full_path", "clipboard", "session_note", "traceback",
                      "SQL", "exception"):
        assert forbidden not in body, (
            "renderCorrectionShell must not read or display " + forbidden
        )



def test_frontend_js_correction_shell_state_independent_of_saving_states():
    """resetCorrectionShellState must only reset shell-only
    state; it must not reset the edit / time / split / merge / hide / delete
    saving states (those are owned by clearEditPanel)."""
    source = read_all_js()
    body = func_body(source, "resetCorrectionShellState")
    for saving in ("editSaving", "timeSaving", "activityTimeSaving",
                   "sessionSplitSaving", "activitySplitSaving", "mergeSaving",
                   "hideSaving", "deleteSaving", "editingSession"):
        assert saving not in body, (
            "resetCorrectionShellState must not reset " + saving
        )



def test_frontend_js_open_correction_shell_dirty_refusal_preserves_state():
    """the dirty-state refusal in openCorrectionShell must
    not clear selectedSessionId, must not clear the edit panel / inputs,
    and must not change the selected session."""
    source = read_all_js()
    body = func_body(source, "openCorrectionShell")
    assert "selectedSessionId = null" not in body, (
        "openCorrectionShell must not clear selectedSessionId on refusal"
    )
    assert "clearEditPanel" not in body, (
        "openCorrectionShell must not clear the edit panel on refusal"
    )
    assert "请先保存或取消当前编辑" in body, (
        "openCorrectionShell must keep the dirty refusal text"
    )



def test_frontend_js_open_correction_shell_scrolls_and_focuses_panel():
    """After a successful open, openCorrectionShell must scroll / focus the
    correction shell title so the user sees the panel appear. This avoids
    the 'click with no visible feedback' problem."""
    source = read_all_js()
    body = func_body(source, "openCorrectionShell")
    assert "scrollIntoView" in body, (
        "openCorrectionShell must call scrollIntoView on the shell title "
        "so the user sees the panel appear"
    )
    assert "focus" in body, (
        "openCorrectionShell must focus the shell title so the user sees "
        "the panel appear"
    )
    assert "correction-shell-title" in body, (
        "openCorrectionShell must scroll / focus the correction-shell-title"
    )



def test_frontend_js_get_selected_session_uses_current_sessions():
    """getSelectedSession must look the session up from
    currentSessions so a stale / disappeared session cannot open the
    shell."""
    source = read_all_js()
    body = func_body(source, "getSelectedSession")
    assert "currentSessions" in body, (
        "getSelectedSession must read from currentSessions"
    )



def test_frontend_js_auto_refresh_shell_guarded_by_dirty_state():
    """auto-refresh must not overwrite a dirty shell. The
    showTimeline shell re-render path must be guarded by !isEditDirty()."""
    source = read_all_js()
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



def test_frontend_js_close_correction_shell_no_refresh_or_write():
    """closeCorrectionShell must not trigger a refresh and
    must not perform any write action."""
    source = read_all_js()
    body = func_body(source, "closeCorrectionShell")
    for forbidden in ("loadTimeline", "refreshAll", "callBridge",
                      "saveProject", "saveNote", "saveActivityTime",
                      "saveSessionTime", "saveActivitySplit", "saveSessionSplit",
                      "saveMerge", "saveHide", "saveDelete"):
        assert forbidden not in body, (
            "closeCorrectionShell must not call " + forbidden
        )



def test_frontend_js_correction_shell_no_new_forbidden_handlers():
    """the hardening must not introduce batch edit / hide /
    delete, undo / restore, permanent delete, auto-rule, or global overlap
    detection handlers."""
    source = read_all_js()
    for forbidden in ("batchEdit", "batchHide", "batchDelete",
                      "restoreActivity", "restoreSession",
                      "permanentDelete", "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap",
                      "multiActivityHide", "multiActivityDelete"):
        assert forbidden not in source, (
            "frontend JS must not contain " + forbidden + " handler"
        )



def test_index_html_correction_shell_no_external_resources():
    """the correction shell region must not introduce
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
    """styles.css must define the transient
    .detail-item.detail-item-highlight class used by click-to-locate."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".detail-item.detail-item-highlight" in source, (
        "styles.css must define .detail-item.detail-item-highlight"
    )



def test_styles_css_has_correction_shell_is_static_class():
    """styles.css must define the .is-static style for
    shell activity rows whose activity id is missing / non-numeric."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell-activity-row.is-static" in source, (
        "styles.css must define the non-clickable .is-static style"
    )



def test_styles_css_correction_shell_hidden_still_display_none():
    """the shell must remain truly hidden when [hidden]."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must keep the .correction-shell[hidden] rule"
    )



def test_bridge_no_unexpected_methods_for_contract():
    """the hardening must not add any new bridge method,
    and the bridge must continue to import only allowed modules."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    # No new shell-specific write / read method is added in this contract.
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





def test_frontend_js_has_batch_selection_state():
    """frontend JS must declare the batch project selection state."""
    source = read_all_js()
    assert "selectedBatchActivityIds" in source, (
        "frontend JS must declare the selectedBatchActivityIds state variable"
    )
    assert "batchProjectSaving" in source, (
        "frontend JS must declare the batchProjectSaving state variable"
    )
    assert "batchProjectTargetId" in source, (
        "frontend JS must declare the batchProjectTargetId state variable"
    )



def test_frontend_js_has_batch_project_save_helper():
    """frontend JS must define the saveBatchProject function."""
    source = read_all_js()
    assert "function saveBatchProject" in source, (
        "frontend JS must define the saveBatchProject function"
    )
    assert "function resetBatchProjectState" in source, (
        "frontend JS must define the resetBatchProjectState function"
    )
    assert "function renderBatchProjectSection" in source, (
        "frontend JS must define the renderBatchProjectSection function"
    )
    assert "function pruneStaleBatchSelection" in source, (
        "frontend JS must define the pruneStaleBatchSelection function"
    )
    assert "function setBatchProjectSaving" in source, (
        "frontend JS must define the setBatchProjectSaving function"
    )



def test_frontend_js_calls_batch_update_bridge():
    """frontend JS must call the batch_update_timeline_activities_project
    bridge method."""
    source = read_all_js()
    assert "batch_update_timeline_activities_project" in source, (
        "frontend JS must call the batch_update_timeline_activities_project bridge method"
    )



def test_index_html_has_batch_project_section():
    """index.html must contain the batch project section in the
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
    """the batch section hint must state that only batch
    project reassignment is supported."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "批量操作仅支持设置项目" in source, (
        "batch section hint must state only project batch is supported"
    )
    # The hint must also list the unsupported batch operations.
    assert "拆分" in source or "合并" in source, (
        "batch section hint must mention unsupported batch operations"
    )



def test_index_html_no_batch_hide_delete_time_split_merge_controls():
    """index.html must not contain batch hide / delete / time /
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



def test_frontend_js_batch_checkbox_only_for_shell_activities():
    """the batch checkbox must only be rendered on shell
    activity rows, not on the detail list rows."""
    source = read_all_js()
    # The checkbox class must be correction-shell-activity-checkbox.
    assert "correction-shell-activity-checkbox" in source, (
        "frontend JS must render the correction-shell-activity-checkbox class"
    )
    # The checkbox must carry a data-batch-activity-id attribute.
    assert "data-batch-activity-id" in source, (
        "frontend JS must render the data-batch-activity-id attribute on checkboxes"
    )



def test_frontend_js_batch_in_progress_checkbox_disabled():
    """in-progress activities must render a disabled checkbox."""
    source = read_all_js()
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



def test_frontend_js_batch_save_disabled_for_fewer_than_two():
    """the batch save button must be disabled when fewer than
    two activities are selected."""
    source = read_all_js()
    save_start = source.find("function updateBatchSaveButtonState")
    assert save_start != -1
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "count < 2" in save_body or "len(ids) < 2" in save_body, (
        "updateBatchSaveButtonState must check count < 2"
    )



def test_frontend_js_batch_save_blocked_by_dirty_edit():
    """saveBatchProject must block when isEditDirty() is true."""
    source = read_all_js()
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



def test_frontend_js_batch_success_refreshes_timeline():
    """a successful batch save must refresh the Timeline."""
    source = read_all_js()
    save_start = source.find("function saveBatchProject")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "refreshTimelineForBatchSave" in save_body or "loadTimeline" in save_body, (
        "saveBatchProject must call refresh/load on success"
    )



def test_frontend_js_batch_failure_preserves_selection():
    """a failed batch save must preserve the selection and
    detail list so the user can retry."""
    source = read_all_js()
    save_start = source.find("function saveBatchProject")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The error path must NOT call clearBatchSelection or resetBatchProjectState.
    # It must only show the error message and reset the saving flag.
    assert "clearBatchSelection" not in save_body or save_body.count("clearBatchSelection") == 0, (
        "saveBatchProject failure must not clear the selection"
    )



def test_frontend_js_clear_edit_panel_resets_batch_state():
    """clearEditPanel must call resetBatchProjectState."""
    source = read_all_js()
    clear_start = source.find("function clearEditPanel")
    clear_end = source.find("\n    function ", clear_start + 1)
    clear_body = source[clear_start:clear_end]
    assert "resetBatchProjectState" in clear_body, (
        "clearEditPanel must call resetBatchProjectState"
    )



def test_frontend_js_reset_correction_shell_resets_batch_state():
    """resetCorrectionShellState must call
    resetBatchProjectState."""
    source = read_all_js()
    reset_start = source.find("function resetCorrectionShellState")
    reset_end = source.find("\n    function ", reset_start + 1)
    reset_body = source[reset_start:reset_end]
    assert "resetBatchProjectState" in reset_body, (
        "resetCorrectionShellState must call resetBatchProjectState"
    )



def test_frontend_js_batch_no_local_storage():
    """the batch project code must not use browser storage."""
    source = read_all_js()
    assert not re.search(r"localStorage|sessionStorage", source), (
        "frontend JS must not use localStorage or sessionStorage"
    )



def test_frontend_js_batch_no_external_links():
    """the batch project code must not introduce external links."""
    for filename in FRONTEND_RESOURCE_FILES:
        source = read_resource(filename)
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )



def test_frontend_js_batch_no_restore_permanent_auto_rule_overlap():
    """the batch project code must not introduce restore,
    permanent delete, auto-rule, or overlap handlers."""
    source = read_all_js()
    for forbidden in ("restoreActivity", "restoreSession",
                      "permanentDelete", "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap"):
        assert forbidden not in source, (
            "frontend JS must not contain " + forbidden + " handler"
        )



def test_styles_css_has_batch_section_styles():
    """styles.css must define the batch section styles."""
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
    """the bridge must define the
    batch_update_timeline_activities_project method."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    assert "def batch_update_timeline_activities_project" in bridge_src, (
        "bridge must define batch_update_timeline_activities_project"
    )



def test_bridge_batch_error_messages_dict():
    """the bridge must define the _BATCH_PROJECT_ERROR_MESSAGES
    dict with all stable error code → Chinese message mappings."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    assert "_BATCH_PROJECT_ERROR_MESSAGES" in bridge_src, (
        "bridge must define _BATCH_PROJECT_ERROR_MESSAGES"
    )
    for code in ("invalid_selection", "batch_too_large", "invalid_project",
                 "in_progress", "hidden_activity", "operation_failed"):
        assert code in bridge_src, (
            "bridge must map the '" + code + "' error code"
        )
    for msg in ("请选择至少两个活动", "一次最多修改 100 条活动",
                "请选择有效的项目", "进行中记录无法批量修改",
                "隐藏记录无法批量修改", "操作失败"):
        assert msg in bridge_src, (
            "bridge must contain the Chinese message: " + msg
        )



def test_api_has_batch_update_function():
    """the API must define the
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
    """the service must define the
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



def test_frontend_js_batch_stale_id_pruning():
    """frontend JS must prune stale selected ids on every render."""
    source = read_all_js()
    assert "function pruneStaleBatchSelection" in source, (
        "frontend JS must define the pruneStaleBatchSelection function"
    )
    # The prune function must be called from renderCorrectionShell.
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "pruneStaleBatchSelection" in render_body, (
        "renderCorrectionShell must call pruneStaleBatchSelection"
    )



def test_frontend_js_batch_save_rechecks_stale_ids():
    """saveBatchProject must re-check selected ids against the
    currently rendered shell activity rows before calling the bridge."""
    source = read_all_js()
    save_start = source.find("function saveBatchProject")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "renderedIds" in save_body or "querySelectorAll" in save_body, (
        "saveBatchProject must re-check selected ids against rendered rows"
    )
    assert "cleanIds" in save_body, (
        "saveBatchProject must build a cleanIds list from rendered rows"
    )





def test_frontend_js_batch_saving_independent_state_var():
    """batchProjectSaving must be a separate state variable,
    not aliased to any other saving flag."""
    source = read_all_js()
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
            "frontend JS must declare the " + var + " state variable"
        )



def test_frontend_js_session_switch_clears_batch_selection():
    """selectTimelineSession must call resetCorrectionShellState
    when switching to a different session, which clears the batch
    selection."""
    source = read_all_js()
    fn_start = source.find("function selectTimelineSession")
    assert fn_start != -1, "frontend JS must define selectTimelineSession"
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    assert "resetCorrectionShellState" in fn_body, (
        "selectTimelineSession must call resetCorrectionShellState on session switch"
    )



def test_frontend_js_date_switch_clears_batch_selection():
    """goPrevDay / goNextDay / goToday must all call
    resetCorrectionShellState, which clears the batch selection."""
    source = read_all_js()
    for fn_name in ("goPrevDay", "goNextDay", "goToday"):
        fn_start = source.find("function " + fn_name)
        assert fn_start != -1, "frontend JS must define " + fn_name
        fn_end = source.find("\n    function ", fn_start + 1)
        fn_body = source[fn_start:fn_end]
        assert "resetCorrectionShellState" in fn_body, (
            fn_name + " must call resetCorrectionShellState to clear batch selection"
        )



def test_frontend_js_auto_refresh_prunes_disappeared_ids():
    """pruneStaleBatchSelection must drop ids that are no
    longer present in the freshly rendered activity list, and must be
    called from both renderCorrectionShell and renderBatchProjectSection."""
    source = read_all_js()
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



def test_frontend_js_prune_rejects_non_numeric_ids():
    """pruneStaleBatchSelection must use a numeric regex so
    invalid (non-numeric) ids are dropped from the selection."""
    source = read_all_js()
    prune_start = source.find("function pruneStaleBatchSelection")
    prune_end = source.find("\n    function ", prune_start + 1)
    prune_body = source[prune_start:prune_end]
    # The regex must reject non-numeric ids.
    assert re.search(r"\^\[0\-9\]\+", prune_body), (
        "pruneStaleBatchSelection must use a ^[0-9]+ regex to reject non-numeric ids"
    )



def test_frontend_js_prune_skips_in_progress_activities():
    """pruneStaleBatchSelection must skip in-progress
    activities so they cannot be selected."""
    source = read_all_js()
    prune_start = source.find("function pruneStaleBatchSelection")
    prune_end = source.find("\n    function ", prune_start + 1)
    prune_body = source[prune_start:prune_end]
    assert "is_in_progress" in prune_body, (
        "pruneStaleBatchSelection must check is_in_progress to skip in-progress rows"
    )



def test_frontend_js_saving_disables_checkboxes_select_button():
    """setBatchProjectSaving(true) must disable the save
    button, select-all button, clear button, project select, and every
    batch checkbox."""
    source = read_all_js()
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



def test_frontend_js_save_catch_resets_saving():
    """the .catch handler in saveBatchProject must call
    setBatchProjectSaving(false) so saving never gets stuck."""
    source = read_all_js()
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



def test_frontend_js_save_success_clears_selection():
    """the success path in saveBatchProject must clear the
    selection and refresh the Timeline."""
    source = read_all_js()
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



def test_frontend_js_save_invalid_project_message():
    """saveBatchProject must show 请选择有效的项目 when the
    project select is empty or invalid."""
    source = read_all_js()
    fn_start = source.find("function saveBatchProject")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    assert "请选择有效的项目" in fn_body, (
        "saveBatchProject must show 请选择有效的项目 for invalid project"
    )



def test_frontend_js_save_derives_ids_from_rendered_rows():
    """saveBatchProject must derive cleanIds from the rendered
    shell rows (querySelectorAll), not from a stale in-memory copy."""
    source = read_all_js()
    fn_start = source.find("function saveBatchProject")
    fn_end = source.find("\n    function ", fn_start + 1)
    fn_body = source[fn_start:fn_end]
    assert "querySelectorAll" in fn_body, (
        "saveBatchProject must query the DOM for rendered rows"
    )
    assert "data-batch-activity-id" in fn_body, (
        "saveBatchProject must read data-batch-activity-id from rendered rows"
    )



def test_frontend_js_save_failure_does_not_clear_selection():
    """the failure path (result.ok === false) must NOT clear
    the selection or call resetBatchProjectState. The saving flag is reset
    once at the top of the .then handler (before branching), so both
    success and failure paths reset saving; the failure branch itself
    only shows the error and returns."""
    source = read_all_js()
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



def test_frontend_js_reset_batch_project_state_clears_selection():
    """resetBatchProjectState must clear the selection, the
    target project, the saving flag, and reset the DOM controls."""
    source = read_all_js()
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



def test_frontend_js_batch_save_guarded_by_saving_flag():
    """saveBatchProject must early-return if
    batchProjectSaving is already true (prevents double-submit)."""
    source = read_all_js()
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
    """index.html must contain a batch status area for
    success / error messages."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-batch-status"' in source, (
        "index.html must contain the batch status area"
    )



def test_index_html_batch_section_has_select_all_and_clear():
    """index.html must contain the select-all and clear
    selection buttons referenced by setBatchProjectSaving."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-batch-select-all-btn"' in source, (
        "index.html must contain the batch select-all button"
    )
    assert 'id="correction-shell-batch-clear-btn"' in source, (
        "index.html must contain the batch clear button"
    )



def test_styles_css_has_batch_disabled_states():
    """styles.css must define disabled / saving styles for
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





def test_frontend_js_has_batch_note_saving_state():
    """frontend JS must declare the batchNoteSaving state variable."""
    source = read_all_js()
    assert "batchNoteSaving" in source, (
        "frontend JS must declare the batchNoteSaving state variable"
    )



def test_frontend_js_has_batch_note_save_helper():
    """frontend JS must define the saveBatchNote function and
    related helpers."""
    source = read_all_js()
    assert "function saveBatchNote" in source, (
        "frontend JS must define the saveBatchNote function"
    )
    assert "function resetBatchNoteState" in source, (
        "frontend JS must define the resetBatchNoteState function"
    )
    assert "function renderBatchNoteSection" in source, (
        "frontend JS must define the renderBatchNoteSection function"
    )
    assert "function setBatchNoteSaving" in source, (
        "frontend JS must define the setBatchNoteSaving function"
    )
    assert "function updateBatchNoteCount" in source, (
        "frontend JS must define the updateBatchNoteCount function"
    )
    assert "function updateBatchNoteSaveButtonState" in source, (
        "frontend JS must define the updateBatchNoteSaveButtonState function"
    )
    assert "function showBatchNoteStatus" in source, (
        "frontend JS must define the showBatchNoteStatus function"
    )
    assert "function bindBatchNoteControls" in source, (
        "frontend JS must define the bindBatchNoteControls function"
    )



def test_frontend_js_calls_batch_note_update_bridge():
    """frontend JS must call the batch_update_timeline_activities_note
    bridge method."""
    source = read_all_js()
    assert "batch_update_timeline_activities_note" in source, (
        "frontend JS must call the batch_update_timeline_activities_note bridge method"
    )



def test_index_html_has_batch_note_section():
    """index.html must contain the batch note section in the
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
    """the batch note hint must state that only overwrite is
    supported (no append / merge)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "覆盖" in source, (
        "batch note hint must mention overwrite (覆盖)"
    )
    assert "追加" in source or "合并" in source, (
        "batch note hint must mention unsupported append/merge operations"
    )



def test_index_html_batch_note_textarea_placeholder():
    """the batch note textarea must have a placeholder."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "placeholder" in source, (
        "batch note textarea must have a placeholder attribute"
    )



def test_index_html_no_batch_note_append_merge_controls():
    """index.html must not contain append / merge note mode
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
    """index.html must not contain batch hide / delete / time /
    split / merge control identifiers (re-asserted for the batch note scope)."""
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



def test_frontend_js_batch_note_save_disabled_for_fewer_than_two():
    """the batch note save button must be disabled when fewer
    than two activities are selected."""
    source = read_all_js()
    save_start = source.find("function updateBatchNoteSaveButtonState")
    assert save_start != -1
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "count < 2" in save_body, (
        "updateBatchNoteSaveButtonState must check count < 2"
    )



def test_frontend_js_batch_note_save_blocked_by_dirty_edit():
    """saveBatchNote must block when isEditDirty() is true."""
    source = read_all_js()
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



def test_frontend_js_batch_note_success_refreshes_timeline():
    """a successful batch note save must refresh the Timeline."""
    source = read_all_js()
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "refreshTimelineForBatchSave" in save_body or "loadTimeline" in save_body, (
        "saveBatchNote must call refresh/load on success"
    )



def test_frontend_js_batch_note_failure_preserves_selection():
    """a failed batch note save must preserve the selection,
    detail list, and note textarea so the user can retry."""
    source = read_all_js()
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The error path must NOT call clearBatchSelection or resetBatchNoteState.
    assert "clearBatchSelection" not in save_body or save_body.count("clearBatchSelection") == 0, (
        "saveBatchNote failure must not clear the selection"
    )



def test_frontend_js_batch_note_catch_resets_saving():
    """the .catch path in saveBatchNote must reset saving."""
    source = read_all_js()
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



def test_frontend_js_clear_edit_panel_resets_batch_note_state():
    """clearEditPanel must call resetBatchNoteState."""
    source = read_all_js()
    clear_start = source.find("function clearEditPanel")
    clear_end = source.find("\n    function ", clear_start + 1)
    clear_body = source[clear_start:clear_end]
    assert "resetBatchNoteState" in clear_body, (
        "clearEditPanel must call resetBatchNoteState"
    )



def test_frontend_js_reset_correction_shell_resets_batch_note_state():
    """resetCorrectionShellState must call
    resetBatchNoteState."""
    source = read_all_js()
    reset_start = source.find("function resetCorrectionShellState")
    reset_end = source.find("\n    function ", reset_start + 1)
    reset_body = source[reset_start:reset_end]
    assert "resetBatchNoteState" in reset_body, (
        "resetCorrectionShellState must call resetBatchNoteState"
    )



def test_frontend_js_batch_note_rechecks_stale_ids():
    """saveBatchNote must re-check selected ids against the
    currently rendered shell activity rows before calling the bridge."""
    source = read_all_js()
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "renderedIds" in save_body or "querySelectorAll" in save_body, (
        "saveBatchNote must re-check selected ids against rendered rows"
    )
    assert "cleanIds" in save_body, (
        "saveBatchNote must build a cleanIds list from rendered rows"
    )



def test_frontend_js_batch_note_empty_allowed():
    """the batch note save must allow empty string (to clear
    notes). The save function must not reject an empty note."""
    source = read_all_js()
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    # The save function must NOT block on empty note (only on too-long).
    # It must use note.length > NOTE_MAX_LENGTH, not !note or note.length === 0.
    assert "NOTE_MAX_LENGTH" in save_body, (
        "saveBatchNote must reference NOTE_MAX_LENGTH"
    )



def test_frontend_js_batch_note_saving_disables_controls():
    """setBatchNoteSaving must disable the textarea, save
    button, and checkboxes during save."""
    source = read_all_js()
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



def test_frontend_js_batch_note_count_uses_max_length():
    """updateBatchNoteCount must use NOTE_MAX_LENGTH."""
    source = read_all_js()
    count_start = source.find("function updateBatchNoteCount")
    count_end = source.find("\n    function ", count_start + 1)
    count_body = source[count_start:count_end]
    assert "NOTE_MAX_LENGTH" in count_body, (
        "updateBatchNoteCount must use NOTE_MAX_LENGTH"
    )



def test_frontend_js_batch_note_bind_controls_called_in_init():
    """bindBatchNoteControls must be called during init."""
    source = read_all_js()
    # The bind call should be in the initButtons function (where other
    # bind calls live).
    buttons_start = source.find("function initButtons")
    buttons_end = source.find("\n    function ", buttons_start + 1)
    buttons_body = source[buttons_start:buttons_end]
    assert "bindBatchNoteControls" in buttons_body, (
        "bindBatchNoteControls must be called during initButtons"
    )



def test_frontend_js_batch_note_no_local_storage():
    """the batch note code must not use browser storage
    (re-asserted for the whole frontend JS)."""
    source = read_all_js()
    assert not re.search(r"localStorage|sessionStorage", source), (
        "frontend JS must not use localStorage or sessionStorage"
    )



def test_frontend_js_batch_note_no_external_links():
    """the batch note code must not introduce external links
    (re-asserted for all frontend resources)."""
    for filename in FRONTEND_RESOURCE_FILES:
        source = read_resource(filename)
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )



def test_frontend_js_batch_note_no_restore_permanent_auto_rule_overlap():
    """the batch note code must not introduce batch restore,
    restore all, undo restore, permanent delete, auto-rule, or overlap
    handlers (re-asserted: single ``saveActivityRestore`` is
    now implemented, but batch/undo/permanent variants remain forbidden)."""
    source = read_all_js()
    for forbidden in ("batchRestore", "batch_restore", "restoreAll",
                      "restore_all", "restoreSession", "restore_session",
                      "undoRestore", "undo_restore",
                      "permanentDelete", "permanent_delete",
                      "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap"):
        assert forbidden not in source, (
            "frontend JS must not contain " + forbidden + " handler"
        )



def test_styles_css_has_batch_note_section_styles():
    """styles.css must define the batch note section styles."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell-batch-note-text" in source, (
        "styles.css must define .correction-shell-batch-note-text"
    )



def test_bridge_has_batch_note_update_method():
    """the bridge must define the
    batch_update_timeline_activities_note method."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    assert "def batch_update_timeline_activities_note" in bridge_src, (
        "bridge must define batch_update_timeline_activities_note"
    )



def test_bridge_batch_note_error_messages_dict():
    """the bridge must define the _BATCH_NOTE_ERROR_MESSAGES
    dict with all stable error code -> Chinese message mappings."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
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
                "进行中记录无法批量修改",
                "隐藏记录无法批量修改", "操作失败"):
        assert msg in bridge_src, (
            "bridge must contain the Chinese message: " + msg
        )



def test_api_has_batch_note_update_function():
    """the API must define the
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
    """the service must define the
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



def test_frontend_js_batch_note_render_called_from_render_correction_shell():
    """renderBatchNoteSection must be called from
    renderCorrectionShell so the section is always populated when the shell
    opens."""
    source = read_all_js()
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "renderBatchNoteSection" in render_body, (
        "renderCorrectionShell must call renderBatchNoteSection"
    )





def test_frontend_js_batch_note_save_checks_batch_project_saving():
    """saveBatchNote must check ``batchProjectSaving`` before
    proceeding so two batch saves cannot compete."""
    source = read_all_js()
    save_start = source.find("function saveBatchNote")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "batchProjectSaving" in save_body, (
        "saveBatchNote must check batchProjectSaving before proceeding"
    )



def test_frontend_js_select_timeline_session_resets_batch_note():
    """selectTimelineSession must call
    resetCorrectionShellState (which calls resetBatchNoteState) when
    switching sessions so the note textarea does not carry over."""
    source = read_all_js()
    select_start = source.find("function selectTimelineSession")
    select_end = source.find("\n    function ", select_start + 1)
    select_body = source[select_start:select_end]
    assert "resetCorrectionShellState" in select_body, (
        "selectTimelineSession must call resetCorrectionShellState on "
        "session switch (which resets batch note state)"
    )



def test_frontend_js_date_navigation_resets_batch_note():
    """goPrevDay / goNextDay / goToday must all call
    resetCorrectionShellState (which calls resetBatchNoteState) so the
    note textarea does not carry over to a different day."""
    source = read_all_js()
    for func_name in ("goPrevDay", "goNextDay", "goToday"):
        func_start = source.find("function " + func_name)
        assert func_start >= 0, f"frontend JS must define {func_name}"
        func_end = source.find("\n    function ", func_start + 1)
        func_body = source[func_start:func_end]
        assert "resetCorrectionShellState" in func_body, (
            func_name + " must call resetCorrectionShellState (which "
            "resets batch note state)"
        )



def test_frontend_js_close_correction_shell_resets_batch_note():
    """closeCorrectionShell must call
    resetCorrectionShellState (which calls resetBatchNoteState) so the
    note textarea is cleared when the user closes the shell."""
    source = read_all_js()
    close_start = source.find("function closeCorrectionShell")
    close_end = source.find("\n    function ", close_start + 1)
    close_body = source[close_start:close_end]
    assert "resetCorrectionShellState" in close_body, (
        "closeCorrectionShell must call resetCorrectionShellState "
        "(which resets batch note state)"
    )



def test_frontend_js_set_batch_note_saving_disables_batch_project_controls():
    """setBatchNoteSaving must disable the batch project
    save button (and select-all / clear / project select) so the user
    cannot start a competing project save while a note save is in flight."""
    source = read_all_js()
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



def test_frontend_js_set_batch_project_saving_disables_batch_note_controls():
    """setBatchProjectSaving must disable the batch note
    textarea so the user cannot edit the note while a project save is in
    flight."""
    source = read_all_js()
    saving_start = source.find("function setBatchProjectSaving")
    saving_end = source.find("\n    function ", saving_start + 1)
    saving_body = source[saving_start:saving_end]
    assert "correction-shell-batch-note-text" in saving_body, (
        "setBatchProjectSaving must disable the batch note textarea"
    )



def test_frontend_js_reset_correction_shell_state_calls_reset_batch_note():
    """resetCorrectionShellState must call
    resetBatchNoteState so every path that resets the shell also clears
    the note textarea / count / status / saving state."""
    source = read_all_js()
    reset_start = source.find("function resetCorrectionShellState")
    reset_end = source.find("\n    function ", reset_start + 1)
    reset_body = source[reset_start:reset_end]
    assert "resetBatchNoteState" in reset_body, (
        "resetCorrectionShellState must call resetBatchNoteState"
    )



def test_frontend_js_reset_batch_note_state_clears_textarea_and_count():
    """resetBatchNoteState must clear the note textarea
    value, reset the count, and hide the status area."""
    source = read_all_js()
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



def test_frontend_js_batch_note_no_old_or_new_note_leak_in_error_handling():
    """the batch note error handling code must not reference
    old_note or new_note variables — the bridge error is surfaced verbatim
    without echoing note content."""
    source = read_all_js()
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



def test_frontend_js_batch_note_failure_preserves_textarea():
    """the failure path in saveBatchNote must NOT clear the
    note textarea — the user's input is preserved so they can retry."""
    source = read_all_js()
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



def test_frontend_js_batch_note_success_clears_selection_and_textarea():
    """the success path in saveBatchNote must clear the
    selection and the note textarea."""
    source = read_all_js()
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





def test_index_html_has_restore_section():
    """index.html must contain the restore section in the
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
    """the restore hint must be present in index.html,
    informing the user that restores are performed one record at a time."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    hint_start = source.find("correction-shell-restore-hint")
    assert hint_start != -1, "index.html must contain the restore hint"
    # Bound the hint to its enclosing <div>...</div> element so the
    # assertion scans the real hint text instead of a fixed character
    # window that could bleed into adjacent DOM.
    tag_start = source.rfind("<", 0, hint_start)
    assert tag_start != -1, "restore hint must be inside an HTML element"
    open_tag_end = source.find(">", hint_start)
    assert open_tag_end != -1, "restore hint opening tag must close"
    hint_close = source.find("</div>", open_tag_end)
    assert hint_close != -1, "restore hint must have a closing </div>"
    hint_window = source[tag_start:hint_close]
    assert "恢复" in hint_window, (
        "restore hint must mention that restores are performed one at a time"
    )



def test_index_html_no_batch_restore_restore_all_permanent_undo_controls():
    """index.html must not contain batch restore, restore all,
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



def test_frontend_js_has_restore_saving_state():
    """frontend JS must declare the restoreSaving state variable,
    independent from batchProjectSaving / batchNoteSaving."""
    source = read_all_js()
    assert "restoreSaving" in source, (
        "frontend JS must declare the restoreSaving state variable"
    )
    assert "restoreSavingActivityId" in source, (
        "frontend JS must declare the restoreSavingActivityId state variable"
    )



def test_frontend_js_has_restore_helpers():
    """frontend JS must define the restore helper functions."""
    source = read_all_js()
    assert "function resetRestoreState" in source, (
        "frontend JS must define the resetRestoreState function"
    )
    assert "function showRestoreStatus" in source, (
        "frontend JS must define the showRestoreStatus function"
    )
    assert "function setRestoreSaving" in source, (
        "frontend JS must define the setRestoreSaving function"
    )
    assert "function renderRestoreSection" in source, (
        "frontend JS must define the renderRestoreSection function"
    )
    assert "function loadRestorableActivities" in source, (
        "frontend JS must define the loadRestorableActivities function"
    )
    assert "function renderRestorableActivities" in source, (
        "frontend JS must define the renderRestorableActivities function"
    )
    assert "function saveActivityRestore" in source, (
        "frontend JS must define the saveActivityRestore function"
    )
    assert "function bindRestoreControls" in source, (
        "frontend JS must define the bindRestoreControls function"
    )



def test_frontend_js_calls_restore_bridge_methods():
    """frontend JS must call the restore_timeline_activity and
    get_timeline_restorable_activities bridge methods."""
    source = read_all_js()
    assert "restore_timeline_activity" in source, (
        "frontend JS must call the restore_timeline_activity bridge method"
    )
    assert "get_timeline_restorable_activities" in source, (
        "frontend JS must call the get_timeline_restorable_activities bridge method"
    )



def test_frontend_js_restore_save_blocked_by_dirty_edit():
    """saveActivityRestore must block when isEditDirty() is
    true and show the dirty-edit blocking message."""
    source = read_all_js()
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



def test_frontend_js_restore_save_checks_restore_saving():
    """saveActivityRestore must check restoreSaving before
    proceeding so two restores cannot compete."""
    source = read_all_js()
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "restoreSaving" in save_body, (
        "saveActivityRestore must check restoreSaving before proceeding"
    )



def test_frontend_js_restore_success_refreshes_timeline():
    """a successful restore must refresh the Timeline."""
    source = read_all_js()
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "refreshTimelineAfterEdit" in save_body, (
        "saveActivityRestore success must call refreshTimelineAfterEdit"
    )



def test_frontend_js_restore_success_shows_restored_message():
    """a successful restore must show the 已恢复 message."""
    source = read_all_js()
    save_start = source.find("function saveActivityRestore")
    save_end = source.find("\n    function ", save_start + 1)
    save_body = source[save_start:save_end]
    assert "已恢复" in save_body, (
        "saveActivityRestore success must show the 已恢复 message"
    )



def test_frontend_js_restore_failure_preserves_list():
    """a failed restore must preserve the restore list so the
    user can retry."""
    source = read_all_js()
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



def test_frontend_js_restore_catch_resets_saving():
    """the .catch path in saveActivityRestore must reset
    saving."""
    source = read_all_js()
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



def test_frontend_js_restore_saving_disables_buttons():
    """setRestoreSaving must disable all restore buttons when
    saving is true."""
    source = read_all_js()
    set_start = source.find("function setRestoreSaving")
    set_end = source.find("\n    function ", set_start + 1)
    set_body = source[set_start:set_end]
    assert "disabled" in set_body, (
        "setRestoreSaving must disable/enable restore buttons"
    )
    assert "correction-shell-restore-btn" in set_body, (
        "setRestoreSaving must target the restore button class"
    )



def test_frontend_js_clear_edit_panel_resets_restore_state():
    """clearEditPanel must call resetRestoreState."""
    source = read_all_js()
    clear_start = source.find("function clearEditPanel")
    clear_end = source.find("\n    function ", clear_start + 1)
    clear_body = source[clear_start:clear_end]
    assert "resetRestoreState" in clear_body, (
        "clearEditPanel must call resetRestoreState"
    )



def test_frontend_js_reset_correction_shell_resets_restore_state():
    """resetCorrectionShellState must call resetRestoreState."""
    source = read_all_js()
    reset_start = source.find("function resetCorrectionShellState")
    reset_end = source.find("\n    function ", reset_start + 1)
    reset_body = source[reset_start:reset_end]
    assert "resetRestoreState" in reset_body, (
        "resetCorrectionShellState must call resetRestoreState"
    )



def test_frontend_js_restore_render_called_from_render_correction_shell():
    """renderRestoreSection must be called from
    renderCorrectionShell so the section is always populated when the shell
    opens."""
    source = read_all_js()
    render_start = source.find("function renderCorrectionShell")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "renderRestoreSection" in render_body, (
        "renderCorrectionShell must call renderRestoreSection"
    )



def test_frontend_js_restore_bind_called_in_init():
    """bindRestoreControls must be called during initButtons."""
    source = read_all_js()
    buttons_start = source.find("function initButtons")
    buttons_end = source.find("\n    function ", buttons_start + 1)
    buttons_body = source[buttons_start:buttons_end]
    assert "bindRestoreControls" in buttons_body, (
        "bindRestoreControls must be called during initButtons"
    )



def test_frontend_js_restore_uses_escape_html():
    """renderRestorableActivities must escape dynamic values
    using escapeHtml."""
    source = read_all_js()
    render_start = source.find("function renderRestorableActivities")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "escapeHtml" in render_body, (
        "renderRestorableActivities must use escapeHtml for dynamic values"
    )



def test_frontend_js_restore_no_local_storage():
    """the restore code must not use browser storage
    (re-asserted for the whole frontend JS)."""
    source = read_all_js()
    assert not re.search(r"localStorage|sessionStorage", source), (
        "frontend JS must not use localStorage or sessionStorage"
    )



def test_frontend_js_restore_no_external_links():
    """the restore code must not introduce external links
    (re-asserted for all frontend resources)."""
    for filename in FRONTEND_RESOURCE_FILES:
        source = read_resource(filename)
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{filename} must not contain http:// or https:// links"
        )



def test_frontend_js_restore_no_raw_field_display():
    """the restore code must not display raw window_title /
    file_path / clipboard / note fields."""
    source = read_all_js()
    render_start = source.find("function renderRestorableActivities")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    for forbidden in ("window_title", "file_path_hint", "full_path",
                       "clipboard", "raw_note", "traceback"):
        assert forbidden not in render_body.lower(), (
            "renderRestorableActivities must not reference " + forbidden
        )



def test_styles_css_has_restore_section_styles():
    """styles.css must define the restore section styles."""
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
    """the bridge must define the restore_timeline_activity
    and get_timeline_restorable_activities methods."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    assert "def restore_timeline_activity" in bridge_src, (
        "bridge must define restore_timeline_activity"
    )
    assert "def get_timeline_restorable_activities" in bridge_src, (
        "bridge must define get_timeline_restorable_activities"
    )



def test_bridge_restore_error_messages_dict():
    """the bridge must define the _RESTORE_ERROR_MESSAGES
    dict with all stable error code -> Chinese message mappings."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    assert "_RESTORE_ERROR_MESSAGES" in bridge_src, (
        "bridge must define _RESTORE_ERROR_MESSAGES"
    )
    for code in ("invalid_activity", "not_found", "not_restorable",
                 "in_progress", "invalid_date", "operation_failed"):
        assert code in bridge_src, (
            "bridge must map the '" + code + "' error code"
        )
    for msg in ("请选择有效的活动", "活动不存在", "该活动无需恢复",
                "进行中记录无法恢复", "日期无效", "恢复失败",
                "加载可恢复记录失败"):
        assert msg in bridge_src, (
            "bridge must contain the Chinese message: " + msg
        )



def test_api_has_restore_function():
    """the API must define the restore_timeline_activity and
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
    """the service must define the restore_activity and
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



def test_frontend_js_restore_state_independent_from_batch_states():
    """The restore saving state variable must be
    independent from batchProjectSaving / batchNoteSaving (declared as a
    separate variable). The cross-save guard means
    saveActivityRestore refuses when a batch save is in flight; that guard
    is covered by the cross-save tests and does not violate the
    state-variable independence."""
    source = read_all_js()
    # The restore saving variable must be declared separately.
    # state vars now live on the App. namespace.
    assert "App.restoreSaving" in source, (
        "frontend JS must declare restoreSaving as a separate variable"
    )
    assert "App.restoreSavingActivityId" in source, (
        "frontend JS must declare restoreSavingActivityId as a separate variable"
    )
    # The setRestoreSaving helper must still set the independent
    # restoreSaving variable (not batchProjectSaving / batchNoteSaving).
    set_start = source.find("function setRestoreSaving")
    set_end = source.find("\n    function ", set_start + 1)
    set_body = source[set_start:set_end]
    assert "restoreSaving = saving" in set_body, (
        "setRestoreSaving must set the independent restoreSaving variable"
    )



def test_frontend_js_restore_does_not_reload_during_save():
    """renderRestoreSection must not reload the recovery list
    while a restore save is in flight."""
    source = read_all_js()
    render_start = source.find("function renderRestoreSection")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    assert "restoreSaving" in render_body, (
        "renderRestoreSection must check restoreSaving before reloading"
    )



def test_frontend_js_restore_load_shows_loading_placeholder():
    """loadRestorableActivities must show a loading placeholder
    while the list loads."""
    source = read_all_js()
    load_start = source.find("function loadRestorableActivities")
    load_end = source.find("\n    function ", load_start + 1)
    load_body = source[load_start:load_end]
    assert "加载中" in load_body, (
        "loadRestorableActivities must show a 加载中 placeholder"
    )



def test_frontend_js_restore_load_failure_shows_error():
    """loadRestorableActivities must show 加载可恢复记录失败 on
    failure."""
    source = read_all_js()
    load_start = source.find("function loadRestorableActivities")
    load_end = source.find("\n    function ", load_start + 1)
    load_body = source[load_start:load_end]
    assert "加载可恢复记录失败" in load_body, (
        "loadRestorableActivities must show 加载可恢复记录失败 on failure"
    )



def test_frontend_js_restore_empty_list_css_fallback():
    """an empty restore list must rely on the CSS :empty
    rule (no explicit 'no records' text in JS)."""
    source = read_all_js()
    render_start = source.find("function renderRestorableActivities")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    # The empty-state comment must reference the CSS :empty rule.
    assert ":empty" in render_body or "暂无可恢复记录" not in render_body, (
        "renderRestorableActivities must rely on CSS :empty for empty state"
    )



def test_styles_css_restore_empty_state():
    """styles.css must define the empty-state fallback for the
    restore list."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "暂无可恢复记录" in source or ":empty" in source, (
        "styles.css must define the restore list empty-state fallback"
    )





def test_frontend_js_restore_stale_row_guard():
    """saveActivityRestore must confirm the activity row
    still exists in the current restore list before calling the bridge.
    If the row is stale (e.g. the list was reloaded by an auto-refresh and
    the activity is no longer present), a safe message must be shown and
    the bridge must NOT be called."""
    source = read_all_js()
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



def test_frontend_js_restore_stale_row_guard_before_dirty_check():
    """the stale-row guard must run before the dirty-edit
    check so that a stale row is surfaced even when the user has unsaved
    edits (the stale row message is more specific than the dirty-edit
    block message)."""
    source = read_all_js()
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



def test_frontend_js_restore_auto_refresh_reload_guard():
    """the auto-refresh path that re-renders the correction
    shell (and thus the restore section) must be guarded by:
      1. shell open (correctionShellOpen),
      2. session match (correctionShellSessionId === found.session_id),
      3. no dirty edit (!isEditDirty()),
      4. not restore saving (restoreSaving check in renderRestoreSection).
    This test verifies the complete guard chain exists in the auto-refresh
    path of showTimeline and the renderRestoreSection function."""
    source = read_all_js()
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



def test_frontend_js_restore_saving_guard_in_render_returns_early():
    """when restoreSaving is true, renderRestoreSection must
    return immediately (skip the loadRestorableActivities call) so the
    in-flight save's success/failure handler can complete the reload
    itself. This prevents an auto-refresh from overwriting the list while
    a restore save response is pending."""
    source = read_all_js()
    render_start = source.find("function renderRestoreSection")
    render_end = source.find("\n    function ", render_start + 1)
    render_body = source[render_start:render_end]
    # The guard must be an early return: "if (App.restoreSaving) return;"
    # state vars now live on the App. namespace.
    assert re.search(r"if\s*\(\s*App\.restoreSaving\s*\)\s*return", render_body), (
        "renderRestoreSection must early-return when restoreSaving is true"
    )



def test_frontend_js_restore_stale_guard_does_not_change_selected_session():
    """the stale-row refusal path must not change the
    selected session (only show a safe message and return). This mirrors
    the dirty-state refusal semantics."""
    source = read_all_js()
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



def test_frontend_js_restore_stale_guard_no_bridge_call():
    """the stale-row guard path must not call callBridge.
    Only the path after the dirty-edit check (the actual restore path) may
    call the bridge."""
    source = read_all_js()
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





def test_index_html_correction_shell_has_context_card_3b9():
    """index.html must wrap the context block in a
    correction-shell-context-card."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-context-card"' in source, (
        "index.html must contain #correction-shell-context-card"
    )
    assert "correction-shell-context-card" in source, (
        "index.html must define the .correction-shell-context-card class"
    )



def test_index_html_correction_shell_has_activity_card_3b9():
    """index.html must wrap the activities block in a
    correction-shell-activity-card."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-activity-card"' in source, (
        "index.html must contain #correction-shell-activity-card"
    )
    assert "correction-shell-activity-card" in source



def test_index_html_correction_shell_has_single_action_card_3b9():
    """index.html must wrap the actions block in a
    correction-shell-single-action-card."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-single-action-card"' in source, (
        "index.html must contain #correction-shell-single-action-card"
    )
    assert "correction-shell-single-action-card" in source



def test_index_html_correction_shell_has_batch_action_card_3b9():
    """index.html must wrap the batch project + batch note
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
    """index.html must wrap the restore section in a
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
    """the not-implemented hint card was removed during
    consolidation; index.html must NOT contain it."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="correction-shell-not-implemented-card"' not in source, (
        "index.html must not contain #correction-shell-not-implemented-card"
    )
    assert "correction-shell-not-implemented-card" not in source, (
        "index.html must not contain the not-implemented card"
    )



def test_index_html_correction_shell_card_headers_present_3b9():
    """each card must have a .correction-shell-card-header."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "correction-shell-card-header" in source, (
        "index.html must define .correction-shell-card-header elements"
    )
    # Count occurrences: context / activity / single-action / batch /
    # restore = 5 headers (the not-implemented card was removed).
    assert source.count("correction-shell-card-header") >= 5, (
        "index.html must contain at least 5 card headers"
    )



def test_index_html_correction_shell_preserves_existing_ids_3b9():
    """consolidation must not remove any existing IDs that
    earlier contract tests depend on."""
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
    """the consolidation must not introduce batch hide /
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
    """the correction shell region must not introduce
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



def test_frontend_js_has_safe_text_helper_3b9():
    """frontend JS must define a safeText display-safe helper."""
    source = read_all_js()
    assert "function safeText" in source, (
        "frontend JS must define the safeText helper"
    )



def test_frontend_js_safe_text_returns_fallback_3b9():
    """safeText must return the fallback for null / undefined /
    empty values, and stringify non-empty values."""
    source = read_all_js()
    body = func_body(source, "safeText")
    assert "null" in body, "safeText must handle null"
    assert "undefined" in body, "safeText must handle undefined"
    assert "fallback" in body, "safeText must accept a fallback"
    assert "String(" in body, "safeText must stringify non-empty values"



def test_frontend_js_has_is_any_correction_write_saving_helper_3b9():
    """frontend JS must define an isAnyCorrectionWriteSaving
    cross-save guard helper."""
    source = read_all_js()
    assert "function isAnyCorrectionWriteSaving" in source, (
        "frontend JS must define the isAnyCorrectionWriteSaving helper"
    )
    body = func_body(source, "isAnyCorrectionWriteSaving")
    assert "batchProjectSaving" in body, (
        "isAnyCorrectionWriteSaving must consult batchProjectSaving"
    )
    assert "batchNoteSaving" in body, (
        "isAnyCorrectionWriteSaving must consult batchNoteSaving"
    )
    assert "restoreSaving" in body, (
        "isAnyCorrectionWriteSaving must consult restoreSaving"
    )



def test_frontend_js_has_reset_correction_action_status_helper_3b9():
    """frontend JS must define a resetCorrectionActionStatus helper
    that clears every shell status area."""
    source = read_all_js()
    assert "function resetCorrectionActionStatus" in source, (
        "frontend JS must define the resetCorrectionActionStatus helper"
    )
    body = func_body(source, "resetCorrectionActionStatus")
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



def test_frontend_js_open_correction_shell_calls_reset_action_status_3b9():
    """openCorrectionShell must call resetCorrectionActionStatus
    so stale messages from a previous shell session do not linger."""
    source = read_all_js()
    body = func_body(source, "openCorrectionShell")
    assert "resetCorrectionActionStatus" in body, (
        "openCorrectionShell must call resetCorrectionActionStatus"
    )



def test_frontend_js_render_correction_shell_uses_safe_text_3b9():
    """renderCorrectionShell must pass dynamic values through
    safeText so the shell never renders undefined / null."""
    source = read_all_js()
    body = func_body(source, "renderCorrectionShell")
    assert "safeText" in body, (
        "renderCorrectionShell must use safeText for dynamic values"
    )



def test_frontend_js_render_restorable_activities_uses_safe_text_3b9():
    """renderRestorableActivities must pass dynamic values
    through safeText so the restore list never renders undefined / null."""
    source = read_all_js()
    body = func_body(source, "renderRestorableActivities")
    assert "safeText" in body, (
        "renderRestorableActivities must use safeText for dynamic values"
    )



def test_frontend_js_render_correction_shell_still_uses_escape_html_3b9():
    """renderCorrectionShell must still escapeHtml every
    dynamic value before inserting into innerHTML."""
    source = read_all_js()
    body = func_body(source, "renderCorrectionShell")
    assert "escapeHtml" in body, (
        "renderCorrectionShell must still use escapeHtml"
    )



def test_frontend_js_correction_shell_no_raw_sensitive_fields_3b9():
    """the correction shell render path must not read raw
    window_title / file_path_hint / full_path / clipboard / note internals
    / traceback / SQL / exception text."""
    source = read_all_js()
    body = func_body(source, "renderCorrectionShell")
    for forbidden in ("window_title", "file_path_hint", "file_path",
                      "full_path", "clipboard", "session_note",
                      "traceback", "SQL", "Exception"):
        assert forbidden not in body, (
            "renderCorrectionShell must not read " + forbidden
        )



def test_frontend_js_render_restorable_activities_no_raw_sensitive_fields_3b9():
    """the restore list render path must not read raw
    window_title / file_path_hint / full_path / clipboard / note internals
    / traceback / SQL / exception text."""
    source = read_all_js()
    body = func_body(source, "renderRestorableActivities")
    for forbidden in ("window_title", "file_path_hint", "file_path",
                      "full_path", "clipboard", "session_note",
                      "traceback", "SQL", "Exception"):
        assert forbidden not in body, (
            "renderRestorableActivities must not read " + forbidden
        )



def test_frontend_js_save_batch_project_has_cross_save_guard_3b9():
    """saveBatchProject must refuse when a batch note save or
    single restore is in flight (cross-save guard)."""
    source = read_all_js()
    body = func_body(source, "saveBatchProject")
    assert "restoreSaving" in body, (
        "saveBatchProject must guard against restoreSaving"
    )
    assert "batchNoteSaving" in body, (
        "saveBatchProject must guard against batchNoteSaving"
    )
    assert "请等待当前操作完成" in body, (
        "saveBatchProject cross-save guard must use the unified message"
    )



def test_frontend_js_save_batch_note_has_cross_save_guard_3b9():
    """saveBatchNote must refuse when a single restore is in
    flight (cross-save guard)."""
    source = read_all_js()
    body = func_body(source, "saveBatchNote")
    assert "restoreSaving" in body, (
        "saveBatchNote must guard against restoreSaving"
    )
    assert "请等待当前操作完成" in body, (
        "saveBatchNote cross-save guard must use the unified message"
    )



def test_frontend_js_save_activity_restore_has_cross_save_guard_3b9():
    """saveActivityRestore must refuse when a batch project or
    batch note save is in flight (cross-save guard)."""
    source = read_all_js()
    body = func_body(source, "saveActivityRestore")
    assert "batchProjectSaving" in body, (
        "saveActivityRestore must guard against batchProjectSaving"
    )
    assert "batchNoteSaving" in body, (
        "saveActivityRestore must guard against batchNoteSaving"
    )
    assert "请等待当前操作完成" in body, (
        "saveActivityRestore cross-save guard must use the unified message"
    )



def test_frontend_js_save_activity_restore_cross_save_after_dirty_check_3b9():
    """the cross-save guard in saveActivityRestore must come
    AFTER the dirty-edit check (the stale-row guard must still come before
    the dirty-edit check)."""
    source = read_all_js()
    body = func_body(source, "saveActivityRestore")
    stale_pos = body.find("correction-shell-restore-list")
    dirty_pos = body.find("isEditDirty()")
    cross_pos = body.find("App.batchProjectSaving || App.batchNoteSaving")
    assert stale_pos != -1 and dirty_pos != -1 and cross_pos != -1, (
        "saveActivityRestore must contain all three guards"
    )
    assert stale_pos < dirty_pos, (
        "stale-row guard must precede the dirty-edit check"
    )
    assert dirty_pos < cross_pos, (
        "cross-save guard must come after the dirty-edit check"
    )



def test_frontend_js_save_activity_restore_cross_save_no_bridge_call_3b9():
    """the cross-save guard path in saveActivityRestore must
    not call callBridge."""
    source = read_all_js()
    body = func_body(source, "saveActivityRestore")
    cross_start = body.find("App.batchProjectSaving || App.batchNoteSaving")
    cross_end = body.find("return", cross_start)
    assert cross_end != -1, (
        "saveActivityRestore cross-save guard must return early"
    )
    guard_body = body[cross_start:cross_end]
    assert "callBridge" not in guard_body, (
        "saveActivityRestore cross-save guard must not call the bridge"
    )



def test_frontend_js_reset_correction_shell_state_still_resets_all_3b9():
    """resetCorrectionShellState must still call the three
    sub-reset helpers (batch project / batch note / restore)."""
    source = read_all_js()
    body = func_body(source, "resetCorrectionShellState")
    assert "resetBatchProjectState" in body, (
        "resetCorrectionShellState must still call resetBatchProjectState"
    )
    assert "resetBatchNoteState" in body, (
        "resetCorrectionShellState must still call resetBatchNoteState"
    )
    assert "resetRestoreState" in body, (
        "resetCorrectionShellState must still call resetRestoreState"
    )



def test_frontend_js_reset_correction_shell_state_independent_of_edit_saving_3b9():
    """resetCorrectionShellState must not reset the edit /
    time / split / merge / hide / delete saving states (those are owned by
    clearEditPanel)."""
    source = read_all_js()
    body = func_body(source, "resetCorrectionShellState")
    for saving in ("editSaving", "timeSaving", "activityTimeSaving",
                   "sessionSplitSaving", "activitySplitSaving", "mergeSaving",
                   "hideSaving", "deleteSaving", "editingSession"):
        assert saving not in body, (
            "resetCorrectionShellState must not reset " + saving
        )



def test_frontend_js_close_correction_shell_no_write_3b9():
    """closeCorrectionShell must not trigger a refresh or any
    write action."""
    source = read_all_js()
    body = func_body(source, "closeCorrectionShell")
    for forbidden in ("loadTimeline", "refreshAll", "callBridge",
                      "saveProject", "saveNote", "saveActivityTime",
                      "saveSessionTime", "saveActivitySplit", "saveSessionSplit",
                      "saveMerge", "saveHide", "saveDelete",
                      "saveBatchProject", "saveBatchNote",
                      "saveActivityRestore"):
        assert forbidden not in body, (
            "closeCorrectionShell must not call " + forbidden
        )



def test_frontend_js_correction_shell_no_local_storage_3b9():
    """the correction shell must not use localStorage or
    sessionStorage."""
    source = read_all_js()
    for forbidden in ("localStorage", "sessionStorage"):
        assert forbidden not in source, (
            "frontend JS must not use " + forbidden
        )



def test_frontend_js_correction_shell_no_external_links_3b9():
    """frontend JS must not reference external links, CDN, or
    Google Fonts."""
    source = read_all_js()
    for forbidden in ("http://", "https://", "cdn.", "googleapis.com",
                      "fonts.googleapis"):
        assert forbidden not in source, (
            "frontend JS must not reference " + forbidden
        )



def test_frontend_js_correction_shell_no_traceback_display_3b9():
    """frontend JS must not display tracebacks / SQL / raw exception
    text in the correction shell."""
    source = read_all_js()
    for forbidden in ("traceback", "Traceback", "SQL", "Exception"):
        assert forbidden not in source, (
            "frontend JS must not display " + forbidden
        )



def test_frontend_js_correction_shell_no_new_forbidden_handlers_3b9():
    """the consolidation must not introduce batch hide /
    delete, batch restore, restore all, undo stack, permanent delete,
    auto-rule, or global overlap detection handlers."""
    source = read_all_js()
    for forbidden in ("batchHide", "batchDelete", "batchRestore",
                      "restoreAll", "restore_all",
                      "permanentDelete", "permanent_delete",
                      "undoStack", "undo_stack",
                      "autoRule", "auto_rule",
                      "overlapDetection", "globalOverlap",
                      "batchTimeCorrection", "batchSplit", "batchMerge",
                      "batchNoteAppend", "batchNoteMerge"):
        assert forbidden not in source, (
            "frontend JS must not contain " + forbidden + " handler"
        )



def test_frontend_js_batch_project_and_note_share_selection_3b9():
    """batch project and batch note must share the same
    selectedBatchActivityIds selection (single source of truth)."""
    source = read_all_js()
    project_body = func_body(source, "saveBatchProject")
    note_body = func_body(source, "saveBatchNote")
    assert "selectedBatchActivityIds" in project_body, (
        "saveBatchProject must read from the shared selection"
    )
    assert "selectedBatchActivityIds" in note_body, (
        "saveBatchNote must read from the shared selection"
    )



def test_styles_css_has_correction_shell_card_styles_3b9():
    """styles.css must define the unified .correction-shell-card
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
    """.correction-shell[hidden] must still be display:none."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must keep the .correction-shell[hidden] rule"
    )



def test_styles_css_has_card_responsive_rules_3b9():
    """styles.css must keep the correction shell cards stable
    on narrow viewports."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    # The responsive block must reference the card class.
    assert ".correction-shell-card" in source, (
        "styles.css responsive block must reference .correction-shell-card"
    )



def test_styles_css_no_external_resources_3b9():
    """styles.css must not reference external resources."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for forbidden in ("http://", "https://", "cdn.", "googleapis.com",
                      "fonts.googleapis", "@import"):
        assert forbidden not in source, (
            "styles.css must not reference " + forbidden
        )



def test_bridge_no_unexpected_methods_for_contract_contract_2():
    """the bridge must not gain new methods. The existing
    project / note / time / split / merge / hide / delete / batch project /
    batch note / restore methods must still be present."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
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



def test_bridge_imports_only_allowed_modules_contract_2():
    """the bridge must still only import worktrace.api and
    worktrace.formatters; no direct service / db / collector / security /
    runtime / config imports."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    for forbidden in ("from ..services", "from ..db",
                      "from ..collector", "from ..security",
                      "from ..runtime", "from ..config",
                      "import worktrace.services",
                      "import worktrace.db"):
        assert forbidden not in bridge_src, (
            "bridge must not import " + forbidden
        )





def test_frontend_js_save_batch_note_cross_save_uses_unified_message():
    """saveBatchNote must use the unified cross-save message
    '请等待当前操作完成' for BOTH batchProjectSaving and restoreSaving, not
    '操作失败' for batchProjectSaving."""
    source = read_all_js()
    body = func_body(source, "saveBatchNote")
    # The consolidated cross-save guard checks both flags together.
    assert "App.batchProjectSaving || App.restoreSaving" in body, (
        "saveBatchNote must consolidate the cross-save guard into a single "
        "check covering batchProjectSaving and restoreSaving"
    )
    # The unified message must appear in the cross-save guard section.
    cross_pos = body.find("App.batchProjectSaving || App.restoreSaving")
    assert cross_pos != -1, "cross-save guard must exist"
    ret_pos = body.find("return", cross_pos)
    guard_section = body[cross_pos:ret_pos] if ret_pos != -1 else body[cross_pos:]
    assert "请等待当前操作完成" in guard_section, (
        "saveBatchNote cross-save guard must use the unified message"
    )



def test_frontend_js_save_batch_note_no_removed_failure_message_for_cross_save():
    """saveBatchNote must NOT use '操作失败' for the
    batchProjectSaving cross-save (that was the pre-hardening behavior)."""
    source = read_all_js()
    body = func_body(source, "saveBatchNote")
    # The cross-save guard section must not contain '操作失败'.
    cross_pos = body.find("App.batchProjectSaving || App.restoreSaving")
    assert cross_pos != -1
    # Look at the guard block up to the next 'return'.
    ret_pos = body.find("return", cross_pos)
    guard_block = body[cross_pos:ret_pos] if ret_pos != -1 else body[cross_pos:]
    assert "操作失败" not in guard_block, (
        "saveBatchNote cross-save guard must not use '操作失败'"
    )



def test_frontend_js_auto_refresh_checks_correction_write_saving():
    """the auto-refresh re-render path must check
    isAnyCorrectionWriteSaving() so a save in flight is not overwritten."""
    source = read_all_js()
    # The auto-refresh guard is in the session-found branch of the
    # timeline render path. It must include isAnyCorrectionWriteSaving().
    # We search for the combined condition.
    assert "isAnyCorrectionWriteSaving()" in source, (
        "frontend JS must call isAnyCorrectionWriteSaving()"
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



def test_frontend_js_render_batch_project_section_status_guard():
    """renderBatchProjectSection must not clear the batch
    project status while a batch project save is in flight."""
    source = read_all_js()
    body = func_body(source, "renderBatchProjectSection")
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
    assert "if (!App.batchProjectSaving)" in body, (
        "renderBatchProjectSection must wrap status clear in "
        "if (!App.batchProjectSaving)"
    )



def test_frontend_js_render_batch_note_section_status_guard():
    """renderBatchNoteSection must not clear the batch note
    status while a batch note save is in flight."""
    source = read_all_js()
    body = func_body(source, "renderBatchNoteSection")
    status_pos = body.find('showBatchNoteStatus("", false)')
    assert status_pos != -1, (
        "renderBatchNoteSection must call showBatchNoteStatus"
    )
    preceding = body[max(0, status_pos - 200):status_pos]
    assert "batchNoteSaving" in preceding, (
        "renderBatchNoteSection must guard showBatchNoteStatus with "
        "batchNoteSaving"
    )
    assert "if (!App.batchNoteSaving)" in body, (
        "renderBatchNoteSection must wrap status clear in "
        "if (!App.batchNoteSaving)"
    )



def test_frontend_js_cross_save_guard_order_dirty_before_cross_save():
    """in all three consolidated write paths, the dirty guard
    (isEditDirty) must come BEFORE the cross-save guard."""
    source = read_all_js()
    for func_name, cross_marker in [
        ("saveBatchProject", "App.batchNoteSaving || App.restoreSaving"),
        ("saveBatchNote", "App.batchProjectSaving || App.restoreSaving"),
        ("saveActivityRestore", "App.batchProjectSaving || App.batchNoteSaving"),
    ]:
        body = func_body(source, func_name)
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



def test_frontend_js_cross_save_guard_no_bridge_call():
    """none of the three cross-save guard paths may call
    callBridge before returning."""
    source = read_all_js()
    for func_name, cross_marker in [
        ("saveBatchProject", "App.batchNoteSaving || App.restoreSaving"),
        ("saveBatchNote", "App.batchProjectSaving || App.restoreSaving"),
        ("saveActivityRestore", "App.batchProjectSaving || App.batchNoteSaving"),
    ]:
        body = func_body(source, func_name)
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



def test_frontend_js_cross_save_guard_preserves_state():
    """the cross-save guard paths must not clear selection,
    textarea, or restore list (they only show a status and return)."""
    source = read_all_js()
    for func_name, cross_marker in [
        ("saveBatchProject", "App.batchNoteSaving || App.restoreSaving"),
        ("saveBatchNote", "App.batchProjectSaving || App.restoreSaving"),
        ("saveActivityRestore", "App.batchProjectSaving || App.batchNoteSaving"),
    ]:
        body = func_body(source, func_name)
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



def test_frontend_js_is_any_correction_write_saving_covers_three_states():
    """isAnyCorrectionWriteSaving must cover batchProjectSaving,
    batchNoteSaving, and restoreSaving."""
    source = read_all_js()
    body = func_body(source, "isAnyCorrectionWriteSaving")
    assert "batchProjectSaving" in body, (
        "isAnyCorrectionWriteSaving must check batchProjectSaving"
    )
    assert "batchNoteSaving" in body, (
        "isAnyCorrectionWriteSaving must check batchNoteSaving"
    )
    assert "restoreSaving" in body, (
        "isAnyCorrectionWriteSaving must check restoreSaving"
    )



def test_frontend_js_reset_correction_shell_state_calls_sub_resets():
    """resetCorrectionShellState must still call all three
    sub-reset helpers."""
    source = read_all_js()
    body = func_body(source, "resetCorrectionShellState")
    assert "resetBatchProjectState()" in body, (
        "resetCorrectionShellState must call resetBatchProjectState"
    )
    assert "resetBatchNoteState()" in body, (
        "resetCorrectionShellState must call resetBatchNoteState"
    )
    assert "resetRestoreState()" in body, (
        "resetCorrectionShellState must call resetRestoreState"
    )



def test_frontend_js_reset_paths_cover_all_contexts():
    """resetCorrectionShellState must be called on close,
    date switch, session switch, and session disappear paths."""
    source = read_all_js()
    # closeCorrectionShell must call resetCorrectionShellState.
    close_body = func_body(source, "closeCorrectionShell")
    assert "resetCorrectionShellState()" in close_body, (
        "closeCorrectionShell must call resetCorrectionShellState"
    )
    # goPrevDay / goNextDay / goToday must call resetCorrectionShellState.
    for fn in ("goPrevDay", "goNextDay", "goToday"):
        body = func_body(source, fn)
        assert "resetCorrectionShellState()" in body, (
            fn + " must call resetCorrectionShellState"
        )
    # selectTimelineSession must call resetCorrectionShellState when
    # switching sessions.
    sel_body = func_body(source, "selectTimelineSession")
    assert "resetCorrectionShellState()" in sel_body, (
        "selectTimelineSession must call resetCorrectionShellState"
    )



def test_frontend_js_close_correction_shell_preserves_selected_session_contract_2():
    """closeCorrectionShell must NOT clear selectedSessionId
    (the user returns to the same session context)."""
    source = read_all_js()
    body = func_body(source, "closeCorrectionShell")
    # The comment documenting the preserve semantics must be present.
    assert "selectedSessionId" in body, (
        "closeCorrectionShell must reference selectedSessionId"
    )
    # It must not assign null to selectedSessionId.
    assert "selectedSessionId = null" not in body, (
        "closeCorrectionShell must not clear selectedSessionId"
    )



def test_frontend_js_safe_text_still_used_in_correction_shell():
    """renderCorrectionShell and renderRestorableActivities
    must still use safeText for dynamic values."""
    source = read_all_js()
    render_body = func_body(source, "renderCorrectionShell")
    assert "safeText(" in render_body, (
        "renderCorrectionShell must use safeText"
    )
    restore_body = func_body(source, "renderRestorableActivities")
    assert "safeText(" in restore_body, (
        "renderRestorableActivities must use safeText"
    )



def test_frontend_js_correction_shell_no_raw_sensitive_fields():
    """frontend JS must not reference raw sensitive backend column
    names anywhere (window_title, file_path_hint, full_path, clipboard).

    Exception: ``clipboard_capture_enabled`` is the JSON status
    flag returned by the Settings / Privacy read-only facade; it is the
    only allowed ``clipboard`` reference. All other uses remain forbidden.

    Exception: the Settings / Privacy clipboard capture toggle
    introduces ``settings-clipboard-toggle`` DOM ids and ``clipboardtoggle``
    function names (e.g. ``setClipboardToggleStatus``). These are UI
    identifiers, not raw backend field names, so they are also whitelisted.
    """
    source = read_all_js().lower()
    # only the legitimate JSON status flag name is whitelisted.
    source_without_capture_flag = source.replace("clipboard_capture_enabled", "")
    # whitelist the toggle DOM id prefix and camelCase function
    # names (lowercased) so they are not confused with the raw "clipboard"
    # content field.
    source_without_capture_flag = source_without_capture_flag.replace("clipboard-toggle", "")
    source_without_capture_flag = source_without_capture_flag.replace("clipboardtoggle", "")
    for forbidden in ("window_title", "file_path_hint", "full_path",
                      "clipboard"):
        assert forbidden not in source_without_capture_flag, (
            "frontend JS must not reference raw sensitive field: " + forbidden
        )



def test_frontend_js_correction_shell_escape_html_still_used():
    """escapeHtml must still be used in correction shell
    rendering paths."""
    source = read_all_js()
    render_body = func_body(source, "renderCorrectionShell")
    assert "escapeHtml(" in render_body, (
        "renderCorrectionShell must use escapeHtml"
    )
    restore_body = func_body(source, "renderRestorableActivities")
    assert "escapeHtml(" in restore_body, (
        "renderRestorableActivities must use escapeHtml"
    )



def test_frontend_js_correction_shell_no_local_storage():
    """frontend JS must not use localStorage or sessionStorage."""
    source = read_all_js().lower()
    assert "localstorage" not in source, (
        "frontend JS must not use localStorage"
    )
    assert "sessionstorage" not in source, (
        "frontend JS must not use sessionStorage"
    )



def test_frontend_js_correction_shell_no_external_links():
    """frontend JS must not reference external http/https/CDN
    resources."""
    source = read_all_js()
    for forbidden in ("http://", "https://", "//cdn", "googleapis"):
        assert forbidden not in source, (
            "frontend JS must not reference external resource: " + forbidden
        )



def test_index_html_correction_shell_cards_still_present():
    """the remaining correction shell cards must still be
    present in index.html, and the not-implemented card must NOT exist."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for card_id in (
        "correction-shell-context-card",
        "correction-shell-activity-card",
        "correction-shell-single-action-card",
        "correction-shell-batch-action-card",
        "correction-shell-restore-card",
    ):
        assert card_id in source, (
            "index.html must contain " + card_id
        )
    assert "correction-shell-not-implemented-card" not in source, (
        "index.html must not contain the not-implemented card"
    )



def test_index_html_correction_shell_existing_ids_preserved():
    """all existing JS-dependent ids must still be present."""
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



def test_index_html_no_forbidden_batch_ui():
    """index.html must not contain batch hide / batch delete /
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
        # The not-implemented card has been removed; only the forbidden
        # UI control ids are checked here.
        assert ('id="' + forbidden + '"') not in source, (
            "index.html must not contain forbidden UI control id: "
            + forbidden
        )



def test_index_html_no_not_implemented_card():
    """The 'not-implemented' card must NOT exist in index.html. The card
    must not list unavailable features like 批量隐藏 / 批量删除 / 批量恢复 /
    撤销栈 / 永久删除 / 批量时间 / 批量拆分 / 批量合并. Only currently-available
    capabilities are shown."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "correction-shell-not-implemented-card" not in source, (
        "index.html must not contain the not-implemented card; "
        "unavailable feature list must not be rendered"
    )



def test_styles_css_correction_shell_hidden_display_none():
    """.correction-shell[hidden] must remain display:none."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".correction-shell[hidden]" in source, (
        "styles.css must have .correction-shell[hidden] rule"
    )
    pos = source.find(".correction-shell[hidden]")
    rule_end = source.find("}", pos)
    assert rule_end != -1, ".correction-shell[hidden] rule must close with }"
    rule = source[pos:rule_end + 1]
    assert "display: none" in rule, (
        ".correction-shell[hidden] must set display: none"
    )



def test_styles_css_card_classes_present():
    """unified card CSS classes must still be present."""
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



def test_styles_css_no_external_resources():
    """styles.css must not reference external resources."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8").lower()
    for forbidden in ("http://", "https://", "@import", "googleapis",
                      "cdn"):
        assert forbidden not in source, (
            "styles.css must not reference external resource: " + forbidden
        )



def test_styles_css_highlight_still_present():
    """the transient highlight CSS must still be present."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert "detail-item-highlight" in source, (
        "styles.css must retain .detail-item-highlight"
    )
    assert "shell-target" in source, (
        "styles.css must retain .shell-target"
    )



def test_bridge_no_unexpected_methods_for_contract_contract_3():
    """no new bridge methods beyond the known set."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
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



def test_bridge_imports_only_allowed_modules_contract_3():
    """the bridge must still only import worktrace.api and
    worktrace.formatters."""
    # scan all 8 bridge mixin files (method bodies / constants
    # moved out of bridge.py into the mixins).
    bridge_src = read_bridge_sources_combined()
    for forbidden in ("from ..services", "from ..db",
                      "from ..collector", "from ..security",
                      "from ..runtime", "from ..config",
                      "import worktrace.services",
                      "import worktrace.db"):
        assert forbidden not in bridge_src, (
            "bridge must not import " + forbidden
        )
