"""Project Rules WebView static-contract tests for Phase 5B.

These tests read bundled frontend resources directly. They lock the
Project Rules existing-rule enable/disable foundation without starting
pywebview or touching the database.
"""

from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import (  # noqa: E402
    ALL_JS_FILES,
    FRONTEND_RESOURCE_FILES,
    NO_STORAGE_FILES,
    REPO_ROOT,
    func_body,
    read_all_js,
    read_js,
    read_resource,
)


PROJECT_RULE_WRITE_METHODS = (
    "create_project",
    "update_project",
    "delete_project",
    "set_project_enabled",
    "create_keyword_rule",
    "create_or_update_folder_rule",
    "set_keyword_rule_enabled",
    "set_folder_rule_enabled",
    "delete_keyword_rule",
    "delete_folder_rule",
    "preview_folder_rule_conflicts",
    "backfill_folder_rule",
)

FORBIDDEN_RULES_JS_HANDLER_TOKENS = (
    "createProject",
    "updateProject",
    "deleteProject",
    "setProjectEnabled",
    "createKeywordRule",
    "createOrUpdateFolderRule",
    "deleteKeywordRule",
    "deleteFolderRule",
    "previewFolderRuleConflicts",
    "backfillFolderRule",
    "automaticRules",
)


def _rules_section() -> str:
    source = read_resource("index.html")
    start = source.find('id="page-rules"')
    assert start != -1, "index.html must contain page-rules"
    end = source.find("</section>", start)
    assert end != -1, "page-rules section must close"
    return source[start:end]


def test_project_rules_page_is_not_placeholder():
    section = _rules_section()
    assert "WebView 迁移中" not in section
    assert "项目规则" in section
    assert "按项目查看" in section
    assert "folder / keyword" in section


def test_project_rules_sidebar_entry_exists():
    source = read_resource("index.html")
    assert 'data-page="rules"' in source
    assert "项目规则" in source


def test_project_rules_required_dom_ids_exist():
    section = _rules_section()
    for dom_id in (
        "rules-error",
        "rules-loading",
        "rules-list",
        "rules-empty",
        "rules-readonly-hint",
    ):
        assert 'id="' + dom_id + '"' in section


def test_project_rules_phase_5b_boundary_copy_present():
    section = _rules_section()
    # Phase 5C: the boundary copy now mentions keyword rule creation as a
    # supported capability. The supported-ops clause still references
    # enable/disable, and the unsupported-ops clause still references the
    # remaining future capabilities.
    assert "启用/停用" in section
    assert "新增关键词规则" in section
    for term in ("编辑", "删除", "冲突预览", "回填"):
        assert term in section


def test_project_rules_page_has_no_static_action_buttons():
    section = _rules_section()
    # Phase 5C: the only allowed static button in the section is the
    # keyword create submit button. All other action buttons (folder
    # create, project create/edit/delete, rule edit/delete, etc.) remain
    # forbidden as static DOM.
    import re as _re

    buttons = _re.findall(r"<button[^>]*>", section, _re.IGNORECASE)
    assert len(buttons) == 1, (
        "Project Rules page must have exactly one static button (keyword "
        "create submit); found: " + repr(buttons)
    )
    assert 'id="rules-keyword-create-submit"' in buttons[0]
    forbidden = (
        "rules-add",
        "rules-create",
        "rules-edit",
        "rules-delete",
        "rules-enable",
        "rules-disable",
        "project-add",
        "project-edit",
        "project-delete",
        "project-enable",
        "project-disable",
        "rule-add",
        "rule-edit",
        "rule-delete",
        "rule-enable",
        "rule-disable",
        "rules-folder-create",
        "rules-project-create",
        "rules-keyword-edit",
        "rules-keyword-delete",
        "rules-folder-edit",
        "rules-folder-delete",
    )
    lowered = section.lower()
    for token in forbidden:
        assert token not in lowered, (
            "Project Rules page must not contain action id/class: " + token
        )


def test_project_rules_js_loaded_before_init():
    source = read_resource("index.html")
    statistics_pos = source.find('src="js/statistics.js"')
    rules_pos = source.find('src="js/rules.js"')
    init_pos = source.find('src="js/init.js"')
    assert statistics_pos != -1
    assert rules_pos != -1
    assert init_pos != -1
    assert statistics_pos < rules_pos
    assert rules_pos < init_pos


