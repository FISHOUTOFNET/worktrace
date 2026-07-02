// WorkTrace WebView frontend - unified Project Rules create/edit panel.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    App.rulesPanelMode = "rule";
    App.rulesPanelRuleType = "folder";
    App.rulesPanelEditingProjectId = null;
    App.rulesPanelLastCreatedProjectId = null;
    App.rulesCreatingPanelProject = false;
    App.rulesCreatingPanelRule = false;
    App.rulesExcludedToggleInFlight = false;
    App.rulesCreatingExcludedRule = false;

    function initRulesPanelEvents() {
        bindClick("rules-open-create-rule", function () {
            openRulesPanel("rule", { ruleType: "folder" });
        });
        bindClick("rules-open-create-project", function () {
            openRulesPanel("project", {});
        });
        bindClick("rules-create-panel-close", closeRulesPanel);
        bindClick("rules-panel-rule-tab", function () { setPanelMode("rule"); });
        bindClick("rules-panel-project-tab", function () { setPanelMode("project"); });
        bindClick("rules-panel-folder-type", function () { setRuleType("folder"); });
        bindClick("rules-panel-keyword-type", function () { setRuleType("keyword"); });
        bindClick("rules-panel-create-project-inline", function () { setPanelMode("project"); });
        bindClick("rules-panel-save-project", savePanelProject);
        bindClick("rules-panel-save-rule", savePanelRule);
        var panel = document.getElementById("rules-create-panel");
        if (panel && panel.getAttribute("data-rules-panel-bound") !== "1") {
            panel.setAttribute("data-rules-panel-bound", "1");
            panel.addEventListener("click", function (event) {
                if (event.target && event.target.getAttribute("data-rules-panel-close") === "1") {
                    closeRulesPanel();
                }
            });
        }
        var languageSelect = document.getElementById("rules-panel-project-language");
        if (languageSelect) languageSelect.addEventListener("change", refreshLanguageOther);
        var sortSelect = document.getElementById("rules-sort-select");
        if (sortSelect && sortSelect.getAttribute("data-rules-sort-bound") !== "1") {
            sortSelect.setAttribute("data-rules-sort-bound", "1");
            sortSelect.addEventListener("change", function () {
                App.rulesSortMode = sortSelect.value === "alpha" ? "alpha" : "last_used";
                App.rerenderProjectRulesList();
            });
        }
        var list = document.getElementById("rules-list");
        if (list && list.getAttribute("data-rules-panel-open-bound") !== "1") {
            list.setAttribute("data-rules-panel-open-bound", "1");
            list.addEventListener("click", handleProjectCardPanelClick);
        }
        var advanced = document.getElementById("rules-advanced");
        if (advanced && advanced.getAttribute("data-rules-advanced-bound") !== "1") {
            advanced.setAttribute("data-rules-advanced-bound", "1");
            advanced.addEventListener("toggle", function () {
                if (advanced.open) renderRulesAdvancedPanel();
            });
            advanced.addEventListener("click", handleRulesAdvancedClick);
        }
    }
    App.initRulesPanelEvents = initRulesPanelEvents;

    function bindClick(id, handler) {
        var el = document.getElementById(id);
        if (!el || el.getAttribute("data-bound") === "1") return;
        el.setAttribute("data-bound", "1");
        el.addEventListener("click", handler);
    }

    function handleProjectCardPanelClick(event) {
        var button = event.target && event.target.closest ? event.target.closest("button") : null;
        if (!button) return;
        if (button.classList.contains("rules-project-edit-button")) {
            openProjectEdit(button);
        } else if (button.classList.contains("rules-project-add-rule-button")) {
            var projectId = parsePositiveInt(button.getAttribute("data-project-id"));
            openRulesPanel("rule", { projectId: projectId, ruleType: "folder" });
        }
    }

    function openProjectEdit(button) {
        var projectId = parsePositiveInt(button.getAttribute("data-project-id"));
        var project = findProject(projectId);
        if (!project) {
            App.showRulesError("保存项目失败");
            return;
        }
        openRulesPanel("project", { project: project });
    }

    function openRulesPanel(mode, options) {
        options = options || {};
        App.rulesPanelEditingProjectId = options.project ? parsePositiveInt(options.project.id) : null;
        var panel = document.getElementById("rules-create-panel");
        if (panel) panel.hidden = false;
        fillProjectFields(options.project || null);
        setRuleType(options.ruleType || "folder");
        setPanelMode(mode === "project" ? "project" : "rule");
        refreshRulesPanelTargets(options.projectId || App.rulesPanelLastCreatedProjectId || null);
        clearPanelStatus();
    }
    App.openRulesPanel = openRulesPanel;

    function closeRulesPanel() {
        var panel = document.getElementById("rules-create-panel");
        if (panel) panel.hidden = true;
        App.rulesPanelEditingProjectId = null;
        clearPanelStatus();
    }
    App.closeRulesPanel = closeRulesPanel;

    function setPanelMode(mode) {
        App.rulesPanelMode = mode === "project" ? "project" : "rule";
        var projectSection = document.getElementById("rules-panel-project-section");
        var ruleSection = document.getElementById("rules-panel-rule-section");
        var projectTab = document.getElementById("rules-panel-project-tab");
        var ruleTab = document.getElementById("rules-panel-rule-tab");
        var title = document.getElementById("rules-create-panel-title");
        if (projectSection) projectSection.hidden = App.rulesPanelMode !== "project";
        if (ruleSection) ruleSection.hidden = App.rulesPanelMode !== "rule";
        if (projectTab) projectTab.classList.toggle("is-active", App.rulesPanelMode === "project");
        if (ruleTab) ruleTab.classList.toggle("is-active", App.rulesPanelMode === "rule");
        if (title) title.textContent = App.rulesPanelMode === "project"
            ? (App.rulesPanelEditingProjectId ? "编辑项目" : "新建项目")
            : "新建规则";
    }

    function setRuleType(ruleType) {
        App.rulesPanelRuleType = ruleType === "keyword" ? "keyword" : "folder";
        var folderBtn = document.getElementById("rules-panel-folder-type");
        var keywordBtn = document.getElementById("rules-panel-keyword-type");
        var folderRow = document.getElementById("rules-panel-folder-row");
        var recursiveRow = document.getElementById("rules-panel-folder-recursive-row");
        var keywordRow = document.getElementById("rules-panel-keyword-row");
        if (folderBtn) folderBtn.classList.toggle("is-active", App.rulesPanelRuleType === "folder");
        if (keywordBtn) keywordBtn.classList.toggle("is-active", App.rulesPanelRuleType === "keyword");
        if (folderRow) folderRow.hidden = App.rulesPanelRuleType !== "folder";
        if (recursiveRow) recursiveRow.hidden = App.rulesPanelRuleType !== "folder";
        if (keywordRow) keywordRow.hidden = App.rulesPanelRuleType !== "keyword";
    }

    function refreshRulesPanelTargets(preferredProjectId) {
        var select = document.getElementById("rules-panel-target-project");
        if (!select) return;
        var projects = ((App.lastProjectRulesData && App.lastProjectRulesData.projects) || []).filter(function (p) {
            return p && p.enabled && !p.is_system && !p.is_excluded && parsePositiveInt(p.id) > 0;
        });
        select.innerHTML = "";
        for (var i = 0; i < projects.length; i++) {
            var option = document.createElement("option");
            option.value = String(projects[i].id);
            option.textContent = App.safeText(projects[i].name, "未命名项目");
            select.appendChild(option);
        }
        if (preferredProjectId) {
            select.value = String(preferredProjectId);
        }
        select.disabled = !projects.length || App.rulesCreatingPanelRule;
    }
    App.refreshRulesPanelTargets = refreshRulesPanelTargets;

    function savePanelProject() {
        if (App.rulesCreatingPanelProject) return;
        var nameInput = document.getElementById("rules-panel-project-name");
        var descInput = document.getElementById("rules-panel-project-description");
        if (!nameInput) return;
        var name = (nameInput.value || "").trim();
        if (!name) {
            showPanelStatus("请输入项目名称", true);
            return;
        }
        var description = descInput ? (descInput.value || "").trim() : "";
        var language = readPanelLanguage();
        App.rulesCreatingPanelProject = true;
        refreshPanelWriteState();
        clearPanelStatus();
        var method = App.rulesPanelEditingProjectId ? "update_project_for_rules" : "create_project_for_rules";
        var args = App.rulesPanelEditingProjectId
            ? [method, App.rulesPanelEditingProjectId, name, description, language]
            : [method, name, description, language];
        App.callBridge.apply(App, args).then(function (result) {
            if (result && result.ok === false) {
                showPanelStatus(result.error || "保存项目失败", true);
                return;
            }
            var project = (result && result.project) || {};
            App.rulesPanelLastCreatedProjectId = parsePositiveInt(project.id);
            return App.loadProjectRules().then(function () {
                showPanelStatus(App.rulesPanelEditingProjectId ? "项目已保存" : "项目已新增", false);
                if (!App.rulesPanelEditingProjectId) {
                    fillProjectFields(null);
                    setPanelMode("rule");
                    refreshRulesPanelTargets(App.rulesPanelLastCreatedProjectId);
                }
            });
        }).catch(function () {
            showPanelStatus("保存项目失败", true);
        }).then(function () {
            App.rulesCreatingPanelProject = false;
            refreshPanelWriteState();
        });
    }

    function savePanelRule() {
        if (App.rulesCreatingPanelRule) return;
        var projectSelect = document.getElementById("rules-panel-target-project");
        var projectId = projectSelect ? parsePositiveInt(projectSelect.value) : 0;
        if (!projectId) {
            showPanelStatus("请选择有效的项目", true);
            return;
        }
        var isFolder = App.rulesPanelRuleType !== "keyword";
        var targetInput = document.getElementById(isFolder ? "rules-panel-folder-path" : "rules-panel-keyword");
        var target = targetInput ? (targetInput.value || "").trim() : "";
        if (!target) {
            showPanelStatus(isFolder ? "请输入文件夹路径" : "请输入关键词", true);
            return;
        }
        var recursiveEl = document.getElementById("rules-panel-folder-recursive");
        var backfillEl = document.getElementById("rules-panel-backfill");
        App.rulesCreatingPanelRule = true;
        refreshPanelWriteState();
        clearPanelStatus();
        var bridgePromise = isFolder
            ? App.callBridge("create_project_folder_rule", projectId, target, recursiveEl ? !!recursiveEl.checked : true)
            : App.callBridge("create_project_keyword_rule", projectId, target);
        bridgePromise.then(function (result) {
            if (result && result.ok === false) {
                showPanelStatus(result.error || "新增规则失败", true);
                return null;
            }
            var rule = (result && result.rule) || {};
            var ruleKind = isFolder ? "folder" : "keyword";
            var ruleId = parsePositiveInt(rule.id);
            if (backfillEl && backfillEl.checked && ruleId && App.backfillCreatedRule) {
                return App.backfillCreatedRule(ruleKind, ruleId).then(function (ok) {
                    if (!ok) {
                        showPanelStatus("规则已新增，但应用到历史记录失败", true);
                        return null;
                    }
                    showPanelStatus("规则已新增并应用到历史记录", false);
                    return true;
                });
            }
            showPanelStatus("规则已新增", false);
            return true;
        }).then(function () {
            return App.loadProjectRules();
        }).catch(function () {
            showPanelStatus("新增规则失败", true);
        }).then(function () {
            App.rulesCreatingPanelRule = false;
            refreshPanelWriteState();
        });
    }

    function backfillCreatedRule(ruleType, ruleId) {
        return App.callBridge("backfill_project_rule", ruleType, ruleId).then(function (result) {
            return !(result && result.ok === false);
        }).catch(function () {
            return false;
        });
    }
    App.backfillCreatedRule = backfillCreatedRule;

    function renderRulesAdvancedPanel() {
        var details = document.getElementById("rules-advanced");
        var content = document.getElementById("rules-advanced-content");
        if (!details || !content || !details.open) return;
        var advanced = (App.lastProjectRulesData && App.lastProjectRulesData.advanced) || {};
        var enabled = !!advanced.excluded_rules_enabled;
        var rules = advanced.excluded_rules || [];
        var disabled = (!enabled || App.rulesCreatingExcludedRule) ? " disabled" : "";
        var rows = rules.length ? rules.map(function (rule) {
            return App.renderExcludedRuleRow(rule);
        }).join("") : '<div class="rules-project-empty">暂无排除规则</div>';
        content.innerHTML = [
            '<div class="rules-advanced-toggle-row">',
            '  <label><input id="rules-excluded-enabled-toggle" type="checkbox"' + (enabled ? " checked" : "") + (App.rulesExcludedToggleInFlight ? " disabled" : "") + '> 启用排除规则</label>',
            '</div>',
            '<div class="rules-excluded-panel">',
            enabled ? "" : '  <div class="rules-excluded-disabled-hint">请先启用排除规则</div>',
            '  <div class="rules-panel-segment">',
            '    <button class="rules-excluded-type-folder is-active" type="button"' + disabled + '>文件夹规则</button>',
            '    <button class="rules-excluded-type-keyword" type="button"' + disabled + '>关键词规则</button>',
            '  </div>',
            '  <label class="rules-panel-field rules-excluded-folder-row">文件夹路径<input class="rules-excluded-folder-input" type="text" maxlength="512"' + disabled + '></label>',
            '  <label class="rules-panel-check rules-excluded-recursive-row"><input class="rules-excluded-folder-recursive" type="checkbox" checked' + disabled + '> 包含子文件夹</label>',
            '  <label class="rules-panel-field rules-excluded-keyword-row" hidden>关键词<input class="rules-excluded-keyword-input" type="text" maxlength="200"' + disabled + '></label>',
            '  <button class="rules-excluded-rule-submit" type="button"' + disabled + '>新增排除规则</button>',
            '</div>',
            '<div class="rules-row-list">' + rows + '</div>'
        ].join("");
    }
    App.renderRulesAdvancedPanel = renderRulesAdvancedPanel;

    function handleRulesAdvancedClick(event) {
        if (event.target && event.target.closest && event.target.closest(".rules-keyword-delete-button")) {
            App.handleProjectRuleDelete(event);
            return;
        }
        if (event.target && event.target.closest && event.target.closest(".rules-folder-delete-button")) {
            App.handleProjectRuleFolderEvent(event);
            return;
        }
        var toggle = event.target && event.target.closest
            ? event.target.closest("#rules-excluded-enabled-toggle")
            : null;
        if (toggle) {
            setExcludedRulesEnabled(!!toggle.checked);
            return;
        }
        var folderType = event.target && event.target.closest
            ? event.target.closest(".rules-excluded-type-folder")
            : null;
        if (folderType) {
            setExcludedType("folder");
            return;
        }
        var keywordType = event.target && event.target.closest
            ? event.target.closest(".rules-excluded-type-keyword")
            : null;
        if (keywordType) {
            setExcludedType("keyword");
            return;
        }
        var submit = event.target && event.target.closest
            ? event.target.closest(".rules-excluded-rule-submit")
            : null;
        if (submit) createExcludedRule();
    }

    function setExcludedType(type) {
        var content = document.getElementById("rules-advanced-content");
        if (!content) return;
        var isKeyword = type === "keyword";
        var folderBtn = content.querySelector(".rules-excluded-type-folder");
        var keywordBtn = content.querySelector(".rules-excluded-type-keyword");
        var folderRow = content.querySelector(".rules-excluded-folder-row");
        var recursiveRow = content.querySelector(".rules-excluded-recursive-row");
        var keywordRow = content.querySelector(".rules-excluded-keyword-row");
        if (folderBtn) folderBtn.classList.toggle("is-active", !isKeyword);
        if (keywordBtn) keywordBtn.classList.toggle("is-active", isKeyword);
        if (folderRow) folderRow.hidden = isKeyword;
        if (recursiveRow) recursiveRow.hidden = isKeyword;
        if (keywordRow) keywordRow.hidden = !isKeyword;
    }

    function setExcludedRulesEnabled(enabled) {
        if (App.rulesExcludedToggleInFlight) return;
        App.rulesExcludedToggleInFlight = true;
        App.callBridge("set_excluded_rules_enabled", enabled).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "更新排除规则状态失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.showRulesError("排除规则状态已更新");
            });
        }).catch(function () {
            App.showRulesError("更新排除规则状态失败");
        }).then(function () {
            App.rulesExcludedToggleInFlight = false;
        });
    }

    function createExcludedRule() {
        var advanced = (App.lastProjectRulesData && App.lastProjectRulesData.advanced) || {};
        if (!advanced.excluded_rules_enabled) {
            App.showRulesError("请先启用排除规则");
            return;
        }
        if (App.rulesCreatingExcludedRule) return;
        var content = document.getElementById("rules-advanced-content");
        if (!content) return;
        var isKeyword = content.querySelector(".rules-excluded-type-keyword.is-active");
        var input = content.querySelector(isKeyword ? ".rules-excluded-keyword-input" : ".rules-excluded-folder-input");
        var value = input ? (input.value || "").trim() : "";
        if (!value) {
            App.showRulesError(isKeyword ? "请输入关键词" : "请输入文件夹路径");
            return;
        }
        var recursiveEl = content.querySelector(".rules-excluded-folder-recursive");
        App.rulesCreatingExcludedRule = true;
        renderRulesAdvancedPanel();
        var promise = isKeyword
            ? App.callBridge("create_excluded_keyword_rule", value)
            : App.callBridge("create_excluded_folder_rule", value, recursiveEl ? !!recursiveEl.checked : true);
        promise.then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "新增排除规则失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.showRulesError("排除规则已新增");
            });
        }).catch(function () {
            App.showRulesError("新增排除规则失败");
        }).then(function () {
            App.rulesCreatingExcludedRule = false;
            renderRulesAdvancedPanel();
        });
    }

    function fillProjectFields(project) {
        setValue("rules-panel-project-name", project ? App.safeText(project.name, "") : "");
        setValue("rules-panel-project-description", project ? App.safeText(project.description, "") : "");
        setLanguage(project ? App.safeText(project.language, "中文") : "中文");
    }

    function readPanelLanguage() {
        var select = document.getElementById("rules-panel-project-language");
        var other = document.getElementById("rules-panel-project-language-other");
        if (!select) return "中文";
        if (select.value === "其他") {
            return other && other.value.trim() ? other.value.trim() : "中文";
        }
        return select.value || "中文";
    }

    function setLanguage(language) {
        var normalized = language || "中文";
        var select = document.getElementById("rules-panel-project-language");
        var other = document.getElementById("rules-panel-project-language-other");
        if (!select) return;
        if (normalized === "中文" || normalized === "英语" || normalized === "日语") {
            select.value = normalized;
            if (other) other.value = "";
        } else {
            select.value = "其他";
            if (other) other.value = normalized;
        }
        refreshLanguageOther();
    }

    function refreshLanguageOther() {
        var select = document.getElementById("rules-panel-project-language");
        var row = document.getElementById("rules-panel-project-language-other-row");
        if (row && select) row.hidden = select.value !== "其他";
    }

    function refreshPanelWriteState() {
        var projectBusy = !!App.rulesCreatingPanelProject;
        var ruleBusy = !!App.rulesCreatingPanelRule;
        setDisabled("rules-panel-save-project", projectBusy);
        setDisabled("rules-panel-save-rule", ruleBusy);
        setDisabled("rules-panel-project-name", projectBusy);
        setDisabled("rules-panel-project-description", projectBusy);
        setDisabled("rules-panel-project-language", projectBusy);
        setDisabled("rules-panel-project-language-other", projectBusy);
        setDisabled("rules-panel-target-project", ruleBusy);
        setDisabled("rules-panel-folder-path", ruleBusy);
        setDisabled("rules-panel-folder-recursive", ruleBusy);
        setDisabled("rules-panel-keyword", ruleBusy);
        setDisabled("rules-panel-backfill", ruleBusy);
    }

    function showPanelStatus(message, isError) {
        var el = document.getElementById("rules-panel-status");
        if (!el) return;
        if (!message) {
            el.hidden = true;
            el.textContent = "";
            el.className = "rules-panel-status";
            return;
        }
        el.hidden = false;
        el.textContent = message;
        el.className = "rules-panel-status" + (isError ? " is-error" : " is-success");
    }

    function clearPanelStatus() {
        showPanelStatus("", false);
    }

    function findProject(projectId) {
        var projects = (App.lastProjectRulesData && App.lastProjectRulesData.projects) || [];
        for (var i = 0; i < projects.length; i++) {
            if (parsePositiveInt(projects[i] && projects[i].id) === projectId) return projects[i];
        }
        return null;
    }

    function setValue(id, value) {
        var el = document.getElementById(id);
        if (el) el.value = value || "";
    }

    function setDisabled(id, disabled) {
        var el = document.getElementById(id);
        if (el) el.disabled = !!disabled;
    }

    function parsePositiveInt(value) {
        var parsed = parseInt(value, 10);
        return parsed > 0 ? parsed : 0;
    }

})();
