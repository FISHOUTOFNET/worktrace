"""Project Rules WebView static-contract tests.

These tests read bundled frontend resources directly. They lock the
Project Rules WebView static surface (rule toggle, keyword create /
edit / delete, folder CRUD, project lifecycle, and the
frontend modularization) without starting pywebview or touching the
database.

The Project Rules surface spans six classic IIFE
modules loaded in order: rules.js, rules_render.js,
rules_rule_actions.js, rules_keyword_actions.js,
rules_folder_actions.js, rules_project_actions.js. Tests that need
to check substring contracts or ``func_body`` across the full
Project Rules surface use ``read_rules_module_js()`` so the split
does not silently break contracts that moved.
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
    read_rules_module_js,
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


def test_project_rules_boundary_copy_lists_supported_capabilities():
    section = _rules_section()
    # Boundary copy: the boundary copy mentions project lifecycle
    assert "启用/停用" in section
    assert "新增关键词规则" in section
    for term in ("编辑", "归档", "预览规则影响", "应用到历史记录"):
        assert term in section


def test_project_rules_page_has_no_static_action_buttons():
    section = _rules_section()
    import re as _re

    buttons = _re.findall(r"<button[^>]*>", section, _re.IGNORECASE)
    assert len(buttons) == 3, (
        "Project Rules page must have exactly three static buttons (project "
        "create submit + keyword create submit + folder create submit); "
        "found: " + repr(buttons)
    )
    button_ids = [_re.search(r'id="([^"]+)"', b) for b in buttons]
    button_ids = [m.group(1) for m in button_ids if m]
    assert "rules-project-create-submit" in button_ids
    assert "rules-keyword-create-submit" in button_ids
    assert "rules-folder-create-submit" in button_ids
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
    actions_pos = source.find('src="js/rules_project_actions.js"')
    init_pos = source.find('src="js/init.js"')
    assert statistics_pos != -1
    assert rules_pos != -1
    assert init_pos != -1
    assert statistics_pos < rules_pos
    assert rules_pos < init_pos
    assert actions_pos != -1, "index.html must include rules_project_actions.js"
    assert rules_pos < actions_pos < init_pos


def test_project_rules_js_in_static_helper_order():
    assert "rules.js" in ALL_JS_FILES
    assert "rules_project_actions.js" in ALL_JS_FILES
    assert "settings.js" in ALL_JS_FILES
    assert ALL_JS_FILES.index("settings.js") == ALL_JS_FILES.index("statistics.js") + 1
    assert ALL_JS_FILES.index("rules.js") == ALL_JS_FILES.index("settings.js") + 1
    assert ALL_JS_FILES.index("rules_render.js") == ALL_JS_FILES.index("rules.js") + 1
    assert ALL_JS_FILES.index("rules_rule_actions.js") == ALL_JS_FILES.index("rules_render.js") + 1
    assert ALL_JS_FILES.index("rules_keyword_actions.js") == ALL_JS_FILES.index("rules_rule_actions.js") + 1
    assert ALL_JS_FILES.index("rules_folder_actions.js") == ALL_JS_FILES.index("rules_keyword_actions.js") + 1
    assert ALL_JS_FILES.index("rules_project_actions.js") == ALL_JS_FILES.index("rules_folder_actions.js") + 1
    assert ALL_JS_FILES.index("init.js") == ALL_JS_FILES.index("rules_project_actions.js") + 1


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
    source = read_rules_module_js()
    assert 'callBridge("get_project_rules")' in source
    assert 'callBridge("set_project_rule_enabled"' in source
    # delete_project_keyword_rule is the new allowed write bridge.
    assert 'callBridge("delete_project_keyword_rule"' in source
    # folder rule create/update/delete are the new allowed write bridges.
    assert 'callBridge("create_project_folder_rule"' in source
    assert 'callBridge("update_project_folder_rule"' in source
    assert 'callBridge("delete_project_folder_rule"' in source
    assert 'callBridge("set_project_enabled"' not in source


def test_project_rules_load_has_loading_guard_and_stale_guard():
    source = read_rules_module_js()
    body = func_body(source, "loadProjectRules")
    assert "if (App.rulesLoading)" in body
    assert "var token = ++App.rulesRequestToken" in body
    assert body.count("token !== App.rulesRequestToken") >= 2
    assert "App.setRulesLoading(true)" in body
    assert "App.setRulesLoading(false)" in body


def test_project_rules_failure_paths_use_stable_fallback_only():
    source = read_rules_module_js()
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
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    assert 'App.callBridge("set_project_rule_enabled", ruleType, ruleId, nextEnabled)' in body
    assert 'ruleType !== "folder" && ruleType !== "keyword"' in body
    assert "App.rulesSavingRuleKey" in body
    assert "window.confirm" in body
    assert "确定停用这条规则吗？停用后它将不再用于自动归类。" in body


def test_project_rules_toggle_success_refreshes_and_failure_keeps_rendered_data():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    assert "App.loadProjectRules()" in body
    assert "规则状态已更新" in body
    assert "更新规则状态失败" in body
    assert "list.innerHTML" not in body


def test_project_rules_toggle_catch_never_reads_raw_exception_message():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    assert ".catch(function ()" in body
    for forbidden in ("err.message", "error.message", ".toString", "reason.message"):
        assert forbidden not in body


def test_project_rules_rendering_uses_escape_helper():
    source = read_rules_module_js()
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
    # the check uses bridge call string patterns (``callBridge("
    for method in PROJECT_RULE_WRITE_METHODS:
        forbidden_call = 'callBridge("' + method + '"'
        assert forbidden_call not in source, (
            "Project Rules frontend must not call write bridge method: " + method
        )
    assert 'callBridge("set_project_rule_enabled"' in source
    assert 'callBridge("create_project_keyword_rule"' in source
    # delete_project_keyword_rule is the new allowed write bridge.
    assert 'callBridge("delete_project_keyword_rule"' in source
    # folder rule create/update/delete are the new allowed write bridges.
    assert 'callBridge("create_project_folder_rule"' in source
    assert 'callBridge("update_project_folder_rule"' in source
    assert 'callBridge("delete_project_folder_rule"' in source


def test_project_rules_js_has_no_create_edit_delete_backfill_preview_handlers():
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source
    for forbidden in ("project-enable", "project-disable", "projectToggle"):
        assert forbidden not in source


def test_project_rules_js_catch_path_never_reads_raw_exception_message():
    source = read_rules_module_js()
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
    """``refreshAll`` is the manual refresh button entry
    point and now delegates to ``refreshCurrentPageData`` which is
    page-scoped (status + current page live data). Rules / Settings /
    Statistics are NOT included in the heartbeat auto-refresh or the
    low-frequency reconciliation; they keep their own page-level refresh
    buttons. This test verifies:
      1. ``refreshAll`` / ``refreshCurrentPageData`` does NOT push
         ``loadProjectRules()`` into its promises.
      2. The heartbeat / reconciliation path does NOT call
         ``loadProjectRules()``.
      3. Rules are still lazy-loaded on first navigation to the rules page
         via ``switchPage`` (covered separately by
         ``test_project_rules_lazy_loads_on_first_navigation_only``)."""
    source = read_js("init.js")
    body = func_body(source, "refreshAll")
    # refreshAll now delegates to refreshCurrentPageData; it must NOT
    assert "promises.push(App.loadProjectRules())" not in body, (
        "refreshAll must not push loadProjectRules; rules are not part of "
        "the page-scoped heavy refresh"
    )
    rcp_body = func_body(source, "refreshCurrentPageData")
    assert "loadProjectRules" not in rcp_body, (
        "refreshCurrentPageData must not reference loadProjectRules; rules "
        "are only lazy-loaded on page switch, not on heartbeat refresh"
    )
    rec_body = func_body(source, "fullReconcileCollectionViews")
    assert "loadProjectRules" not in rec_body, (
        "fullReconcileCollectionViews must not reference loadProjectRules; "
        "low-frequency reconciliation never refreshes Rules"
    )


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
    assert "'rules_project_actions.js'" in source or '"rules_project_actions.js"' in source
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
    source = read_rules_module_js()
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




def test_project_rules_toggle_button_is_inside_rule_row_not_project_card():
    # LIFECYCLE toggle button (``rules-project-toggle-button`` class) which
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    row_body = func_body(source, "renderProjectRuleRow")
    assert "rules-toggle-btn" in row_body
    assert "rules-toggle-btn" not in project_body
    # bridge call (without the ``_for_rules`` suffix) must never appear.
    for forbidden in (
        'data-rule-type="project"',
        "setProjectEnabled",
        'callBridge("set_project_enabled"',
    ):
        assert forbidden not in project_body


def test_project_rules_toggle_handler_clears_saving_state_on_all_paths():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    assert "App.setProjectRuleSaving(ruleType" in body
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setProjectRuleSaving(null)", catch_pos)
    assert cleanup_pos != -1, (
        "App.setProjectRuleSaving(null) must run after .catch so the saving "
        "state clears on success, failure, and rejected-promise paths"
    )


def test_project_rules_toggle_handler_single_in_flight_guard():
    # Regression lock: only one toggle write may be in flight at
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    guard_pos = body.find("App.rulesSavingRuleKey")
    confirm_pos = body.find("window.confirm")
    bridge_pos = body.find('App.callBridge("set_project_rule_enabled"')
    assert guard_pos != -1 and confirm_pos != -1 and bridge_pos != -1
    assert guard_pos < confirm_pos < bridge_pos, (
        "in-flight guard must run before confirmation dialog and bridge call"
    )


def test_project_rules_toggle_button_saving_label_present():
    # stable ``正在更新…`` label so the user sees a clear in-progress state.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "正在更新…" in row_body
    set_saving_body = func_body(source, "setProjectRuleSaving")
    assert "正在更新…" in set_saving_body


def test_project_rules_toggle_success_then_refresh_chain():
    # Regression lock: the success path must call
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    refresh_pos = body.find("App.loadProjectRules()")
    success_pos = body.find("规则状态已更新")
    assert refresh_pos != -1 and success_pos != -1
    assert refresh_pos < success_pos


def test_project_rules_toggle_failure_keeps_existing_list_rendered():
    # Regression lock: the failure path must not clear the
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body


def test_project_rules_toggle_dataset_id_is_parsed_and_validated():
    # result is NaN or 0, before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    assert 'parseInt(button.getAttribute("data-rule-id"), 10)' in body
    assert "!ruleId" in body
    # The guard must run before the bridge call.
    guard_pos = body.find("!ruleId")
    bridge_pos = body.find('App.callBridge("set_project_rule_enabled"')
    assert guard_pos < bridge_pos


def test_project_rules_toggle_rejects_unknown_rule_type_from_dataset():
    # validated against ``folder`` / ``keyword`` before the bridge call so
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    assert 'ruleType !== "folder" && ruleType !== "keyword"' in body
    # The type check must run before the bridge call.
    type_check_pos = body.find('ruleType !== "folder" && ruleType !== "keyword"')
    bridge_pos = body.find('App.callBridge("set_project_rule_enabled"')
    assert type_check_pos < bridge_pos


def test_project_rules_toggle_cancellation_does_not_call_bridge():
    # confirmation, the handler must ``return`` immediately without calling
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    confirm_pos = body.find("window.confirm")
    # path. Verify the bridge call is not inside the cancellation branch.
    bridge_pos = body.find('App.callBridge("set_project_rule_enabled"')
    assert confirm_pos < bridge_pos
    cancellation_return = body.find("return;", confirm_pos)
    assert cancellation_return != -1 and cancellation_return < bridge_pos


def test_project_rules_no_duplicate_static_dom_ids_in_section():
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
    section = _rules_section()
    for required_id in (
        "rules-loading",
        "rules-error",
        "rules-empty",
        "rules-list",
    ):
        assert 'id="' + required_id + '"' in section
    source = read_rules_module_js()
    assert "正在更新…" in source
    assert 'getElementById("rules-loading")' in source
    assert 'getElementById("rules-error")' in source
    # No code path writes the loading banner text into the error banner.
    assert "rules-error" not in func_body(source, "setRulesLoading")
    assert "rules-loading" not in func_body(source, "showRulesError")


def test_project_rules_bridge_call_only_allows_toggle_write():
    # write bridge calls anywhere in the frontend. No other write bridge
    source = read_all_js()
    assert 'callBridge("set_project_rule_enabled"' in source
    assert 'callBridge("create_project_keyword_rule"' in source
    # delete_project_keyword_rule is the new allowed write bridge.
    assert 'callBridge("delete_project_keyword_rule"' in source
    # folder rule create/update/delete are the new allowed write bridges.
    assert 'callBridge("create_project_folder_rule"' in source
    assert 'callBridge("update_project_folder_rule"' in source
    assert 'callBridge("delete_project_folder_rule"' in source
    # The forbidden write method names are already covered by
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




def test_project_rules_keyword_create_form_anchors_exist():
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
    # regression lock (updated in folder CRUD and lifecycle): the project
    section = _rules_section()
    import re as _re

    buttons = _re.findall(r"<button[^>]*>", section, _re.IGNORECASE)
    assert len(buttons) == 3
    button_ids = [_re.search(r'id="([^"]+)"', b) for b in buttons]
    button_ids = [m.group(1) for m in button_ids if m]
    assert "rules-project-create-submit" in button_ids
    assert "rules-keyword-create-submit" in button_ids
    assert "rules-folder-create-submit" in button_ids
    for forbidden_id in (
        "rules-project-edit",
        "rules-project-delete",
        "rules-keyword-edit",
        "rules-keyword-delete",
        "rules-folder-edit",
        "rules-folder-delete",
    ):
        assert 'id="' + forbidden_id + '"' not in section


def test_project_rules_keyword_create_form_has_empty_hint():
    section = _rules_section()
    assert 'id="rules-keyword-create-empty"' in section


def test_project_rules_keyword_create_state_variable_declared():
    # two write paths can never pollute each other.
    source = read_js("core.js")
    assert "App.rulesCreatingKeyword = false" in source
    assert "App.rulesSavingRuleKey = null" in source


def test_project_rules_keyword_create_js_calls_bridge_method():
    # ``create_project_keyword_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("create_project_keyword_rule"' in source


def test_project_rules_keyword_create_js_does_not_call_folder_create():
    source = read_rules_module_js()
    assert 'callBridge("create_or_update_folder_rule"' not in source
    assert "createOrUpdateFolderRule" not in source


def test_project_rules_keyword_create_js_does_not_call_project_write():
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("create_project"',
        'callBridge("update_project"',
        'callBridge("delete_project"',
        'callBridge("archive_project"',
        'callBridge("set_project_enabled"',
    ):
        assert forbidden not in source


def test_project_rules_keyword_create_js_does_not_call_rule_edit_delete():
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("delete_keyword_rule"',
        'callBridge("delete_folder_rule"',
        'callBridge("set_keyword_rule_enabled"',
        'callBridge("set_folder_rule_enabled"',
    ):
        assert forbidden not in source


def test_project_rules_keyword_create_js_does_not_call_preview_or_backfill():
    source = read_rules_module_js()
    assert 'callBridge("preview_folder_rule_conflicts"' not in source
    assert 'callBridge("backfill_folder_rule"' not in source


def test_project_rules_keyword_create_js_validates_project_id_before_bridge():
    # id (``projectId > 0``) before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "parseInt(select.value, 10)" in body
    assert "!(projectId > 0)" in body
    guard_pos = body.find("!(projectId > 0)")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_keyword_create_js_validates_keyword_before_bridge():
    # non-empty before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "!keyword" in body
    guard_pos = body.find("!keyword")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_keyword_create_js_trims_keyword_before_bridge():
    # validation and before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert ".trim()" in body
    trim_pos = body.find(".trim()")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert trim_pos != -1 and bridge_pos != -1
    assert trim_pos < bridge_pos


def test_project_rules_keyword_create_js_has_creating_guard():
    # keyword create is already in flight, before any bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "if (App.rulesCreatingKeyword) return" in body
    guard_pos = body.find("if (App.rulesCreatingKeyword) return")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_keyword_create_js_has_creating_button_label():
    # stable ``正在新增…`` label.
    source = read_rules_module_js()
    body = func_body(source, "setKeywordCreateCreating")
    assert "正在新增…" in body


def test_project_rules_keyword_create_js_success_refreshes_project_rules():
    # Regression lock: the success path must call
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "App.loadProjectRules()" in body


def test_project_rules_keyword_create_js_success_clears_keyword_input():
    # Regression lock: the success path must clear the keyword
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert 'input.value = ""' in body
    # The clear must run before the refresh (success path).
    clear_pos = body.find('input.value = ""')
    refresh_pos = body.find("App.loadProjectRules()")
    assert clear_pos != -1 and refresh_pos != -1
    assert clear_pos < refresh_pos


def test_project_rules_keyword_create_js_failure_preserves_rendered_list():
    # Regression lock: the failure path must not clear the
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body


def test_project_rules_keyword_create_js_failure_preserves_keyword_input():
    # Regression lock: the failure path must not clear the
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert body.count('input.value = ""') == 1
    failure_guard = body.find("result && result.ok === false")
    clear_pos = body.find('input.value = ""')
    assert failure_guard != -1 and clear_pos != -1
    assert failure_guard < clear_pos


def test_project_rules_keyword_create_js_catch_never_reads_raw_exception():
    # Regression lock: the catch path must never read
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_keyword_create_js_uses_escape_helper_for_dynamic_text():
    # helper. The keyword create status uses ``textContent`` (which is
    source = read_rules_module_js()
    status_body = func_body(source, "showKeywordCreateStatus")
    assert "textContent" in status_body
    assert ".innerHTML" not in status_body


def test_project_rules_keyword_create_state_isolation_from_toggle_saving():
    # state (``rulesSavingRuleKey``). The two write paths must not pollute
    source = read_js("core.js")
    assert "App.rulesCreatingKeyword" in source
    assert "App.rulesSavingRuleKey" in source
    # The toggle saving handler must not read or write the keyword create
    rules_source = read_rules_module_js()
    toggle_body = func_body(rules_source, "setProjectRuleSaving")
    assert "App.rulesCreatingKeyword" not in toggle_body
    # The keyword create handler must not read or write the toggle saving
    create_body = func_body(rules_source, "setKeywordCreateCreating")
    assert "App.rulesSavingRuleKey" not in create_body


def test_project_rules_keyword_create_selector_population_guard():
    source = read_rules_module_js()
    body = func_body(source, "populateKeywordCreateProjectSelector")
    assert "if (App.rulesCreatingKeyword) return" in body


def test_project_rules_keyword_create_stale_guard_preserved():
    # Regression lock: the existing ``rulesRequestToken`` stale
    source = read_rules_module_js()
    load_body = func_body(source, "loadProjectRules")
    assert "var token = ++App.rulesRequestToken" in load_body
    assert load_body.count("token !== App.rulesRequestToken") >= 2


def test_project_rules_keyword_create_no_storage_or_network():
    # browser storage or network APIs.
    source = read_rules_module_js()
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "fetch(",
        "XMLHttpRequest",
    ):
        assert forbidden not in source


def test_project_rules_keyword_create_init_binds_submit_button():
    source = read_js("init.js")
    assert 'getElementById("rules-keyword-create-submit")' in source
    assert "App.handleKeywordCreateSubmit" in source


def test_project_rules_keyword_create_no_app_js_reintroduced():
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_keyword_create_no_forbidden_handler_tokens():
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source




def test_project_rules_keyword_create_creating_state_clears_on_all_paths():
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "App.setKeywordCreateCreating(true)" in body
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setKeywordCreateCreating(false)", catch_pos)
    assert cleanup_pos != -1, (
        "App.setKeywordCreateCreating(false) must run after .catch so the "
        "creating state clears on success, failure, and rejected-promise paths"
    )


def test_project_rules_keyword_create_whitespace_keyword_does_not_call_bridge():
    # to empty and rejected before any bridge call. The handler must
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    trim_pos = body.find(".trim()")
    empty_guard_pos = body.find("!keyword")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert trim_pos != -1 and empty_guard_pos != -1 and bridge_pos != -1
    assert trim_pos < empty_guard_pos < bridge_pos
    # The return after the empty guard must precede the bridge call.
    return_pos = body.find("return;", empty_guard_pos)
    assert return_pos != -1 and return_pos < bridge_pos


def test_project_rules_keyword_create_success_path_order_clear_then_refresh():
    # Regression lock: the success path must clear the keyword
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    clear_pos = body.find('input.value = ""')
    refresh_pos = body.find("App.loadProjectRules()")
    success_pos = body.find('showKeywordCreateStatus("关键词规则已新增"')
    assert clear_pos != -1 and refresh_pos != -1 and success_pos != -1
    assert clear_pos < refresh_pos < success_pos


def test_project_rules_keyword_create_failure_does_not_clear_selector():
    # Regression lock: the failure path must not clear the
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    failure_guard = body.find("result && result.ok === false")
    assert failure_guard != -1
    # ``.catch`` that follows it. Selector writes (``select.value =`` /
    failure_branch = body[failure_guard : body.find(".catch(function ()", failure_guard)]
    assert "select.value =" not in failure_branch
    assert "select.innerHTML" not in failure_branch


def test_project_rules_keyword_create_no_duplicate_static_dom_ids_in_form():
    import re as _re

    section = _rules_section()
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
    # updated via ``textContent`` (HTML-safe), never ``innerHTML``. This
    source = read_rules_module_js()
    status_body = func_body(source, "showKeywordCreateStatus")
    assert "textContent" in status_body
    assert ".innerHTML" not in status_body




def test_project_rules_keyword_delete_state_variable_declared():
    # the keyword create state so the three write paths can never
    source = read_js("core.js")
    assert "App.rulesDeletingRuleKey = null" in source
    assert "App.rulesSavingRuleKey = null" in source
    assert "App.rulesCreatingKeyword = false" in source


def test_project_rules_keyword_delete_js_calls_bridge_method():
    # ``delete_project_keyword_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("delete_project_keyword_rule"' in source


def test_project_rules_keyword_delete_js_does_not_call_folder_delete():
    source = read_rules_module_js()
    assert 'callBridge("delete_folder_rule"' not in source
    assert "deleteFolderRule" not in source


def test_project_rules_keyword_delete_js_does_not_call_project_write():
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("create_project"',
        'callBridge("update_project"',
        'callBridge("delete_project"',
        'callBridge("archive_project"',
        'callBridge("set_project_enabled"',
    ):
        assert forbidden not in source


def test_project_rules_keyword_delete_js_does_not_call_rule_edit_or_toggle():
    # Regression lock: the delete path must not invoke the toggle
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("set_keyword_rule_enabled"',
        'callBridge("set_folder_rule_enabled"',
        'callBridge("set_project_rule_enabled"',
    ):
        delete_body = func_body(source, "handleProjectRuleDelete")
        assert forbidden not in delete_body


def test_project_rules_keyword_delete_js_does_not_call_preview_or_backfill():
    source = read_rules_module_js()
    assert 'callBridge("preview_folder_rule_conflicts"' not in source
    assert 'callBridge("backfill_folder_rule"' not in source


def test_project_rules_keyword_delete_js_validates_rule_id_before_bridge():
    # before calling the bridge. Malformed dataset must not call bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert 'parseInt(rawId, 10)' in body
    assert "ruleId <= 0" in body
    guard_pos = body.find("ruleId <= 0")
    bridge_pos = body.find('callBridge("delete_project_keyword_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_keyword_delete_js_validates_rule_kind_before_bridge():
    # validated against ``keyword`` before the bridge call so a malformed
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert 'kind !== "keyword"' in body
    type_check_pos = body.find('kind !== "keyword"')
    bridge_pos = body.find('callBridge("delete_project_keyword_rule"')
    assert type_check_pos < bridge_pos


def test_project_rules_keyword_delete_js_has_deleting_guard():
    # keyword delete is already in flight, before any bridge call or
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert "if (App.rulesDeletingRuleKey) return" in body
    guard_pos = body.find("if (App.rulesDeletingRuleKey) return")
    confirm_pos = body.find("window.confirm")
    bridge_pos = body.find('callBridge("delete_project_keyword_rule"')
    assert guard_pos != -1 and confirm_pos != -1 and bridge_pos != -1
    assert guard_pos < confirm_pos < bridge_pos, (
        "in-flight guard must run before confirmation dialog and bridge call"
    )


def test_project_rules_keyword_delete_js_has_deleting_button_label():
    # stable ``正在删除…`` label.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "正在删除…" in row_body
    set_deleting_body = func_body(source, "setRuleDeleting")
    assert "正在删除…" in set_deleting_body


def test_project_rules_keyword_delete_js_confirmation_text_present():
    # Regression lock: the confirmation text must explicitly
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert "确定删除这条关键词规则吗？删除后该关键词将不再用于自动归类。" in body


def test_project_rules_keyword_delete_js_cancellation_does_not_call_bridge():
    # confirmation, the handler must ``return`` immediately without calling
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    confirm_pos = body.find("window.confirm")
    bridge_pos = body.find('callBridge("delete_project_keyword_rule"')
    assert confirm_pos < bridge_pos
    cancellation_return = body.find("return;", confirm_pos)
    assert cancellation_return != -1 and cancellation_return < bridge_pos


def test_project_rules_keyword_delete_js_success_refreshes_project_rules():
    # Regression lock: the success path must call
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert "App.loadProjectRules()" in body


def test_project_rules_keyword_delete_js_success_shows_stable_message():
    # Regression lock: the success path must show the stable
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    refresh_pos = body.find("App.loadProjectRules()")
    success_pos = body.find("关键词规则已删除")
    assert refresh_pos != -1 and success_pos != -1
    assert refresh_pos < success_pos


def test_project_rules_keyword_delete_js_failure_preserves_rendered_list():
    # Regression lock: the failure path must not clear the
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body
    assert "删除关键词规则失败" in body


def test_project_rules_keyword_delete_js_catch_never_reads_raw_exception():
    # Regression lock: the catch path must never read
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_keyword_delete_js_deleting_state_clears_on_all_paths():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert "App.setRuleDeleting(" in body
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setRuleDeleting(null)", catch_pos)
    assert cleanup_pos != -1, (
        "App.setRuleDeleting(null) must run after .catch so the deleting "
        "state clears on success, failure, and rejected-promise paths"
    )


def test_project_rules_keyword_delete_state_isolation_from_toggle_saving():
    # (``rulesCreatingKeyword``). The three write paths must not pollute
    source = read_js("core.js")
    assert "App.rulesDeletingRuleKey" in source
    assert "App.rulesSavingRuleKey" in source
    assert "App.rulesCreatingKeyword" in source
    # The toggle saving handler must not read or write the delete state.
    rules_source = read_rules_module_js()
    toggle_body = func_body(rules_source, "setProjectRuleSaving")
    assert "App.rulesDeletingRuleKey" not in toggle_body
    # The delete handler must not read or write the toggle saving state
    delete_body = func_body(rules_source, "handleProjectRuleDelete")
    assert "App.rulesSavingRuleKey" not in delete_body
    assert "App.rulesCreatingKeyword" not in delete_body


def test_project_rules_keyword_delete_state_isolation_from_keyword_create():
    # read or write the delete state.
    source = read_rules_module_js()
    create_body = func_body(source, "setKeywordCreateCreating")
    assert "App.rulesDeletingRuleKey" not in create_body


def test_project_rules_keyword_delete_button_only_on_keyword_rows():
    # renderProjectRuleRow function must gate the delete button on
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'kind === "keyword"' in row_body
    assert "rules-keyword-delete-button" in row_body
    project_body = func_body(source, "renderProjectRuleProject")
    assert "rules-keyword-delete-button" not in project_body


def test_project_rules_keyword_delete_button_uses_stable_class_and_attributes():
    # Regression lock: the delete button must use the stable
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'class="rules-keyword-delete-button"' in row_body
    assert 'data-rule-kind="keyword"' in row_body
    assert 'data-rule-id="' in row_body


def test_project_rules_keyword_delete_button_does_not_appear_on_folder_rows():
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    keyword_guard_pos = row_body.find('kind === "keyword"')
    delete_html_assign_pos = row_body.find("deleteButton = '", keyword_guard_pos)
    assert keyword_guard_pos != -1 and delete_html_assign_pos != -1
    assert keyword_guard_pos < delete_html_assign_pos


def test_project_rules_keyword_delete_button_disabled_when_any_write_in_flight():
    # rule write (toggle saving or keyword delete) is in flight on this row.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "App.rulesSavingRuleKey" in row_body
    assert "App.rulesDeletingRuleKey" in row_body
    toggle_disabled_pos = row_body.find("disabledAttr")
    assert toggle_disabled_pos != -1
    toggle_disabled_clause = row_body[toggle_disabled_pos:row_body.find("?", toggle_disabled_pos)]
    assert "rulesSavingRuleKey" in toggle_disabled_clause
    assert "rulesDeletingRuleKey" in toggle_disabled_clause


def test_project_rules_keyword_delete_set_rule_deleting_updates_toggle_buttons():
    # buttons while a delete is in flight so the toggle and delete paths
    source = read_rules_module_js()
    body = func_body(source, "setRuleDeleting")
    assert "rules-toggle-btn" in body
    assert "App.rulesSavingRuleKey" in body
    assert "App.rulesDeletingRuleKey" in body


def test_project_rules_keyword_delete_stale_guard_preserved():
    # Regression lock: the existing ``rulesRequestToken`` stale
    source = read_rules_module_js()
    load_body = func_body(source, "loadProjectRules")
    assert "var token = ++App.rulesRequestToken" in load_body
    assert load_body.count("token !== App.rulesRequestToken") >= 2


def test_project_rules_keyword_delete_no_storage_or_network():
    # browser storage or network APIs.
    source = read_rules_module_js()
    delete_body = func_body(source, "handleProjectRuleDelete")
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "fetch(",
        "XMLHttpRequest",
    ):
        assert forbidden not in delete_body


def test_project_rules_keyword_delete_js_uses_escape_helper_for_dynamic_text():
    source = read_rules_module_js()
    count_body = func_body(source, "count")
    assert "App.escapeHtml" in count_body
    row_body = func_body(source, "renderProjectRuleRow")
    assert "count(ruleId)" in row_body


def test_project_rules_keyword_delete_no_forbidden_handler_tokens():
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source


def test_project_rules_keyword_delete_init_does_not_bind_delete_event():
    source = read_js("init.js")
    for forbidden in (
        "rules-keyword-delete",
        "handleProjectRuleDelete",
        "setRuleDeleting",
    ):
        assert forbidden not in source, (
            "init.js must not bind Project Rules delete event: " + forbidden
        )


def test_project_rules_keyword_delete_no_app_js_reintroduced():
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_keyword_delete_no_duplicate_static_dom_ids():
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


def test_project_rules_keyword_delete_no_static_delete_button_in_html():
    section = _rules_section()
    assert "rules-keyword-delete-button" not in section
    assert "rules-folder-delete-button" not in section
    assert "rules-keyword-edit-button" not in section
    assert "rules-folder-edit-button" not in section


def test_project_rules_keyword_delete_page_has_no_export_or_auto_submit_controls():
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


def test_project_rules_keyword_delete_css_class_exists():
    # button has a stable visual style.
    source = read_resource("styles.css")
    assert ".rules-keyword-delete-button" in source
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"cdn", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_keyword_delete_packaging_spec_still_includes_rules_js():
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'rules.js'" in source or '"rules.js"' in source
    assert "'rules_project_actions.js'" in source or '"rules_project_actions.js"' in source
    assert "'worktrace/webview_ui/js'" in source or '"worktrace/webview_ui/js"' in source


def test_project_rules_keyword_delete_boundary_copy_present():
    section = _rules_section()
    assert "启用/停用" in section
    assert "新增关键词规则" in section
    for term in ("编辑", "归档", "预览规则影响", "应用到历史记录"):
        assert term in section


def test_project_rules_keyword_delete_js_does_not_call_create_or_folder_create():
    source = read_rules_module_js()
    delete_body = func_body(source, "handleProjectRuleDelete")
    for forbidden in (
        'callBridge("create_project_keyword_rule"',
        'callBridge("create_or_update_folder_rule"',
        'callBridge("create_keyword_rule"',
        'callBridge("create_project"',
    ):
        assert forbidden not in delete_body




def test_project_rules_keyword_delete_css_class_scoped_to_rules_page():
    css = read_resource("styles.css")
    assert ".rules-keyword-delete-button" in css
    assert ".rules-keyword-delete-button" == ".rules-keyword-delete-button"

    index = read_resource("index.html")
    for page_id in ("page-overview", "page-timeline", "page-statistics"):
        start = index.find('id="' + page_id + '"')
        assert start != -1, "index.html must contain " + page_id
        end = index.find("</section>", start)
        assert end != -1, page_id + " section must close"
        section = index[start:end]
        assert "rules-keyword-delete-button" not in section, (
            page_id + " section must not reference the Project Rules delete button class"
        )


def test_project_rules_keyword_delete_handler_does_not_read_global_toggle_or_create_state():
    # write the toggle saving state (``rulesSavingRuleKey``) or
    source = read_rules_module_js()
    delete_body = func_body(source, "handleProjectRuleDelete")
    assert "App.rulesSavingRuleKey" not in delete_body
    assert "App.rulesCreatingKeyword" not in delete_body
    assert "App.rulesDeletingRuleKey" in delete_body


def test_project_rules_keyword_delete_button_disabled_coordination_uses_deleting_state():
    # state (``rulesCreatingKeyword``), keeping the create and delete paths
    source = read_rules_module_js()
    body = func_body(source, "setRuleDeleting")
    assert "App.rulesDeletingRuleKey" in body
    assert "App.rulesSavingRuleKey" in body
    assert "rules-toggle-btn" in body
    assert "rules-keyword-delete-button" in body
    assert "App.rulesCreatingKeyword" not in body




def test_project_rules_folder_create_form_anchors_exist():
    # stable folder create form DOM anchors.
    section = _rules_section()
    for dom_id in (
        "rules-folder-create-form",
        "rules-folder-create-project",
        "rules-folder-create-input",
        "rules-folder-create-recursive",
        "rules-folder-create-submit",
        "rules-folder-create-status",
    ):
        assert 'id="' + dom_id + '"' in section, (
            "Project Rules page must contain folder create anchor: " + dom_id
        )


def test_project_rules_folder_create_form_has_project_selector():
    section = _rules_section()
    assert '<select id="rules-folder-create-project"' in section


def test_project_rules_folder_create_form_has_folder_path_input():
    section = _rules_section()
    assert '<input id="rules-folder-create-input"' in section


def test_project_rules_folder_create_form_has_recursive_checkbox():
    section = _rules_section()
    assert '<input id="rules-folder-create-recursive"' in section
    assert 'type="checkbox"' in section


def test_project_rules_folder_create_submit_button_exists():
    section = _rules_section()
    assert '<button id="rules-folder-create-submit"' in section
    assert 'type="button"' in section


def test_project_rules_folder_create_form_has_empty_hint():
    section = _rules_section()
    assert 'id="rules-folder-create-empty"' in section


def test_project_rules_folder_create_state_variable_declared():
    # so the five write paths can never pollute each other.
    source = read_js("core.js")
    assert "App.rulesCreatingFolder = false" in source
    assert "App.rulesEditingFolderKey = null" in source
    assert "App.rulesDeletingFolderKey = null" in source
    assert "App.lastProjectRulesData = null" in source
    assert "App.rulesSavingRuleKey = null" in source
    assert "App.rulesCreatingKeyword = false" in source
    assert "App.rulesDeletingRuleKey = null" in source


def test_project_rules_folder_create_js_calls_bridge_method():
    # ``create_project_folder_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("create_project_folder_rule"' in source


def test_project_rules_folder_update_js_calls_bridge_method():
    # ``update_project_folder_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("update_project_folder_rule"' in source


def test_project_rules_folder_delete_js_calls_bridge_method():
    # ``delete_project_folder_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("delete_project_folder_rule"' in source


def test_project_rules_folder_create_js_does_not_call_keyword_create_or_delete():
    # keyword create or keyword delete bridge methods.
    source = read_rules_module_js()
    create_body = func_body(source, "handleFolderCreateSubmit")
    for forbidden in (
        'callBridge("create_project_keyword_rule"',
        'callBridge("delete_project_keyword_rule"',
        'callBridge("delete_keyword_rule"',
    ):
        assert forbidden not in create_body


def test_project_rules_folder_delete_js_does_not_call_keyword_delete():
    # the keyword delete bridge method.
    source = read_rules_module_js()
    delete_body = func_body(source, "handleFolderDelete")
    for forbidden in (
        'callBridge("delete_project_keyword_rule"',
        'callBridge("delete_keyword_rule"',
        'callBridge("create_project_keyword_rule"',
    ):
        assert forbidden not in delete_body


def test_project_rules_folder_update_js_does_not_call_keyword_or_create():
    # keyword create/delete or folder create/delete bridge methods.
    source = read_rules_module_js()
    update_body = func_body(source, "handleFolderEditSave")
    for forbidden in (
        'callBridge("create_project_keyword_rule"',
        'callBridge("delete_project_keyword_rule"',
        'callBridge("create_project_folder_rule"',
        'callBridge("delete_project_folder_rule"',
    ):
        assert forbidden not in update_body


def test_project_rules_folder_js_does_not_call_preview_or_backfill():
    source = read_rules_module_js()
    assert 'callBridge("preview_folder_rule_conflicts"' not in source
    assert 'callBridge("backfill_folder_rule"' not in source


def test_project_rules_folder_js_does_not_call_project_write():
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("create_project"',
        'callBridge("update_project"',
        'callBridge("delete_project"',
        'callBridge("archive_project"',
        'callBridge("set_project_enabled"',
    ):
        assert forbidden not in source


def test_project_rules_folder_create_js_validates_project_id_before_bridge():
    # id (``projectId > 0``) before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "parseInt(select.value, 10)" in body
    assert "!(projectId > 0)" in body
    guard_pos = body.find("!(projectId > 0)")
    bridge_pos = body.find('callBridge("create_project_folder_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_folder_create_js_validates_folder_path_before_bridge():
    # Regression lock: the JS must validate the folder_path is
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "!folderPath" in body
    guard_pos = body.find("!folderPath")
    bridge_pos = body.find('callBridge("create_project_folder_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_folder_create_js_trims_folder_path_before_bridge():
    # Regression lock: the JS must trim the folder_path before
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert ".trim()" in body
    trim_pos = body.find(".trim()")
    bridge_pos = body.find('callBridge("create_project_folder_rule"')
    assert trim_pos != -1 and bridge_pos != -1
    assert trim_pos < bridge_pos


def test_project_rules_folder_create_js_has_creating_guard():
    # folder create is already in flight, before any bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "if (App.rulesCreatingFolder) return" in body
    guard_pos = body.find("if (App.rulesCreatingFolder) return")
    bridge_pos = body.find('callBridge("create_project_folder_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_folder_create_js_has_creating_button_label():
    # stable ``正在新增…`` label.
    source = read_rules_module_js()
    body = func_body(source, "setFolderCreateCreating")
    assert "正在新增…" in body


def test_project_rules_folder_create_js_success_refreshes_project_rules():
    # Regression lock: the success path must call
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "App.loadProjectRules()" in body


def test_project_rules_folder_create_js_success_clears_folder_path_input():
    # Regression lock: the success path must clear the folder_path
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert 'input.value = ""' in body


def test_project_rules_folder_create_js_failure_preserves_rendered_list():
    # Regression lock: the failure path must not clear the
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "list.innerHTML" not in body


def test_project_rules_folder_create_js_catch_never_reads_raw_exception():
    # Regression lock: the catch path must never read
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_folder_create_js_uses_textcontent_for_status():
    # ``textContent`` (HTML-safe), not ``innerHTML``.
    source = read_rules_module_js()
    status_body = func_body(source, "showFolderCreateStatus")
    assert "textContent" in status_body
    assert ".innerHTML" not in status_body


def test_project_rules_folder_create_state_isolation_from_other_write_paths():
    source = read_js("core.js")
    assert "App.rulesCreatingFolder" in source
    assert "App.rulesEditingFolderKey" in source
    assert "App.rulesDeletingFolderKey" in source
    rules_source = read_rules_module_js()
    create_body = func_body(rules_source, "handleFolderCreateSubmit")
    assert "App.rulesSavingRuleKey" not in create_body
    assert "App.rulesCreatingKeyword" not in create_body
    assert "App.rulesDeletingRuleKey" not in create_body


def test_project_rules_folder_create_selector_population_guard():
    source = read_rules_module_js()
    body = func_body(source, "populateFolderCreateProjectSelector")
    assert "if (App.rulesCreatingFolder) return" in body


def test_project_rules_folder_edit_buttons_only_on_folder_rows():
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'kind === "folder"' in row_body
    assert "rules-folder-edit-button" in row_body
    assert "rules-folder-delete-button" in row_body
    project_body = func_body(source, "renderProjectRuleProject")
    assert "rules-folder-edit-button" not in project_body
    assert "rules-folder-delete-button" not in project_body


def test_project_rules_folder_edit_button_uses_stable_class_and_attributes():
    # the stable class / data attributes.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'class="rules-folder-edit-button"' in row_body
    assert 'class="rules-folder-delete-button"' in row_body
    assert 'data-rule-kind="folder"' in row_body


def test_project_rules_folder_edit_js_validates_rule_id_before_bridge():
    # before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "parseInt(rawId, 10)" in body
    assert "ruleId <= 0" in body
    guard_pos = body.find("ruleId <= 0")
    bridge_pos = body.find('callBridge("update_project_folder_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_folder_edit_js_validates_rule_kind_before_bridge():
    # validated against ``folder`` before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert 'kind !== "folder"' in body
    type_check_pos = body.find('kind !== "folder"')
    bridge_pos = body.find('callBridge("update_project_folder_rule"')
    assert type_check_pos < bridge_pos


def test_project_rules_folder_edit_js_has_editing_guard():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "if (!App.rulesEditingFolderKey) return" in body


def test_project_rules_folder_edit_js_has_saving_button_label():
    # stable ``正在保存…`` label.
    source = read_rules_module_js()
    body = func_body(source, "setFolderSaving")
    assert "正在保存…" in body


def test_project_rules_folder_edit_js_success_refreshes_project_rules():
    # Regression lock: the success path must call
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "App.loadProjectRules()" in body


def test_project_rules_folder_edit_js_catch_never_reads_raw_exception():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_folder_edit_js_saving_state_clears_on_all_paths():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "App.setFolderSaving(true)" in body
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setFolderSaving(false)", catch_pos)
    assert cleanup_pos != -1


def test_project_rules_folder_edit_js_editing_state_clears_on_success():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "App.setFolderEditing(null)" in body


def test_project_rules_folder_delete_js_validates_rule_id_before_bridge():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    assert "parseInt(rawId, 10)" in body
    assert "ruleId <= 0" in body
    guard_pos = body.find("ruleId <= 0")
    bridge_pos = body.find('callBridge("delete_project_folder_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_folder_delete_js_validates_rule_kind_before_bridge():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    assert 'kind !== "folder"' in body
    type_check_pos = body.find('kind !== "folder"')
    bridge_pos = body.find('callBridge("delete_project_folder_rule"')
    assert type_check_pos < bridge_pos


def test_project_rules_folder_delete_js_has_deleting_guard():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    assert "if (App.rulesDeletingFolderKey) return" in body
    guard_pos = body.find("if (App.rulesDeletingFolderKey) return")
    confirm_pos = body.find("window.confirm")
    bridge_pos = body.find('callBridge("delete_project_folder_rule"')
    assert guard_pos != -1 and confirm_pos != -1 and bridge_pos != -1
    assert guard_pos < confirm_pos < bridge_pos


def test_project_rules_folder_delete_js_has_deleting_button_label():
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "正在删除…" in row_body
    set_deleting_body = func_body(source, "setFolderDeleting")
    assert "正在删除…" in set_deleting_body


def test_project_rules_folder_delete_js_confirmation_text_present():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    assert "确定删除这条文件夹规则吗？删除后该文件夹将不再用于自动归类。" in body


def test_project_rules_folder_delete_js_cancellation_does_not_call_bridge():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    confirm_pos = body.find("window.confirm")
    bridge_pos = body.find('callBridge("delete_project_folder_rule"')
    assert confirm_pos < bridge_pos
    cancellation_return = body.find("return;", confirm_pos)
    assert cancellation_return != -1 and cancellation_return < bridge_pos


def test_project_rules_folder_delete_js_success_refreshes_project_rules():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    assert "App.loadProjectRules()" in body


def test_project_rules_folder_delete_js_success_shows_stable_message():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    refresh_pos = body.find("App.loadProjectRules()")
    success_pos = body.find("文件夹规则已删除")
    assert refresh_pos != -1 and success_pos != -1
    assert refresh_pos < success_pos


def test_project_rules_folder_delete_js_failure_preserves_rendered_list():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    assert "list.innerHTML" not in body
    assert "删除文件夹规则失败" in body


def test_project_rules_folder_delete_js_catch_never_reads_raw_exception():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_folder_delete_js_deleting_state_clears_on_all_paths():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderDelete")
    assert "App.setFolderDeleting(" in body
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setFolderDeleting(null)", catch_pos)
    assert cleanup_pos != -1


def test_project_rules_folder_delete_js_does_not_call_keyword_delete_contract_2():
    source = read_rules_module_js()
    delete_body = func_body(source, "handleFolderDelete")
    assert 'callBridge("delete_project_keyword_rule"' not in delete_body
    assert 'callBridge("delete_keyword_rule"' not in delete_body


def test_project_rules_folder_delete_button_does_not_appear_on_keyword_rows():
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    folder_guard_pos = row_body.find('kind === "folder"')
    folder_html_pos = row_body.find("rules-folder-edit-button", folder_guard_pos)
    assert folder_guard_pos != -1 and folder_html_pos != -1
    assert folder_guard_pos < folder_html_pos


def test_project_rules_folder_buttons_disabled_when_any_write_in_flight():
    # disabled when any rule write is in flight on this row.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "App.rulesCreatingFolder" in row_body
    assert "App.rulesEditingFolderKey" in row_body
    assert "App.rulesDeletingFolderKey" in row_body
    assert "App.rulesSavingRuleKey" in row_body
    assert "App.rulesDeletingRuleKey" in row_body


def test_project_rules_folder_delete_set_deleting_updates_toggle_buttons():
    source = read_rules_module_js()
    body = func_body(source, "setFolderDeleting")
    assert "rules-toggle-btn" in body
    assert "App.rulesDeletingFolderKey" in body


def test_project_rules_folder_create_init_binds_submit_button():
    source = read_js("init.js")
    assert 'getElementById("rules-folder-create-submit")' in source
    assert "App.handleFolderCreateSubmit" in source


def test_project_rules_folder_create_no_app_js_reintroduced():
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_folder_create_no_forbidden_handler_tokens():
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source


def test_project_rules_folder_create_no_storage_or_network():
    source = read_rules_module_js()
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "fetch(",
        "XMLHttpRequest",
    ):
        assert forbidden not in source


def test_project_rules_folder_create_no_duplicate_static_dom_ids_in_form():
    import re as _re

    section = _rules_section()
    form_start = section.find('id="rules-folder-create-form"')
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
    assert not duplicates, "duplicate DOM id in folder create form: " + ", ".join(duplicates)


def test_project_rules_folder_css_class_exists():
    # folder create form have stable visual styles.
    source = read_resource("styles.css")
    for css_class in (
        ".rules-folder-create-form",
        ".rules-folder-create-submit",
        ".rules-folder-edit-button",
        ".rules-folder-delete-button",
        ".rules-folder-edit-form",
        ".rules-folder-edit-save",
        ".rules-folder-edit-cancel",
    ):
        assert css_class in source, "styles.css must contain: " + css_class
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"cdn", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_folder_css_class_scoped_to_rules_page():
    index = read_resource("index.html")
    for page_id in ("page-overview", "page-timeline", "page-statistics"):
        start = index.find('id="' + page_id + '"')
        assert start != -1, "index.html must contain " + page_id
        end = index.find("</section>", start)
        assert end != -1, page_id + " section must close"
        section = index[start:end]
        for css_class in (
            "rules-folder-create-form",
            "rules-folder-edit-button",
            "rules-folder-delete-button",
        ):
            assert css_class not in section, (
                page_id + " section must not reference folder CRUD class: " + css_class
            )


def test_project_rules_folder_create_stale_guard_preserved():
    # Regression lock: the existing ``rulesRequestToken`` stale
    source = read_rules_module_js()
    load_body = func_body(source, "loadProjectRules")
    assert "var token = ++App.rulesRequestToken" in load_body
    assert load_body.count("token !== App.rulesRequestToken") >= 2


def test_project_rules_folder_create_no_export_or_auto_submit_controls():
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


def test_project_rules_folder_create_no_project_management_controls():
    section = _rules_section().lower()
    for token in (
        "project-add",
        "project-edit",
        "project-delete",
        "project-archive",
        "project-enable",
        "project-disable",
    ):
        assert token not in section


def test_project_rules_folder_events_use_event_delegation_on_rules_list():
    # edit-cancel events must be delegated via a single click handler on
    source = read_rules_module_js()
    bind_body = func_body(source, "bindProjectRuleFolderEvents")
    assert 'getElementById("rules-list")' in bind_body
    assert "addEventListener" in bind_body
    assert "handleProjectRuleFolderEvent" in bind_body


def test_project_rules_folder_event_handler_routes_by_button_class():
    # Regression lock: the delegated folder event handler must
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleFolderEvent")
    assert "rules-folder-edit-button" in body
    assert "rules-folder-delete-button" in body
    assert "rules-folder-edit-save" in body
    assert "rules-folder-edit-cancel" in body
    assert "handleFolderEditStart" in body
    assert "handleFolderDelete" in body
    assert "handleFolderEditSave" in body
    assert "handleFolderEditCancel" in body


def test_project_rules_folder_create_js_creating_state_clears_on_all_paths():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "App.setFolderCreateCreating(true)" in body
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setFolderCreateCreating(false)", catch_pos)
    assert cleanup_pos != -1


def test_project_rules_folder_delete_state_isolation_from_other_write_paths():
    source = read_rules_module_js()
    delete_body = func_body(source, "handleFolderDelete")
    assert "App.rulesSavingRuleKey" not in delete_body
    assert "App.rulesCreatingKeyword" not in delete_body
    assert "App.rulesDeletingRuleKey" not in delete_body
    assert "App.rulesCreatingFolder" in delete_body
    assert "App.rulesDeletingFolderKey" in delete_body


def test_project_rules_folder_edit_state_isolation_from_other_write_paths():
    source = read_rules_module_js()
    edit_body = func_body(source, "handleFolderEditSave")
    assert "App.rulesSavingRuleKey" not in edit_body
    assert "App.rulesCreatingKeyword" not in edit_body
    assert "App.rulesDeletingRuleKey" not in edit_body


def test_project_rules_folder_inline_edit_form_renders_in_place_of_row():
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "is-folder-editing" in row_body
    assert "rules-folder-edit-form" in row_body
    assert "rules-folder-edit-input" in row_body
    assert "rules-folder-edit-recursive" in row_body
    assert "rules-folder-edit-save" in row_body
    assert "rules-folder-edit-cancel" in row_body


def test_project_rules_folder_show_project_rules_caches_last_data():
    source = read_rules_module_js()
    body = func_body(source, "showProjectRules")
    assert "App.lastProjectRulesData" in body


def test_project_rules_folder_show_project_rules_populates_folder_selector():
    source = read_rules_module_js()
    body = func_body(source, "showProjectRules")
    assert "populateFolderCreateProjectSelector" in body


def test_project_rules_folder_show_project_rules_binds_folder_events():
    source = read_rules_module_js()
    body = func_body(source, "showProjectRules")
    assert "bindProjectRuleFolderEvents" in body


def test_project_rules_folder_rerender_uses_cached_data():
    # cached ``lastProjectRulesData`` instead of calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "rerenderProjectRulesList")
    assert "App.lastProjectRulesData" in body


def test_project_rules_folder_packaging_spec_still_includes_rules_js():
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'rules.js'" in source or '"rules.js"' in source
    assert "'rules_project_actions.js'" in source or '"rules_project_actions.js"' in source
    assert "'worktrace/webview_ui/js'" in source or '"worktrace/webview_ui/js"' in source




def test_project_rules_folder_edit_cancel_does_not_call_bridge():
    # call any bridge method. It only clears the editing state and
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditCancel")
    assert "callBridge(" not in body


def test_project_rules_folder_edit_cancel_clears_editing_state():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditCancel")
    assert "App.setFolderEditing(null)" in body


def test_project_rules_folder_edit_cancel_has_early_return_guard():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditCancel")
    assert "if (!App.rulesEditingFolderKey) return" in body


def test_project_rules_folder_edit_start_sets_editing_key():
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditStart")
    assert "App.setFolderEditing" in body
    assert '"folder:"' in body or "'folder:'" in body


def test_project_rules_folder_edit_save_disables_save_and_cancel_buttons():
    source = read_rules_module_js()
    body = func_body(source, "setFolderSaving")
    assert "rules-folder-edit-save" in body
    assert "rules-folder-edit-cancel" in body
    assert "btn.disabled = !!saving" in body


def test_project_rules_folder_edit_form_has_maxlength_on_input():
    # ``maxlength`` attribute so the user cannot enter an over-long path.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'maxlength="512"' in row_body


def test_project_rules_folder_edit_form_css_classes_exist():
    # styles.css so the inline edit form has stable visual styles. The
    source = read_resource("styles.css")
    for css_class in (
        ".rules-folder-edit-input",
        ".rules-folder-edit-recursive",
        ".rules-folder-edit-recursive-label",
        ".rules-folder-create-input",
        ".rules-folder-create-recursive",
        ".rules-folder-create-status",
    ):
        assert css_class in source, "styles.css must contain: " + css_class


def test_project_rules_folder_edit_form_css_scoped_to_rules_page():
    index = read_resource("index.html")
    for page_id in ("page-overview", "page-timeline", "page-statistics"):
        start = index.find('id="' + page_id + '"')
        assert start != -1, "index.html must contain " + page_id
        end = index.find("</section>", start)
        assert end != -1, page_id + " section must close"
        section = index[start:end]
        for css_class in (
            "rules-folder-edit-input",
            "rules-folder-edit-recursive",
            "rules-folder-edit-form",
            "rules-folder-edit-save",
            "rules-folder-edit-cancel",
        ):
            assert css_class not in section, (
                page_id + " section must not reference folder edit class: " + css_class
            )


def test_project_rules_core_js_no_storage_or_network():
    # state variables) must not use forbidden storage / network / module
    source = read_js("core.js")
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "fetch(",
        "XMLHttpRequest",
    ):
        assert forbidden not in source


def test_project_rules_init_js_no_storage_or_network():
    # submit button) must not use forbidden storage / network / module
    source = read_js("init.js")
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "fetch(",
        "XMLHttpRequest",
    ):
        assert forbidden not in source


def test_project_rules_folder_js_no_external_urls():
    source = read_rules_module_js()
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"\bcdn\b", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_folder_js_no_es_module_syntax():
    source = read_rules_module_js()
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_folder_core_js_no_es_module_syntax():
    source = read_js("core.js")
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_folder_init_js_no_es_module_syntax():
    source = read_js("init.js")
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_folder_packaging_spec_includes_core_and_init_js():
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    for js_file in ("core.js", "init.js", "rules.js"):
        assert ("'" + js_file + "'") in source or ('"' + js_file + '"') in source, (
            "WorkTrace.spec must include: " + js_file
        )


def test_project_rules_folder_state_variables_declared_once():
    source = read_js("core.js")
    for var_decl in (
        "App.rulesCreatingFolder = false",
        "App.rulesEditingFolderKey = null",
        "App.rulesDeletingFolderKey = null",
        "App.lastProjectRulesData = null",
    ):
        assert source.count(var_decl) == 1, (
            var_decl + " must be declared exactly once in core.js"
        )


def test_project_rules_folder_create_status_uses_textcontent():
    # use ``textContent`` (HTML-safe), not ``innerHTML``. The existing
    source = read_rules_module_js()
    create_body = func_body(source, "handleFolderCreateSubmit")
    edit_save_body = func_body(source, "handleFolderEditSave")
    delete_body = func_body(source, "handleFolderDelete")
    for body in (create_body, edit_save_body, delete_body):
        assert ".innerHTML" not in body


def test_project_rules_folder_edit_save_failure_preserves_rendered_list():
    # Regression lock: the folder edit save failure path must
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "list.innerHTML" not in body


def test_project_rules_folder_edit_save_clears_editing_state_on_success():
    # Regression lock: the edit save success path must clear
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "App.setFolderEditing(null)" in body


def test_project_rules_folder_event_delegation_bound_once():
    source = read_rules_module_js()
    body = func_body(source, "bindProjectRuleFolderEvents")
    assert "data-rules-folder-bound" in body
    assert 'getAttribute("data-rules-folder-bound")' in body
    assert 'setAttribute("data-rules-folder-bound", "1")' in body


# stable anchors / attributes, the save / cancel handlers obey the


def test_project_rules_keyword_edit_state_variables_declared():
    # keyword edit updating (in-flight save) state must each be a separate
    source = read_js("core.js")
    assert "App.rulesEditingKeywordKey = null" in source
    assert "App.rulesUpdatingKeywordKey = null" in source
    assert "App.rulesSavingRuleKey = null" in source
    assert "App.rulesCreatingKeyword = false" in source
    assert "App.rulesDeletingRuleKey = null" in source
    assert "App.rulesCreatingFolder = false" in source
    assert "App.rulesEditingFolderKey = null" in source
    assert "App.rulesDeletingFolderKey = null" in source


def test_project_rules_keyword_edit_state_variables_declared_once():
    source = read_js("core.js")
    for var_decl in (
        "App.rulesEditingKeywordKey = null",
        "App.rulesUpdatingKeywordKey = null",
    ):
        assert source.count(var_decl) == 1, (
            var_decl + " must be declared exactly once in core.js"
        )


def test_project_rules_keyword_edit_js_calls_bridge_method():
    # ``update_project_keyword_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("update_project_keyword_rule"' in source


def test_project_rules_keyword_edit_buttons_only_on_keyword_rows():
    # renderProjectRuleRow function must gate the edit button on
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'kind === "keyword"' in row_body
    assert "rules-keyword-edit-button" in row_body
    project_body = func_body(source, "renderProjectRuleProject")
    assert "rules-keyword-edit-button" not in project_body


def test_project_rules_keyword_edit_button_does_not_appear_on_folder_rows():
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    keyword_guard_pos = row_body.find('kind === "keyword"')
    edit_html_assign_pos = row_body.find("keywordEditButton = '", keyword_guard_pos)
    assert keyword_guard_pos != -1 and edit_html_assign_pos != -1
    assert keyword_guard_pos < edit_html_assign_pos


def test_project_rules_keyword_edit_button_uses_stable_class_and_attributes():
    # Regression lock: the keyword edit button must use the stable
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'class="rules-keyword-edit-button"' in row_body
    assert 'data-rule-kind="keyword"' in row_body
    assert 'data-rule-id="' in row_body


def test_project_rules_keyword_edit_button_disabled_when_any_write_in_flight():
    # when any rule write is in flight on this row (toggle saving, keyword
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "App.rulesSavingRuleKey" in row_body
    assert "App.rulesDeletingRuleKey" in row_body
    assert "App.rulesEditingKeywordKey" in row_body
    assert "App.rulesUpdatingKeywordKey" in row_body


def test_project_rules_keyword_edit_start_sets_editing_key():
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditStart")
    assert "App.setKeywordEditing" in body
    assert '"keyword:"' in body or "'keyword:'" in body


def test_project_rules_keyword_edit_start_has_in_flight_guard():
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditStart")
    assert "if (App.rulesEditingKeywordKey) return" in body
    assert "if (App.rulesUpdatingKeywordKey) return" in body
    assert "if (App.rulesDeletingRuleKey) return" in body


def test_project_rules_keyword_edit_start_validates_rule_kind_before_state():
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditStart")
    assert 'kind !== "keyword"' in body
    type_check_pos = body.find('kind !== "keyword"')
    set_editing_pos = body.find("App.setKeywordEditing(")
    assert type_check_pos < set_editing_pos


def test_project_rules_keyword_edit_start_validates_rule_id_before_state():
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditStart")
    assert 'parseInt(rawId, 10)' in body
    assert "ruleId <= 0" in body
    guard_pos = body.find("ruleId <= 0")
    set_editing_pos = body.find("App.setKeywordEditing(")
    assert guard_pos < set_editing_pos


def test_project_rules_keyword_edit_save_calls_bridge_method():
    # ``update_project_keyword_rule`` bridge method.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert 'callBridge("update_project_keyword_rule"' in body


def test_project_rules_keyword_edit_save_validates_rule_kind_before_bridge():
    # validated against ``keyword`` before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert 'kind !== "keyword"' in body
    type_check_pos = body.find('kind !== "keyword"')
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert type_check_pos < bridge_pos


def test_project_rules_keyword_edit_save_validates_rule_id_before_bridge():
    # before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert 'parseInt(rawId, 10)' in body
    assert "ruleId <= 0" in body
    guard_pos = body.find("ruleId <= 0")
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert guard_pos < bridge_pos


def test_project_rules_keyword_edit_save_trims_input_before_bridge():
    # validation and before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert ".trim()" in body
    trim_pos = body.find(".trim()")
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert trim_pos != -1 and bridge_pos != -1
    assert trim_pos < bridge_pos


def test_project_rules_keyword_edit_save_rejects_empty_input_client_side():
    # rejected before any bridge call. The handler must ``return``
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "!keyword" in body
    empty_guard_pos = body.find("!keyword")
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert empty_guard_pos < bridge_pos
    return_pos = body.find("return;", empty_guard_pos)
    assert return_pos != -1 and return_pos < bridge_pos


def test_project_rules_keyword_edit_save_has_editing_guard():
    # keyword edit is in flight, before any bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "if (!App.rulesEditingKeywordKey) return" in body
    guard_pos = body.find("if (!App.rulesEditingKeywordKey) return")
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert guard_pos < bridge_pos


def test_project_rules_keyword_edit_save_has_saving_button_label():
    # stable ``正在保存…`` label.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "正在保存…" in row_body
    set_saving_body = func_body(source, "setKeywordSaving")
    assert "正在保存…" in set_saving_body


def test_project_rules_keyword_edit_save_success_refreshes_project_rules():
    # Regression lock: the success path must call
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "App.loadProjectRules()" in body


def test_project_rules_keyword_edit_save_success_clears_editing_state():
    # Regression lock: the success path must clear the editing
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "App.setKeywordEditing(null)" in body


def test_project_rules_keyword_edit_save_success_shows_stable_message():
    # Regression lock: the success path must show the stable
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    refresh_pos = body.find("App.loadProjectRules()")
    success_pos = body.find("关键词规则已保存")
    assert refresh_pos != -1 and success_pos != -1
    assert refresh_pos < success_pos


def test_project_rules_keyword_edit_save_failure_preserves_editing_state():
    # Regression lock: the failure path (ok=false) must not clear
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    failure_guard = body.find("result && result.ok === false")
    assert failure_guard != -1
    failure_return = body.find("return;", failure_guard)
    assert failure_return != -1
    failure_block = body[failure_guard:failure_return]
    assert "App.setKeywordEditing(null)" not in failure_block
    assert "App.setKeywordEditing(" not in failure_block


def test_project_rules_keyword_edit_save_failure_preserves_rendered_list():
    # Regression lock: the failure path must not clear the
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body
    assert "保存关键词规则失败" in body


def test_project_rules_keyword_edit_save_catch_never_reads_raw_exception():
    # Regression lock: the catch path must never read
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_keyword_edit_save_saving_state_clears_on_all_paths():
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "App.setKeywordSaving(" in body
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setKeywordSaving(null)", catch_pos)
    assert cleanup_pos != -1, (
        "App.setKeywordSaving(null) must run after .catch so the saving "
        "state clears on success, failure, and rejected-promise paths"
    )


def test_project_rules_keyword_edit_cancel_does_not_call_bridge():
    # Regression lock: the cancel handler must not call any bridge
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditCancel")
    assert "callBridge(" not in body


def test_project_rules_keyword_edit_cancel_clears_editing_state():
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditCancel")
    assert "App.setKeywordEditing(null)" in body


def test_project_rules_keyword_edit_cancel_has_early_return_guard():
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditCancel")
    assert "if (!App.rulesEditingKeywordKey) return" in body


def test_project_rules_keyword_edit_set_keyword_editing_rerenders_from_cache():
    source = read_rules_module_js()
    body = func_body(source, "setKeywordEditing")
    assert "App.rerenderProjectRulesList()" in body


def test_project_rules_keyword_edit_set_keyword_saving_disables_save_and_cancel():
    source = read_rules_module_js()
    body = func_body(source, "setKeywordSaving")
    assert "rules-keyword-edit-save" in body
    assert "rules-keyword-edit-cancel" in body
    assert "btn.disabled" in body


def test_project_rules_keyword_edit_inline_form_renders_in_place_of_row():
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "is-keyword-editing" in row_body
    assert "rules-keyword-edit-form" in row_body
    assert "rules-keyword-edit-input" in row_body
    assert "rules-keyword-edit-save" in row_body
    assert "rules-keyword-edit-cancel" in row_body


def test_project_rules_keyword_edit_form_has_maxlength_on_input():
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'maxlength="200"' in row_body


def test_project_rules_keyword_edit_form_uses_stable_class_and_attributes():
    # must use the stable class / data attributes.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'class="rules-keyword-edit-save"' in row_body
    assert 'class="rules-keyword-edit-cancel"' in row_body
    assert 'data-rule-kind="keyword"' in row_body


def test_project_rules_keyword_edit_events_use_event_delegation_on_rules_list():
    # events must be delegated via a single click handler on
    source = read_rules_module_js()
    bind_body = func_body(source, "bindProjectRuleKeywordEditEvents")
    assert 'getElementById("rules-list")' in bind_body
    assert "addEventListener" in bind_body
    assert "handleProjectRuleKeywordEditEvent" in bind_body


def test_project_rules_keyword_edit_event_handler_routes_by_button_class():
    # Regression lock: the delegated keyword edit event handler
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleKeywordEditEvent")
    assert "rules-keyword-edit-button" in body
    assert "rules-keyword-edit-save" in body
    assert "rules-keyword-edit-cancel" in body
    assert "handleKeywordEditStart" in body
    assert "handleKeywordEditSave" in body
    assert "handleKeywordEditCancel" in body


def test_project_rules_keyword_edit_event_delegation_bound_once():
    source = read_rules_module_js()
    body = func_body(source, "bindProjectRuleKeywordEditEvents")
    assert "data-rules-keyword-edit-bound" in body
    assert 'getAttribute("data-rules-keyword-edit-bound")' in body
    assert 'setAttribute("data-rules-keyword-edit-bound", "1")' in body


def test_project_rules_keyword_edit_show_project_rules_binds_events():
    source = read_rules_module_js()
    body = func_body(source, "showProjectRules")
    assert "bindProjectRuleKeywordEditEvents" in body


def test_project_rules_keyword_edit_rerender_binds_events():
    source = read_rules_module_js()
    body = func_body(source, "rerenderProjectRulesList")
    assert "bindProjectRuleKeywordEditEvents" in body


def test_project_rules_keyword_edit_state_isolation_from_other_write_paths():
    source = read_rules_module_js()
    edit_body = func_body(source, "handleKeywordEditSave")
    assert "App.rulesSavingRuleKey" not in edit_body
    assert "App.rulesCreatingKeyword" not in edit_body
    assert "App.rulesDeletingRuleKey" not in edit_body
    assert "App.rulesCreatingFolder" not in edit_body
    assert "App.rulesEditingFolderKey" not in edit_body
    assert "App.rulesDeletingFolderKey" not in edit_body
    assert "App.rulesEditingKeywordKey" in edit_body
    assert "App.setKeywordSaving" in edit_body


def test_project_rules_keyword_edit_start_state_isolation_from_other_write_paths():
    source = read_rules_module_js()
    start_body = func_body(source, "handleKeywordEditStart")
    assert "App.rulesSavingRuleKey" not in start_body
    assert "App.rulesCreatingKeyword" not in start_body
    assert "App.rulesCreatingFolder" not in start_body
    assert "App.rulesEditingFolderKey" not in start_body
    assert "App.rulesDeletingFolderKey" not in start_body


def test_project_rules_keyword_edit_cancel_state_isolation_from_other_write_paths():
    source = read_rules_module_js()
    cancel_body = func_body(source, "handleKeywordEditCancel")
    assert "App.rulesSavingRuleKey" not in cancel_body
    assert "App.rulesCreatingKeyword" not in cancel_body
    assert "App.rulesDeletingRuleKey" not in cancel_body
    assert "App.rulesCreatingFolder" not in cancel_body
    assert "App.rulesEditingFolderKey" not in cancel_body
    assert "App.rulesDeletingFolderKey" not in cancel_body


def test_project_rules_keyword_edit_set_keyword_editing_state_isolation():
    # keyword editing state, not any other write-path state.
    source = read_rules_module_js()
    body = func_body(source, "setKeywordEditing")
    assert "App.rulesEditingKeywordKey" in body
    assert "App.rulesSavingRuleKey" not in body
    assert "App.rulesCreatingKeyword" not in body
    assert "App.rulesDeletingRuleKey" not in body
    assert "App.rulesCreatingFolder" not in body
    assert "App.rulesEditingFolderKey" not in body
    assert "App.rulesDeletingFolderKey" not in body


def test_project_rules_keyword_edit_set_keyword_saving_state_isolation():
    # keyword saving state, not any other write-path state.
    source = read_rules_module_js()
    body = func_body(source, "setKeywordSaving")
    assert "App.rulesUpdatingKeywordKey" in body
    assert "App.rulesSavingRuleKey" not in body
    assert "App.rulesCreatingKeyword" not in body
    assert "App.rulesDeletingRuleKey" not in body
    assert "App.rulesCreatingFolder" not in body
    assert "App.rulesEditingFolderKey" not in body
    assert "App.rulesDeletingFolderKey" not in body


def test_project_rules_keyword_edit_js_does_not_call_other_write_bridges():
    # call any other Project Rules write bridge (create / delete / toggle /
    source = read_rules_module_js()
    save_body = func_body(source, "handleKeywordEditSave")
    for forbidden in (
        'callBridge("create_project_keyword_rule"',
        'callBridge("delete_project_keyword_rule"',
        'callBridge("set_project_rule_enabled"',
        'callBridge("create_project_folder_rule"',
        'callBridge("update_project_folder_rule"',
        'callBridge("delete_project_folder_rule"',
    ):
        assert forbidden not in save_body, (
            "keyword edit save must not call: " + forbidden
        )


def test_project_rules_keyword_edit_js_does_not_call_preview_or_backfill():
    # preview / backfill bridges.
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("preview_folder_rule_conflicts"',
        'callBridge("backfill_folder_rule"',
    ):
        assert forbidden not in source


def test_project_rules_keyword_edit_js_does_not_call_project_write():
    # any project write bridge.
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("create_project"',
        'callBridge("update_project"',
        'callBridge("delete_project"',
        'callBridge("archive_project"',
        'callBridge("set_project_enabled"',
    ):
        assert forbidden not in source


def test_project_rules_keyword_edit_no_storage_or_network():
    # browser storage or network APIs.
    source = read_rules_module_js()
    for handler_name in (
        "handleKeywordEditStart",
        "handleKeywordEditSave",
        "handleKeywordEditCancel",
        "setKeywordEditing",
        "setKeywordSaving",
        "bindProjectRuleKeywordEditEvents",
        "handleProjectRuleKeywordEditEvent",
    ):
        body = func_body(source, handler_name)
        for forbidden in (
            "localStorage",
            "sessionStorage",
            "document.cookie",
            "fetch(",
            "XMLHttpRequest",
        ):
            assert forbidden not in body, (
                handler_name + " must not use forbidden storage/network API: " + forbidden
            )


def test_project_rules_keyword_edit_no_forbidden_handler_tokens():
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source


def test_project_rules_keyword_edit_no_app_js_reintroduced():
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_keyword_edit_no_static_edit_button_in_html():
    section = _rules_section()
    assert "rules-keyword-edit-button" not in section
    assert "rules-keyword-edit-form" not in section
    assert "rules-keyword-edit-save" not in section
    assert "rules-keyword-edit-cancel" not in section


def test_project_rules_keyword_edit_no_duplicate_static_dom_ids():
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


def test_project_rules_keyword_edit_no_export_or_auto_submit_controls():
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


def test_project_rules_keyword_edit_no_project_management_controls():
    section = _rules_section().lower()
    for token in (
        "project-add",
        "project-edit",
        "project-delete",
        "project-archive",
        "project-enable",
        "project-disable",
    ):
        assert token not in section


def test_project_rules_keyword_edit_css_class_exists():
    # form have stable visual styles.
    source = read_resource("styles.css")
    for css_class in (
        ".rules-keyword-edit-button",
        ".rules-keyword-edit-form",
        ".rules-keyword-edit-input",
        ".rules-keyword-edit-save",
        ".rules-keyword-edit-cancel",
    ):
        assert css_class in source, "styles.css must contain: " + css_class
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"cdn", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_keyword_edit_css_class_scoped_to_rules_page():
    index = read_resource("index.html")
    for page_id in ("page-overview", "page-timeline", "page-statistics"):
        start = index.find('id="' + page_id + '"')
        assert start != -1, "index.html must contain " + page_id
        end = index.find("</section>", start)
        assert end != -1, page_id + " section must close"
        section = index[start:end]
        for css_class in (
            "rules-keyword-edit-button",
            "rules-keyword-edit-form",
            "rules-keyword-edit-input",
            "rules-keyword-edit-save",
            "rules-keyword-edit-cancel",
        ):
            assert css_class not in section, (
                page_id + " section must not reference keyword edit class: " + css_class
            )


def test_project_rules_keyword_edit_js_no_external_urls():
    source = read_rules_module_js()
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"\bcdn\b", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_keyword_edit_js_no_es_module_syntax():
    source = read_rules_module_js()
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_keyword_edit_core_js_no_es_module_syntax():
    source = read_js("core.js")
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_keyword_edit_init_js_no_es_module_syntax():
    source = read_js("init.js")
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_keyword_edit_init_does_not_bind_edit_event():
    source = read_js("init.js")
    for forbidden in (
        "rules-keyword-edit",
        "handleKeywordEditStart",
        "handleKeywordEditSave",
        "handleKeywordEditCancel",
        "setKeywordEditing",
        "setKeywordSaving",
        "bindProjectRuleKeywordEditEvents",
    ):
        assert forbidden not in source, (
            "init.js must not bind Project Rules keyword edit event: " + forbidden
        )


def test_project_rules_keyword_edit_packaging_spec_still_includes_rules_js():
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'rules.js'" in source or '"rules.js"' in source
    assert "'rules_project_actions.js'" in source or '"rules_project_actions.js"' in source
    assert "'worktrace/webview_ui/js'" in source or '"worktrace/webview_ui/js"' in source


def test_project_rules_keyword_edit_stale_guard_preserved():
    # Regression lock: the existing ``rulesRequestToken`` stale
    source = read_rules_module_js()
    load_body = func_body(source, "loadProjectRules")
    assert "var token = ++App.rulesRequestToken" in load_body
    assert load_body.count("token !== App.rulesRequestToken") >= 2


def test_project_rules_keyword_edit_boundary_copy_present():
    section = _rules_section()
    assert "启用/停用" in section
    assert "新增关键词规则" in section
    for term in ("编辑", "归档", "预览规则影响", "应用到历史记录"):
        assert term in section


def test_project_rules_keyword_edit_js_uses_escape_helper_for_dynamic_text():
    source = read_rules_module_js()
    count_body = func_body(source, "count")
    assert "App.escapeHtml" in count_body
    row_body = func_body(source, "renderProjectRuleRow")
    assert "count(ruleId)" in row_body


# Project lifecycle foundation + hardening


def test_project_rules_project_create_form_anchors_exist():
    # stable project create form DOM anchors.
    section = _rules_section()
    for dom_id in (
        "rules-project-create-form",
        "rules-project-create-input",
        "rules-project-create-description",
        "rules-project-create-submit",
        "rules-project-create-status",
    ):
        assert 'id="' + dom_id + '"' in section, (
            "Project Rules page must contain project create anchor: " + dom_id
        )


def test_project_rules_project_create_form_has_name_input():
    section = _rules_section()
    assert '<input id="rules-project-create-input"' in section
    assert 'type="text"' in section
    assert 'maxlength="100"' in section


def test_project_rules_project_create_form_has_description_input():
    section = _rules_section()
    assert '<input id="rules-project-create-description"' in section
    assert 'maxlength="500"' in section


def test_project_rules_project_create_submit_button_exists():
    section = _rules_section()
    assert '<button id="rules-project-create-submit"' in section
    assert 'type="button"' in section


def test_project_rules_project_lifecycle_state_variables_declared():
    # Regression lock: the five project lifecycle state variables
    source = read_js("core.js")
    assert "App.rulesCreatingProject = false" in source
    assert "App.rulesEditingProjectId = null" in source
    assert "App.rulesUpdatingProjectId = null" in source
    assert "App.rulesTogglingProjectId = null" in source
    assert "App.rulesArchivingProjectId = null" in source


def test_project_rules_project_lifecycle_state_variables_declared_once():
    # Regression lock: each project lifecycle state variable must
    source = read_js("core.js")
    for var_decl in (
        "App.rulesCreatingProject = false",
        "App.rulesEditingProjectId = null",
        "App.rulesUpdatingProjectId = null",
        "App.rulesTogglingProjectId = null",
        "App.rulesArchivingProjectId = null",
    ):
        assert source.count(var_decl) == 1, (
            var_decl + " must be declared exactly once in core.js"
        )


def test_project_rules_project_lifecycle_js_calls_bridge_methods():
    # bridge methods.
    source = read_rules_module_js()
    assert 'callBridge("create_project_for_rules"' in source
    assert 'callBridge("update_project_for_rules"' in source
    assert 'callBridge("set_project_enabled_for_rules"' in source
    assert 'callBridge("archive_project_for_rules"' in source


def test_project_rules_project_lifecycle_js_does_not_call_bare_project_write():
    # project write bridge methods. Hard delete is never exposed.
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("create_project"',
        'callBridge("update_project"',
        'callBridge("delete_project"',
        'callBridge("archive_project"',
        'callBridge("set_project_enabled"',
    ):
        assert forbidden not in source, (
            "Project Rules frontend must not call bare project write bridge: "
            + forbidden
        )


def test_project_rules_project_lifecycle_buttons_only_on_user_projects():
    # Regression lock: the lifecycle buttons (edit / toggle /
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    assert "rules-project-edit-button" in project_body
    assert "rules-project-toggle-button" in project_body
    assert "rules-project-archive-button" in project_body
    # The editable gate must be present before the buttons are rendered.
    editable_gate_pos = project_body.find("editable && projectId")
    edit_button_pos = project_body.find("rules-project-edit-button")
    assert editable_gate_pos != -1 and edit_button_pos != -1
    assert editable_gate_pos < edit_button_pos


def test_project_rules_project_lifecycle_buttons_use_stable_classes_and_attributes():
    # Regression lock: the lifecycle buttons must use the stable
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    for cls in (
        "rules-project-edit-button",
        "rules-project-toggle-button",
        "rules-project-archive-button",
    ):
        assert 'class="' + cls + '"' in project_body, cls
    assert 'data-project-id="' in project_body


def test_project_rules_project_lifecycle_buttons_disabled_when_any_write_in_flight():
    # Regression lock: the lifecycle buttons must be disabled when
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    assert "rulesCreatingProject" in project_body
    assert "rulesEditingProjectId" in project_body
    assert "rulesUpdatingProjectId" in project_body
    assert "rulesTogglingProjectId" in project_body
    assert "rulesArchivingProjectId" in project_body
    assert "projectWriteInProgress" in project_body


def test_project_rules_project_lifecycle_inline_edit_form_anchors():
    # stable CSS classes for the name input, description input, save button,
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    for cls in (
        "rules-project-edit-form",
        "rules-project-edit-name",
        "rules-project-edit-description",
        "rules-project-edit-save",
        "rules-project-edit-cancel",
    ):
        assert cls in project_body, cls
    assert 'maxlength="100"' in project_body
    assert 'maxlength="500"' in project_body


def test_project_rules_project_create_js_validates_name_before_bridge():
    # the name is non-empty (after trim) before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectCreateSubmit")
    trim_pos = body.find(".trim()")
    empty_check_pos = body.find("请输入项目名称")
    bridge_pos = body.find('callBridge("create_project_for_rules"')
    assert trim_pos != -1 and empty_check_pos != -1 and bridge_pos != -1
    assert trim_pos < empty_check_pos < bridge_pos


def test_project_rules_project_create_js_has_creating_guard():
    # set, before any bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectCreateSubmit")
    guard_pos = body.find("App.rulesCreatingProject")
    bridge_pos = body.find('callBridge("create_project_for_rules"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_project_create_js_success_clears_inputs_and_refreshes():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectCreateSubmit")
    assert 'input.value = ""' in body
    assert "descInput.value" in body
    assert "App.loadProjectRules()" in body


def test_project_rules_project_create_js_failure_preserves_inputs():
    # inputs so the user can edit and retry. The success path (which clears
    source = read_rules_module_js()
    body = func_body(source, "handleProjectCreateSubmit")
    ok_check_pos = body.find("result.ok === false")
    clear_pos = body.find('input.value = ""')
    assert ok_check_pos != -1 and clear_pos != -1
    assert ok_check_pos < clear_pos


def test_project_rules_project_create_js_catch_never_reads_raw_exception():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectCreateSubmit")
    for forbidden in (
        "err.message",
        "error.message",
        ".toString",
        "reason.message",
    ):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_project_edit_save_js_validates_name_before_bridge():
    # the name is non-empty (after trim) before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectEditSave")
    trim_pos = body.find(".trim()")
    empty_check_pos = body.find("请输入项目名称")
    bridge_pos = body.find('callBridge("update_project_for_rules"')
    assert trim_pos != -1 and empty_check_pos != -1 and bridge_pos != -1
    assert trim_pos < empty_check_pos < bridge_pos


def test_project_rules_project_edit_save_js_success_refreshes():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectEditSave")
    assert "App.loadProjectRules()" in body
    assert "项目已保存" in body


def test_project_rules_project_edit_save_js_catch_never_reads_raw_exception():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectEditSave")
    for forbidden in (
        "err.message",
        "error.message",
        ".toString",
        "reason.message",
    ):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_project_edit_cancel_does_not_call_bridge():
    # Regression lock: the cancel handler must NOT call any bridge
    source = read_rules_module_js()
    body = func_body(source, "handleProjectEditCancel")
    assert "callBridge" not in body
    assert "App.setProjectEditing(null)" in body


def test_project_rules_project_toggle_js_has_confirmation():
    # Regression lock: the toggle handler must show a confirmation
    source = read_rules_module_js()
    body = func_body(source, "handleProjectToggle")
    assert "window.confirm" in body
    assert "确定停用这个项目吗？" in body
    assert 'callBridge("set_project_enabled_for_rules"' in body


def test_project_rules_project_toggle_js_success_refreshes():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectToggle")
    assert "App.loadProjectRules()" in body
    assert "项目状态已更新" in body


def test_project_rules_project_toggle_js_catch_never_reads_raw_exception():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectToggle")
    for forbidden in (
        "err.message",
        "error.message",
        ".toString",
        "reason.message",
    ):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_project_archive_js_has_confirmation():
    # Regression lock: the archive handler must show a confirmation
    source = read_rules_module_js()
    body = func_body(source, "handleProjectArchive")
    assert "window.confirm" in body
    assert "确定归档这个项目吗？" in body
    assert 'callBridge("archive_project_for_rules"' in body


def test_project_rules_project_archive_js_success_refreshes():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectArchive")
    assert "App.loadProjectRules()" in body
    assert "项目已归档" in body


def test_project_rules_project_archive_js_catch_never_reads_raw_exception():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectArchive")
    for forbidden in (
        "err.message",
        "error.message",
        ".toString",
        "reason.message",
    ):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_project_lifecycle_event_delegation_bound_once():
    # use the ``data-rules-project-lifecycle-bound`` guard so it is only
    source = read_rules_module_js()
    body = func_body(source, "bindProjectLifecycleEvents")
    assert "data-rules-project-lifecycle-bound" in body
    assert "handleProjectLifecycleEvent" in body


def test_project_rules_project_lifecycle_no_storage_or_network():
    # Regression lock: the project lifecycle handlers must not use
    source = read_rules_module_js()
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "localStorage",
        "sessionStorage",
        "document.cookie",
    ):
        assert forbidden not in source


def test_project_rules_project_lifecycle_no_es_module_syntax():
    source = read_rules_module_js()
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_project_lifecycle_init_binds_create_submit_only():
    # must NOT bind any project lifecycle handler directly (edit / toggle /
    source = read_js("init.js")
    assert 'getElementById("rules-project-create-submit")' in source
    assert "handleProjectCreateSubmit" in source
    for forbidden in (
        "handleProjectEditStart",
        "handleProjectEditSave",
        "handleProjectEditCancel",
        "handleProjectToggle",
        "handleProjectArchive",
        "bindProjectLifecycleEvents",
    ):
        assert forbidden not in source, (
            "init.js must not bind Project Rules lifecycle handler: " + forbidden
        )


def test_project_rules_project_lifecycle_packaging_spec_unchanged():
    # Regression lock: no new packaging resource paths are needed
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'rules.js'" in source or '"rules.js"' in source
    assert "'rules_project_actions.js'" in source or '"rules_project_actions.js"' in source
    assert "'worktrace/webview_ui/js'" in source or '"worktrace/webview_ui/js"' in source


def test_project_rules_project_lifecycle_no_app_js_reintroduced():
    # index.html. The project lifecycle code lives in rules.js and
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_project_lifecycle_no_forbidden_handler_tokens():
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source, (
            "Project Rules JS must not contain forbidden handler token: " + token
        )


# module from index.html, WorkTrace.spec, or the ALL_JS_FILES list.


def test_project_rules_mc2_split_modules_exist_on_disk():
    import os

    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "worktrace",
            "webview_ui",
            "js",
            name,
        )
        assert os.path.isfile(path), f"missing rules split module: {name}"


def test_project_rules_mc2_split_modules_in_all_js_files():
    expected_order = [
        "rules.js",
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
        "rules_project_actions.js",
    ]
    for name in expected_order:
        assert name in ALL_JS_FILES, (
            f"ALL_JS_FILES must include rules split module: {name}"
        )
    indices = [ALL_JS_FILES.index(name) for name in expected_order]
    assert indices == sorted(indices), (
        "rules split modules must appear in ALL_JS_FILES in order: "
        + ", ".join(expected_order)
    )


def test_project_rules_mc2_split_modules_in_index_html():
    html = read_resource("index.html")
    import re

    scripts = re.findall(r'<script\s+src="js/([^"]+)"\s*>\s*</script>', html)
    assert scripts == ALL_JS_FILES, (
        "index.html script order must match ALL_JS_FILES exactly"
    )
    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        assert 'src="js/' + name + '"' in html, (
            f"index.html must load rules split module: {name}"
        )


def test_project_rules_mc2_split_modules_in_spec():
    # Regression lock: WorkTrace.spec must bundle every split
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        assert name in spec, (
            f"WorkTrace.spec must bundle rules split module: {name}"
        )


def test_project_rules_mc2_split_modules_are_iife_classic_scripts():
    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        source = read_js(name).strip()
        assert "(function () {" in source[:400], (
            f"{name} must open with an IIFE near the top"
        )
        assert source.rstrip().endswith("})();"), (
            f"{name} must end with IIFE close"
        )
        assert '"use strict"' in source, f"{name} must use strict mode"
        assert "var App = window.WorkTraceApp" in source, (
            f"{name} must attach to window.WorkTraceApp namespace"
        )
        for forbidden in ("export ", "import ", "export default", "import("):
            assert forbidden not in source, (
                f"{name} must not use ES module syntax: {forbidden}"
            )


def test_project_rules_mc2_render_helpers_attach_to_app():
    source = read_js("rules_render.js")
    assert "App.renderProjectRuleProject = renderProjectRuleProject" in source
    assert "App.renderProjectRuleRow = renderProjectRuleRow" in source


def test_project_rules_mc2_rule_actions_attach_to_app():
    source = read_js("rules_rule_actions.js")
    assert "App.bindProjectRuleToggles = bindProjectRuleToggles" in source
    assert "App.handleProjectRuleToggle = handleProjectRuleToggle" in source
    assert "App.setProjectRuleSaving = setProjectRuleSaving" in source


def test_project_rules_mc2_keyword_actions_attach_to_app():
    source = read_js("rules_keyword_actions.js")
    for name in (
        "bindProjectRuleDelete",
        "handleProjectRuleDelete",
        "setRuleDeleting",
        "bindProjectRuleKeywordEditEvents",
        "handleProjectRuleKeywordEditEvent",
        "handleKeywordEditStart",
        "handleKeywordEditSave",
        "handleKeywordEditCancel",
        "setKeywordEditing",
        "setKeywordSaving",
        "populateKeywordCreateProjectSelector",
        "handleKeywordCreateSubmit",
        "setKeywordCreateCreating",
        "showKeywordCreateStatus",
        "clearKeywordCreateStatus",
    ):
        assert ("App." + name + " = " + name) in source, (
            f"rules_keyword_actions.js must attach {name} to App"
        )


def test_project_rules_mc2_folder_actions_attach_to_app():
    source = read_js("rules_folder_actions.js")
    for name in (
        "populateFolderCreateProjectSelector",
        "handleFolderCreateSubmit",
        "setFolderCreateCreating",
        "showFolderCreateStatus",
        "clearFolderCreateStatus",
        "bindProjectRuleFolderEvents",
        "handleProjectRuleFolderEvent",
        "handleFolderEditStart",
        "handleFolderEditSave",
        "handleFolderEditCancel",
        "handleFolderDelete",
        "setFolderEditing",
        "setFolderSaving",
        "setFolderDeleting",
    ):
        assert ("App." + name + " = " + name) in source, (
            f"rules_folder_actions.js must attach {name} to App"
        )


def test_project_rules_mc2_core_module_keeps_load_and_refresh():
    source = read_js("rules.js")
    for name in (
        "loadProjectRules",
        "showProjectRules",
        "rerenderProjectRulesList",
        "setRulesLoading",
        "showRulesError",
        "clearRulesError",
    ):
        assert ("function " + name) in source, (
            f"rules.js core must still define {name}"
        )
        assert ("App." + name + " = " + name) in source, (
            f"rules.js core must still attach {name} to App"
        )


def test_project_rules_mc2_core_module_does_not_render_html():
    source = read_js("rules.js")
    assert "function renderProjectRuleProject" not in source, (
        "rules.js core must not define renderProjectRuleProject (moved to rules_render.js)"
    )
    assert "function renderProjectRuleRow" not in source, (
        "rules.js core must not define renderProjectRuleRow (moved to rules_render.js)"
    )


def test_project_rules_mc2_render_module_does_not_call_bridge():
    # module — no bridge calls. The bridge calls live in the action
    source = read_js("rules_render.js")
    assert "callBridge(" not in source, (
        "rules_render.js must not call bridge (pure render module)"
    )


def test_project_rules_mc2_state_keys_unchanged():
    # stable frontend contract.
    core = read_js("core.js")
    for key in (
        "rulesLoaded",
        "rulesLoading",
        "rulesRequestToken",
        "rulesSavingRuleKey",
        "rulesDeletingRuleKey",
        "rulesCreatingKeyword",
        "rulesEditingKeywordKey",
        "rulesUpdatingKeywordKey",
        "rulesCreatingFolder",
        "rulesEditingFolderKey",
        "rulesDeletingFolderKey",
        "rulesCreatingProject",
        "rulesEditingProjectId",
        "rulesUpdatingProjectId",
        "rulesTogglingProjectId",
        "rulesArchivingProjectId",
        "lastProjectRulesData",
    ):
        assert ("App." + key + " =") in core, (
            f"core.js must declare state key: App.{key}"
        )


def test_project_rules_mc2_no_app_js_reintroduced():
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_mc2_no_forbidden_handler_tokens_in_split_modules():
    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        source = read_js(name)
        for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
            assert token not in source, (
                f"{name} must not contain forbidden handler token: {token}"
            )


def test_project_rules_mc2_split_modules_no_storage_or_network():
    # browser storage or network APIs.
    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        source = read_js(name)
        for forbidden in (
            "localStorage",
            "sessionStorage",
            "document.cookie",
            "fetch(",
            "XMLHttpRequest",
        ):
            assert forbidden not in source, (
                f"{name} must not use forbidden storage/network API: {forbidden}"
            )


def test_project_rules_mc2_split_modules_no_external_resources():
    # external network resources (CDN, Google Fonts, http/https links).
    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        source = read_js(name)
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{name} must not reference external URLs"
        )
        assert not re.search(r"cdn", source, re.IGNORECASE), (
            f"{name} must not reference CDN"
        )
        assert not re.search(r"google\s*fonts", source, re.IGNORECASE), (
            f"{name} must not reference Google Fonts"
        )




def test_project_rules_impact_panel_dom_id_exists():
    section = _rules_section()
    assert 'id="rules-impact-panel"' in section


def test_project_rules_impact_readonly_hint_mentions_5h_capabilities():
    section = _rules_section()
    for term in (
        "预览规则影响",
        "应用到历史记录",
        "批量预览",
        "批量应用",
    ):
        assert term in section, (
            "rules-readonly-hint must mention rule-impact capability: " + term
        )


def test_project_rules_impact_state_variables_declared():
    # button state and the cached preview payload.
    core = read_js("core.js")
    for key in (
        "rulesPreviewingImpactKey",
        "rulesBackfillingRuleKey",
        "rulesImpactPreviewKey",
        "rulesImpactPreviewData",
    ):
        assert ("App." + key + " =") in core, (
            f"core.js must declare state key: App.{key}"
        )


def test_project_rules_impact_preview_button_rendered_for_folder_and_keyword():
    # both folder and keyword paths).
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "rules-preview-impact-button" in row_body


def test_project_rules_impact_backfill_button_rendered_for_folder_and_keyword():
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "rules-backfill-button" in row_body


def test_project_rules_impact_buttons_have_data_rule_kind_and_data_rule_id():
    # data-rule-id attributes so the delegated click handler can resolve
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert '''data-rule-kind="' + kind + '"''' in row_body
    assert '''data-rule-id="' + count(ruleId) + '"''' in row_body


def test_project_rules_impact_preview_button_label_is_preview_impact():
    # in-flight variant handled separately).
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "预览影响" in row_body


def test_project_rules_impact_backfill_button_label_is_apply_to_history():
    # "正在应用…" in-flight variant handled separately).
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "应用到历史记录" in row_body


def test_project_rules_impact_backfill_button_disabled_for_disabled_rules():
    # rule is not enabled, because the bridge refuses to backfill a
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "backfillDisabled" in row_body
    assert "!enabled" in row_body


def test_project_rules_impact_preview_handler_calls_bridge_preview():
    # preview_project_rule_impact bridge method.
    source = read_rules_module_js()
    assert 'callBridge("preview_project_rule_impact"' in source


def test_project_rules_impact_backfill_handler_calls_bridge_backfill():
    # backfill_project_rule bridge method.
    source = read_rules_module_js()
    assert 'callBridge("backfill_project_rule"' in source


def test_project_rules_impact_backfill_confirm_text_mentions_manual_records():
    source = read_rules_module_js()
    assert "手动修改过的记录不会被覆盖" in source
    assert "确定将这条规则应用到符合条件的历史记录吗" in source


def test_project_rules_impact_preview_success_renders_panel_not_list_refresh():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleImpactPreview")
    assert "showProjectRuleImpactPanel" in body
    assert "loadProjectRules()" not in body


def test_project_rules_impact_backfill_success_refreshes_list():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleBackfill")
    assert "loadProjectRules()" in body


def test_project_rules_impact_close_button_does_not_call_bridge():
    # must not call any bridge method (close is a pure UI tear-down).
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleImpactPanelClick")
    assert "clearProjectRuleImpactPanel" in body
    assert "callBridge(" not in body


def test_project_rules_impact_preview_catch_never_reads_raw_exception():
    # error string and never read ``.message`` off the raw exception.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleImpactPreview")
    assert ".message" not in body


def test_project_rules_impact_backfill_catch_never_reads_raw_exception():
    # error string and never read ``.message`` off the raw exception.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleBackfill")
    assert ".message" not in body


def test_project_rules_impact_no_storage_or_network():
    # not use browser storage or network APIs.
    for name in ("rules_render.js", "rules_rule_actions.js"):
        source = read_js(name)
        for forbidden in (
            "localStorage",
            "sessionStorage",
            "document.cookie",
            "fetch(",
            "XMLHttpRequest",
        ):
            assert forbidden not in source, (
                f"{name} must not use forbidden storage/network API: {forbidden}"
            )


def test_project_rules_impact_no_external_resources():
    # not reference external network resources (CDN, Google Fonts,
    for name in ("rules_render.js", "rules_rule_actions.js"):
        source = read_js(name)
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{name} must not reference external URLs"
        )
        assert not re.search(r"cdn", source, re.IGNORECASE), (
            f"{name} must not reference CDN"
        )
        assert not re.search(r"google\s*fonts", source, re.IGNORECASE), (
            f"{name} must not reference Google Fonts"
        )


def test_project_rules_impact_no_forbidden_handler_tokens():
    source = read_js("rules_rule_actions.js")
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source, (
            f"rules_rule_actions.js must not contain forbidden handler token: {token}"
        )


def test_project_rules_impact_no_es_module_syntax():
    for name in ("rules_render.js", "rules_rule_actions.js"):
        source = read_js(name)
        assert "export " not in source, (
            f"{name} must not use ES module export syntax"
        )
        assert "import " not in source, (
            f"{name} must not use ES module import syntax"
        )


def test_project_rules_impact_css_classes_exist():
    css = read_resource("styles.css")
    for cls in (
        ".rules-preview-impact-button",
        ".rules-backfill-button",
        ".rules-impact-panel",
        ".rules-impact-panel-inner",
        ".rules-impact-header",
        ".rules-impact-title",
        ".rules-impact-subtitle",
        ".rules-impact-counts",
        ".rules-impact-samples",
        ".rules-impact-actions",
        ".rules-impact-close-button",
    ):
        assert cls in css, (
            "styles.css must define class: " + cls
        )


def test_project_rules_impact_css_classes_scoped_to_rules_page():
    for cls in (
        ".rules-preview-impact-button",
        ".rules-backfill-button",
        ".rules-impact-panel",
        ".rules-impact-panel-inner",
        ".rules-impact-header",
        ".rules-impact-title",
        ".rules-impact-subtitle",
        ".rules-impact-counts",
        ".rules-impact-samples",
        ".rules-impact-actions",
        ".rules-impact-close-button",
    ):
        assert cls.startswith(".rules-"), (
            "impact CSS class must be scoped under .rules-: " + cls
        )


def test_project_rules_impact_state_isolation_from_other_write_paths():
    # when the other impact write path is in flight, guarding against
    source = read_rules_module_js()
    preview_body = func_body(source, "handleProjectRuleImpactPreview")
    backfill_body = func_body(source, "handleProjectRuleBackfill")
    for body, label in (
        (preview_body, "handleProjectRuleImpactPreview"),
        (backfill_body, "handleProjectRuleBackfill"),
    ):
        assert "App.rulesPreviewingImpactKey" in body, (
            f"{label} must reference App.rulesPreviewingImpactKey guard"
        )
        assert "App.rulesBackfillingRuleKey" in body, (
            f"{label} must reference App.rulesBackfillingRuleKey guard"
        )


def test_project_rules_impact_render_panel_function_exists():
    source = read_js("rules_render.js")
    assert "App.renderProjectRuleImpactPreview = renderProjectRuleImpactPreview" in source
    assert "App.renderProjectRuleBackfillResult = renderProjectRuleBackfillResult" in source


def test_project_rules_impact_render_panel_does_not_call_bridge():
    # bridge calls. Bridge calls live in the action modules.
    source = read_js("rules_render.js")
    assert "callBridge(" not in source, (
        "rules_render.js must not call bridge (pure render module)"
    )


def test_project_rules_impact_render_panel_uses_escape_helper():
    source = read_js("rules_render.js")
    assert "App.escapeHtml" in source


def test_project_rules_impact_packaging_spec_still_includes_rules_js():
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "rules_render.js" in spec
    assert "rules_rule_actions.js" in spec


def test_project_rules_impact_no_new_js_file_added():
    assert "rules_rule_actions.js" in ALL_JS_FILES
    assert "rules_impact_actions.js" not in ALL_JS_FILES


def test_project_rules_impact_init_does_not_bind_impact_buttons_directly():
    source = read_js("init.js")
    assert "rules-preview-impact-button" not in source
    assert "rules-backfill-button" not in source


def test_project_rules_impact_bind_function_called_in_show_and_rerender():
    source = read_js("rules.js")
    assert "App.bindProjectRuleImpactEvents" in source
    assert source.count("App.bindProjectRuleImpactEvents") >= 2


def test_project_rules_impact_buttons_disabled_during_other_writes():
    # renderProjectRuleRow must reference the other rule write state
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    for key in (
        "App.rulesSavingRuleKey",
        "App.rulesDeletingRuleKey",
        "App.rulesEditingKeywordKey",
        "App.rulesEditingFolderKey",
    ):
        assert key in row_body, (
            "renderProjectRuleRow impact section must reference " + key
        )




def test_project_rules_batch_dom_ids_exist():
    # action buttons; the panel holds aggregate counts + per-rule
    section = _rules_section()
    for dom_id in ("rules-batch-toolbar", "rules-batch-panel"):
        assert 'id="' + dom_id + '"' in section, (
            "Project Rules page must contain batch anchor: " + dom_id
        )


def test_project_rules_batch_toolbar_and_panel_are_hidden_by_default():
    section = _rules_section()
    for dom_id in ("rules-batch-toolbar", "rules-batch-panel"):
        needle = 'id="' + dom_id + '"'
        pos = section.find(needle)
        assert pos != -1, "batch container missing: " + dom_id
        tag_end = section.find(">", pos)
        assert tag_end != -1, "batch container tag unclosed: " + dom_id
        assert " hidden" in section[pos:tag_end], (
            "batch container must be hidden by default: " + dom_id
        )


def test_project_rules_batch_static_button_count_unchanged():
    import re as _re

    section = _rules_section()
    buttons = _re.findall(r"<button[^>]*>", section, _re.IGNORECASE)
    assert len(buttons) == 3, (
        "Project Rules page must still have exactly three static buttons "
        "after automatic rules were added; found: " + repr(buttons)
    )
    button_ids = [_re.search(r'id="([^"]+)"', b) for b in buttons]
    button_ids = [m.group(1) for m in button_ids if m]
    assert "rules-project-create-submit" in button_ids
    assert "rules-keyword-create-submit" in button_ids
    assert "rules-folder-create-submit" in button_ids

def test_project_rules_core_js_declares_batch_state_variables():
    # single-rule write states.
    source = read_js("core.js")
    assert "App.rulesBatchSelectedKeys = {}" in source
    assert "App.rulesBatchInFlight = false" in source
    assert "App.rulesBatchPanelData = null" in source


def test_project_rules_js_calls_batch_bridge_methods():
    # the batch handlers must call the new batch bridge methods.
    source = read_rules_module_js()
    assert 'callBridge("preview_project_rules_batch_impact"' in source
    assert 'callBridge("backfill_project_rules_batch"' in source
    assert 'callBridge("set_project_rules_batch_enabled"' in source
    # The new batch bridges must NOT be classified as forbidden write
    for method in (
        "preview_project_rules_batch_impact",
        "backfill_project_rules_batch",
        "set_project_rules_batch_enabled",
    ):
        assert method not in PROJECT_RULE_WRITE_METHODS, (
            "batch bridge method must be allowed (not in "
            "PROJECT_RULE_WRITE_METHODS): " + method
        )


def test_project_rules_batch_handlers_no_forbidden_tokens():
    source = read_js("rules_rule_actions.js")
    batch_functions = (
        "bindProjectRuleBatchEvents",
        "handleProjectRuleBatchCheckboxChange",
        "handleProjectRuleBatchToolbarClick",
        "handleProjectRuleBatchPanelClick",
        "getProjectRulesBatchSelectedRules",
        "clearProjectRulesBatchSelection",
        "handleProjectRulesBatchClear",
        "setProjectRulesBatchInFlight",
        "refreshProjectRulesBatchToolbar",
        "showProjectRulesBatchPanel",
        "clearProjectRulesBatchPanel",
        "handleProjectRulesBatchPreview",
        "handleProjectRulesBatchApply",
        "handleProjectRulesBatchToggle",
    )
    for name in batch_functions:
        body = func_body(source, name)
        for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
            assert token not in body, (
                "batch handler " + name
                + " must not contain forbidden handler token: " + token
            )


def test_project_rules_batch_apply_confirm_text():
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRulesBatchApply")
    assert "window.confirm" in body
    assert "手动修改过的记录不会被覆盖" in body
    assert "命中记录过多时不会写入" in body

def test_project_rules_batch_state_isolated_from_other_write_states():
    # state variable from every other rule write-state variable so batch
    source = read_js("core.js")
    assert "App.rulesBatchInFlight = false" in source
    other_write_states = (
        "App.rulesSavingRuleKey",
        "App.rulesCreatingKeyword",
        "App.rulesDeletingRuleKey",
        "App.rulesEditingKeywordKey",
        "App.rulesUpdatingKeywordKey",
        "App.rulesCreatingFolder",
        "App.rulesEditingFolderKey",
        "App.rulesDeletingFolderKey",
        "App.rulesCreatingProject",
        "App.rulesEditingProjectId",
        "App.rulesUpdatingProjectId",
        "App.rulesPreviewingImpactKey",
        "App.rulesBackfillingRuleKey",
    )
    for var in other_write_states:
        assert var in source, (
            "core.js must declare write-state variable: " + var
        )
        # Each write-state variable must be a distinct identifier from the
        assert var != "App.rulesBatchInFlight"
    # The batch in-flight flag must not be aliased to any other App state.
    assert "App.rulesBatchInFlight = App." not in source


def test_project_rules_batch_css_classes_exist():
    css = read_resource("styles.css")
    for cls in (
        ".rules-batch-toolbar",
        ".rules-batch-toolbar-inner",
        ".rules-batch-selected-count",
        ".rules-batch-preview-button",
        ".rules-batch-apply-button",
        ".rules-batch-enable-button",
        ".rules-batch-disable-button",
        ".rules-batch-clear-button",
        ".rules-batch-panel",
        ".rules-batch-rule-summary",
        ".rules-batch-rule-head",
        ".rules-batch-rule-counts",
        ".rules-batch-rules-list",
        ".rules-batch-checkbox",
        ".rules-row.is-batch-selected",
        ".rules-batch-panel-close-button",
    ):
        assert cls in css, "styles.css must define batch class: " + cls


def test_project_rules_batch_hidden_css_rules_exist():
    css = read_resource("styles.css")
    assert ".rules-batch-toolbar[hidden]" in css, (
        "styles.css must define .rules-batch-toolbar[hidden] rule"
    )
    assert ".rules-batch-panel[hidden]" in css, (
        "styles.css must define .rules-batch-panel[hidden] rule"
    )


def test_project_rules_script_order_preserved_with_batch():
    source = read_resource("index.html")
    positions = []
    for name in ALL_JS_FILES:
        needle = 'src="js/' + name + '"'
        pos = source.find(needle)
        assert pos != -1, "index.html must include script: " + name
        positions.append(pos)
    for i in range(1, len(positions)):
        assert positions[i] > positions[i - 1], (
            "script load order broken around: " + ALL_JS_FILES[i]
        )
    assert "rules_batch_actions.js" not in source
    assert "rules_batch_actions.js" not in ALL_JS_FILES




def test_project_rules_batch_checkbox_groups_by_rule_kind_and_id():
    source = read_js("rules_render.js")
    func = func_body(source, "renderProjectRuleRow")
    assert 'class="rules-batch-checkbox"' in func, (
        "batch checkbox must use the rules-batch-checkbox class"
    )
    assert 'data-rule-kind="' in func, (
        "batch checkbox must carry data-rule-kind attribute"
    )
    assert 'data-rule-id="' in func, (
        "batch checkbox must carry data-rule-id attribute"
    )
    assert "rulesBatchSelectedKeys[ruleKey]" in func, (
        "batch selection state must be keyed by composite ruleKey"
    )


def test_project_rules_no_automatic_rules_on_off_toggle_in_frontend():
    # read-only status payload via ``automatic_rules_status``; the on/off
    html = read_resource("index.html")
    rules_section = _rules_section()
    forbidden_id_patterns = (
        'id="rules-automatic-toggle"',
        'id="rules-automatic-enable"',
        'id="rules-automatic-disable"',
        'id="rules-automatic-switch"',
        'id="rules-automatic-on"',
        'id="rules-automatic-off"',
    )
    for pat in forbidden_id_patterns:
        assert pat not in rules_section, (
            "Project Rules page must not contain an automatic-rules toggle "
            "anchor: " + pat
        )
    forbidden_class_patterns = (
        "rules-automatic-toggle",
        "rules-automatic-switch",
        "rules-automatic-onoff",
    )
    for pat in forbidden_class_patterns:
        assert pat not in rules_section, (
            "Project Rules page must not contain an automatic-rules toggle "
            "class: " + pat
        )
    # would enable/disable the automatic-rules engine. The bridge has
    rules_js = read_rules_module_js()
    forbidden_js_tokens = (
        "set_automatic_rules_enabled",
        "setAutomaticRulesEnabled",
        "toggleAutomaticRules",
        "automaticRulesToggle",
    )
    for token in forbidden_js_tokens:
        assert token not in rules_js, (
            "Project Rules JS must not reference an automatic-rules toggle "
            "entry: " + token
        )
    # which the existing ``test_project_rules_js_calls_allowed_bridge_methods_only``


def test_project_rules_batch_toolbar_buttons_disabled_when_in_flight():
    # in-flight batch operation cannot trigger a duplicate submit. The
    source = read_js("rules_render.js")
    func = func_body(source, "renderProjectRulesBatchToolbar")
    # The in-flight flag must be read.
    assert "App.rulesBatchInFlight" in func, (
        "batch toolbar must reference App.rulesBatchInFlight"
    )
    # in-flight (the ``actionDisabled`` variable carries the disabled
    assert "actionDisabled" in func, (
        "batch toolbar must compute an actionDisabled guard"
    )
    for cls in (
        "rules-batch-preview-button",
        "rules-batch-apply-button",
        "rules-batch-enable-button",
        "rules-batch-disable-button",
    ):
        assert cls in func, "batch toolbar must render button: " + cls


def test_project_rules_batch_handlers_have_no_storage_or_network():
    # ``localStorage`` / ``sessionStorage`` (selection lives in JS memory
    source = read_rules_module_js()
    forbidden_tokens = (
        "localStorage",
        "sessionStorage",
        "window.fetch",
        "fetch(",
        "XMLHttpRequest",
        "navigator.sendBeacon",
        "WebSocket",
        "EventSource",
    )
    for token in forbidden_tokens:
        assert token not in source, (
            "Project Rules JS must not use storage / network API: " + token
        )




def test_rules_render_js_defines_excluded_rule_create_form():
    source = read_js("rules_render.js")
    assert "function renderExcludedRuleCreateForm" in source, (
        "rules_render.js must define renderExcludedRuleCreateForm"
    )
    assert "App.renderExcludedRuleCreateForm = renderExcludedRuleCreateForm" in source, (
        "rules_render.js must attach renderExcludedRuleCreateForm to App"
    )
    for cls in (
        "rules-excluded-keyword-input",
        "rules-excluded-keyword-submit",
        "rules-excluded-folder-input",
        "rules-excluded-folder-recursive",
        "rules-excluded-folder-submit",
    ):
        assert cls in source, (
            "renderExcludedRuleCreateForm must render expected class: " + cls
        )


def test_rules_render_js_renders_excluded_form_only_for_excluded_project():
    source = read_js("rules_render.js")
    assert "isExcluded ? renderExcludedRuleCreateForm()" in source, (
        "renderProjectRuleProject must call renderExcludedRuleCreateForm() "
        "only when isExcluded is true"
    )


def test_rules_keyword_actions_js_binds_and_handles_excluded_keyword_create():
    # with a data attribute, and call the dedicated bridge method WITHOUT
    source = read_js("rules_keyword_actions.js")
    for name in (
        "bindExcludedKeywordRuleEvents",
        "handleExcludedKeywordCreateSubmit",
    ):
        assert ("function " + name) in source, (
            f"rules_keyword_actions.js must define {name}"
        )
        assert ("App." + name + " = " + name) in source, (
            f"rules_keyword_actions.js must attach {name} to App"
        )
    # Event-delegated binding guard.
    assert 'data-excluded-keyword-bound' in source, (
        "bindExcludedKeywordRuleEvents must guard re-binding via "
        "data-excluded-keyword-bound"
    )
    body = func_body(source, "handleExcludedKeywordCreateSubmit")
    # The bridge call must pass only the keyword (no project_id argument).
    assert 'App.callBridge("create_excluded_keyword_rule", keyword)' in body, (
        "handleExcludedKeywordCreateSubmit must call "
        'App.callBridge("create_excluded_keyword_rule", keyword) without '
        "a project_id argument"
    )


def test_rules_folder_actions_js_binds_and_handles_excluded_folder_create():
    # with a data attribute, and call the dedicated bridge method WITHOUT
    source = read_js("rules_folder_actions.js")
    for name in (
        "bindExcludedFolderRuleEvents",
        "handleExcludedFolderCreateSubmit",
    ):
        assert ("function " + name) in source, (
            f"rules_folder_actions.js must define {name}"
        )
        assert ("App." + name + " = " + name) in source, (
            f"rules_folder_actions.js must attach {name} to App"
        )
    assert 'data-excluded-folder-bound' in source, (
        "bindExcludedFolderRuleEvents must guard re-binding via "
        "data-excluded-folder-bound"
    )
    body = func_body(source, "handleExcludedFolderCreateSubmit")
    # The bridge call must pass folderPath + recursive only (no project_id
    assert 'App.callBridge("create_excluded_folder_rule", folderPath, recursive)' in body, (
        "handleExcludedFolderCreateSubmit must call "
        'App.callBridge("create_excluded_folder_rule", folderPath, recursive) '
        "without a project_id argument"
    )


def test_excluded_rule_js_no_storage_network_or_external_resources():
    # browser storage, network APIs, or external resources.
    for name in (
        "rules_render.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        source = read_js(name)
        for forbidden in (
            "localStorage",
            "sessionStorage",
            "document.cookie",
            "fetch(",
            "XMLHttpRequest",
            "navigator.sendBeacon",
            "WebSocket",
            "EventSource",
        ):
            assert forbidden not in source, (
                f"{name} must not use storage / network API: {forbidden}"
            )
        assert not re.search(r"https?://", source, re.IGNORECASE), (
            f"{name} must not reference external URLs"
        )
        assert not re.search(r"cdn", source, re.IGNORECASE), (
            f"{name} must not reference CDN"
        )