def test_project_rules_js_in_static_helper_order():
    assert "rules.js" in ALL_JS_FILES
    assert ALL_JS_FILES.index("rules.js") == ALL_JS_FILES.index("statistics.js") + 1
    assert ALL_JS_FILES.index("init.js") == ALL_JS_FILES.index("rules.js") + 1


def test_project_rules_state_variables_declared():
    source = read_js("core.js")
    assert "App.rulesLoaded = false" in source
    assert "App.rulesLoading = false" in source
    assert "App.rulesRequestToken = 0" in source
    assert "App.rulesSavingRuleKey = null" in source


def test_project_rules_js_defines_load_and_render_functions():
    source = read_all_js()
    assert "function loadProjectRules" in source
    assert "function showProjectRules" in source
    assert "function renderProjectRuleProject" in source
    assert "function renderProjectRuleRow" in source


def test_project_rules_js_calls_allowed_bridge_methods_only():
    source = read_js("rules.js")
    assert 'callBridge("get_project_rules")' in source
    assert 'callBridge("set_project_rule_enabled"' in source
    assert 'callBridge("set_project_enabled"' not in source


def test_project_rules_load_has_loading_guard_and_stale_guard():
    source = read_js("rules.js")
    body = func_body(source, "loadProjectRules")
    assert "if (App.rulesLoading)" in body
    assert "var token = ++App.rulesRequestToken" in body
    assert body.count("token !== App.rulesRequestToken") >= 2
    assert "App.setRulesLoading(true)" in body
    assert "App.setRulesLoading(false)" in body


def test_project_rules_failure_paths_use_stable_fallback_only():
    source = read_js("rules.js")
    body = func_body(source, "loadProjectRules")
    assert 'App.showRulesError("加载项目规则失败")' in body
    assert "result.error" not in body
    for forbidden in (
        ".message",
        ".toString",
        "err",
        "error",
        "reason",
    ):
        assert forbidden not in body


def test_project_rules_toggle_handler_uses_single_rule_write_contract():
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    assert 'App.callBridge("set_project_rule_enabled", ruleType, ruleId, nextEnabled)' in body
    assert 'ruleType !== "folder" && ruleType !== "keyword"' in body
    assert "App.rulesSavingRuleKey" in body
    assert "window.confirm" in body
    assert "确定停用这条规则吗？停用后它将不再用于自动归类。" in body


def test_project_rules_toggle_success_refreshes_and_failure_keeps_rendered_data():
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    assert "App.loadProjectRules()" in body
    assert "规则状态已更新" in body
    assert "更新规则状态失败" in body
    assert "list.innerHTML" not in body


def test_project_rules_toggle_catch_never_reads_raw_exception_message():
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    assert ".catch(function ()" in body
    for forbidden in ("err.message", "error.message", ".toString", "reason.message"):
        assert forbidden not in body


def test_project_rules_rendering_uses_escape_helper():
    source = read_js("rules.js")
    text_body = func_body(source, "text")
    count_body = func_body(source, "count")
    assert "App.escapeHtml" in text_body
    assert "App.safeText" in text_body
    assert "App.escapeHtml" in count_body
    assert ".innerHTML" in source
    assert "renderProjectRuleProject(project)" in source
    assert "renderProjectRuleRow(rule)" in source


def test_project_rules_js_does_not_call_forbidden_write_methods():
    source = read_all_js()
    # Phase 5C: the check uses bridge call string patterns (``callBridge("
    # <method>"``) rather than bare method names so that the allowed
    # ``create_project_keyword_rule`` call is not falsely flagged by the
    # ``create_project`` substring check.
    for method in PROJECT_RULE_WRITE_METHODS:
        forbidden_call = 'callBridge("' + method + '"'
        assert forbidden_call not in source, (
            "Project Rules frontend must not call write bridge method: " + method
        )
    assert 'callBridge("set_project_rule_enabled"' in source
    assert 'callBridge("create_project_keyword_rule"' in source


def test_project_rules_js_has_no_create_edit_delete_backfill_preview_handlers():
    source = read_js("rules.js")
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source
    for forbidden in ("project-enable", "project-disable", "projectToggle"):
        assert forbidden not in source


def test_project_rules_js_catch_path_never_reads_raw_exception_message():
    source = read_js("rules.js")
    for forbidden in (
        "err.message",
        "err.toString",
        "error.message",
        "error.toString",
        "reason.message",
        "reason.toString",
    ):
        assert forbidden not in source
    assert ".catch(function ()" in source
    assert "加载项目规则失败" in source


