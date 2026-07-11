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
        } else if (button.classList.contains("rules-project-delete-button")) {
            deleteProject(button);
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

    function deleteProject(button) {
        var projectId = parsePositiveInt(button.getAttribute("data-project-id"));
        if (!projectId || !window.confirm("确定删除项目吗？项目将不再显示，历史活动记录不会被删除。")) return;
        App.callBridge("delete_project_for_rules", projectId).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "删除项目失败");
                return;
            }
            return App.loadProjectRules().then(function () { App.showRulesError("项目已删除"); });
        }).catch(function () { App.showRulesError("删除项目失败"); });
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
                    showPanelStatus("规则已新增，并已应用到历史记录。", false);
                    return true;
                });
            }
            showPanelStatus("规则已新增。", false);
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
