"""Project Rules WebView static-contract tests for the lightweight IA."""

from __future__ import annotations

import os
import re
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

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
    assert 'id="rules-open-create-project"' in section
    assert 'id="rules-search-input"' in section
    assert 'id="rules-sort-select"' in section
    assert "最近使用" in section
    assert "项目名称" in section
    assert 'id="rules-open-create-rule"' not in section
    assert 'id="rules-advanced"' not in section
    assert "高级功能" not in section


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
    assert re.search(r'id="rules-panel-project-language"[^>]*hidden', section)
    assert re.search(r'id="rules-panel-backfill"[^>]*checked', section)
    assert re.search(r'id="rules-panel-folder-recursive-row"[^>]*hidden', section)
    assert re.search(r'id="rules-panel-folder-recursive"[^>]*checked', section)


def test_project_rules_deletion_uses_shared_dialog_and_explicit_history_policy():
    section = _rules_section()
    index = read_resource("index.html")
    assert 'id="rules-delete-modal"' not in section
    assert 'id="confirm-dialog"' in index
    delete = func_body(read_js("rules_keyword_actions.js"), "deleteRule")
    assert "deleteProjectFolderRule(ruleId, applyToHistory)" in delete
    assert "deleteProjectKeywordRule(ruleId, applyToHistory)" in delete
    assert "deleteRule(kind, ruleId, false)" in read_js("rules_keyword_actions.js")


def test_project_rules_script_order_includes_create_panel_before_actions():
    assert ALL_JS_FILES.index("rules.js") < ALL_JS_FILES.index("rules_render.js")
    assert ALL_JS_FILES.index("rules_create_panel.js") == ALL_JS_FILES.index("rules_render.js") + 1
    assert ALL_JS_FILES.index("rules_rule_actions.js") == ALL_JS_FILES.index("rules_create_panel.js") + 1
    assert ALL_JS_FILES.index("rules_folder_actions.js") < ALL_JS_FILES.index("init.js")


def test_project_rules_static_helper_reads_create_panel_module():
    source = read_rules_module_js()
    assert "function initRulesPanelEvents" in source
    assert "function savePanelRule" in source
    assert "function openProjectRuleDeleteModal" in read_js("rules_keyword_actions.js")


def test_project_rules_home_render_only_exposes_edit_project_add_rule_and_delete():
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    row_body = func_body(source, "renderProjectRuleRow")
    assert "rules-project-edit-button" in project_body
    assert "rules-project-add-rule-button" in project_body
    assert "rules-project-delete-button" in project_body
    assert "rules-count-grid" not in project_body
    assert "rules-project-toggle" in project_body
    assert "rules-project-archive-button" not in project_body
    assert "rules-" in row_body and "-delete-button" in row_body
    for forbidden in (
        "rules-toggle-btn",
        "rules-keyword-edit-button",
        "rules-folder-edit-button",
        "rules-preview-impact-button",
        "rules-backfill-button",
        "rules-batch-checkbox",
        "rules-status",
    ):
        assert forbidden not in row_body


def test_project_rules_collapsed_row_uses_accessible_icons_without_rule_count():
    source = read_rules_module_js()
    project_body = func_body(source, "renderProjectRuleProject")
    row_body = func_body(source, "renderProjectRuleRow")
    toggle_body = func_body(source, "handleProjectCardPanelClick")
    assert 'App.iconMarkup("chevron-right")' in project_body
    assert 'App.iconMarkup("trash")' in project_body
    assert 'App.iconMarkup("trash")' in row_body
    assert 'aria-label="删除项目"' in project_body
    assert 'aria-label="删除规则"' in row_body
    assert "rule_count" not in project_body
    assert "textContent = rows.hidden" not in toggle_body
    assert 'classList.toggle("is-expanded"' in toggle_body


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
    assert "App.bridge.createProjectFolderRule" in body
    assert "App.bridge.createProjectKeywordRule" in body
    assert "App.backfillCreatedRule" in body
    assert "规则已新增，但应用到历史记录失败" in body
    assert "同时应用到历史记录" in _rules_section()
    assert ".catch(function ()" in body
    for forbidden in ("err.message", "error.message", "reason.message", ".toString"):
        assert forbidden not in body


def test_project_rules_do_not_expose_excluded_or_advanced_actions():
    source = read_rules_module_js()
    section = _rules_section()
    for forbidden in ("rules-advanced", "高级功能", "排除规则", "启用", "禁用", "暂停", "归档"):
        assert forbidden not in section


def test_project_rules_sort_state_is_memory_only():
    source = read_rules_module_js()
    assert 'App.rulesSortMode = "last_used"' in read_js("core.js")
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "function sortProjectsForRulesHome" in source


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