def test_project_rules_refresh_all_only_when_active_and_loaded():
    source = read_js("init.js")
    body = func_body(source, "refreshAll")
    assert 'App.currentPage === "rules"' in body
    assert "App.rulesLoaded" in body
    assert "!App.rulesLoading" in body
    assert "promises.push(App.loadProjectRules())" in body


def test_project_rules_lazy_loads_on_first_navigation_only():
    source = read_js("init.js")
    body = func_body(source, "switchPage")
    assert 'pageId === "rules"' in body
    assert "!App.rulesLoaded" in body
    assert "!App.rulesLoading" in body
    assert "App.loadProjectRules()" in body


def test_project_rules_packaging_spec_includes_rules_js():
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'rules.js'" in source or '"rules.js"' in source
    assert "'worktrace/webview_ui/js'" in source or '"worktrace/webview_ui/js"' in source


def test_project_rules_frontend_resources_keep_global_boundaries():
    for filename in FRONTEND_RESOURCE_FILES:
        source = read_resource(filename)
        assert not re.search(r"https?://", source, re.IGNORECASE)
        assert not re.search(r"cdn", source, re.IGNORECASE)
        assert not re.search(r"google\s*fonts", source, re.IGNORECASE)
    for filename in NO_STORAGE_FILES:
        source = read_resource(filename)
        assert "localStorage" not in source
        assert "sessionStorage" not in source
    assert "app.js" not in read_resource("index.html")


def test_project_rules_js_has_no_direct_file_or_network_write():
    source = read_js("rules.js")
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "FileReader",
        "showSaveFilePicker",
        "writeText",
        "download",
    ):
        assert forbidden not in source


def test_project_rules_page_does_not_add_export_or_auto_submit_controls():
    section = _rules_section().lower()
    for token in (
        "excel",
        "pdf",
        "timesheet",
        "open-folder",
        "open_folder",
        "auto-submit",
        "auto_submit",
        "自动提交工时",
        "打开文件夹",
    ):
        assert token not in section


# --- Phase 5B.1 hardening regression locks ---------------------------------


def test_project_rules_toggle_button_is_inside_rule_row_not_project_card():
    # Phase 5B.1 regression lock: the toggle button must be rendered inside
    # ``renderProjectRuleRow`` (i.e. on the rule row), never directly on the
    # project card. The project card template may not contain a
    # ``rules-toggle-btn`` of its own.
    source = read_js("rules.js")
    project_body = func_body(source, "renderProjectRuleProject")
    row_body = func_body(source, "renderProjectRuleRow")
    assert "rules-toggle-btn" in row_body
    assert "rules-toggle-btn" not in project_body
    # The project card only renders rows via the row helper, never a static
    # project-level toggle button.
    for forbidden in (
        "rules-project-toggle",
        'data-rule-type="project"',
        "setProjectEnabled",
        "set_project_enabled",
    ):
        assert forbidden not in project_body


def test_project_rules_toggle_handler_clears_saving_state_on_all_paths():
    # Phase 5B.1 regression lock: the saving state must clear on success,
    # on failure (ok=false), and on rejected promise. The handler achieves
    # this by chaining ``App.setProjectRuleSaving(null)`` in the final
    # ``.then`` that runs after ``.catch`` (which always resolves).
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    assert "App.setProjectRuleSaving(ruleType" in body
    # The final cleanup must run unconditionally after the catch.
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setProjectRuleSaving(null)", catch_pos)
    assert cleanup_pos != -1, (
        "App.setProjectRuleSaving(null) must run after .catch so the saving "
        "state clears on success, failure, and rejected-promise paths"
    )


def test_project_rules_toggle_handler_single_in_flight_guard():
    # Phase 5B.1 regression lock: only one toggle write may be in flight at
    # a time. The handler must early-return when ``App.rulesSavingRuleKey``
    # is set, before any bridge call or confirmation dialog.
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    guard_pos = body.find("App.rulesSavingRuleKey")
    confirm_pos = body.find("window.confirm")
    bridge_pos = body.find('App.callBridge("set_project_rule_enabled"')
    assert guard_pos != -1 and confirm_pos != -1 and bridge_pos != -1
    assert guard_pos < confirm_pos < bridge_pos, (
        "in-flight guard must run before confirmation dialog and bridge call"
    )


