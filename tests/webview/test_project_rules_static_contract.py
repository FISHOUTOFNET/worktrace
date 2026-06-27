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
    assert "当前支持启用/停用已有规则" in section
    for term in ("新增", "编辑", "删除", "冲突预览", "回填"):
        assert term in section


def test_project_rules_page_has_no_static_action_buttons():
    section = _rules_section()
    assert "<button" not in section.lower()
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
    for method in PROJECT_RULE_WRITE_METHODS:
        assert method not in source, (
            "Project Rules frontend must not call write bridge method: " + method
        )
    assert "set_project_rule_enabled" in source


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
    # Phase 5B.1 regression lock: ``set_project_rule_enabled`` is the only
    # Project Rules write bridge call anywhere in the frontend. No other
    # write bridge call (project toggle / create / edit / delete / preview /
    # backfill) may be introduced even in init.js / core.js.
    source = read_all_js()
    assert 'callBridge("set_project_rule_enabled"' in source
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
    # rules list, set up inside ``rules.js``.
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
