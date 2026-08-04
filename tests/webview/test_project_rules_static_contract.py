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
    source = read_resource("index_fd_work_v5.html")
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
    assert 'id="rules-panel-folder-group"' in section
    assert re.search(r'id="rules-panel-folder-recursive"[^>]*checked', section)
    textarea = re.search(r'id="rules-panel-project-description"[^>]*>', section)
    assert textarea is not None
    assert 'rows="2"' in textarea.group(0)
    assert 'maxlength="500"' in textarea.group(0)


def test_fd_work_case_semantics_are_enabled_only_by_shared_capability_status():
    section = _rules_section()
    name_input = re.search(r'id="rules-panel-project-name"[^>]*>', section)
    assert name_input is not None
    assert 'maxlength="100"' in name_input.group(0)
    assert 'role="combobox"' not in name_input.group(0)
    assert 'aria-autocomplete="list"' not in name_input.group(0)
    selected = re.search(r'id="rules-panel-fd-work-selected-label"[^>]*>', section)
    assert selected is not None
    assert "readonly" in selected.group(0)
    assert 'id="rules-panel-fd-work-pick"' in section
    source = read_js("rules_create_panel_v5.js")
    presentation = func_body(source, "syncFDWorkCasePickerStatus")
    assert "input.hidden = enabled" in presentation
    assert "picker.hidden = !enabled" in presentation
    assert 'nameInput.addEventListener("focus"' not in source
    assert 'nameInput.addEventListener("click"' not in source
    assert 'nameInput.addEventListener("input"' not in source
    assert "searchFDWorkCases" not in source


def test_fd_work_frontend_contract_scripts_are_cache_versioned_together():
    index = read_resource("index_fd_work_v5.html")

    assert 'src="js/fd_work_v5.js"' in index
    assert 'src="js/rules_create_panel_v5.js"' in index
    assert 'src="js/init_fd_work_v5.js"' in index


def test_project_rules_folder_path_uses_native_readonly_picker_contract():
    section = _rules_section()
    path_input = re.search(r'id="rules-panel-folder-path"[^>]*>', section)
    assert path_input is not None
    assert "readonly" in path_input.group(0)
    assert "请选择要自动归类的文件夹" in path_input.group(0)
    assert 'id="rules-panel-choose-folder"' in section
    assert "选择文件夹" in section

    source = read_js("rules_create_panel_v5.js")
    assert "App.bridge.chooseProjectRuleFolder()" in source
    assert "App.rulesChoosingFolder" in source
    assert "选择文件夹失败" in source


def test_project_rules_folder_picker_and_drawer_stay_bounded_at_supported_sizes():
    styles = read_resource("styles.css")
    picker = re.search(r"\.folder-picker-control\s*\{([^}]*)\}", styles)
    picker_input = re.search(r"\.folder-picker-control input\s*\{([^}]*)\}", styles)
    drawer = re.search(r"\.drawer\s*\{([^}]*)\}", styles)
    assert picker is not None
    assert "grid-template-columns: minmax(0, 1fr) auto" in picker.group(1)
    assert "min-width: 0" in picker.group(1)
    assert picker_input is not None and "min-width: 0" in picker_input.group(1)
    assert drawer is not None and "width: min(430px, calc(100% - 8px))" in drawer.group(1)
    assert "@media (max-width: 959px)" in styles


def test_project_rules_panel_presentation_context_and_tab_state_are_single_owner():
    source = read_js("rules_create_panel_v5.js")
    presentation = func_body(source, "syncProjectPanelPresentation")
    for expected in (
        "新建项目",
        "编辑项目",
        "保存修改",
        "正在新建…",
        "正在保存…",
        "aria-label",
        "disabled",
    ):
        assert expected in presentation

    context = func_body(source, "renderRulesPanelProjectContext")
    assert "为项目“" in context
    assert "项目已新增：“" in context
    assert "请继续添加自动归类规则。" in context
    assert "is-success" in context

    rule_type = func_body(source, "setRuleType")
    assert 'setAttribute("aria-selected"' in rule_type
    assert ".tabIndex =" in rule_type
    assert 'classList.toggle("is-active"' in rule_type
    assert "folderGroup.hidden" in rule_type
    assert "keywordRow.hidden" in rule_type
    assert "recursive.checked = true" in rule_type
    assert "folderRow" not in rule_type
    assert "recursiveRow" not in rule_type


def test_project_rule_drawer_has_session_guard_and_shared_discard_reset():
    source = read_js("rules_create_panel_v5.js")
    assert "App.rulesPanelSessionToken" in source
    assert "function resetRulesTransientUi" in source
    assert "App.resetRulesTransientUi = resetRulesTransientUi" in source
    assert "requestClose: closeRulesPanel" in source
    for name in ("chooseProjectRuleFolder", "savePanelProject", "savePanelRule"):
        assert "sessionToken" in func_body(source, name)