def test_project_rules_toggle_button_saving_label_present():
    # Phase 5B.1 regression lock: the saving button text must remain the
    # stable ``正在更新…`` label so the user sees a clear in-progress state.
    source = read_js("rules.js")
    row_body = func_body(source, "renderProjectRuleRow")
    assert "正在更新…" in row_body
    set_saving_body = func_body(source, "setProjectRuleSaving")
    assert "正在更新…" in set_saving_body


def test_project_rules_toggle_success_then_refresh_chain():
    # Phase 5B.1 regression lock: the success path must call
    # ``loadProjectRules`` (refresh) before showing the success banner so a
    # stale rendered list is never left on screen after a successful toggle.
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    refresh_pos = body.find("App.loadProjectRules()")
    success_pos = body.find("规则状态已更新")
    assert refresh_pos != -1 and success_pos != -1
    assert refresh_pos < success_pos


def test_project_rules_toggle_failure_keeps_existing_list_rendered():
    # Phase 5B.1 regression lock: the failure path must not clear the
    # already-rendered list. The toggle handler may only call
    # ``showRulesError`` on failure, never ``list.innerHTML = ""`` or
    # ``showProjectRules`` with an empty payload.
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body


def test_project_rules_toggle_dataset_id_is_parsed_and_validated():
    # Phase 5B.1 regression lock: the dataset ``data-rule-id`` must be
    # parsed via ``parseInt(..., 10)`` and rejected (``!ruleId``) when the
    # result is NaN or 0, before the bridge call.
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    assert 'parseInt(button.getAttribute("data-rule-id"), 10)' in body
    assert "!ruleId" in body
    # The guard must run before the bridge call.
    guard_pos = body.find("!ruleId")
    bridge_pos = body.find('App.callBridge("set_project_rule_enabled"')
    assert guard_pos < bridge_pos


def test_project_rules_toggle_rejects_unknown_rule_type_from_dataset():
    # Phase 5B.1 regression lock: the dataset ``data-rule-type`` must be
    # validated against ``folder`` / ``keyword`` before the bridge call so
    # a malformed dataset cannot trigger an arbitrary write.
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    assert 'ruleType !== "folder" && ruleType !== "keyword"' in body
    # The type check must run before the bridge call.
    type_check_pos = body.find('ruleType !== "folder" && ruleType !== "keyword"')
    bridge_pos = body.find('App.callBridge("set_project_rule_enabled"')
    assert type_check_pos < bridge_pos


def test_project_rules_toggle_cancellation_does_not_call_bridge():
    # Phase 5B.1 regression lock: when the user cancels the disable
    # confirmation, the handler must ``return`` immediately without calling
    # ``App.setProjectRuleSaving`` or the bridge.
    source = read_js("rules.js")
    body = func_body(source, "handleProjectRuleToggle")
    confirm_pos = body.find("window.confirm")
    # The ``return;`` immediately after the confirm guard is the cancellation
    # path. Verify the bridge call is not inside the cancellation branch.
    bridge_pos = body.find('App.callBridge("set_project_rule_enabled"')
    assert confirm_pos < bridge_pos
    # Locate the cancellation ``return;`` that closes the confirm branch.
    # The body contains: ``if (!nextEnabled && !window.confirm("...")) { return; }``
    cancellation_return = body.find("return;", confirm_pos)
    assert cancellation_return != -1 and cancellation_return < bridge_pos


def test_project_rules_no_duplicate_static_dom_ids_in_section():
    # Phase 5B.1 regression lock: the static ``page-rules`` section in
    # ``index.html`` must not declare the same DOM id twice. Dynamic ids
    # (rendered by JS at runtime) are out of scope here.
    import re as _re

    section = _rules_section()
    ids = _re.findall(r'\sid="([^"]+)"', section)
    seen: set[str] = set()
    duplicates: list[str] = []
    for dom_id in ids:
        if dom_id in seen:
            duplicates.append(dom_id)
        seen.add(dom_id)
    assert not duplicates, "duplicate DOM id in page-rules section: " + ", ".join(duplicates)


