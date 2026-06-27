"""Project Rules WebView static-contract tests for Phase 5A.

These tests read bundled frontend resources directly. They lock the
Project Rules read-only foundation without starting pywebview or touching
the database.
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


def test_project_rules_readonly_boundary_copy_present():
    section = _rules_section()
    assert "只读" in section or "本阶段仅支持查看" in section
    for term in ("新增", "编辑", "启用禁用", "删除"):
        assert term in section


def test_project_rules_page_has_no_action_buttons():
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


def test_project_rules_js_defines_load_and_render_functions():
    source = read_all_js()
    assert "function loadProjectRules" in source
    assert "function showProjectRules" in source
    assert "function renderProjectRuleProject" in source
    assert "function renderProjectRuleRow" in source


def test_project_rules_js_calls_readonly_bridge_method():
    source = read_js("rules.js")
    assert 'callBridge("get_project_rules")' in source


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


def test_project_rules_js_does_not_call_write_methods():
    source = read_all_js()
    for method in PROJECT_RULE_WRITE_METHODS:
        assert method not in source, (
            "Project Rules frontend must not call write bridge method: " + method
        )


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
