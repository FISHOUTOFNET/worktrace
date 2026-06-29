"""Project Rules WebView static-contract tests through Phase 5G / MC2.

These tests read bundled frontend resources directly. They lock the
Project Rules WebView static surface (rule toggle, keyword create /
edit / delete, folder CRUD, project lifecycle, and the Phase MC2
frontend modularization) without starting pywebview or touching the
database.

Phase MC2 split the Project Rules surface into six classic IIFE
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


def test_project_rules_phase_5b_boundary_copy_present():
    section = _rules_section()
    # Phase 5H: the boundary copy now mentions project lifecycle
    # (create/edit/enable-disable/archive) and single-rule impact preview +
    # safe backfill as supported capabilities alongside the existing
    # folder/keyword rule CRUD. The unsupported-ops clause references
    # automatic rules, batch operations, and project hard delete.
    assert "启用/停用" in section
    assert "新增关键词规则" in section
    assert "删除已有关键词规则" in section
    assert "新增/编辑/删除文件夹规则" in section
    for term in ("编辑", "删除", "预览单条规则影响", "安全应用"):
        assert term in section


def test_project_rules_page_has_no_static_action_buttons():
    section = _rules_section()
    # Phase 5G: the only allowed static buttons in the section are the
    # project create submit button, the keyword create submit button, and
    # the folder create submit button. All other action buttons (project
    # edit/delete, rule edit/delete, etc.) remain forbidden as static DOM.
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
    # Phase M3: rules_project_actions.js loads after rules.js and before init.js.
    assert actions_pos != -1, "index.html must include rules_project_actions.js"
    assert rules_pos < actions_pos < init_pos


def test_project_rules_js_in_static_helper_order():
    assert "rules.js" in ALL_JS_FILES
    assert "rules_project_actions.js" in ALL_JS_FILES
    # Phase 6A: settings.js is loaded between statistics.js and rules.js, so
    # rules.js is no longer immediately after statistics.js.
    assert "settings.js" in ALL_JS_FILES
    assert ALL_JS_FILES.index("settings.js") == ALL_JS_FILES.index("statistics.js") + 1
    assert ALL_JS_FILES.index("rules.js") == ALL_JS_FILES.index("settings.js") + 1
    # Phase MC2: rules.js now splits into render / rule actions / keyword
    # actions / folder actions modules before rules_project_actions.js.
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
    # Phase 5D: delete_project_keyword_rule is the new allowed write bridge.
    assert 'callBridge("delete_project_keyword_rule"' in source
    # Phase 5E: folder rule create/update/delete are the new allowed write bridges.
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
    # Phase 5C: the check uses bridge call string patterns (``callBridge("
    # <method>"``) rather than bare method names so that the allowed
    # ``create_project_keyword_rule`` call is not falsely flagged by the
    # ``create_project`` substring check.
    # Phase 5E: ``create_project_folder_rule``, ``update_project_folder_rule``,
    # and ``delete_project_folder_rule`` are the allowed folder write bridges
    # and are NOT in PROJECT_RULE_WRITE_METHODS.
    for method in PROJECT_RULE_WRITE_METHODS:
        forbidden_call = 'callBridge("' + method + '"'
        assert forbidden_call not in source, (
            "Project Rules frontend must not call write bridge method: " + method
        )
    assert 'callBridge("set_project_rule_enabled"' in source
    assert 'callBridge("create_project_keyword_rule"' in source
    # Phase 5D: delete_project_keyword_rule is the new allowed write bridge.
    assert 'callBridge("delete_project_keyword_rule"' in source
    # Phase 5E: folder rule create/update/delete are the new allowed write bridges.
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


# --- Phase 5B.1 hardening regression locks ---------------------------------


def test_project_rules_toggle_button_is_inside_rule_row_not_project_card():
    # Phase 5B.1 regression lock: the RULE toggle button must be rendered
    # inside ``renderProjectRuleRow`` (i.e. on the rule row), never directly
    # on the project card. The project card template may not contain a
    # ``rules-toggle-btn`` of its own.
    #
    # Phase 5G update: the project card now legitimately contains a project
    # LIFECYCLE toggle button (``rules-project-toggle-button`` class) which
    # is distinct from the rule-level toggle button. The forbidden tokens
    # below protect against accidentally adding a RULE toggle to the
    # project card; they do not forbid the project lifecycle toggle.
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    row_body = func_body(source, "renderProjectRuleRow")
    assert "rules-toggle-btn" in row_body
    assert "rules-toggle-btn" not in project_body
    # The project card only renders rows via the row helper, never a static
    # project-level RULE toggle button. The bare ``set_project_enabled``
    # bridge call (without the ``_for_rules`` suffix) must never appear.
    for forbidden in (
        'data-rule-type="project"',
        "setProjectEnabled",
        'callBridge("set_project_enabled"',
    ):
        assert forbidden not in project_body


def test_project_rules_toggle_handler_clears_saving_state_on_all_paths():
    # Phase 5B.1 regression lock: the saving state must clear on success,
    # on failure (ok=false), and on rejected promise. The handler achieves
    # this by chaining ``App.setProjectRuleSaving(null)`` in the final
    # ``.then`` that runs after ``.catch`` (which always resolves).
    source = read_rules_module_js()
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
    # Phase 5B.1 regression lock: the saving button text must remain the
    # stable ``正在更新…`` label so the user sees a clear in-progress state.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "正在更新…" in row_body
    set_saving_body = func_body(source, "setProjectRuleSaving")
    assert "正在更新…" in set_saving_body


def test_project_rules_toggle_success_then_refresh_chain():
    # Phase 5B.1 regression lock: the success path must call
    # ``loadProjectRules`` (refresh) before showing the success banner so a
    # stale rendered list is never left on screen after a successful toggle.
    source = read_rules_module_js()
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
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleToggle")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body


def test_project_rules_toggle_dataset_id_is_parsed_and_validated():
    # Phase 5B.1 regression lock: the dataset ``data-rule-id`` must be
    # parsed via ``parseInt(..., 10)`` and rejected (``!ruleId``) when the
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
    # Phase 5B.1 regression lock: the dataset ``data-rule-type`` must be
    # validated against ``folder`` / ``keyword`` before the bridge call so
    # a malformed dataset cannot trigger an arbitrary write.
    source = read_rules_module_js()
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
    source = read_rules_module_js()
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
    source = read_rules_module_js()
    assert "正在更新…" in source
    # Loading and error banners are separate DOM nodes.
    assert 'getElementById("rules-loading")' in source
    assert 'getElementById("rules-error")' in source
    # No code path writes the loading banner text into the error banner.
    assert "rules-error" not in func_body(source, "setRulesLoading")
    assert "rules-loading" not in func_body(source, "showRulesError")


def test_project_rules_bridge_call_only_allows_toggle_write():
    # Phase 5B.1 regression lock: ``set_project_rule_enabled``,
    # ``create_project_keyword_rule`` (Phase 5C),
    # ``delete_project_keyword_rule`` (Phase 5D), and
    # ``create_project_folder_rule`` / ``update_project_folder_rule`` /
    # ``delete_project_folder_rule`` (Phase 5E) are the only Project Rules
    # write bridge calls anywhere in the frontend. No other write bridge
    # call (project toggle / create / edit / delete / preview / backfill)
    # may be introduced even in init.js / core.js.
    source = read_all_js()
    assert 'callBridge("set_project_rule_enabled"' in source
    assert 'callBridge("create_project_keyword_rule"' in source
    # Phase 5D: delete_project_keyword_rule is the new allowed write bridge.
    assert 'callBridge("delete_project_keyword_rule"' in source
    # Phase 5E: folder rule create/update/delete are the new allowed write bridges.
    assert 'callBridge("create_project_folder_rule"' in source
    assert 'callBridge("update_project_folder_rule"' in source
    assert 'callBridge("delete_project_folder_rule"' in source
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
    # Phase 5C regression lock (updated in Phase 5E and 5G): the project
    # create submit button, the keyword create submit button, and the
    # folder create submit button are the only new create actions on the
    # Project Rules page. No project edit/delete or rule edit/delete
    # buttons may appear as static DOM.
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
    # Phase 5C regression lock: the JS must parse and validate the project
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
    # Phase 5C regression lock: the JS must validate the keyword is
    # non-empty before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "!keyword" in body
    guard_pos = body.find("!keyword")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_keyword_create_js_trims_keyword_before_bridge():
    # Phase 5C regression lock: the JS must trim the keyword before
    # validation and before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert ".trim()" in body
    trim_pos = body.find(".trim()")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert trim_pos != -1 and bridge_pos != -1
    assert trim_pos < bridge_pos


def test_project_rules_keyword_create_js_has_creating_guard():
    # Phase 5C regression lock: the handler must early-return when a
    # keyword create is already in flight, before any bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "if (App.rulesCreatingKeyword) return" in body
    guard_pos = body.find("if (App.rulesCreatingKeyword) return")
    bridge_pos = body.find('callBridge("create_project_keyword_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_keyword_create_js_has_creating_button_label():
    # Phase 5C regression lock: the creating button text must remain the
    # stable ``正在新增…`` label.
    source = read_rules_module_js()
    body = func_body(source, "setKeywordCreateCreating")
    assert "正在新增…" in body


def test_project_rules_keyword_create_js_success_refreshes_project_rules():
    # Phase 5C regression lock: the success path must call
    # ``loadProjectRules()`` to refresh the Project Rules list.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "App.loadProjectRules()" in body


def test_project_rules_keyword_create_js_success_clears_keyword_input():
    # Phase 5C regression lock: the success path must clear the keyword
    # input so the user can immediately create another rule.
    source = read_rules_module_js()
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
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body


def test_project_rules_keyword_create_js_failure_preserves_keyword_input():
    # Phase 5C regression lock: the failure path must not clear the
    # keyword input so the user can edit and retry.
    source = read_rules_module_js()
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
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordCreateSubmit")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_keyword_create_js_uses_escape_helper_for_dynamic_text():
    # Phase 5C regression lock: dynamic text rendering must use the escape
    # helper. The keyword create status uses ``textContent`` (which is
    # HTML-safe), not ``innerHTML``.
    source = read_rules_module_js()
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
    rules_source = read_rules_module_js()
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
    source = read_rules_module_js()
    body = func_body(source, "populateKeywordCreateProjectSelector")
    assert "if (App.rulesCreatingKeyword) return" in body


def test_project_rules_keyword_create_stale_guard_preserved():
    # Phase 5C regression lock: the existing ``rulesRequestToken`` stale
    # guard in ``loadProjectRules`` must remain intact. The keyword create
    # success path calls ``loadProjectRules()`` which inherits this
    # protection.
    source = read_rules_module_js()
    load_body = func_body(source, "loadProjectRules")
    assert "var token = ++App.rulesRequestToken" in load_body
    assert load_body.count("token !== App.rulesRequestToken") >= 2


def test_project_rules_keyword_create_no_storage_or_network():
    # Phase 5C regression lock: the keyword create form must not use
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
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source


# --- Phase 5C.1: keyword creation hardening static-contract locks ---------


def test_project_rules_keyword_create_creating_state_clears_on_all_paths():
    # Phase 5C.1 regression lock: the creating state must clear on success,
    # on failure (ok=false), and on rejected promise. The handler achieves
    # this by chaining ``App.setKeywordCreateCreating(false)`` in the final
    # ``.then`` that runs after ``.catch`` (which always resolves).
    source = read_rules_module_js()
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
    source = read_rules_module_js()
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
    source = read_rules_module_js()
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
    source = read_rules_module_js()
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
    source = read_rules_module_js()
    status_body = func_body(source, "showKeywordCreateStatus")
    assert "textContent" in status_body
    assert ".innerHTML" not in status_body


# --- Phase 5D: keyword rule deletion foundation static contract ----------


def test_project_rules_keyword_delete_state_variable_declared():
    # Phase 5D regression lock: the keyword delete saving state must be a
    # separate state variable from the Phase 5B toggle saving state and
    # the Phase 5C keyword create state so the three write paths can never
    # pollute each other.
    source = read_js("core.js")
    assert "App.rulesDeletingRuleKey = null" in source
    # The toggle saving state and the keyword create state must still exist
    # alongside it.
    assert "App.rulesSavingRuleKey = null" in source
    assert "App.rulesCreatingKeyword = false" in source


def test_project_rules_keyword_delete_js_calls_bridge_method():
    # Phase 5D regression lock: the JS must call the
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
    # Phase 5D regression lock: the delete path must not invoke the toggle
    # or any edit API.
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("set_keyword_rule_enabled"',
        'callBridge("set_folder_rule_enabled"',
        'callBridge("set_project_rule_enabled"',
    ):
        # The toggle handler may call ``set_project_rule_enabled``; the
        # delete handler must not. Verify by checking the delete handler
        # body specifically.
        delete_body = func_body(source, "handleProjectRuleDelete")
        assert forbidden not in delete_body


def test_project_rules_keyword_delete_js_does_not_call_preview_or_backfill():
    source = read_rules_module_js()
    assert 'callBridge("preview_folder_rule_conflicts"' not in source
    assert 'callBridge("backfill_folder_rule"' not in source


def test_project_rules_keyword_delete_js_validates_rule_id_before_bridge():
    # Phase 5D regression lock: the JS must parse and validate the rule id
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
    # Phase 5D regression lock: the dataset ``data-rule-kind`` must be
    # validated against ``keyword`` before the bridge call so a malformed
    # dataset cannot trigger an arbitrary write.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert 'kind !== "keyword"' in body
    type_check_pos = body.find('kind !== "keyword"')
    bridge_pos = body.find('callBridge("delete_project_keyword_rule"')
    assert type_check_pos < bridge_pos


def test_project_rules_keyword_delete_js_has_deleting_guard():
    # Phase 5D regression lock: the handler must early-return when a
    # keyword delete is already in flight, before any bridge call or
    # confirmation dialog.
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
    # Phase 5D regression lock: the deleting button text must remain the
    # stable ``正在删除…`` label.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "正在删除…" in row_body
    set_deleting_body = func_body(source, "setRuleDeleting")
    assert "正在删除…" in set_deleting_body


def test_project_rules_keyword_delete_js_confirmation_text_present():
    # Phase 5D regression lock: the confirmation text must explicitly
    # mention deleting this keyword rule and that it will no longer be
    # used for auto-classification.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert "确定删除这条关键词规则吗？删除后该关键词将不再用于自动归类。" in body


def test_project_rules_keyword_delete_js_cancellation_does_not_call_bridge():
    # Phase 5D regression lock: when the user cancels the delete
    # confirmation, the handler must ``return`` immediately without calling
    # ``App.setRuleDeleting`` or the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    confirm_pos = body.find("window.confirm")
    bridge_pos = body.find('callBridge("delete_project_keyword_rule"')
    assert confirm_pos < bridge_pos
    # Locate the cancellation ``return;`` that closes the confirm branch.
    cancellation_return = body.find("return;", confirm_pos)
    assert cancellation_return != -1 and cancellation_return < bridge_pos


def test_project_rules_keyword_delete_js_success_refreshes_project_rules():
    # Phase 5D regression lock: the success path must call
    # ``loadProjectRules()`` to refresh the Project Rules list.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert "App.loadProjectRules()" in body


def test_project_rules_keyword_delete_js_success_shows_stable_message():
    # Phase 5D regression lock: the success path must show the stable
    # ``关键词规则已删除`` message after refresh.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    refresh_pos = body.find("App.loadProjectRules()")
    success_pos = body.find("关键词规则已删除")
    assert refresh_pos != -1 and success_pos != -1
    assert refresh_pos < success_pos


def test_project_rules_keyword_delete_js_failure_preserves_rendered_list():
    # Phase 5D regression lock: the failure path must not clear the
    # already-rendered Project Rules list. The handler may only show a
    # stable error message, never ``list.innerHTML = ""`` or
    # ``showProjectRules`` with an empty payload.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body
    assert "删除关键词规则失败" in body


def test_project_rules_keyword_delete_js_catch_never_reads_raw_exception():
    # Phase 5D regression lock: the catch path must never read
    # ``.message`` from the error.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_keyword_delete_js_deleting_state_clears_on_all_paths():
    # Phase 5D regression lock: the deleting state must clear on success,
    # on failure (ok=false), and on rejected promise. The handler achieves
    # this by chaining ``App.setRuleDeleting(null)`` in the final
    # ``.then`` that runs after ``.catch`` (which always resolves).
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleDelete")
    assert "App.setRuleDeleting(" in body
    # The final cleanup must run unconditionally after the catch.
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setRuleDeleting(null)", catch_pos)
    assert cleanup_pos != -1, (
        "App.setRuleDeleting(null) must run after .catch so the deleting "
        "state clears on success, failure, and rejected-promise paths"
    )


def test_project_rules_keyword_delete_state_isolation_from_toggle_saving():
    # Phase 5D regression lock: the keyword delete saving state
    # (``rulesDeletingRuleKey``) must be separate from the toggle saving
    # state (``rulesSavingRuleKey``) and the keyword create state
    # (``rulesCreatingKeyword``). The three write paths must not pollute
    # each other's button / input disabled state.
    source = read_js("core.js")
    assert "App.rulesDeletingRuleKey" in source
    assert "App.rulesSavingRuleKey" in source
    assert "App.rulesCreatingKeyword" in source
    # The toggle saving handler must not read or write the delete state.
    rules_source = read_rules_module_js()
    toggle_body = func_body(rules_source, "setProjectRuleSaving")
    assert "App.rulesDeletingRuleKey" not in toggle_body
    # The delete handler must not read or write the toggle saving state
    # directly (it may only read the global state for disable coordination
    # in ``setRuleDeleting``, not in ``handleProjectRuleDelete``).
    delete_body = func_body(rules_source, "handleProjectRuleDelete")
    assert "App.rulesSavingRuleKey" not in delete_body
    assert "App.rulesCreatingKeyword" not in delete_body


def test_project_rules_keyword_delete_state_isolation_from_keyword_create():
    # Phase 5D regression lock: the keyword create saving handler must not
    # read or write the delete state.
    source = read_rules_module_js()
    create_body = func_body(source, "setKeywordCreateCreating")
    assert "App.rulesDeletingRuleKey" not in create_body


def test_project_rules_keyword_delete_button_only_on_keyword_rows():
    # Phase 5D regression lock: the delete button must be rendered only on
    # keyword rule rows, never on folder rule rows or project cards. The
    # renderProjectRuleRow function must gate the delete button on
    # ``kind === "keyword"``.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'kind === "keyword"' in row_body
    assert "rules-keyword-delete-button" in row_body
    # The project card template must not contain a delete button.
    project_body = func_body(source, "renderProjectRuleProject")
    assert "rules-keyword-delete-button" not in project_body


def test_project_rules_keyword_delete_button_uses_stable_class_and_attributes():
    # Phase 5D regression lock: the delete button must use the stable
    # class / data attributes specified in the Phase 5D contract.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'class="rules-keyword-delete-button"' in row_body
    assert 'data-rule-kind="keyword"' in row_body
    assert 'data-rule-id="' in row_body


def test_project_rules_keyword_delete_button_does_not_appear_on_folder_rows():
    # Phase 5D regression lock: the delete button is rendered conditionally
    # inside the ``if (kind === "keyword" && ruleId)`` block. Folder rows
    # (kind === "folder") never enter that block, so they never get a
    # delete button.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    # The delete button HTML assignment (``deleteButton = '  <button ...``)
    # is inside the keyword-only branch. The ``var deleteButton = ""``
    # initialization is outside the branch and must not be confused with it.
    keyword_guard_pos = row_body.find('kind === "keyword"')
    delete_html_assign_pos = row_body.find("deleteButton = '", keyword_guard_pos)
    assert keyword_guard_pos != -1 and delete_html_assign_pos != -1
    assert keyword_guard_pos < delete_html_assign_pos


def test_project_rules_keyword_delete_button_disabled_when_any_write_in_flight():
    # Phase 5D regression lock: the delete button must be disabled when any
    # rule write (toggle saving or keyword delete) is in flight on this row.
    # The toggle button must likewise be disabled when a delete is in
    # flight. This keeps the two write paths from concurrently polluting
    # the same row.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    # The delete button disabled condition must check both saving states.
    assert "App.rulesSavingRuleKey" in row_body
    assert "App.rulesDeletingRuleKey" in row_body
    # The toggle button disabled condition must also check both states.
    toggle_disabled_pos = row_body.find("disabledAttr")
    assert toggle_disabled_pos != -1
    toggle_disabled_clause = row_body[toggle_disabled_pos:row_body.find("?", toggle_disabled_pos)]
    assert "rulesSavingRuleKey" in toggle_disabled_clause
    assert "rulesDeletingRuleKey" in toggle_disabled_clause


def test_project_rules_keyword_delete_set_rule_deleting_updates_toggle_buttons():
    # Phase 5D regression lock: ``setRuleDeleting`` must disable toggle
    # buttons while a delete is in flight so the toggle and delete paths
    # cannot run concurrently on one row.
    source = read_rules_module_js()
    body = func_body(source, "setRuleDeleting")
    assert "rules-toggle-btn" in body
    assert "App.rulesSavingRuleKey" in body
    assert "App.rulesDeletingRuleKey" in body


def test_project_rules_keyword_delete_stale_guard_preserved():
    # Phase 5D regression lock: the existing ``rulesRequestToken`` stale
    # guard in ``loadProjectRules`` must remain intact. The keyword delete
    # success path calls ``loadProjectRules()`` which inherits this
    # protection.
    source = read_rules_module_js()
    load_body = func_body(source, "loadProjectRules")
    assert "var token = ++App.rulesRequestToken" in load_body
    assert load_body.count("token !== App.rulesRequestToken") >= 2


def test_project_rules_keyword_delete_no_storage_or_network():
    # Phase 5D regression lock: the keyword delete handler must not use
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
    # Phase 5D regression lock: dynamic text rendering in the delete button
    # must use the escape helper. The rule id is rendered via ``count()``
    # which calls ``App.escapeHtml``.
    source = read_rules_module_js()
    count_body = func_body(source, "count")
    assert "App.escapeHtml" in count_body
    row_body = func_body(source, "renderProjectRuleRow")
    assert "count(ruleId)" in row_body


def test_project_rules_keyword_delete_no_forbidden_handler_tokens():
    # Phase 5D regression lock: the keyword delete JS must not introduce
    # any of the forbidden camelCase handler tokens.
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source


def test_project_rules_keyword_delete_init_does_not_bind_delete_event():
    # Phase 5D regression lock: the init module must not bind any delete
    # event directly. The delete button uses event delegation on the
    # rules-list container, set up inside ``rules.js`` (Phase 5D), not in
    # init.js.
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
    # Phase 5D regression lock: the frontend must not reintroduce app.js.
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_keyword_delete_no_duplicate_static_dom_ids():
    # Phase 5D regression lock: the static ``page-rules`` section in
    # ``index.html`` must not declare the same DOM id twice. The Phase 5D
    # addition does not introduce any new static DOM (the delete button is
    # rendered dynamically by JS).
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
    # Phase 5D regression lock: the static ``page-rules`` section in
    # ``index.html`` must not contain a delete button. The delete button is
    # rendered dynamically by JS only on keyword rule rows.
    section = _rules_section()
    assert "rules-keyword-delete-button" not in section
    assert "rules-folder-delete-button" not in section
    assert "rules-keyword-edit-button" not in section
    assert "rules-folder-edit-button" not in section


def test_project_rules_keyword_delete_page_has_no_export_or_auto_submit_controls():
    # Phase 5D regression lock: the Project Rules page must not contain
    # Excel / PDF / timesheet / open-folder / auto-submit controls.
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
    # Phase 5D regression lock: the ``.rules-keyword-delete-button`` CSS
    # class must exist in styles.css so the dynamically-rendered delete
    # button has a stable visual style.
    source = read_resource("styles.css")
    assert ".rules-keyword-delete-button" in source
    # The CSS must not depend on external resources.
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"cdn", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_keyword_delete_packaging_spec_still_includes_rules_js():
    # Phase 5D regression lock: the packaging spec must still include
    # rules.js so the delete button handler ships in the packaged build.
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'rules.js'" in source or '"rules.js"' in source
    assert "'rules_project_actions.js'" in source or '"rules_project_actions.js"' in source
    assert "'worktrace/webview_ui/js'" in source or '"worktrace/webview_ui/js"' in source


def test_project_rules_keyword_delete_boundary_copy_present():
    # Phase 5D regression lock: the boundary copy must mention keyword rule
    # deletion as a supported capability and still reference the remaining
    # future capabilities.
    section = _rules_section()
    assert "启用/停用" in section
    assert "新增关键词规则" in section
    assert "删除已有关键词规则" in section
    for term in ("编辑", "删除", "预览单条规则影响", "安全应用"):
        assert term in section


def test_project_rules_keyword_delete_js_does_not_call_create_or_folder_create():
    # Phase 5D regression lock: the delete handler must not call create
    # APIs or folder create APIs.
    source = read_rules_module_js()
    delete_body = func_body(source, "handleProjectRuleDelete")
    for forbidden in (
        'callBridge("create_project_keyword_rule"',
        'callBridge("create_or_update_folder_rule"',
        'callBridge("create_keyword_rule"',
        'callBridge("create_project"',
    ):
        assert forbidden not in delete_body


# --- Phase 5D.1: keyword deletion hardening static-contract locks ---------


def test_project_rules_keyword_delete_css_class_scoped_to_rules_page():
    # Phase 5D.1 regression lock: the ``.rules-keyword-delete-button`` CSS
    # class must be namespaced with the ``rules-`` prefix and must not be
    # referenced by the Overview / Timeline / Statistics static HTML
    # sections, so the Project Rules delete button style cannot leak into
    # (or be re-styled by) the other pages.
    css = read_resource("styles.css")
    assert ".rules-keyword-delete-button" in css
    # The selector must carry the Project Rules namespace prefix.
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
    # Phase 5D.1 regression lock: the delete handler body must not read or
    # write the Phase 5B toggle saving state (``rulesSavingRuleKey``) or
    # the Phase 5C keyword create state (``rulesCreatingKeyword``). The
    # three write paths are coordinated only through ``setRuleDeleting``
    # (which disables toggle buttons) and the per-row render-time disabled
    # attribute — never by cross-reading the other handlers' state inside
    # ``handleProjectRuleDelete``. This complements the existing state
    # isolation locks with a handler-body-specific check.
    source = read_rules_module_js()
    delete_body = func_body(source, "handleProjectRuleDelete")
    assert "App.rulesSavingRuleKey" not in delete_body
    assert "App.rulesCreatingKeyword" not in delete_body
    # The deleting state itself must be present.
    assert "App.rulesDeletingRuleKey" in delete_body


def test_project_rules_keyword_delete_button_disabled_coordination_uses_deleting_state():
    # Phase 5D.1 regression lock: ``setRuleDeleting`` must toggle the
    # ``disabled`` state of both delete buttons and toggle buttons based on
    # ``App.rulesDeletingRuleKey`` (and ``App.rulesSavingRuleKey`` for the
    # toggle side), so a keyword delete in flight blocks concurrent toggles
    # on the same row. The function must not consult the keyword create
    # state (``rulesCreatingKeyword``), keeping the create and delete paths
    # independent.
    source = read_rules_module_js()
    body = func_body(source, "setRuleDeleting")
    assert "App.rulesDeletingRuleKey" in body
    assert "App.rulesSavingRuleKey" in body
    assert "rules-toggle-btn" in body
    assert "rules-keyword-delete-button" in body
    assert "App.rulesCreatingKeyword" not in body


# --- Phase 5E: folder rule CRUD foundation static contract ---------------


def test_project_rules_folder_create_form_anchors_exist():
    # Phase 5E regression lock: the Project Rules page must contain the
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
    # Phase 5E regression lock: the folder create saving state must be a
    # separate state variable from the Phase 5B toggle saving state, the
    # Phase 5C keyword create state, and the Phase 5D keyword delete state
    # so the five write paths can never pollute each other.
    source = read_js("core.js")
    assert "App.rulesCreatingFolder = false" in source
    assert "App.rulesEditingFolderKey = null" in source
    assert "App.rulesDeletingFolderKey = null" in source
    assert "App.lastProjectRulesData = null" in source
    # The earlier state variables must still exist alongside the new ones.
    assert "App.rulesSavingRuleKey = null" in source
    assert "App.rulesCreatingKeyword = false" in source
    assert "App.rulesDeletingRuleKey = null" in source


def test_project_rules_folder_create_js_calls_bridge_method():
    # Phase 5E regression lock: the JS must call the
    # ``create_project_folder_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("create_project_folder_rule"' in source


def test_project_rules_folder_update_js_calls_bridge_method():
    # Phase 5E regression lock: the JS must call the
    # ``update_project_folder_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("update_project_folder_rule"' in source


def test_project_rules_folder_delete_js_calls_bridge_method():
    # Phase 5E regression lock: the JS must call the
    # ``delete_project_folder_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("delete_project_folder_rule"' in source


def test_project_rules_folder_create_js_does_not_call_keyword_create_or_delete():
    # Phase 5E regression lock: the folder create handler must not call
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
    # Phase 5E regression lock: the folder delete handler must not call
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
    # Phase 5E regression lock: the folder update handler must not call
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
    # Phase 5E regression lock: the JS must parse and validate the project
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
    # Phase 5E regression lock: the JS must validate the folder_path is
    # non-empty before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "!folderPath" in body
    guard_pos = body.find("!folderPath")
    bridge_pos = body.find('callBridge("create_project_folder_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_folder_create_js_trims_folder_path_before_bridge():
    # Phase 5E regression lock: the JS must trim the folder_path before
    # validation and before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert ".trim()" in body
    trim_pos = body.find(".trim()")
    bridge_pos = body.find('callBridge("create_project_folder_rule"')
    assert trim_pos != -1 and bridge_pos != -1
    assert trim_pos < bridge_pos


def test_project_rules_folder_create_js_has_creating_guard():
    # Phase 5E regression lock: the handler must early-return when a
    # folder create is already in flight, before any bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "if (App.rulesCreatingFolder) return" in body
    guard_pos = body.find("if (App.rulesCreatingFolder) return")
    bridge_pos = body.find('callBridge("create_project_folder_rule"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_folder_create_js_has_creating_button_label():
    # Phase 5E regression lock: the creating button text must remain the
    # stable ``正在新增…`` label.
    source = read_rules_module_js()
    body = func_body(source, "setFolderCreateCreating")
    assert "正在新增…" in body


def test_project_rules_folder_create_js_success_refreshes_project_rules():
    # Phase 5E regression lock: the success path must call
    # ``loadProjectRules()`` to refresh the Project Rules list.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "App.loadProjectRules()" in body


def test_project_rules_folder_create_js_success_clears_folder_path_input():
    # Phase 5E regression lock: the success path must clear the folder_path
    # input so the user can immediately create another rule.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert 'input.value = ""' in body


def test_project_rules_folder_create_js_failure_preserves_rendered_list():
    # Phase 5E regression lock: the failure path must not clear the
    # already-rendered Project Rules list.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "list.innerHTML" not in body


def test_project_rules_folder_create_js_catch_never_reads_raw_exception():
    # Phase 5E regression lock: the catch path must never read
    # ``.message`` from the error.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_folder_create_js_uses_textcontent_for_status():
    # Phase 5E regression lock: the folder create status must use
    # ``textContent`` (HTML-safe), not ``innerHTML``.
    source = read_rules_module_js()
    status_body = func_body(source, "showFolderCreateStatus")
    assert "textContent" in status_body
    assert ".innerHTML" not in status_body


def test_project_rules_folder_create_state_isolation_from_other_write_paths():
    # Phase 5E regression lock: the folder create saving state
    # (``rulesCreatingFolder``) must be separate from the toggle saving
    # state (``rulesSavingRuleKey``), the keyword create state
    # (``rulesCreatingKeyword``), the keyword delete state
    # (``rulesDeletingRuleKey``), the folder edit state
    # (``rulesEditingFolderKey``), and the folder delete state
    # (``rulesDeletingFolderKey``).
    source = read_js("core.js")
    assert "App.rulesCreatingFolder" in source
    assert "App.rulesEditingFolderKey" in source
    assert "App.rulesDeletingFolderKey" in source
    rules_source = read_rules_module_js()
    # The folder create handler must not read the toggle saving state or
    # keyword create/delete state.
    create_body = func_body(rules_source, "handleFolderCreateSubmit")
    assert "App.rulesSavingRuleKey" not in create_body
    assert "App.rulesCreatingKeyword" not in create_body
    assert "App.rulesDeletingRuleKey" not in create_body


def test_project_rules_folder_create_selector_population_guard():
    # Phase 5E regression lock: the project selector must not be
    # re-populated while a folder create is in flight, so the user's
    # selection is never displaced by an auto-refresh.
    source = read_rules_module_js()
    body = func_body(source, "populateFolderCreateProjectSelector")
    assert "if (App.rulesCreatingFolder) return" in body


def test_project_rules_folder_edit_buttons_only_on_folder_rows():
    # Phase 5E regression lock: the edit / delete buttons must be rendered
    # only on folder rule rows, never on keyword rule rows or project cards.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'kind === "folder"' in row_body
    assert "rules-folder-edit-button" in row_body
    assert "rules-folder-delete-button" in row_body
    project_body = func_body(source, "renderProjectRuleProject")
    assert "rules-folder-edit-button" not in project_body
    assert "rules-folder-delete-button" not in project_body


def test_project_rules_folder_edit_button_uses_stable_class_and_attributes():
    # Phase 5E regression lock: the folder edit / delete buttons must use
    # the stable class / data attributes.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'class="rules-folder-edit-button"' in row_body
    assert 'class="rules-folder-delete-button"' in row_body
    assert 'data-rule-kind="folder"' in row_body


def test_project_rules_folder_edit_js_validates_rule_id_before_bridge():
    # Phase 5E regression lock: the JS must parse and validate the rule id
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
    # Phase 5E regression lock: the dataset ``data-rule-kind`` must be
    # validated against ``folder`` before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert 'kind !== "folder"' in body
    type_check_pos = body.find('kind !== "folder"')
    bridge_pos = body.find('callBridge("update_project_folder_rule"')
    assert type_check_pos < bridge_pos


def test_project_rules_folder_edit_js_has_editing_guard():
    # Phase 5E regression lock: the handler must early-return when no
    # folder edit is in flight.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "if (!App.rulesEditingFolderKey) return" in body


def test_project_rules_folder_edit_js_has_saving_button_label():
    # Phase 5E regression lock: the saving button text must remain the
    # stable ``正在保存…`` label.
    source = read_rules_module_js()
    body = func_body(source, "setFolderSaving")
    assert "正在保存…" in body


def test_project_rules_folder_edit_js_success_refreshes_project_rules():
    # Phase 5E regression lock: the success path must call
    # ``loadProjectRules()`` to refresh the Project Rules list.
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
    # Phase 5E regression lock: the saving state must clear on success,
    # on failure, and on rejected promise.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "App.setFolderSaving(true)" in body
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setFolderSaving(false)", catch_pos)
    assert cleanup_pos != -1


def test_project_rules_folder_edit_js_editing_state_clears_on_success():
    # Phase 5E regression lock: the editing state must clear on success.
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


def test_project_rules_folder_delete_js_does_not_call_keyword_delete():
    source = read_rules_module_js()
    delete_body = func_body(source, "handleFolderDelete")
    assert 'callBridge("delete_project_keyword_rule"' not in delete_body
    assert 'callBridge("delete_keyword_rule"' not in delete_body


def test_project_rules_folder_delete_button_does_not_appear_on_keyword_rows():
    # Phase 5E regression lock: the folder edit / delete buttons are rendered
    # only inside the ``if (kind === "folder" && ruleId)`` block. Keyword rows
    # never enter that block, so they never get folder buttons.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    folder_guard_pos = row_body.find('kind === "folder"')
    folder_html_pos = row_body.find("rules-folder-edit-button", folder_guard_pos)
    assert folder_guard_pos != -1 and folder_html_pos != -1
    assert folder_guard_pos < folder_html_pos


def test_project_rules_folder_buttons_disabled_when_any_write_in_flight():
    # Phase 5E regression lock: the folder edit / delete buttons must be
    # disabled when any rule write is in flight on this row.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "App.rulesCreatingFolder" in row_body
    assert "App.rulesEditingFolderKey" in row_body
    assert "App.rulesDeletingFolderKey" in row_body
    assert "App.rulesSavingRuleKey" in row_body
    assert "App.rulesDeletingRuleKey" in row_body


def test_project_rules_folder_delete_set_deleting_updates_toggle_buttons():
    # Phase 5E regression lock: ``setFolderDeleting`` must disable toggle
    # buttons while a folder delete is in flight.
    source = read_rules_module_js()
    body = func_body(source, "setFolderDeleting")
    assert "rules-toggle-btn" in body
    assert "App.rulesDeletingFolderKey" in body


def test_project_rules_folder_create_init_binds_submit_button():
    # Phase 5E regression lock: the init module must bind the folder
    # create submit button click event.
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
    # Phase 5E regression lock: the folder CRUD CSS classes must exist in
    # styles.css so the dynamically-rendered folder buttons and the static
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
    # The CSS must not depend on external resources.
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"cdn", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_folder_css_class_scoped_to_rules_page():
    # Phase 5E regression lock: the folder CRUD CSS classes must be
    # namespaced with the ``rules-`` prefix and must not be referenced by
    # the Overview / Timeline / Statistics static HTML sections.
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
    # Phase 5E regression lock: the existing ``rulesRequestToken`` stale
    # guard in ``loadProjectRules`` must remain intact. The folder create
    # success path calls ``loadProjectRules()`` which inherits this
    # protection.
    source = read_rules_module_js()
    load_body = func_body(source, "loadProjectRules")
    assert "var token = ++App.rulesRequestToken" in load_body
    assert load_body.count("token !== App.rulesRequestToken") >= 2


def test_project_rules_folder_create_no_export_or_auto_submit_controls():
    # Phase 5E regression lock: the Project Rules page must not contain
    # Excel / PDF / timesheet / open-folder / auto-submit controls.
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
    # Phase 5E regression lock: the Project Rules page must not contain
    # project create / edit / delete / archive / enable / disable controls.
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
    # Phase 5E regression lock: the folder edit / delete / edit-save /
    # edit-cancel events must be delegated via a single click handler on
    # ``#rules-list``, not via per-button listeners in init.js.
    source = read_rules_module_js()
    bind_body = func_body(source, "bindProjectRuleFolderEvents")
    assert 'getElementById("rules-list")' in bind_body
    assert "addEventListener" in bind_body
    assert "handleProjectRuleFolderEvent" in bind_body


def test_project_rules_folder_event_handler_routes_by_button_class():
    # Phase 5E regression lock: the delegated folder event handler must
    # route to the correct sub-handler based on the button class.
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
    # Phase 5E regression lock: the creating state must clear on success,
    # on failure, and on rejected promise.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderCreateSubmit")
    assert "App.setFolderCreateCreating(true)" in body
    assert ".catch(function ()" in body
    catch_pos = body.find(".catch(function ()")
    cleanup_pos = body.find("App.setFolderCreateCreating(false)", catch_pos)
    assert cleanup_pos != -1


def test_project_rules_folder_delete_state_isolation_from_other_write_paths():
    # Phase 5E regression lock: the folder delete handler must not read
    # the toggle saving state, keyword create state, or keyword delete
    # state directly.
    source = read_rules_module_js()
    delete_body = func_body(source, "handleFolderDelete")
    assert "App.rulesSavingRuleKey" not in delete_body
    assert "App.rulesCreatingKeyword" not in delete_body
    assert "App.rulesDeletingRuleKey" not in delete_body
    assert "App.rulesCreatingFolder" in delete_body
    assert "App.rulesDeletingFolderKey" in delete_body


def test_project_rules_folder_edit_state_isolation_from_other_write_paths():
    # Phase 5E regression lock: the folder edit save handler must not read
    # the toggle saving state, keyword create state, or keyword delete
    # state directly.
    source = read_rules_module_js()
    edit_body = func_body(source, "handleFolderEditSave")
    assert "App.rulesSavingRuleKey" not in edit_body
    assert "App.rulesCreatingKeyword" not in edit_body
    assert "App.rulesDeletingRuleKey" not in edit_body


def test_project_rules_folder_inline_edit_form_renders_in_place_of_row():
    # Phase 5E regression lock: when a folder row is being edited, the
    # renderProjectRuleRow function must render the inline edit form
    # (with input + checkbox + save / cancel buttons) in place of the
    # normal row body.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "is-folder-editing" in row_body
    assert "rules-folder-edit-form" in row_body
    assert "rules-folder-edit-input" in row_body
    assert "rules-folder-edit-recursive" in row_body
    assert "rules-folder-edit-save" in row_body
    assert "rules-folder-edit-cancel" in row_body


def test_project_rules_folder_show_project_rules_caches_last_data():
    # Phase 5E regression lock: the ``showProjectRules`` function must
    # cache the last-loaded data so the inline folder edit form can
    # re-render the list immediately without a round-trip.
    source = read_rules_module_js()
    body = func_body(source, "showProjectRules")
    assert "App.lastProjectRulesData" in body


def test_project_rules_folder_show_project_rules_populates_folder_selector():
    # Phase 5E regression lock: ``showProjectRules`` must call
    # ``populateFolderCreateProjectSelector`` so the folder create form's
    # project selector stays in sync with the loaded data.
    source = read_rules_module_js()
    body = func_body(source, "showProjectRules")
    assert "populateFolderCreateProjectSelector" in body


def test_project_rules_folder_show_project_rules_binds_folder_events():
    # Phase 5E regression lock: ``showProjectRules`` must call
    # ``bindProjectRuleFolderEvents`` so the folder edit / delete
    # delegation is set up after every render.
    source = read_rules_module_js()
    body = func_body(source, "showProjectRules")
    assert "bindProjectRuleFolderEvents" in body


def test_project_rules_folder_rerender_uses_cached_data():
    # Phase 5E regression lock: ``rerenderProjectRulesList`` must use the
    # cached ``lastProjectRulesData`` instead of calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "rerenderProjectRulesList")
    assert "App.lastProjectRulesData" in body


def test_project_rules_folder_packaging_spec_still_includes_rules_js():
    # Phase 5E regression lock: the packaging spec must still include
    # rules.js so the folder CRUD handlers ship in the packaged build.
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'rules.js'" in source or '"rules.js"' in source
    assert "'rules_project_actions.js'" in source or '"rules_project_actions.js"' in source
    assert "'worktrace/webview_ui/js'" in source or '"worktrace/webview_ui/js"' in source


# --- Phase 5E.1: folder rule CRUD static contract hardening ---------------
#
# These locks complement the Phase 5E static contract with additional
# DOM-anchor, CSS-scoping, no-forbidden-features, packaging-inclusion,
# edit-cancel, and state-declaration regression locks. They do not open
# any new capability; they only harden the existing folder rule
# create / edit / delete static contract.


def test_project_rules_folder_edit_cancel_does_not_call_bridge():
    # Phase 5E.1 regression lock: the folder edit cancel handler must not
    # call any bridge method. It only clears the editing state and
    # re-renders. This complements the existing delete-cancel guard.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditCancel")
    assert "callBridge(" not in body


def test_project_rules_folder_edit_cancel_clears_editing_state():
    # Phase 5E.1 regression lock: the cancel handler must clear the
    # editing state by calling ``setFolderEditing(null)``.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditCancel")
    assert "App.setFolderEditing(null)" in body


def test_project_rules_folder_edit_cancel_has_early_return_guard():
    # Phase 5E.1 regression lock: the cancel handler must early-return
    # when no folder edit is in flight.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditCancel")
    assert "if (!App.rulesEditingFolderKey) return" in body


def test_project_rules_folder_edit_start_sets_editing_key():
    # Phase 5E.1 regression lock: the edit-start handler must set the
    # editing key to ``"folder:<id>"`` so the inline edit form renders
    # for the correct row only.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditStart")
    assert "App.setFolderEditing" in body
    assert '"folder:"' in body or "'folder:'" in body


def test_project_rules_folder_edit_save_disables_save_and_cancel_buttons():
    # Phase 5E.1 regression lock: ``setFolderSaving`` must disable both
    # the save and cancel buttons while a save is in flight so the user
    # cannot double-submit or cancel mid-save.
    source = read_rules_module_js()
    body = func_body(source, "setFolderSaving")
    assert "rules-folder-edit-save" in body
    assert "rules-folder-edit-cancel" in body
    assert "btn.disabled = !!saving" in body


def test_project_rules_folder_edit_form_has_maxlength_on_input():
    # Phase 5E.1 regression lock: the inline edit form input must have a
    # ``maxlength`` attribute so the user cannot enter an over-long path.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'maxlength="512"' in row_body


def test_project_rules_folder_edit_form_css_classes_exist():
    # Phase 5E.1 regression lock: the additional folder edit form CSS
    # classes (input, recursive, recursive-label) must exist in
    # styles.css so the inline edit form has stable visual styles. The
    # existing Phase 5E test only checks a subset of these.
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
    # Phase 5E.1 regression lock: the folder edit form CSS classes must
    # not be referenced by the Overview / Timeline / Statistics static
    # HTML sections. This complements the existing Phase 5E CSS scoping
    # test with the edit-form-specific classes.
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
    # Phase 5E.1 regression lock: core.js (which declares the folder
    # state variables) must not use forbidden storage / network / module
    # features. The existing Phase 5E test only checks rules.js.
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
    # Phase 5E.1 regression lock: init.js (which binds the folder create
    # submit button) must not use forbidden storage / network / module
    # features.
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
    # Phase 5E.1 regression lock: rules.js must not reference any
    # external URL (http/https) or CDN or Google Fonts.
    source = read_rules_module_js()
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"\bcdn\b", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_folder_js_no_es_module_syntax():
    # Phase 5E.1 regression lock: rules.js must not use ES module syntax
    # (import / export). The frontend uses classic scripts only.
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
    # Phase 5E.1 regression lock: the packaging spec must include core.js
    # and init.js (not just rules.js) so the folder state variables and
    # event bindings ship in the packaged build.
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    for js_file in ("core.js", "init.js", "rules.js"):
        assert ("'" + js_file + "'") in source or ('"' + js_file + '"') in source, (
            "WorkTrace.spec must include: " + js_file
        )


def test_project_rules_folder_state_variables_declared_once():
    # Phase 5E.1 regression lock: each folder state variable must be
    # declared exactly once in core.js so there is no accidental
    # duplicate declaration that could shadow or reset the state.
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
    # Phase 5E.1 regression lock: the folder create status helper must
    # use ``textContent`` (HTML-safe), not ``innerHTML``. The existing
    # test checks ``showFolderCreateStatus``; this is a consolidation
    # lock that also verifies no ``innerHTML`` appears anywhere in the
    # folder create / edit / delete handlers.
    source = read_rules_module_js()
    create_body = func_body(source, "handleFolderCreateSubmit")
    edit_save_body = func_body(source, "handleFolderEditSave")
    delete_body = func_body(source, "handleFolderDelete")
    for body in (create_body, edit_save_body, delete_body):
        assert ".innerHTML" not in body


def test_project_rules_folder_edit_save_failure_preserves_rendered_list():
    # Phase 5E.1 regression lock: the folder edit save failure path must
    # not clear the already-rendered Project Rules list. This mirrors the
    # existing create / delete failure-list-preservation locks.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "list.innerHTML" not in body


def test_project_rules_folder_edit_save_clears_editing_state_on_success():
    # Phase 5E.1 regression lock: the edit save success path must clear
    # the editing state so the inline edit form closes after a successful
    # save.
    source = read_rules_module_js()
    body = func_body(source, "handleFolderEditSave")
    assert "App.setFolderEditing(null)" in body


def test_project_rules_folder_event_delegation_bound_once():
    # Phase 5E.1 regression lock: ``bindProjectRuleFolderEvents`` must
    # use the same ``data-*-bound`` idempotency pattern as the toggle /
    # delete binders so repeated renders do not attach duplicate click
    # handlers to ``#rules-list``.
    source = read_rules_module_js()
    body = func_body(source, "bindProjectRuleFolderEvents")
    assert "data-rules-folder-bound" in body
    assert 'getAttribute("data-rules-folder-bound")' in body
    assert 'setAttribute("data-rules-folder-bound", "1")' in body


# --- Phase 5F: keyword rule edit foundation + in-phase hardening ---------
#
# These locks cover the new keyword rule edit capability. They verify the
# edit button appears only on keyword rows, the inline edit form uses the
# stable anchors / attributes, the save / cancel handlers obey the
# Phase 5F contract (trim, empty reject, success refresh, failure preserve,
# no bridge on cancel, no .message reads, etc.), and the new CSS classes
# are scoped to the Project Rules page.


def test_project_rules_keyword_edit_state_variables_declared():
    # Phase 5F regression lock: the keyword edit saving state and the
    # keyword edit updating (in-flight save) state must each be a separate
    # state variable from the existing write-path states (toggle saving,
    # keyword create, keyword delete, folder create/edit/delete) so the
    # seven write paths can never pollute each other.
    source = read_js("core.js")
    assert "App.rulesEditingKeywordKey = null" in source
    assert "App.rulesUpdatingKeywordKey = null" in source
    # Earlier state variables must still exist alongside the new ones.
    assert "App.rulesSavingRuleKey = null" in source
    assert "App.rulesCreatingKeyword = false" in source
    assert "App.rulesDeletingRuleKey = null" in source
    assert "App.rulesCreatingFolder = false" in source
    assert "App.rulesEditingFolderKey = null" in source
    assert "App.rulesDeletingFolderKey = null" in source


def test_project_rules_keyword_edit_state_variables_declared_once():
    # Phase 5F regression lock: each keyword edit state variable must be
    # declared exactly once in core.js so there is no accidental duplicate
    # declaration that could shadow or reset the state.
    source = read_js("core.js")
    for var_decl in (
        "App.rulesEditingKeywordKey = null",
        "App.rulesUpdatingKeywordKey = null",
    ):
        assert source.count(var_decl) == 1, (
            var_decl + " must be declared exactly once in core.js"
        )


def test_project_rules_keyword_edit_js_calls_bridge_method():
    # Phase 5F regression lock: the JS must call the
    # ``update_project_keyword_rule`` bridge method.
    source = read_rules_module_js()
    assert 'callBridge("update_project_keyword_rule"' in source


def test_project_rules_keyword_edit_buttons_only_on_keyword_rows():
    # Phase 5F regression lock: the edit button must be rendered only on
    # keyword rule rows, never on folder rule rows or project cards. The
    # renderProjectRuleRow function must gate the edit button on
    # ``kind === "keyword"``.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'kind === "keyword"' in row_body
    assert "rules-keyword-edit-button" in row_body
    # The project card template must not contain an edit button.
    project_body = func_body(source, "renderProjectRuleProject")
    assert "rules-keyword-edit-button" not in project_body


def test_project_rules_keyword_edit_button_does_not_appear_on_folder_rows():
    # Phase 5F regression lock: the keyword edit button is rendered
    # conditionally inside the ``if (kind === "keyword" && ruleId)`` block.
    # Folder rows (kind === "folder") never enter that block, so they never
    # get a keyword edit button.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    keyword_guard_pos = row_body.find('kind === "keyword"')
    edit_html_assign_pos = row_body.find("keywordEditButton = '", keyword_guard_pos)
    assert keyword_guard_pos != -1 and edit_html_assign_pos != -1
    assert keyword_guard_pos < edit_html_assign_pos


def test_project_rules_keyword_edit_button_uses_stable_class_and_attributes():
    # Phase 5F regression lock: the keyword edit button must use the stable
    # class / data attributes specified in the Phase 5F contract.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'class="rules-keyword-edit-button"' in row_body
    assert 'data-rule-kind="keyword"' in row_body
    assert 'data-rule-id="' in row_body


def test_project_rules_keyword_edit_button_disabled_when_any_write_in_flight():
    # Phase 5F regression lock: the keyword edit button must be disabled
    # when any rule write is in flight on this row (toggle saving, keyword
    # delete, keyword edit, or keyword save). This keeps the four keyword
    # write paths from concurrently polluting the same row.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "App.rulesSavingRuleKey" in row_body
    assert "App.rulesDeletingRuleKey" in row_body
    assert "App.rulesEditingKeywordKey" in row_body
    assert "App.rulesUpdatingKeywordKey" in row_body


def test_project_rules_keyword_edit_start_sets_editing_key():
    # Phase 5F regression lock: the edit-start handler must set the editing
    # key to ``"keyword:<id>"`` so the inline edit form renders for the
    # correct row only.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditStart")
    assert "App.setKeywordEditing" in body
    assert '"keyword:"' in body or "'keyword:'" in body


def test_project_rules_keyword_edit_start_has_in_flight_guard():
    # Phase 5F regression lock: the edit-start handler must early-return
    # when a keyword edit / save / delete is already in flight, before any
    # state mutation.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditStart")
    assert "if (App.rulesEditingKeywordKey) return" in body
    assert "if (App.rulesUpdatingKeywordKey) return" in body
    assert "if (App.rulesDeletingRuleKey) return" in body


def test_project_rules_keyword_edit_start_validates_rule_kind_before_state():
    # Phase 5F regression lock: the dataset ``data-rule-kind`` must be
    # validated against ``keyword`` before the editing state is set so a
    # malformed dataset cannot trigger an arbitrary edit.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditStart")
    assert 'kind !== "keyword"' in body
    type_check_pos = body.find('kind !== "keyword"')
    set_editing_pos = body.find("App.setKeywordEditing(")
    assert type_check_pos < set_editing_pos


def test_project_rules_keyword_edit_start_validates_rule_id_before_state():
    # Phase 5F regression lock: the JS must parse and validate the rule id
    # before setting the editing state. Malformed dataset must not enter
    # edit mode.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditStart")
    assert 'parseInt(rawId, 10)' in body
    assert "ruleId <= 0" in body
    guard_pos = body.find("ruleId <= 0")
    set_editing_pos = body.find("App.setKeywordEditing(")
    assert guard_pos < set_editing_pos


def test_project_rules_keyword_edit_save_calls_bridge_method():
    # Phase 5F regression lock: the save handler must call the
    # ``update_project_keyword_rule`` bridge method.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert 'callBridge("update_project_keyword_rule"' in body


def test_project_rules_keyword_edit_save_validates_rule_kind_before_bridge():
    # Phase 5F regression lock: the dataset ``data-rule-kind`` must be
    # validated against ``keyword`` before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert 'kind !== "keyword"' in body
    type_check_pos = body.find('kind !== "keyword"')
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert type_check_pos < bridge_pos


def test_project_rules_keyword_edit_save_validates_rule_id_before_bridge():
    # Phase 5F regression lock: the JS must parse and validate the rule id
    # before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert 'parseInt(rawId, 10)' in body
    assert "ruleId <= 0" in body
    guard_pos = body.find("ruleId <= 0")
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert guard_pos < bridge_pos


def test_project_rules_keyword_edit_save_trims_input_before_bridge():
    # Phase 5F regression lock: the JS must trim the input value before
    # validation and before the bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert ".trim()" in body
    trim_pos = body.find(".trim()")
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert trim_pos != -1 and bridge_pos != -1
    assert trim_pos < bridge_pos


def test_project_rules_keyword_edit_save_rejects_empty_input_client_side():
    # Phase 5F regression lock: an empty (after trim) keyword must be
    # rejected before any bridge call. The handler must ``return``
    # immediately after showing the status, without calling
    # ``App.callBridge``.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "!keyword" in body
    empty_guard_pos = body.find("!keyword")
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert empty_guard_pos < bridge_pos
    return_pos = body.find("return;", empty_guard_pos)
    assert return_pos != -1 and return_pos < bridge_pos


def test_project_rules_keyword_edit_save_has_editing_guard():
    # Phase 5F regression lock: the save handler must early-return when no
    # keyword edit is in flight, before any bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "if (!App.rulesEditingKeywordKey) return" in body
    guard_pos = body.find("if (!App.rulesEditingKeywordKey) return")
    bridge_pos = body.find('callBridge("update_project_keyword_rule"')
    assert guard_pos < bridge_pos


def test_project_rules_keyword_edit_save_has_saving_button_label():
    # Phase 5F regression lock: the saving button text must remain the
    # stable ``正在保存…`` label.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "正在保存…" in row_body
    set_saving_body = func_body(source, "setKeywordSaving")
    assert "正在保存…" in set_saving_body


def test_project_rules_keyword_edit_save_success_refreshes_project_rules():
    # Phase 5F regression lock: the success path must call
    # ``loadProjectRules()`` to refresh the Project Rules list.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "App.loadProjectRules()" in body


def test_project_rules_keyword_edit_save_success_clears_editing_state():
    # Phase 5F regression lock: the success path must clear the editing
    # state by calling ``setKeywordEditing(null)`` so the inline edit form
    # closes after a successful save.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "App.setKeywordEditing(null)" in body


def test_project_rules_keyword_edit_save_success_shows_stable_message():
    # Phase 5F regression lock: the success path must show the stable
    # ``关键词规则已保存`` message after refresh.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    refresh_pos = body.find("App.loadProjectRules()")
    success_pos = body.find("关键词规则已保存")
    assert refresh_pos != -1 and success_pos != -1
    assert refresh_pos < success_pos


def test_project_rules_keyword_edit_save_failure_preserves_editing_state():
    # Phase 5F regression lock: the failure path (ok=false) must not clear
    # the editing state. The handler may only show a status message, never
    # call ``setKeywordEditing(null)`` inside the failure branch. The
    # cleanup ``setKeywordSaving(null)`` only clears the saving state, not
    # the editing state, so the user can edit and retry. The success branch
    # (after the failure guard returns) does call ``setKeywordEditing(null)``
    # — that is expected and correct.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    failure_guard = body.find("result && result.ok === false")
    assert failure_guard != -1
    # The failure branch is the block inside the ``if (result && result.ok
    # === false) { ... }``. Extract just that block (up to the first
    # ``return;`` after the guard) and verify it does not clear the editing
    # state.
    failure_return = body.find("return;", failure_guard)
    assert failure_return != -1
    failure_block = body[failure_guard:failure_return]
    assert "App.setKeywordEditing(null)" not in failure_block
    assert "App.setKeywordEditing(" not in failure_block


def test_project_rules_keyword_edit_save_failure_preserves_rendered_list():
    # Phase 5F regression lock: the failure path must not clear the
    # already-rendered Project Rules list. The handler may only show a
    # status message on failure, never ``list.innerHTML = ""`` or
    # ``showProjectRules`` with an empty payload.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    assert "list.innerHTML" not in body
    assert 'showProjectRules({ projects: [] })' not in body
    assert 'showProjectRules([])' not in body
    assert "保存关键词规则失败" in body


def test_project_rules_keyword_edit_save_catch_never_reads_raw_exception():
    # Phase 5F regression lock: the catch path must never read
    # ``.message`` from the error.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditSave")
    for forbidden in ("err.message", "error.message", "reason.message"):
        assert forbidden not in body
    assert ".catch(function ()" in body


def test_project_rules_keyword_edit_save_saving_state_clears_on_all_paths():
    # Phase 5F regression lock: the saving state must clear on success,
    # on failure (ok=false), and on rejected promise. The handler achieves
    # this by chaining ``App.setKeywordSaving(null)`` in the final
    # ``.then`` that runs after ``.catch`` (which always resolves).
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
    # Phase 5F regression lock: the cancel handler must not call any bridge
    # method. It only clears the editing state and re-renders.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditCancel")
    assert "callBridge(" not in body


def test_project_rules_keyword_edit_cancel_clears_editing_state():
    # Phase 5F regression lock: the cancel handler must clear the editing
    # state by calling ``setKeywordEditing(null)``.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditCancel")
    assert "App.setKeywordEditing(null)" in body


def test_project_rules_keyword_edit_cancel_has_early_return_guard():
    # Phase 5F regression lock: the cancel handler must early-return when
    # no keyword edit is in flight.
    source = read_rules_module_js()
    body = func_body(source, "handleKeywordEditCancel")
    assert "if (!App.rulesEditingKeywordKey) return" in body


def test_project_rules_keyword_edit_set_keyword_editing_rerenders_from_cache():
    # Phase 5F regression lock: ``setKeywordEditing`` must re-render the
    # list from cached data (via ``rerenderProjectRulesList``) so the edit
    # form appears / disappears immediately without a round-trip through
    # ``loadProjectRules``.
    source = read_rules_module_js()
    body = func_body(source, "setKeywordEditing")
    assert "App.rerenderProjectRulesList()" in body


def test_project_rules_keyword_edit_set_keyword_saving_disables_save_and_cancel():
    # Phase 5F regression lock: ``setKeywordSaving`` must disable both the
    # save and cancel buttons while a save is in flight so the user cannot
    # double-submit or cancel mid-save.
    source = read_rules_module_js()
    body = func_body(source, "setKeywordSaving")
    assert "rules-keyword-edit-save" in body
    assert "rules-keyword-edit-cancel" in body
    assert "btn.disabled" in body


def test_project_rules_keyword_edit_inline_form_renders_in_place_of_row():
    # Phase 5F regression lock: when a keyword row is being edited, the
    # renderProjectRuleRow function must render the inline edit form
    # (with input + save / cancel buttons) in place of the normal row body.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "is-keyword-editing" in row_body
    assert "rules-keyword-edit-form" in row_body
    assert "rules-keyword-edit-input" in row_body
    assert "rules-keyword-edit-save" in row_body
    assert "rules-keyword-edit-cancel" in row_body


def test_project_rules_keyword_edit_form_has_maxlength_on_input():
    # Phase 5F regression lock: the inline edit form input must have a
    # ``maxlength="200"`` attribute so the user cannot enter an over-long
    # keyword. This matches the keyword create input maxlength.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'maxlength="200"' in row_body


def test_project_rules_keyword_edit_form_uses_stable_class_and_attributes():
    # Phase 5F regression lock: the inline edit form save / cancel buttons
    # must use the stable class / data attributes.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert 'class="rules-keyword-edit-save"' in row_body
    assert 'class="rules-keyword-edit-cancel"' in row_body
    assert 'data-rule-kind="keyword"' in row_body


def test_project_rules_keyword_edit_events_use_event_delegation_on_rules_list():
    # Phase 5F regression lock: the keyword edit / edit-save / edit-cancel
    # events must be delegated via a single click handler on
    # ``#rules-list``, not via per-button listeners in init.js.
    source = read_rules_module_js()
    bind_body = func_body(source, "bindProjectRuleKeywordEditEvents")
    assert 'getElementById("rules-list")' in bind_body
    assert "addEventListener" in bind_body
    assert "handleProjectRuleKeywordEditEvent" in bind_body


def test_project_rules_keyword_edit_event_handler_routes_by_button_class():
    # Phase 5F regression lock: the delegated keyword edit event handler
    # must route to the correct sub-handler based on the button class.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleKeywordEditEvent")
    assert "rules-keyword-edit-button" in body
    assert "rules-keyword-edit-save" in body
    assert "rules-keyword-edit-cancel" in body
    assert "handleKeywordEditStart" in body
    assert "handleKeywordEditSave" in body
    assert "handleKeywordEditCancel" in body


def test_project_rules_keyword_edit_event_delegation_bound_once():
    # Phase 5F regression lock: ``bindProjectRuleKeywordEditEvents`` must
    # use the same ``data-*-bound`` idempotency pattern as the toggle /
    # delete / folder binders so repeated renders do not attach duplicate
    # click handlers to ``#rules-list``.
    source = read_rules_module_js()
    body = func_body(source, "bindProjectRuleKeywordEditEvents")
    assert "data-rules-keyword-edit-bound" in body
    assert 'getAttribute("data-rules-keyword-edit-bound")' in body
    assert 'setAttribute("data-rules-keyword-edit-bound", "1")' in body


def test_project_rules_keyword_edit_show_project_rules_binds_events():
    # Phase 5F regression lock: ``showProjectRules`` must call
    # ``bindProjectRuleKeywordEditEvents`` so the keyword edit delegation
    # is set up after every render.
    source = read_rules_module_js()
    body = func_body(source, "showProjectRules")
    assert "bindProjectRuleKeywordEditEvents" in body


def test_project_rules_keyword_edit_rerender_binds_events():
    # Phase 5F regression lock: ``rerenderProjectRulesList`` must call
    # ``bindProjectRuleKeywordEditEvents`` so the keyword edit delegation
    # is set up after every re-render from cached data.
    source = read_rules_module_js()
    body = func_body(source, "rerenderProjectRulesList")
    assert "bindProjectRuleKeywordEditEvents" in body


def test_project_rules_keyword_edit_state_isolation_from_other_write_paths():
    # Phase 5F regression lock: the keyword edit save handler must not read
    # the toggle saving state, keyword create state, keyword delete state,
    # or folder create/edit/delete states directly. The seven write paths
    # are coordinated only through per-row render-time disabled attributes
    # — never by cross-reading the other handlers' state inside
    # ``handleKeywordEditSave``. The handler accesses its own state via the
    # ``setKeywordSaving`` helper (which internally sets
    # ``rulesUpdatingKeywordKey``) and reads ``rulesEditingKeywordKey`` for
    # the in-flight guard.
    source = read_rules_module_js()
    edit_body = func_body(source, "handleKeywordEditSave")
    assert "App.rulesSavingRuleKey" not in edit_body
    assert "App.rulesCreatingKeyword" not in edit_body
    assert "App.rulesDeletingRuleKey" not in edit_body
    assert "App.rulesCreatingFolder" not in edit_body
    assert "App.rulesEditingFolderKey" not in edit_body
    assert "App.rulesDeletingFolderKey" not in edit_body
    # The edit state itself must be present (editing key guard + saving
    # helper which internally manages the updating key).
    assert "App.rulesEditingKeywordKey" in edit_body
    assert "App.setKeywordSaving" in edit_body


def test_project_rules_keyword_edit_start_state_isolation_from_other_write_paths():
    # Phase 5F regression lock: the keyword edit start handler must not
    # read the toggle saving state, keyword create state, or folder
    # create/edit/delete states directly.
    source = read_rules_module_js()
    start_body = func_body(source, "handleKeywordEditStart")
    assert "App.rulesSavingRuleKey" not in start_body
    assert "App.rulesCreatingKeyword" not in start_body
    assert "App.rulesCreatingFolder" not in start_body
    assert "App.rulesEditingFolderKey" not in start_body
    assert "App.rulesDeletingFolderKey" not in start_body


def test_project_rules_keyword_edit_cancel_state_isolation_from_other_write_paths():
    # Phase 5F regression lock: the keyword edit cancel handler must not
    # read the toggle saving state, keyword create state, keyword delete
    # state, or folder create/edit/delete states directly.
    source = read_rules_module_js()
    cancel_body = func_body(source, "handleKeywordEditCancel")
    assert "App.rulesSavingRuleKey" not in cancel_body
    assert "App.rulesCreatingKeyword" not in cancel_body
    assert "App.rulesDeletingRuleKey" not in cancel_body
    assert "App.rulesCreatingFolder" not in cancel_body
    assert "App.rulesEditingFolderKey" not in cancel_body
    assert "App.rulesDeletingFolderKey" not in cancel_body


def test_project_rules_keyword_edit_set_keyword_editing_state_isolation():
    # Phase 5F regression lock: ``setKeywordEditing`` must only touch the
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
    # Phase 5F regression lock: ``setKeywordSaving`` must only touch the
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
    # Phase 5F regression lock: the keyword edit save handler must not
    # call any other Project Rules write bridge (create / delete / toggle /
    # folder CRUD).
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
    # Phase 5F regression lock: the keyword edit handlers must not call
    # preview / backfill bridges.
    source = read_rules_module_js()
    for forbidden in (
        'callBridge("preview_folder_rule_conflicts"',
        'callBridge("backfill_folder_rule"',
    ):
        assert forbidden not in source


def test_project_rules_keyword_edit_js_does_not_call_project_write():
    # Phase 5F regression lock: the keyword edit handlers must not call
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
    # Phase 5F regression lock: the keyword edit handlers must not use
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
    # Phase 5F regression lock: the keyword edit JS must not introduce any
    # of the forbidden camelCase handler tokens.
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source


def test_project_rules_keyword_edit_no_app_js_reintroduced():
    # Phase 5F regression lock: the frontend must not reintroduce app.js.
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_keyword_edit_no_static_edit_button_in_html():
    # Phase 5F regression lock: the static ``page-rules`` section in
    # ``index.html`` must not contain a keyword edit button. The edit
    # button is rendered dynamically by JS only on keyword rule rows.
    section = _rules_section()
    assert "rules-keyword-edit-button" not in section
    assert "rules-keyword-edit-form" not in section
    assert "rules-keyword-edit-save" not in section
    assert "rules-keyword-edit-cancel" not in section


def test_project_rules_keyword_edit_no_duplicate_static_dom_ids():
    # Phase 5F regression lock: the static ``page-rules`` section in
    # ``index.html`` must not declare the same DOM id twice. The Phase 5F
    # addition does not introduce any new static DOM (the edit form is
    # rendered dynamically by JS).
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
    # Phase 5F regression lock: the Project Rules page must not contain
    # Excel / PDF / timesheet / open-folder / auto-submit controls.
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
    # Phase 5F regression lock: the Project Rules page must not contain
    # project create / edit / delete / archive / enable / disable controls.
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
    # Phase 5F regression lock: the keyword edit CSS classes must exist in
    # styles.css so the dynamically-rendered edit button and inline edit
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
    # The CSS must not depend on external resources.
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"cdn", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_keyword_edit_css_class_scoped_to_rules_page():
    # Phase 5F regression lock: the keyword edit CSS classes must be
    # namespaced with the ``rules-`` prefix and must not be referenced by
    # the Overview / Timeline / Statistics static HTML sections, so the
    # Project Rules edit button / form style cannot leak into (or be
    # re-styled by) the other pages.
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
    # Phase 5F regression lock: rules.js must not reference any external
    # URL (http/https) or CDN or Google Fonts.
    source = read_rules_module_js()
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"\bcdn\b", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)


def test_project_rules_keyword_edit_js_no_es_module_syntax():
    # Phase 5F regression lock: rules.js must not use ES module syntax
    # (import / export). The frontend uses classic scripts only.
    source = read_rules_module_js()
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_keyword_edit_core_js_no_es_module_syntax():
    # Phase 5F regression lock: core.js must not use ES module syntax.
    source = read_js("core.js")
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_keyword_edit_init_js_no_es_module_syntax():
    # Phase 5F regression lock: init.js must not use ES module syntax.
    source = read_js("init.js")
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_keyword_edit_init_does_not_bind_edit_event():
    # Phase 5F regression lock: the init module must not bind any keyword
    # edit event directly. The edit button uses event delegation on the
    # rules-list container, set up inside ``rules.js`` (Phase 5F), not in
    # init.js.
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
    # Phase 5F regression lock: the packaging spec must still include
    # rules.js so the keyword edit handlers ship in the packaged build.
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'rules.js'" in source or '"rules.js"' in source
    assert "'rules_project_actions.js'" in source or '"rules_project_actions.js"' in source
    assert "'worktrace/webview_ui/js'" in source or '"worktrace/webview_ui/js"' in source


def test_project_rules_keyword_edit_stale_guard_preserved():
    # Phase 5F regression lock: the existing ``rulesRequestToken`` stale
    # guard in ``loadProjectRules`` must remain intact. The keyword edit
    # success path calls ``loadProjectRules()`` which inherits this
    # protection.
    source = read_rules_module_js()
    load_body = func_body(source, "loadProjectRules")
    assert "var token = ++App.rulesRequestToken" in load_body
    assert load_body.count("token !== App.rulesRequestToken") >= 2


def test_project_rules_keyword_edit_boundary_copy_present():
    # Phase 5F regression lock: the boundary copy must mention keyword rule
    # edit as a supported capability and still reference the remaining
    # future capabilities.
    section = _rules_section()
    assert "启用/停用" in section
    assert "新增关键词规则" in section
    assert "编辑已有关键词规则" in section
    assert "删除已有关键词规则" in section
    for term in ("编辑", "删除", "预览单条规则影响", "安全应用"):
        assert term in section


def test_project_rules_keyword_edit_js_uses_escape_helper_for_dynamic_text():
    # Phase 5F regression lock: dynamic text rendering in the edit button
    # and inline edit form must use the escape helper. The rule id is
    # rendered via ``count()`` which calls ``App.escapeHtml``.
    source = read_rules_module_js()
    count_body = func_body(source, "count")
    assert "App.escapeHtml" in count_body
    row_body = func_body(source, "renderProjectRuleRow")
    assert "count(ruleId)" in row_body


# --- Phase 5G: Project lifecycle foundation + in-phase hardening ---------
#
# These locks cover the new project lifecycle capability (create / edit /
# enable-disable / archive existing user projects). They verify the project
# create form DOM anchors, the lifecycle buttons appear only on user project
# cards, the inline edit form uses the stable anchors / attributes, the
# save / cancel / toggle / archive handlers obey the Phase 5G contract
# (trim, empty reject, success refresh, failure preserve, no bridge on
# cancel, confirm archive, no .message reads, etc.), the project lifecycle
# state variables are independent, CSS classes are scoped to the Project
# Rules page, and init.js binds the project create submit but not the
# lifecycle handlers.


def test_project_rules_project_create_form_anchors_exist():
    # Phase 5G regression lock: the Project Rules page must contain the
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
    # Phase 5G regression lock: the five project lifecycle state variables
    # must each be declared in core.js, separate from all rule write states
    # (toggle saving, keyword create/delete/edit, folder create/edit/delete)
    # so the project lifecycle write paths can never pollute rule write
    # paths and vice versa.
    source = read_js("core.js")
    assert "App.rulesCreatingProject = false" in source
    assert "App.rulesEditingProjectId = null" in source
    assert "App.rulesUpdatingProjectId = null" in source
    assert "App.rulesTogglingProjectId = null" in source
    assert "App.rulesArchivingProjectId = null" in source


def test_project_rules_project_lifecycle_state_variables_declared_once():
    # Phase 5G regression lock: each project lifecycle state variable must
    # be declared exactly once in core.js so there is no accidental
    # duplicate declaration that could shadow or reset the state.
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
    # Phase 5G regression lock: the JS must call the four ``*_for_rules``
    # bridge methods.
    source = read_rules_module_js()
    assert 'callBridge("create_project_for_rules"' in source
    assert 'callBridge("update_project_for_rules"' in source
    assert 'callBridge("set_project_enabled_for_rules"' in source
    assert 'callBridge("archive_project_for_rules"' in source


def test_project_rules_project_lifecycle_js_does_not_call_bare_project_write():
    # Phase 5G regression lock: the JS must NOT call the bare (non-_for_rules)
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
    # Phase 5G regression lock: the lifecycle buttons (edit / toggle /
    # archive) must only be rendered when ``editable`` is true. System /
    # special projects (``未归类`` / ``排除规则``) never get these buttons.
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
    # Phase 5G regression lock: the lifecycle buttons must use the stable
    # CSS classes and ``data-project-id`` attributes.
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
    # Phase 5G regression lock: the lifecycle buttons must be disabled when
    # any project lifecycle write is in flight (create / edit / toggle /
    # archive). This keeps the four project lifecycle write paths from
    # running concurrently.
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    assert "rulesCreatingProject" in project_body
    assert "rulesEditingProjectId" in project_body
    assert "rulesUpdatingProjectId" in project_body
    assert "rulesTogglingProjectId" in project_body
    assert "rulesArchivingProjectId" in project_body
    assert "projectWriteInProgress" in project_body


def test_project_rules_project_lifecycle_inline_edit_form_anchors():
    # Phase 5G regression lock: the inline project edit form must use the
    # stable CSS classes for the name input, description input, save button,
    # and cancel button.
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
    # The edit form must have maxlength on both inputs.
    assert 'maxlength="100"' in project_body
    assert 'maxlength="500"' in project_body


def test_project_rules_project_create_js_validates_name_before_bridge():
    # Phase 5G regression lock: the project create handler must validate
    # the name is non-empty (after trim) before calling the bridge.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectCreateSubmit")
    trim_pos = body.find(".trim()")
    empty_check_pos = body.find("请输入项目名称")
    bridge_pos = body.find('callBridge("create_project_for_rules"')
    assert trim_pos != -1 and empty_check_pos != -1 and bridge_pos != -1
    assert trim_pos < empty_check_pos < bridge_pos


def test_project_rules_project_create_js_has_creating_guard():
    # Phase 5G regression lock: only one project create may be in flight at
    # a time. The handler must early-return when ``rulesCreatingProject`` is
    # set, before any bridge call.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectCreateSubmit")
    guard_pos = body.find("App.rulesCreatingProject")
    bridge_pos = body.find('callBridge("create_project_for_rules"')
    assert guard_pos != -1 and bridge_pos != -1
    assert guard_pos < bridge_pos


def test_project_rules_project_create_js_success_clears_inputs_and_refreshes():
    # Phase 5G regression lock: on success the handler must clear both
    # inputs and refresh the Project Rules list.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectCreateSubmit")
    assert 'input.value = ""' in body
    assert "descInput.value" in body
    assert "App.loadProjectRules()" in body


def test_project_rules_project_create_js_failure_preserves_inputs():
    # Phase 5G regression lock: on failure the handler must NOT clear the
    # inputs so the user can edit and retry. The success path (which clears
    # inputs) must be gated on ``result.ok !== false``.
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
    # Phase 5G regression lock: the project edit save handler must validate
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
    # Phase 5G regression lock: the cancel handler must NOT call any bridge
    # method. It only clears the editing state and re-renders.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectEditCancel")
    assert "callBridge" not in body
    assert "App.setProjectEditing(null)" in body


def test_project_rules_project_toggle_js_has_confirmation():
    # Phase 5G regression lock: the toggle handler must show a confirmation
    # dialog before disabling a project.
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
    # Phase 5G regression lock: the archive handler must show a confirmation
    # dialog before archiving.
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
    # Phase 5G regression lock: the event delegation on #rules-list must
    # use the ``data-rules-project-lifecycle-bound`` guard so it is only
    # bound once per page lifecycle.
    source = read_rules_module_js()
    body = func_body(source, "bindProjectLifecycleEvents")
    assert "data-rules-project-lifecycle-bound" in body
    assert "handleProjectLifecycleEvent" in body


def test_project_rules_project_lifecycle_no_storage_or_network():
    # Phase 5G regression lock: the project lifecycle handlers must not use
    # browser storage, fetch, XMLHttpRequest, or any network API.
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
    # Phase 5G regression lock: rules.js must not use ES module syntax.
    source = read_rules_module_js()
    assert not re.search(r"^\s*import\s+", source, re.MULTILINE)
    assert not re.search(r"^\s*export\s+", source, re.MULTILINE)


def test_project_rules_project_lifecycle_init_binds_create_submit_only():
    # Phase 5G regression lock: init.js must bind the project create submit
    # button (following the keyword / folder create submit pattern) but
    # must NOT bind any project lifecycle handler directly (edit / toggle /
    # archive use event delegation set up inside rules.js).
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
    # Phase 5G regression lock: no new packaging resource paths are needed
    # because project lifecycle reuses the existing rules.js / core.js /
    # index.html / styles.css resources. The spec must still include
    # rules.js and the js directory.
    source = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'rules.js'" in source or '"rules.js"' in source
    assert "'rules_project_actions.js'" in source or '"rules_project_actions.js"' in source
    assert "'worktrace/webview_ui/js'" in source or '"worktrace/webview_ui/js"' in source


def test_project_rules_project_lifecycle_no_app_js_reintroduced():
    # Phase 5G regression lock: app.js must not be reintroduced in
    # index.html. The project lifecycle code lives in rules.js and
    # rules_project_actions.js only (Phase M3 split).
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_project_lifecycle_no_forbidden_handler_tokens():
    # Phase 5G regression lock: Project Rules JS must not contain any of the
    # forbidden camelCase handler tokens (these would indicate accidental
    # exposure of bare project management APIs). After the Phase M3 split
    # this checks both rules.js and rules_project_actions.js.
    source = read_rules_module_js()
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source, (
            "Project Rules JS must not contain forbidden handler token: " + token
        )


# --- Phase MC2: Project Rules frontend modularization static contract ----
#
# Phase MC2 split the Project Rules surface from rules.js +
# rules_project_actions.js into six classic IIFE modules:
#   rules.js                 (core load / refresh / wiring)
#   rules_render.js          (renderProjectRuleProject / renderProjectRuleRow)
#   rules_rule_actions.js    (rule toggle)
#   rules_keyword_actions.js (keyword create / edit / delete)
#   rules_folder_actions.js  (folder create / edit / delete)
#   rules_project_actions.js (project lifecycle)
#
# These tests lock the split so a future change cannot silently drop a
# module from index.html, WorkTrace.spec, or the ALL_JS_FILES list.


def test_project_rules_mc2_split_modules_exist_on_disk():
    # Phase MC2 regression lock: each new split module must exist on disk.
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
        assert os.path.isfile(path), f"missing Phase MC2 split module: {name}"


def test_project_rules_mc2_split_modules_in_all_js_files():
    # Phase MC2 regression lock: ALL_JS_FILES (the test-side single source
    # of truth) must include every new split module in the correct order.
    expected_order = [
        "rules.js",
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
        "rules_project_actions.js",
    ]
    # Each module must be present.
    for name in expected_order:
        assert name in ALL_JS_FILES, (
            f"ALL_JS_FILES must include Phase MC2 split module: {name}"
        )
    # The rules modules must appear consecutively and in the correct order.
    indices = [ALL_JS_FILES.index(name) for name in expected_order]
    assert indices == sorted(indices), (
        "Phase MC2 split modules must appear in ALL_JS_FILES in order: "
        + ", ".join(expected_order)
    )


def test_project_rules_mc2_split_modules_in_index_html():
    # Phase MC2 regression lock: index.html must load every split module
    # in the same order as ALL_JS_FILES.
    html = read_resource("index.html")
    import re

    scripts = re.findall(r'<script\s+src="js/([^"]+)"\s*>\s*</script>', html)
    assert scripts == ALL_JS_FILES, (
        "index.html script order must match ALL_JS_FILES exactly"
    )
    # Specifically check the four new modules are present.
    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        assert 'src="js/' + name + '"' in html, (
            f"index.html must load Phase MC2 split module: {name}"
        )


def test_project_rules_mc2_split_modules_in_spec():
    # Phase MC2 regression lock: WorkTrace.spec must bundle every split
    # module so PyInstaller packages them into the release build.
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        assert name in spec, (
            f"WorkTrace.spec must bundle Phase MC2 split module: {name}"
        )


def test_project_rules_mc2_split_modules_are_iife_classic_scripts():
    # Phase MC2 regression lock: each split module must be a classic IIFE
    # script (no ES module syntax, no import/export, no bundler). This
    # matches the existing rules.js / rules_project_actions.js pattern.
    for name in (
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ):
        source = read_js(name).strip()
        # A short leading comment header is permitted before the IIFE
        # opening (same rule as test_phase_r2_each_js_file_is_iife).
        assert "(function () {" in source[:400], (
            f"{name} must open with an IIFE near the top"
        )
        assert source.rstrip().endswith("})();"), (
            f"{name} must end with IIFE close"
        )
        # Strict mode.
        assert '"use strict"' in source, f"{name} must use strict mode"
        # App namespace.
        assert "var App = window.WorkTraceApp" in source, (
            f"{name} must attach to window.WorkTraceApp namespace"
        )
        # No ES module syntax.
        for forbidden in ("export ", "import ", "export default", "import("):
            assert forbidden not in source, (
                f"{name} must not use ES module syntax: {forbidden}"
            )


def test_project_rules_mc2_render_helpers_attach_to_app():
    # Phase MC2 regression lock: renderProjectRuleProject and
    # renderProjectRuleRow must remain attached to App.* (public surface
    # preserved) even though they moved to rules_render.js.
    source = read_js("rules_render.js")
    assert "App.renderProjectRuleProject = renderProjectRuleProject" in source
    assert "App.renderProjectRuleRow = renderProjectRuleRow" in source


def test_project_rules_mc2_rule_actions_attach_to_app():
    # Phase MC2 regression lock: rule toggle handlers must remain attached
    # to App.* even though they moved to rules_rule_actions.js.
    source = read_js("rules_rule_actions.js")
    assert "App.bindProjectRuleToggles = bindProjectRuleToggles" in source
    assert "App.handleProjectRuleToggle = handleProjectRuleToggle" in source
    assert "App.setProjectRuleSaving = setProjectRuleSaving" in source


def test_project_rules_mc2_keyword_actions_attach_to_app():
    # Phase MC2 regression lock: keyword action handlers must remain
    # attached to App.* even though they moved to rules_keyword_actions.js.
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
    # Phase MC2 regression lock: folder action handlers must remain
    # attached to App.* even though they moved to rules_folder_actions.js.
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
    # Phase MC2 regression lock: rules.js (core) must keep loadProjectRules,
    # showProjectRules, rerenderProjectRulesList, setRulesLoading,
    # showRulesError, clearRulesError. These are the core entry points
    # referenced by init.js and other modules.
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
    # Phase MC2 regression lock: rules.js (core) must no longer carry the
    # large render HTML helpers — they moved to rules_render.js. The
    # core module may still call App.renderProjectRuleProject (delegating
    # to the render module) but must not DEFINE it.
    source = read_js("rules.js")
    assert "function renderProjectRuleProject" not in source, (
        "rules.js core must not define renderProjectRuleProject (moved to rules_render.js)"
    )
    assert "function renderProjectRuleRow" not in source, (
        "rules.js core must not define renderProjectRuleRow (moved to rules_render.js)"
    )


def test_project_rules_mc2_render_module_does_not_call_bridge():
    # Phase MC2 regression lock: rules_render.js must be a pure render
    # module — no bridge calls. The bridge calls live in the action
    # modules (rule_actions / keyword_actions / folder_actions /
    # project_actions).
    source = read_js("rules_render.js")
    assert "callBridge(" not in source, (
        "rules_render.js must not call bridge (pure render module)"
    )


def test_project_rules_mc2_state_keys_unchanged():
    # Phase MC2 regression lock: all Project Rules frontend state keys
    # must remain available (declared in core.js) and the split modules
    # must not re-declare or rename them. The state keys are part of the
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
    # Phase MC2 regression lock: the removed monolithic app.js must not
    # be reintroduced by the split.
    source = read_resource("index.html")
    assert "app.js" not in source


def test_project_rules_mc2_no_forbidden_handler_tokens_in_split_modules():
    # Phase MC2 regression lock: the new split modules must not introduce
    # any forbidden camelCase handler tokens.
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
    # Phase MC2 regression lock: the new split modules must not use
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
    # Phase MC2 regression lock: the new split modules must not reference
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


# --- Phase 5H: rule impact preview + safe single-rule backfill ---
#
# Phase 5H added two read-only / safe-write user capabilities to the
# Project Rules page:
#   1. "预览影响" button  -> preview_project_rule_impact(rule_type, rule_id)
#      renders a read-only panel with counts + up to 20 display-safe
#      sample rows (no list refresh).
#   2. "应用到历史记录" button -> backfill_project_rule(rule_type, rule_id)
#      after a window.confirm() dialog; refreshes the Project Rules list
#      on success.
# The tests below lock down the static contract for both paths.


def test_project_rules_impact_panel_dom_id_exists():
    # Phase 5H: the rules page must contain the impact / backfill result
    # panel container between rules-loading and rules-list.
    section = _rules_section()
    assert 'id="rules-impact-panel"' in section


def test_project_rules_impact_readonly_hint_mentions_5h_capabilities():
    # Phase 5H: the readonly hint must mention the new single-rule
    # preview + safe backfill capability and still flag the deferred
    # capabilities (automatic rules, batch ops, project hard delete).
    section = _rules_section()
    for term in (
        "预览单条规则影响",
        "安全应用",
        "自动规则",
        "项目硬删除",
    ):
        assert term in section, (
            "rules-readonly-hint must mention Phase 5H capability: " + term
        )


def test_project_rules_impact_state_variables_declared():
    # Phase 5H: core.js must declare the four new impact / backfill
    # state keys so the render + action modules can coordinate disabled
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
    # Phase 5H: the preview impact button class appears in the shared
    # renderProjectRuleRow body (rendered for any rule with a valid id,
    # both folder and keyword paths).
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "rules-preview-impact-button" in row_body


def test_project_rules_impact_backfill_button_rendered_for_folder_and_keyword():
    # Phase 5H: the backfill button class appears in the shared
    # renderProjectRuleRow body (rendered for any rule with a valid id).
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "rules-backfill-button" in row_body


def test_project_rules_impact_buttons_have_data_rule_kind_and_data_rule_id():
    # Phase 5H: both impact buttons must carry data-rule-kind and
    # data-rule-id attributes so the delegated click handler can resolve
    # the rule type and id. The render builds them via string concat:
    #   data-rule-kind="' + kind + '"
    #   data-rule-id="' + count(ruleId) + '"
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert '''data-rule-kind="' + kind + '"''' in row_body
    assert '''data-rule-id="' + count(ruleId) + '"''' in row_body


def test_project_rules_impact_preview_button_label_is_preview_impact():
    # Phase 5H: the preview button label is "预览影响" (with a "正在预览…"
    # in-flight variant handled separately).
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "预览影响" in row_body


def test_project_rules_impact_backfill_button_label_is_apply_to_history():
    # Phase 5H: the backfill button label is "应用到历史记录" (with a
    # "正在应用…" in-flight variant handled separately).
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "应用到历史记录" in row_body


def test_project_rules_impact_backfill_button_disabled_for_disabled_rules():
    # Phase 5H: the backfill button must be rendered disabled when the
    # rule is not enabled, because the bridge refuses to backfill a
    # disabled rule (``rule_disabled``). The render uses ``!enabled`` in
    # the backfillDisabled expression.
    source = read_rules_module_js()
    row_body = func_body(source, "renderProjectRuleRow")
    assert "backfillDisabled" in row_body
    assert "!enabled" in row_body


def test_project_rules_impact_preview_handler_calls_bridge_preview():
    # Phase 5H: the preview handler must call the new
    # preview_project_rule_impact bridge method.
    source = read_rules_module_js()
    assert 'callBridge("preview_project_rule_impact"' in source


def test_project_rules_impact_backfill_handler_calls_bridge_backfill():
    # Phase 5H: the backfill handler must call the new
    # backfill_project_rule bridge method.
    source = read_rules_module_js()
    assert 'callBridge("backfill_project_rule"' in source


def test_project_rules_impact_backfill_confirm_text_mentions_manual_records():
    # Phase 5H: the backfill confirm dialog must warn the user that
    # manually-modified records will not be overwritten, and must use
    # the exact determinate Chinese prompt.
    source = read_rules_module_js()
    assert "手动修改过的记录不会被覆盖" in source
    assert "确定将这条规则应用到符合条件的历史记录吗" in source


def test_project_rules_impact_preview_success_renders_panel_not_list_refresh():
    # Phase 5H: on preview success the handler shows the impact panel
    # via showProjectRuleImpactPanel and must NOT refresh the list
    # (preview is read-only and does not mutate data).
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleImpactPreview")
    assert "showProjectRuleImpactPanel" in body
    assert "loadProjectRules()" not in body


def test_project_rules_impact_backfill_success_refreshes_list():
    # Phase 5H: on backfill success the handler must refresh the
    # Project Rules list via loadProjectRules() so the updated counts
    # are reflected.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleBackfill")
    assert "loadProjectRules()" in body


def test_project_rules_impact_close_button_does_not_call_bridge():
    # Phase 5H: the impact panel close button only clears the panel; it
    # must not call any bridge method (close is a pure UI tear-down).
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleImpactPanelClick")
    assert "clearProjectRuleImpactPanel" in body
    assert "callBridge(" not in body


def test_project_rules_impact_preview_catch_never_reads_raw_exception():
    # Phase 5H: the preview catch handler must use a hardcoded Chinese
    # error string and never read ``.message`` off the raw exception.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleImpactPreview")
    assert ".message" not in body


def test_project_rules_impact_backfill_catch_never_reads_raw_exception():
    # Phase 5H: the backfill catch handler must use a hardcoded Chinese
    # error string and never read ``.message`` off the raw exception.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRuleBackfill")
    assert ".message" not in body


def test_project_rules_impact_no_storage_or_network():
    # Phase 5H regression lock: the impact render + action modules must
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
    # Phase 5H regression lock: the impact render + action modules must
    # not reference external network resources (CDN, Google Fonts,
    # http/https links).
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
    # Phase 5H regression lock: the impact action module must not
    # reintroduce any forbidden camelCase handler tokens.
    source = read_js("rules_rule_actions.js")
    for token in FORBIDDEN_RULES_JS_HANDLER_TOKENS:
        assert token not in source, (
            f"rules_rule_actions.js must not contain forbidden handler token: {token}"
        )


def test_project_rules_impact_no_es_module_syntax():
    # Phase 5H regression lock: the impact render + action modules must
    # stay classic IIFEs (no ES module export / import syntax).
    for name in ("rules_render.js", "rules_rule_actions.js"):
        source = read_js(name)
        assert "export " not in source, (
            f"{name} must not use ES module export syntax"
        )
        assert "import " not in source, (
            f"{name} must not use ES module import syntax"
        )


def test_project_rules_impact_css_classes_exist():
    # Phase 5H: styles.css must define every impact panel CSS class used
    # by the render module.
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
    # Phase 5H: every impact CSS class must be scoped under the
    # ``rules-`` namespace (no bare ``.impact-`` / ``.preview-``
    # classes leaking outside the rules page namespace).
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
    # Phase 5H: both the preview and backfill handlers must early-return
    # when the other impact write path is in flight, guarding against
    # concurrent pollution. Each handler must reference both
    # rulesPreviewingImpactKey and rulesBackfillingRuleKey.
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
    # Phase 5H: rules_render.js must define the two impact panel render
    # helpers and attach them to App.
    source = read_js("rules_render.js")
    assert "App.renderProjectRuleImpactPreview = renderProjectRuleImpactPreview" in source
    assert "App.renderProjectRuleBackfillResult = renderProjectRuleBackfillResult" in source


def test_project_rules_impact_render_panel_does_not_call_bridge():
    # Phase 5H regression lock: the render module must stay pure — no
    # bridge calls. Bridge calls live in the action modules.
    source = read_js("rules_render.js")
    assert "callBridge(" not in source, (
        "rules_render.js must not call bridge (pure render module)"
    )


def test_project_rules_impact_render_panel_uses_escape_helper():
    # Phase 5H: the render module must use the escape helper for
    # dynamic text so display-safe sample rows cannot inject HTML.
    source = read_js("rules_render.js")
    assert "App.escapeHtml" in source


def test_project_rules_impact_packaging_spec_still_includes_rules_js():
    # Phase 5H regression lock: the packaging spec must still bundle
    # rules_render.js and rules_rule_actions.js so the impact modules
    # ship in the frozen executable.
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "rules_render.js" in spec
    assert "rules_rule_actions.js" in spec


def test_project_rules_impact_no_new_js_file_added():
    # Phase 5H regression lock: the impact logic was added to the
    # existing split modules; no new rules_impact_actions.js file was
    # introduced. ALL_JS_FILES must still list rules_rule_actions.js
    # and must NOT list rules_impact_actions.js.
    assert "rules_rule_actions.js" in ALL_JS_FILES
    assert "rules_impact_actions.js" not in ALL_JS_FILES


def test_project_rules_impact_init_does_not_bind_impact_buttons_directly():
    # Phase 5H regression lock: init.js must not bind the impact
    # buttons directly. Event delegation is wired in
    # rules_rule_actions.js via bindProjectRuleImpactEvents.
    source = read_js("init.js")
    assert "rules-preview-impact-button" not in source
    assert "rules-backfill-button" not in source


def test_project_rules_impact_bind_function_called_in_show_and_rerender():
    # Phase 5H regression lock: rules.js must call
    # App.bindProjectRuleImpactEvents in both showProjectRules and
    # rerenderProjectRulesList so the impact event delegation is
    # re-bound after every re-render.
    source = read_js("rules.js")
    assert "App.bindProjectRuleImpactEvents" in source
    # At least two call sites (show + rerender).
    assert source.count("App.bindProjectRuleImpactEvents") >= 2


def test_project_rules_impact_buttons_disabled_during_other_writes():
    # Phase 5H regression lock: the impact button section in
    # renderProjectRuleRow must reference the other rule write state
    # keys so the impact buttons are disabled while any rule write is
    # in flight (preventing cross-path pollution).
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


# --- Phase 5I: selected-rule batch operations static contract ------------


def test_project_rules_batch_dom_ids_exist():
    # Phase 5I: the rules section must contain the batch toolbar and
    # batch panel container divs. The toolbar holds the selected count +
    # action buttons; the panel holds aggregate counts + per-rule
    # summaries. Both are populated dynamically by JS.
    section = _rules_section()
    for dom_id in ("rules-batch-toolbar", "rules-batch-panel"):
        assert 'id="' + dom_id + '"' in section, (
            "Project Rules page must contain batch anchor: " + dom_id
        )


def test_project_rules_batch_toolbar_and_panel_are_hidden_by_default():
    # Phase 5I: both batch containers must be hidden by default in the
    # static HTML. The toolbar / panel content is rendered dynamically by
    # rules_render.js / rules_rule_actions.js, so the static divs ship
    # empty with the ``hidden`` attribute.
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
    # Phase 5I regression lock: the batch toolbar buttons are rendered
    # dynamically by ``renderProjectRulesBatchToolbar`` (JS), so the static
    # button count in the rules section must remain exactly three (project
    # create submit + keyword create submit + folder create submit). No
    # batch button may leak into the static HTML.
    import re as _re

    section = _rules_section()
    buttons = _re.findall(r"<button[^>]*>", section, _re.IGNORECASE)
    assert len(buttons) == 3, (
        "Project Rules page must still have exactly three static buttons "
        "after Phase 5I; found: " + repr(buttons)
    )
    button_ids = [_re.search(r'id="([^"]+)"', b) for b in buttons]
    button_ids = [m.group(1) for m in button_ids if m]
    assert "rules-project-create-submit" in button_ids
    assert "rules-keyword-create-submit" in button_ids
    assert "rules-folder-create-submit" in button_ids

def test_project_rules_core_js_declares_batch_state_variables():
    # Phase 5I: core.js must declare the three batch state variables so
    # the batch surface has its own JS-memory state distinct from the
    # single-rule write states.
    source = read_js("core.js")
    assert "App.rulesBatchSelectedKeys = {}" in source
    assert "App.rulesBatchInFlight = false" in source
    assert "App.rulesBatchPanelData = null" in source


def test_project_rules_js_calls_batch_bridge_methods():
    # Phase 5I: the batch handlers must call the new batch bridge methods.
    # These are ALLOWED batch bridges and are NOT in
    # PROJECT_RULE_WRITE_METHODS (preview / backfill / set-enabled are the
    # batch equivalents of the single-rule impact / backfill / toggle
    # bridges).
    source = read_rules_module_js()
    assert 'callBridge("preview_project_rules_batch_impact"' in source
    assert 'callBridge("backfill_project_rules_batch"' in source
    assert 'callBridge("set_project_rules_batch_enabled"' in source
    # The new batch bridges must NOT be classified as forbidden write
    # methods -- they are explicitly allowed.
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
    # Phase 5I regression lock: the batch handler functions in
    # rules_rule_actions.js must not reintroduce any forbidden camelCase
    # handler tokens (including ``automaticRules``).
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
    # Phase 5I regression lock: the batch apply confirm dialog must warn
    # the user that manually edited records are preserved and that
    # excessively large hit sets are not written.
    source = read_rules_module_js()
    body = func_body(source, "handleProjectRulesBatchApply")
    assert "window.confirm" in body
    assert "手动修改过的记录不会被覆盖" in body
    assert "命中记录过多时不会写入" in body

def test_project_rules_batch_state_isolated_from_other_write_states():
    # Phase 5I regression lock: ``rulesBatchInFlight`` must be a separate
    # state variable from every other rule write-state variable so batch
    # operations cannot pollute single-rule write paths (and vice versa).
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
        # batch in-flight flag (no aliasing / name reuse).
        assert var != "App.rulesBatchInFlight"
    # The batch in-flight flag must not be aliased to any other App state.
    assert "App.rulesBatchInFlight = App." not in source


def test_project_rules_batch_css_classes_exist():
    # Phase 5I: styles.css must define every batch CSS class used by the
    # render module (toolbar / buttons / panel / per-rule summary / row
    # selection highlight / checkbox / close button).
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
    # Phase 5I: styles.css must define ``[hidden]`` rules for both batch
    # containers so they are fully suppressed (display: none) when the
    # ``hidden`` attribute is set on the static divs.
    css = read_resource("styles.css")
    assert ".rules-batch-toolbar[hidden]" in css, (
        "styles.css must define .rules-batch-toolbar[hidden] rule"
    )
    assert ".rules-batch-panel[hidden]" in css, (
        "styles.css must define .rules-batch-panel[hidden] rule"
    )


def test_project_rules_script_order_preserved_with_batch():
    # Phase 5I regression lock: no new JS file was added for the batch
    # logic (it lives in the existing split modules). The script load
    # order in index.html must still match ALL_JS_FILES exactly, in order.
    source = read_resource("index.html")
    positions = []
    for name in ALL_JS_FILES:
        needle = 'src="js/' + name + '"'
        pos = source.find(needle)
        assert pos != -1, "index.html must include script: " + name
        positions.append(pos)
    # Positions must be strictly increasing (correct load order).
    for i in range(1, len(positions)):
        assert positions[i] > positions[i - 1], (
            "script load order broken around: " + ALL_JS_FILES[i]
        )
    # No dedicated batch JS module was introduced.
    assert "rules_batch_actions.js" not in source
    assert "rules_batch_actions.js" not in ALL_JS_FILES


# ---------------------------------------------------------------------------
# Phase 5I.1 hardening: additional static-contract locks for the batch
# surface and the automatic-rules status contract. These complement the
# existing 5I static tests by locking:
#   - batch checkbox groups selection by (rule_kind, rule_id) via the
#     ``data-rule-kind`` + ``data-rule-id`` attribute pair (so a folder
#     rule id and a keyword rule id never collide in selection state);
#   - no automatic-rules on/off toggle UI exists in the static HTML/JS
#     (Phase 5I only exposes a read-only status payload);
#   - the batch toolbar buttons carry a ``disabled`` attribute when
#     ``rulesBatchInFlight`` is true (duplicate-submit guard);
#   - the batch handlers do not use ``localStorage`` / ``sessionStorage``
#     or issue network requests (``fetch`` / ``XMLHttpRequest``).
# ---------------------------------------------------------------------------


def test_project_rules_batch_checkbox_groups_by_rule_kind_and_id():
    # Phase 5I.1 hardening: the per-rule batch-selection checkbox must
    # carry BOTH ``data-rule-kind`` and ``data-rule-id`` so selection state
    # is keyed by the composite rule key (``kind:id``), not by rule id
    # alone. Without ``data-rule-kind``, a folder rule with id 5 and a
    # keyword rule with id 5 would alias to the same selection entry.
    source = read_js("rules_render.js")
    func = func_body(source, "renderProjectRuleRow")
    # The checkbox input must carry both attributes.
    assert 'class="rules-batch-checkbox"' in func, (
        "batch checkbox must use the rules-batch-checkbox class"
    )
    assert 'data-rule-kind="' in func, (
        "batch checkbox must carry data-rule-kind attribute"
    )
    assert 'data-rule-id="' in func, (
        "batch checkbox must carry data-rule-id attribute"
    )
    # The selection lookup must use the composite rule key, not bare id.
    assert "rulesBatchSelectedKeys[ruleKey]" in func, (
        "batch selection state must be keyed by composite ruleKey"
    )


def test_project_rules_no_automatic_rules_on_off_toggle_in_frontend():
    # Phase 5I.1 hardening: the frontend must NOT render any on/off
    # toggle for the automatic-rules engine. Phase 5I only exposes a
    # read-only status payload via ``automatic_rules_status``; the on/off
    # UI toggle is explicitly out of scope. This lock prevents a future
    # change from silently introducing a toggle button / checkbox /
    # switch bound to an automatic-rules enable/disable bridge call.
    html = read_resource("index.html")
    rules_section = _rules_section()
    # No element whose id or class suggests an automatic-rules toggle.
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
    # The full rules JS module set must not bind a toggle handler that
    # would enable/disable the automatic-rules engine. The bridge has
    # no ``set_automatic_rules_enabled`` method, and the JS must not
    # reference one either.
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
    # ``automaticRules`` is already in FORBIDDEN_RULES_JS_HANDLER_TOKENS,
    # which the existing ``test_project_rules_js_calls_allowed_bridge_methods_only``
    # and ``test_project_rules_batch_handlers_no_forbidden_tokens`` enforce.


def test_project_rules_batch_toolbar_buttons_disabled_when_in_flight():
    # Phase 5I.1 hardening: the batch toolbar action buttons (preview /
    # apply / enable / disable) must carry a ``disabled`` attribute when
    # ``App.rulesBatchInFlight`` is true, so a second click during an
    # in-flight batch operation cannot trigger a duplicate submit. The
    # clear button is exempt — it is allowed to remain enabled so the
    # user can dismiss the selection (the in-flight guard in the handler
    # still refuses to act).
    source = read_js("rules_render.js")
    func = func_body(source, "renderProjectRulesBatchToolbar")
    # The in-flight flag must be read.
    assert "App.rulesBatchInFlight" in func, (
        "batch toolbar must reference App.rulesBatchInFlight"
    )
    # The action buttons must be bound to the disabled attribute when
    # in-flight (the ``actionDisabled`` variable carries the disabled
    # attribute and is applied to all four action buttons).
    assert "actionDisabled" in func, (
        "batch toolbar must compute an actionDisabled guard"
    )
    # All four action button classes must appear in the toolbar render.
    for cls in (
        "rules-batch-preview-button",
        "rules-batch-apply-button",
        "rules-batch-enable-button",
        "rules-batch-disable-button",
    ):
        assert cls in func, "batch toolbar must render button: " + cls


def test_project_rules_batch_handlers_have_no_storage_or_network():
    # Phase 5I.1 hardening: the batch handler functions must not use
    # ``localStorage`` / ``sessionStorage`` (selection lives in JS memory
    # only) and must not issue network requests (``fetch`` /
    # ``XMLHttpRequest`` / ``navigator.sendBeacon``). The frontend is
    # strictly local and talks to the bridge via ``callBridge``.
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