def test_project_rules_state_isolation_across_loading_saving_error():
    # Phase 5B.1 regression lock: the four rule-page UI states
    # (loading / saving / error / empty) must be represented by separate
    # DOM ids so they cannot visually pollute each other.
    section = _rules_section()
    for required_id in (
        "rules-loading",
        "rules-error",
        "rules-empty",
        "rules-list",
    ):
        assert 'id="' + required_id + '"' in section
    # The saving state lives on the toggle buttons themselves (``正在更新…``
    # label + ``disabled`` attribute), not as a separate top-level banner
    # that could conflict with loading / error / empty banners.
    source = read_js("rules.js")
    assert "正在更新…" in source
    # Loading and error banners are separate DOM nodes.
    assert 'getElementById("rules-loading")' in source
    assert 'getElementById("rules-error")' in source
    # No code path writes the loading banner text into the error banner.
    assert "rules-error" not in func_body(source, "setRulesLoading")
    assert "rules-loading" not in func_body(source, "showRulesError")


def test_project_rules_bridge_call_only_allows_toggle_write():
    # Phase 5B.1 regression lock: ``set_project_rule_enabled`` and
    # ``create_project_keyword_rule`` (Phase 5C) are the only Project Rules
    # write bridge calls anywhere in the frontend. No other write bridge
    # call (project toggle / create / edit / delete / preview / backfill)
    # may be introduced even in init.js / core.js.
    source = read_all_js()
    assert 'callBridge("set_project_rule_enabled"' in source
    assert 'callBridge("create_project_keyword_rule"' in source
    # The forbidden write method names are already covered by
    # ``test_project_rules_js_does_not_call_forbidden_write_methods``; here
    # we additionally guard against accidental bridge call strings.
    for forbidden_call in (
        'callBridge("set_project_enabled"',
        'callBridge("create_project"',
        'callBridge("update_project"',
        'callBridge("delete_project"',
        'callBridge("archive_project"',
        'callBridge("create_keyword_rule"',
        'callBridge("create_or_update_folder_rule"',
        'callBridge("delete_keyword_rule"',
        'callBridge("delete_folder_rule"',
        'callBridge("preview_folder_rule_conflicts"',
        'callBridge("backfill_folder_rule"',
        'callBridge("automatic_rules"',
    ):
        assert forbidden_call not in source, (
            "frontend must not call forbidden Project Rules write bridge: "
            + forbidden_call
        )


def test_project_rules_init_does_not_bind_project_or_rule_create_events():
    # Phase 5B.1 regression lock: the init module must not bind any
    # create / edit / delete / project-toggle events for Project Rules.
    # The only Project Rules event binding is the click delegation on the
    # rules list, set up inside ``rules.js`` (Phase 5B), plus the keyword
    # create submit button (Phase 5C).
    source = read_js("init.js")
    for forbidden in (
        "rules-add",
        "rules-create",
        "rules-edit",
        "rules-delete",
        "project-add",
        "project-edit",
        "project-delete",
        "project-enable",
        "project-disable",
        "rule-add",
        "rule-edit",
        "rule-delete",
        "rule-enable",
        "rule-disable",
    ):
        assert forbidden not in source, (
            "init.js must not bind Project Rules create/edit/delete/project-toggle event: "
            + forbidden
        )


# --- Phase 5C: keyword rule creation foundation static contract ----------


def test_project_rules_keyword_create_form_anchors_exist():
    # Phase 5C regression lock: the Project Rules page must contain the
    # stable keyword create form DOM anchors.
    section = _rules_section()
    for dom_id in (
        "rules-keyword-create-form",
        "rules-keyword-create-project",
        "rules-keyword-create-input",
        "rules-keyword-create-submit",
        "rules-keyword-create-status",
    ):
        assert 'id="' + dom_id + '"' in section, (
            "Project Rules page must contain keyword create anchor: " + dom_id
        )


def test_project_rules_keyword_create_form_has_project_selector():
    section = _rules_section()
    assert '<select id="rules-keyword-create-project"' in section


def test_project_rules_keyword_create_form_has_keyword_input():
    section = _rules_section()
    assert '<input id="rules-keyword-create-input"' in section
    assert 'type="text"' in section


def test_project_rules_keyword_create_submit_button_exists():
    section = _rules_section()
    assert '<button id="rules-keyword-create-submit"' in section
    assert 'type="button"' in section


def test_project_rules_keyword_create_submit_is_only_new_create_action():
    # Phase 5C regression lock: the keyword create submit button is the
    # only new create action on the Project Rules page. No folder create,
    # project create/edit/delete, or rule edit/delete buttons may appear.
    section = _rules_section()
    import re as _re

    buttons = _re.findall(r"<button[^>]*>", section, _re.IGNORECASE)
    assert len(buttons) == 1
    assert 'id="rules-keyword-create-submit"' in buttons[0]
    for forbidden_id in (
        "rules-folder-create",
        "rules-project-create",
        "rules-project-edit",
        "rules-project-delete",
        "rules-keyword-edit",
        "rules-keyword-delete",
        "rules-folder-edit",
        "rules-folder-delete",
    ):
        assert 'id="' + forbidden_id + '"' not in section


