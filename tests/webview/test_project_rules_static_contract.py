"""Project Rules WebView static-contract tests for the lightweight IA."""

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
    func_body,
    read_all_js,
    read_js,
    read_resource,
    read_rules_module_js,
)


def _rules_section() -> str:
    source = read_resource("index.html")
    start = source.find('id="page-rules"')
    assert start != -1
    end = source.find('<section id="page-settings"', start)
    assert end != -1
    return source[start:end]


def test_project_rules_home_keeps_lightweight_entry_points():
    section = _rules_section()
    assert "项目规则" in section
    assert 'id="rules-open-create-rule"' in section
    assert 'id="rules-open-create-project"' in section
    assert 'id="rules-sort-select"' in section
    assert "按上次使用排序" in section
    assert "按首字母排序" in section
    assert 'id="rules-advanced"' in section


def test_project_rules_home_removes_static_legacy_forms_and_batch_surfaces():
    section = _rules_section()
    for forbidden in (
        "rules-project-create-form",
        "rules-keyword-create-form",
        "rules-folder-create-form",
        "rules-count-grid",
        "rules-batch-toolbar",
        "rules-impact-panel",
        "rules-batch-panel",
    ):
        assert forbidden not in section


def test_project_rules_unified_panel_contains_project_and_rule_flows():
    section = _rules_section()
    assert 'id="rules-create-panel"' in section
    assert 'id="rules-panel-rule-section"' in section
    assert 'id="rules-panel-project-section"' in section
    assert 'id="rules-panel-folder-type"' in section
    assert 'id="rules-panel-keyword-type"' in section
    assert 'id="rules-panel-backfill"' in section
    assert 'id="rules-panel-project-language"' in section
    assert "中文" in section and "英语" in section and "日语" in section and "其他" in section
    assert re.search(r'id="rules-panel-folder-type"[^>]*class="[^"]*is-active', section)
    assert re.search(r'id="rules-panel-backfill"[^>]*checked', section)


def test_project_rules_advanced_is_collapsed_and_content_is_rendered_by_js():
    section = _rules_section()
    details = re.search(r'<details[^>]*id="rules-advanced"[^>]*>', section)
    assert details
    assert " open" not in details.group(0)
    assert 'id="rules-advanced-content"' in section
    advanced_container = re.search(
        r'<div id="rules-advanced-content"[^>]*>(.*?)</div>',
        section,
        re.DOTALL,
    )
    assert advanced_container
    assert advanced_container.group(1).strip() == ""


def test_project_rules_script_order_includes_create_panel_before_actions():
    assert ALL_JS_FILES.index("rules.js") < ALL_JS_FILES.index("rules_render.js")
    assert ALL_JS_FILES.index("rules_create_panel.js") == ALL_JS_FILES.index("rules_render.js") + 1
    assert ALL_JS_FILES.index("rules_rule_actions.js") == ALL_JS_FILES.index("rules_create_panel.js") + 1
    assert ALL_JS_FILES.index("rules_project_actions.js") < ALL_JS_FILES.index("init.js")


def test_project_rules_static_helper_reads_create_panel_module():
    source = read_rules_module_js()
    assert "function initRulesPanelEvents" in source
    assert "function savePanelRule" in source
    assert "function renderRulesAdvancedPanel" in source


def test_project_rules_home_render_only_exposes_edit_project_add_rule_and_delete():
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    row_body = func_body(source, "renderProjectRuleRow")
    assert "rules-project-edit-button" in project_body
    assert "rules-project-add-rule-button" in project_body
    assert "rules-count-grid" not in project_body
    assert "rules-project-toggle-button" not in project_body
    assert "rules-project-archive-button" not in project_body
    assert "rules-keyword-delete-button" in row_body
    assert "rules-folder-delete-button" in row_body
    for forbidden in (
        "rules-toggle-btn",
        "rules-keyword-edit-button",
        "rules-folder-edit-button",
        "rules-preview-impact-button",
        "rules-backfill-button",
        "rules-batch-checkbox",
    ):
        assert forbidden not in row_body


def test_project_rules_show_does_not_bind_removed_home_actions():
    body = func_body(read_rules_module_js(), "showProjectRules")
    for forbidden in (
        "bindProjectRuleToggles",
        "bindProjectRuleImpactEvents",
        "bindProjectRuleBatchEvents",
        "bindExcludedKeywordRuleEvents",
        "bindExcludedFolderRuleEvents",
        "bindProjectRuleKeywordEditEvents",
    ):
        assert forbidden not in body
    assert "bindProjectRuleDelete" in body
    assert "bindProjectRuleFolderEvents" in body


def test_project_rules_panel_create_backfill_contract_is_stable():
    source = read_rules_module_js()
    body = func_body(source, "savePanelRule")
    assert 'callBridge("create_project_folder_rule"' in body
    assert 'callBridge("create_project_keyword_rule"' in body
    assert 'callBridge("backfill_project_rule"' in source
    assert "规则已新增，但应用到历史记录失败" in body
    assert ".catch(function ()" in body
    for forbidden in ("err.message", "error.message", "reason.message", ".toString"):
        assert forbidden not in body


def test_project_rules_excluded_rules_are_advanced_only():
    source = read_rules_module_js()
    advanced_body = func_body(source, "renderRulesAdvancedPanel")
    assert "rules-excluded-enabled-toggle" in advanced_body
    assert "rules-excluded-rule-submit" in advanced_body
    assert "rules-panel-target-project" not in advanced_body
    assert "rules-panel-backfill" not in advanced_body
    assert 'callBridge("set_excluded_rules_enabled"' in source
    assert 'callBridge("create_excluded_keyword_rule"' in source
    assert 'callBridge("create_excluded_folder_rule"' in source


def test_project_rules_sort_state_is_memory_only():
    source = read_rules_module_js()
    assert 'App.rulesSortMode = "last_used"' in read_js("core.js")
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "function _sortProjectsForRulesHome" in source


def test_project_rules_frontend_resources_keep_local_boundaries():
    for filename in FRONTEND_RESOURCE_FILES:
        source = read_resource(filename)
        assert not re.search(r"https?://", source, re.IGNORECASE)
        assert not re.search(r"cdn", source, re.IGNORECASE)
        assert not re.search(r"google\s*fonts", source, re.IGNORECASE)
    for filename in NO_STORAGE_FILES:
        source = read_resource(filename)
        assert "localStorage" not in source
        assert "sessionStorage" not in source
    assert "fetch(" not in read_all_js()
    assert "XMLHttpRequest" not in read_all_js()