def test_project_rules_deletion_uses_shared_dialog_and_explicit_history_policy():
    section = _rules_section()
    index = read_resource("index_fd_work_v5.html")
    assert 'id="rules-delete-modal"' not in section
    assert 'id="confirm-dialog"' in index
    delete = func_body(read_js("rules_keyword_actions.js"), "deleteRule")
    assert "deleteProjectFolderRule(ruleId, applyToHistory)" in delete
    assert "deleteProjectKeywordRule(ruleId, applyToHistory)" in delete
    assert "deleteRule(kind, ruleId, false)" in read_js("rules_keyword_actions.js")


def test_project_rules_script_order_includes_create_panel_before_actions():
    assert ALL_JS_FILES.index("rules.js") < ALL_JS_FILES.index("rules_render.js")
    assert ALL_JS_FILES.index("rules_create_panel_v5.js") == ALL_JS_FILES.index("rules_render.js") + 1
    assert ALL_JS_FILES.index("rules_rule_actions.js") == ALL_JS_FILES.index("rules_create_panel_v5.js") + 1
    assert ALL_JS_FILES.index("rules_folder_actions.js") < ALL_JS_FILES.index("init_fd_work_v5.js")


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
    assert project_body.count("compact-icon-button") == 3
    assert row_body.count("compact-icon-button") == 1
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


def test_project_rules_header_places_description_left_and_actions_with_metadata_right():
    source = read_js("rules_render.js")
    body = func_body(source, "renderProjectRuleProject")
    css = read_resource("styles.css")
    title_start = body.index('<div class="rules-project-title-group">')
    description = body.index("rules-project-description")
    side = body.index('<div class="rules-project-side">')
    actions = body.index('<div class="rules-project-actions">')
    meta = body.index('<div class="rules-project-meta">')
    assert title_start < description < side < actions < meta
    side_markup = body[side:body.index('</div></div><div class="rules-row-list"')]
    assert side_markup.count("<button") == 3
    assert "rules-project-meta" in side_markup
    assert 'projectDescription ? "" : " is-empty"' in body
    assert 'projectDescription || "无描述"' in body
    head = re.search(r"\.rules-project-head\s*\{([^}]*)\}", css)
    assert head is not None
    assert "grid-template-columns: 22px minmax(0, 1fr) auto" in head.group(1)
    side_style = re.search(r"\.rules-project-side\s*\{([^}]*)\}", css)
    meta_style = re.search(r"\.rules-project-meta\s*\{([^}]*)\}", css)
    empty_style = re.search(r"\.rules-project-description\.is-empty\s*\{([^}]*)\}", css)
    assert side_style is not None
    assert meta_style is not None and "text-align: right" in meta_style.group(1)
    assert empty_style is not None and "var(--color-text-tertiary)" in empty_style.group(1)
    assert "minmax(250px, auto)" not in css
    assert "minmax(220px, auto)" not in css
    assert (
        ".rules-project-delete-button, .rules-keyword-delete-button, "
        ".rules-folder-delete-button" not in css
    )
    danger = re.search(r"\.danger-icon-button\s*\{([^}]*)\}", css)
    assert danger is not None and "var(--color-danger)" in danger.group(1)


def test_project_rule_folder_fields_are_one_aligned_group():
    section = _rules_section()
    styles = read_resource("styles.css")
    source = read_js("rules_create_panel_v5.js")
    folder_start = section.index('id="rules-panel-folder-group"')
    keyword_start = section.index('id="rules-panel-keyword-row"')
    folder = section[folder_start:keyword_start]
    for control_id in (
        "rules-panel-folder-path",
        "rules-panel-choose-folder",
        "rules-panel-folder-recursive",
    ):
        assert f'id="{control_id}"' in folder
    assert "文件夹规则默认匹配该文件夹及全部子文件夹。" not in section
    assert "默认匹配该文件夹及全部子文件夹" in folder
    checkbox = re.search(r"\.rule-folder-recursive\s*\{([^}]*)\}", styles)
    checkbox_input = re.search(r"\.rule-folder-recursive input\s*\{([^}]*)\}", styles)
    assert checkbox is not None and "align-items: flex-start" in checkbox.group(1)
    assert checkbox_input is not None
    assert "width: 14px" in checkbox_input.group(1)
    assert "height: 14px" in checkbox_input.group(1)
    assert "min-height: 0" in checkbox_input.group(1)
    rule_type = func_body(source, "setRuleType")
    assert "folderGroup.hidden" in rule_type
    assert "keywordRow.hidden" in rule_type


def test_project_description_height_is_local_to_rules_drawer():
    styles = read_resource("styles.css")
    description = re.search(
        r"#rules-panel-project-description\s*\{([^}]*)\}",
        styles,
    )
    assert description is not None
    assert "height: 50px" in description.group(1)
    assert "min-height: 50px" in description.group(1)
    assert "resize: vertical" in description.group(1)


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