def test_project_rules_keyword_create_form_has_empty_hint():
    # Phase 5C regression lock: the form must include an empty hint that
    # shows when no target projects are available, disabling the submit.
    section = _rules_section()
    assert 'id="rules-keyword-create-empty"' in section


def test_project_rules_keyword_create_state_variable_declared():
    # Phase 5C regression lock: the keyword create saving state must be a
    # separate state variable from the Phase 5B toggle saving state so the
    # two write paths can never pollute each other.
    source = read_js("core.js")
    assert "App.rulesCreatingKeyword = false" in source
    # The toggle saving state must still exist alongside it.
    assert "App.rulesSavingRuleKey = null" in source


def test_project_rules_keyword_create_js_calls_bridge_method():
    # Phase 5C regression lock: the JS must call the
    # ``create_project_keyword_rule`` bridge method.
    source = read_js("rules.js")
    assert 'callBridge("create_project_keyword_rule"' in source


def test_project_rules_keyword_create_js_does_not_call_folder_create():
    source = read_js("rules.js")
    assert 'callBridge("create_or_update_folder_rule"' not in source
    assert "createOrUpdateFolderRule" not in source


def test_project_rules_keyword_create_js_does_not_call_project_write():
    source = read_js("rules.js")
    for forbidden in (
        'callBridge("create_project"',
        'callBridge("update_project"',
        'callBridge("delete_project"',
        'callBridge("archive_project"',
        'callBridge("set_project_enabled"',
    ):
        assert forbidden not in source


def test_project_rules_keyword_create_js_does_not_call_rule_edit_delete():
    source = read_js("rules.js")
    for forbidden in (
        'callBridge("delete_keyword_rule"',
        'callBridge("delete_folder_rule"',
        'callBridge("set_keyword_rule_enabled"',
        'callBridge("set_folder_rule_enabled"',
    ):
        assert forbidden not in source


def test_project_rules_keyword_create_js_does_not_call_preview_or_backfill():
    source = read_js("rules.js")
    assert 'callBridge("preview_folder_rule_conflicts"' not in source
    assert 'callBridge("backfill_folder_rule"' not in source


def test_project_rules_keyword_create_js_validates_project_id_before_bridge():
    # Phase 5C regression lock: the JS must parse and validate the project
    # id (``projectId > 0``) before calling the bridge.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "parseInt(select.value, 10)" in body
    assert "!(projectId > 0)" in body
    guard_pos = body.find("!(projectId > 0)")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_keyword_create_js_validates_keyword_before_bridge():
    # Phase 5C regression lock: the JS must validate the keyword is
    # non-empty before calling the bridge.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "!keyword" in body
    guard_pos = body.find("!keyword")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_keyword_create_js_trims_keyword_before_bridge():
    # Phase 5C regression lock: the JS must trim the keyword before
    # validation and before the bridge call.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    assert ".trim()" in body
    trim_pos = body.find(".trim()")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert trim_pos != -1 and bridge_pos != -1
    assert trim_pos < bridge_pos


def test_project_rules_keyword_create_js_has_creating_guard():
    # Phase 5C regression lock: the handler must early-return when a
    # keyword create is already in flight, before any bridge call.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "if (App.rulesCreatingKeyword) return" in body
    guard_pos = body.find("if (App.rulesCreatingKeyword) return")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_keyword_create_js_has_creating_button_label():
    # Phase 5C regression lock: the creating button text must remain the
    # stable ``正在新增…`` label.
    source = read_js("rules.js")
    body = func_body(source, "setKeywordCreateCreating")
    assert "正在新增…" in body


def test_project_rules_keyword_create_js_success_refreshes_project_rules():
    # Phase 5C regression lock: the success path must call
    # ``loadProjectRules()`` to refresh the Project Rules list.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "App.loadProjectRules()" in body


def test_project_rules_keyword_create_js_success_clears_keyword_input():
    # Phase 5C regression lock: the success path must clear the keyword
    # input so the user can immediately create another rule.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    assert 'input.value = ""' in body
    # The clear must run before the refresh (success path).
    clear_pos = body.find('input.value = ""')
    refresh_pos = body.find("App.loadProjectRules()")
    assert clear_pos != -1 and refresh_pos != -1
    assert clear_pos < refresh_pos


def test_project_rules_keyword_create_js_failure_preserves_rendered_list():
    # Phase 5C regression lock: the failure path must not clear the
    # already-rendered Project Rules list. The handler may only show a
    # status message on failure, never ``list.innerHTML = ""`` or
    # ``showProjectRules`` with an empty payload.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body


def test_project_rules_keyword_create_js_failure_preserves_keyword_input():
    # Phase 5C regression lock: the failure path must not clear the
    # keyword input so the user can edit and retry.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    # The only ``input.value = ""`` must be inside the success branch
    # (after the ``result.ok === false`` check). Verify there is exactly
    # one input clear and it appears after the failure-check guard.
    assert body.count('input.value = ""') == 1
    failure_guard = body.find("result && result.ok === false")
    clear_pos = body.find('input.value = ""')
    assert failure_guard != -1 and clear_pos != -1
    assert failure_guard < clear_pos


def test_project_rules_keyword_create_js_catch_never_reads_raw_exception():
    # Phase 5C regression lock: the catch path must never read
    # ``.message`` from the error.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_keyword_create_js_uses_escape_helper_for_dynamic_text():
    # Phase 5C regression lock: dynamic text rendering must use the escape
    # helper. The keyword create status uses ``textContent`` (which is
    # HTML-safe), not ``innerHTML``.
    source = read_js("rules.js")
    status_body = func_body(source, "showKeywordCreateStatus")
    assert "textContent" in status_body
    assert ".innerHTML" not in status_body


def test_project_rules_keyword_create_state_isolation_from_toggle_saving():
    # Phase 5C regression lock: the keyword create saving state
    # (``rulesCreatingKeyword``) must be separate from the toggle saving
    # state (``rulesSavingRuleKey``). The two write paths must not pollute
    # each other's button / input disabled state. The check looks for
    # actual variable reads / writes (``App.rulesCreatingKeyword`` /
    # ``App.rulesSavingRuleKey``), not bare comment mentions.
    source = read_js("core.js")
    assert "App.rulesCreatingKeyword" in source
    assert "App.rulesSavingRuleKey" in source
    # The toggle saving handler must not read or write the keyword create
    # state variable.
    rules_source = read_js("rules.js")
    toggle_body = func_body(rules_source, "setProjectRuleSaving")
    assert "App.rulesCreatingKeyword" not in toggle_body
    # The keyword create handler must not read or write the toggle saving
    # state variable.
    create_body = func_body(rules_source, "setKeywordCreateCreating")
    assert "App.rulesSavingRuleKey" not in create_body


def test_project_rules_keyword_create_selector_population_guard():
    # Phase 5C regression lock: the project selector must not be
    # re-populated while a keyword create is in flight, so the user's
    # selection is never displaced by an auto-refresh.
    source = read_js("rules.js")
    body = func_body(source, "populateKeywordCreateProjectSelector")
    assert "if (App.rulesCreatingKeyword) return" in body


def test_project_rules_keyword_create_stale_guard_preserved():
    # Phase 5C regression lock: the existing ``rulesRequestToken`` stale
    # guard in ``loadProjectRules`` must remain intact. The keyword create
    # success path calls ``loadProjectRules()`` which inherits this
    # protection.
    source = read_js("rules.js")
    load_body = func_body(source, "loadProjectRules")
    assert "var token = ++App.rulesRequestToken" in load_body
    assert load_body.count("token !== App.rulesRequestToken") >= 2


def test_project_rules_keyword_create_no_storage_or_network():
    # Phase 5C regression lock: the keyword create form must not use
    # browser storage or network APIs.
    source = read_js("rules.js")
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "fetch(",
        "XMLHttpRequest",
    ):
        assert forbidden not in source


def test_project_rules_keyword_create_init_binds_submit_button():
    # Phase 5C regression lock: the init module must bind the keyword
    # create submit button click event.
    source = read_js("init.js")
    assert 'getElementById("rules-keyword-create-submit")' in source
    assert "App.handleKeywordCreateSubmit" in source


def test_project_rules_keyword_create_no_app_js_reintroduced():
    # Phase 5C regression lock: the frontend must not reintroduce app.js.
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_keyword_create_no_forbidden_handler_tokens():
    # Phase 5C regression lock: the keyword create JS must not introduce
    # any of the forbidden camelCase handler tokens.
    source = read_js("rules.js")
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source


# --- Phase 5C.1: keyword creation hardening static-contract locks ---------


def test_project_rules_keyword_create_creating_state_clears_on_all_paths():
    # Phase 5C.1 regression lock: the creating state must clear on success,
    # on failure (ok=false), and on rejected promise. The handler achieves
    # this by chaining ``App.setKeywordCreateCreating(false)`` in the final
    # ``.then`` that runs after ``.catch`` (which always resolves).
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "App.setKeywordCreateCreating(true)" in body
    # The final cleanup must run unconditionally after the catch.
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setKeywordCreateCreating(false)", catch_pos)
    assert cleanup_pos != -1, (
        "App.setKeywordCreateCreating(false) must run after .catch so the "
        "creating state clears on success, failure, and rejected-promise paths"
    )


def test_project_rules_keyword_create_whitespace_keyword_does_not_call_bridge():
    # Phase 5C.1 regression lock: a whitespace-only keyword must be trimmed
    # to empty and rejected before any bridge call. The handler must
    # ``return`` immediately after showing the status, without calling
    # ``App.callBridge``.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    # The trim happens before the empty check.
    trim_pos = body.find(".trim()")
    empty_guard_pos = body.find("!keyword")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert trim_pos != -1 and empty_guard_pos != -1 and bridge_pos != -1
    assert trim_pos < empty_guard_pos < bridge_pos
    # The return after the empty guard must precede the bridge call.
    return_pos = body.find("return;", empty_guard_pos)
    assert return_pos != -1 and return_pos < bridge_pos


def test_project_rules_keyword_create_success_path_order_clear_then_refresh():
    # Phase 5C.1 regression lock: the success path must clear the keyword
    # input, then refresh the Project Rules list, then show the success
    # status — in that order.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    clear_pos = body.find('input.value = ""')
    refresh_pos = body.find("App.loadProjectRules()")
    success_pos = body.find('showKeywordCreateStatus("关键词规则已新增"')
    assert clear_pos != -1 and refresh_pos != -1 and success_pos != -1
    assert clear_pos < refresh_pos < success_pos


def test_project_rules_keyword_create_failure_does_not_clear_selector():
    # Phase 5C.1 regression lock: the failure path must not clear the
    # project selector. The handler may only show a status message on
    # failure, never reset ``select.value`` or ``select.innerHTML``.
    source = read_js("rules.js")
    body = func_body(source, "handleKeywordCreateSubmit")
    failure_guard = body.find("result && result.ok === false")
    assert failure_guard != -1
    # The failure branch runs from the ``ok === false`` guard to the
    # ``.catch`` that follows it. Selector writes (``select.value =`` /
    # ``select.innerHTML``) must not appear in that branch.
    failure_branch = body[failure_guard : body.find(".catch(function ()", failure_guard)]
    assert "select.value =" not in failure_branch
    assert "select.innerHTML" not in failure_branch


def test_project_rules_keyword_create_no_duplicate_static_dom_ids_in_form():
    # Phase 5C.1 regression lock: the keyword create form must not declare
    # the same DOM id twice.
    import re as _re

    section = _rules_section()
    # Extract just the form portion.
    form_start = section.find('id="rules-keyword-create-form"')
    assert form_start != -1
    form_end = section.find("</form>", form_start)
    assert form_end != -1
    form_html = section[form_start : form_end + len("</form>")]
    ids = _re.findall(r'\sid="([^"]+)"', form_html)
    seen: set[str] = set()
    duplicates: list[str] = []
    for dom_id in ids:
        if dom_id in seen:
            duplicates.append(dom_id)
        seen.add(dom_id)
    assert not duplicates, "duplicate DOM id in keyword create form: " + ", ".join(duplicates)


def test_project_rules_keyword_create_status_uses_textcontent_not_innerhtml():
    # Phase 5C.1 regression lock: the keyword create status element must be
    # updated via ``textContent`` (HTML-safe), never ``innerHTML``. This
    # ensures a keyword containing HTML/script content can never execute in
    # the status banner even if it appears in an error message.
    source = read_js("rules.js")
    status_body = func_body(source, "showKeywordCreateStatus")
    assert "textContent" in status_body
    assert ".innerHTML" not in status_body
