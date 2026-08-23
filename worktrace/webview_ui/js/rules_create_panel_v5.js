// WorkTrace WebView frontend - unified Project Rules create/edit panel.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    App.rulesPanelMode = "rule";
    App.rulesPanelRuleType = "folder";
    App.rulesPanelEditingProjectId = null;
    App.rulesPanelLastCreatedProjectId = null;
    App.rulesPanelOriginalLanguage = null;
    App.rulesPanelSessionToken = 0;
    App.rulesPanelTargetMissing = false;
    App.rulesChoosingFolder = false;
    App.rulesCreatingPanelProject = false;
    App.rulesCreatingPanelRule = false;
    App.rulesDeletingProjectId = null;
    var rulesPanelFolderRecursiveDraft = true;

    function initRulesPanelEvents() {
        bindClick("rules-open-create-rule", function () { openRulesPanel("rule", { ruleType: "folder" }); });
        bindClick("rules-open-create-project", function () { openRulesPanel("project", {}); });
        bindClick("rules-create-panel-close", closeRulesPanel);
        bindClick("rules-panel-rule-tab", function () { setPanelMode("rule"); });
        bindClick("rules-panel-project-tab", function () { setPanelMode("project"); });
        bindClick("rules-panel-folder-type", function () { setRuleType("folder"); });
        bindClick("rules-panel-keyword-type", function () { setRuleType("keyword"); });
        bindClick("rules-panel-choose-folder", chooseProjectRuleFolder);
        bindClick("rules-panel-create-project-inline", function () { setPanelMode("project"); });
        bindClick("rules-panel-save-project", savePanelProject);
        bindClick("rules-panel-save-rule", savePanelRule);
        var panel = document.getElementById("rules-create-panel");
        if (panel && panel.getAttribute("data-rules-panel-bound") !== "1") {
            panel.setAttribute("data-rules-panel-bound", "1");
            panel.addEventListener("click", function (event) {
                if (event.target && event.target.getAttribute("data-rules-panel-close") === "1") closeRulesPanel();
            });
        }
        var recursive = document.getElementById("rules-panel-folder-recursive");
        if (recursive && recursive.getAttribute("data-rules-recursive-bound") !== "1") {
            recursive.setAttribute("data-rules-recursive-bound", "1");
            recursive.addEventListener("change", function () {
                rulesPanelFolderRecursiveDraft = !!recursive.checked;
            });
        }
        ["folder", "keyword"].forEach(function (type) {
            var tab = document.getElementById("rules-panel-" + type + "-type");
            if (!tab || tab.getAttribute("data-rules-tab-keyboard-bound") === "1") return;
            tab.setAttribute("data-rules-tab-keyboard-bound", "1");
            tab.addEventListener("keydown", function (event) {
                handleRuleTypeKeydown(event, type);
            });
        });
        var languageSelect = document.getElementById("rules-panel-project-language");
        if (languageSelect) languageSelect.addEventListener("change", refreshLanguageOther);
        App.projectIdentity.bindHost({
            onStateChanged: refreshPanelWriteState,
            onBindingChanged: function () {
                if (App.reloadProjectRules) return App.reloadProjectRules();
                return App.loadProjectRules ? App.loadProjectRules() : Promise.resolve();
            }
        });
        App.projectIdentity.bindEvents();
        App.projectIdentity.syncStatus();
        var sortSelect = document.getElementById("rules-sort-select");
        if (sortSelect && sortSelect.getAttribute("data-rules-sort-bound") !== "1") {
            sortSelect.setAttribute("data-rules-sort-bound", "1");
            sortSelect.addEventListener("change", function () {
                App.rulesSortMode = ["alpha"].indexOf(sortSelect.value) >= 0
                    ? sortSelect.value : "last_used";
                App.rerenderProjectRulesList();
            });
        }
        var searchInput = document.getElementById("rules-search-input");
        if (searchInput && searchInput.getAttribute("data-rules-search-bound") !== "1") {
            searchInput.setAttribute("data-rules-search-bound", "1");
            searchInput.addEventListener("input", App.applyRulesSearch);
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
        if (button.classList.contains("rules-project-toggle")) {
            var card = button.closest(".rules-project-card");
            var rows = card && card.querySelector(".rules-row-list");
            if (rows) {
                rows.hidden = !rows.hidden;
                button.setAttribute("aria-expanded", rows.hidden ? "false" : "true");
                button.classList.toggle("is-expanded", !rows.hidden);
                button.setAttribute("aria-label", (rows.hidden ? "展开" : "收起") + "项目规则");
                button.setAttribute("data-tooltip", rows.hidden ? "展开规则" : "收起规则");
            }
        } else if (button.classList.contains("rules-project-edit-button")) {
            openProjectEdit(button);
        } else if (button.classList.contains("rules-project-add-rule-button")) {
            openRulesPanel("rule", {
                projectId: parsePositiveInt(button.getAttribute("data-project-id")),
                ruleType: "folder",
                trigger: button
            });
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
        openRulesPanel("project", { project: project, trigger: button });
    }

    function setProjectDeleting(projectId) {
        App.rulesDeletingProjectId = parsePositiveInt(projectId) || null;
        var buttons = document.querySelectorAll(".rules-project-delete-button");
        Array.prototype.forEach.call(buttons, function (button) {
            var currentId = parsePositiveInt(button.getAttribute("data-project-id"));
            var busy = currentId === App.rulesDeletingProjectId;
            button.disabled = !!App.rulesDeletingProjectId;
            button.classList.toggle("is-busy", busy);
            button.setAttribute("aria-label", busy ? "正在删除项目" : "删除项目");
            button.setAttribute("data-tooltip", busy ? "正在删除" : "删除项目");
        });
    }
    App.setProjectDeleting = setProjectDeleting;

    function deleteProject(button) {
        if (App.rulesDeletingProjectId) return;
        var projectId = parsePositiveInt(button.getAttribute("data-project-id"));
        var project = findProject(projectId);
        if (!projectId || !App.openDeleteDialog) return;
        App.openDeleteDialog({
            trigger: button,
            title: "删除项目",
            secondTitle: "确认删除项目",
            secondIntro: "即将删除：",
            objectLabel: App.safeText(project && project.name, "当前项目"),
            warning: "此操作不可撤销。",
            twoStep: true,
            confirmLabel: "删除项目"
        }).then(function (confirmed) {
            if (!confirmed || App.rulesDeletingProjectId) return null;
            setProjectDeleting(projectId);
            App.clearRulesError();
            return App.bridge.deleteProjectForRules(projectId);
        }).then(function (result) {
            if (!result) return false;
            if (result && result.ok === false) {
                App.showRulesError(result.error || "删除项目失败");
                return false;
            }
            var reload = App.reloadProjectRules
                ? App.reloadProjectRules()
                : App.loadProjectRules({ forceFresh: true });
            return reload.then(function (readback) {
                if (!readback) {
                    App.showRulesError("项目已删除，但列表刷新失败，请刷新后检查");
                    return false;
                }
                App.clearRulesError();
                if (App.showToast) App.showToast("项目已删除");
                return true;
            });
        }).catch(function () {
            App.showRulesError("删除项目失败");
            return false;
        }).finally(function () {
            setProjectDeleting(null);
        });
    }

    function openRulesPanel(mode, options) {
        options = options || {};
        App.rulesPanelSessionToken += 1;
        App.rulesPanelEditingProjectId = options.project ? parsePositiveInt(options.project.id) : null;
        var panel = document.getElementById("rules-create-panel");
        setValue("rules-panel-folder-path", "");
        setValue("rules-panel-keyword", "");
        rulesPanelFolderRecursiveDraft = true;
        var recursive = document.getElementById("rules-panel-folder-recursive");
        if (recursive) recursive.checked = true;
        var backfill = document.getElementById("rules-panel-backfill");
        if (backfill) backfill.checked = true;
        fillProjectFields(options.project || null);
        App.projectIdentity.syncStatus();
        setRuleType(options.ruleType || "folder");
        setPanelMode(mode === "project" ? "project" : "rule");
        refreshRulesPanelTargets(options.projectId || App.rulesPanelLastCreatedProjectId || null);
        renderRulesPanelProjectContext(options.projectId || 0, {});
        clearPanelStatus();
        if (panel && App.openManagedDrawer) {
            var focus = document.getElementById(mode === "project"
                ? "rules-panel-project-name" : "rules-panel-choose-folder");
            App.openManagedDrawer(
                panel,
                options.trigger || document.activeElement,
                focus,
                { requestClose: closeRulesPanel }
            );
        } else if (panel) panel.hidden = false;
        refreshPanelWriteState();
    }
    App.openRulesPanel = openRulesPanel;

    function collapseExpandedProjectRules() {
        if (typeof document.querySelectorAll !== "function") return;
        var buttons = document.querySelectorAll(".rules-project-toggle");
        Array.prototype.forEach.call(buttons, function (button) {
            var card = button && button.closest ? button.closest(".rules-project-card") : null;
            var rows = card && card.querySelector ? card.querySelector(".rules-row-list") : null;
            if (rows) rows.hidden = true;
            if (!button) return;
            button.setAttribute("aria-expanded", "false");
            button.classList.remove("is-expanded");
            button.setAttribute("aria-label", "展开项目规则");
            button.setAttribute("data-tooltip", "展开规则");
        });
    }
    App.collapseExpandedProjectRules = collapseExpandedProjectRules;

    function resetRulesTransientUi(options) {
        options = options || {};
        App.rulesPanelSessionToken += 1;
        collapseExpandedProjectRules();
        var panel = document.getElementById("rules-create-panel");
        if (panel && App.closeManagedDrawer) {
            App.closeManagedDrawer(panel, {
                restoreFocus: options.restoreFocus !== false
            });
        }
        else if (panel) panel.hidden = true;
        App.rulesPanelEditingProjectId = null;
        App.rulesPanelLastCreatedProjectId = null;
        App.rulesPanelOriginalLanguage = null;
        App.rulesPanelTargetMissing = false;
        fillProjectFields(null);
        setValue("rules-panel-folder-path", "");
        setValue("rules-panel-keyword", "");
        rulesPanelFolderRecursiveDraft = true;
        var recursive = document.getElementById("rules-panel-folder-recursive");
        if (recursive) recursive.checked = true;
        setRuleType("folder");
        var backfill = document.getElementById("rules-panel-backfill");
        if (backfill) backfill.checked = true;
        renderRulesPanelProjectContext(0, {});
        clearPanelStatus();
        setPanelMode("project");
        refreshPanelWriteState();
    }
    App.resetRulesTransientUi = resetRulesTransientUi;

    function closeRulesPanel() {
        App.projectIdentity.reset();
        resetRulesTransientUi({ restoreFocus: true });
    }
    App.closeRulesPanel = closeRulesPanel;

    function setPanelMode(mode) {
        App.rulesPanelMode = mode === "project" ? "project" : "rule";
        var projectSection = document.getElementById("rules-panel-project-section");
        var ruleSection = document.getElementById("rules-panel-rule-section");
        var projectTab = document.getElementById("rules-panel-project-tab");
        var ruleTab = document.getElementById("rules-panel-rule-tab");
        if (projectSection) projectSection.hidden = App.rulesPanelMode !== "project";
        if (ruleSection) ruleSection.hidden = App.rulesPanelMode !== "rule";
        if (projectTab) projectTab.classList.toggle("is-active", App.rulesPanelMode === "project");
        if (ruleTab) ruleTab.classList.toggle("is-active", App.rulesPanelMode === "rule");
        syncProjectPanelPresentation();
    }

    function syncProjectPanelPresentation() {
        var editing = !!App.rulesPanelEditingProjectId;
        var busy = !!App.rulesCreatingPanelProject;
        var title = document.getElementById("rules-create-panel-title");
        var button = document.getElementById("rules-panel-save-project");
        var idleText = editing ? "保存修改" : "新建项目";
        var busyText = editing ? "正在保存…" : "正在新建…";
        if (title) {
            title.textContent = App.rulesPanelMode === "project"
                ? (editing ? "编辑项目" : "新建项目")
                : "新建规则";
        }
        if (button) {
            button.textContent = busy ? busyText : idleText;
            button.setAttribute("aria-label", busy ? busyText : idleText);
            button.disabled = busy;
        }
    }
    App.syncProjectPanelPresentation = syncProjectPanelPresentation;

    function setRuleType(ruleType) {
        App.rulesPanelRuleType = ruleType === "keyword" ? "keyword" : "folder";
        var folderBtn = document.getElementById("rules-panel-folder-type");
        var keywordBtn = document.getElementById("rules-panel-keyword-type");
        var folderGroup = document.getElementById("rules-panel-folder-group");
        var keywordRow = document.getElementById("rules-panel-keyword-row");
        var isFolder = App.rulesPanelRuleType === "folder";
        if (folderBtn) {
            folderBtn.classList.toggle("is-active", isFolder);
            folderBtn.setAttribute("aria-selected", isFolder ? "true" : "false");
            folderBtn.tabIndex = isFolder ? 0 : -1;
        }
        if (keywordBtn) {
            keywordBtn.classList.toggle("is-active", !isFolder);
            keywordBtn.setAttribute("aria-selected", isFolder ? "false" : "true");
            keywordBtn.tabIndex = isFolder ? -1 : 0;
        }
        if (folderGroup) folderGroup.hidden = !isFolder;
        var recursive = document.getElementById("rules-panel-folder-recursive");
        if (recursive) recursive.checked = rulesPanelFolderRecursiveDraft;
        if (keywordRow) keywordRow.hidden = isFolder;
    }
    App.setRulesPanelRuleType = setRuleType;

    function handleRuleTypeKeydown(event, type) {
        var key = event && event.key;
        if (["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(key) < 0) return;
        if (event.preventDefault) event.preventDefault();
        var targetType = type;
        if (key === "Home") targetType = "folder";
        else if (key === "End") targetType = "keyword";
        else targetType = type === "folder" ? "keyword" : "folder";
        setRuleType(targetType);
        var target = document.getElementById("rules-panel-" + targetType + "-type");
        if (target && target.focus) target.focus();
    }
    App.handleRulesRuleTypeKeydown = handleRuleTypeKeydown;

    function renderRulesPanelProjectContext(projectId, options) {
        options = options || {};
        var context = document.getElementById("rules-panel-project-context");
        if (!context) return;
        var project = options.project || findProject(parsePositiveInt(projectId));
        var projectName = project ? App.safeText(project.name, "未命名项目") : "";
        if (!projectName) {
            context.textContent = "";
            context.classList.remove("is-success");
            return;
        }
        context.textContent = options.isSuccess
            ? "项目已新增"
            : "为项目“" + projectName + "”添加规则。";
        context.classList.toggle("is-success", !!options.isSuccess);
    }
    App.renderRulesPanelProjectContext = renderRulesPanelProjectContext;

    function isCurrentRulesPanelSession(sessionToken) {
        return sessionToken === App.rulesPanelSessionToken;
    }

    function chooseProjectRuleFolder() {
        if (App.rulesChoosingFolder || App.rulesCreatingPanelRule) return;
        var sessionToken = App.rulesPanelSessionToken;
        App.rulesChoosingFolder = true;
        if (isCurrentRulesPanelSession(sessionToken)) clearPanelStatus();
        refreshPanelWriteState();
        App.bridge.chooseProjectRuleFolder().then(function (result) {
            if (!isCurrentRulesPanelSession(sessionToken)) return;
            if (!result || result.ok === false) {
                showPanelStatus("选择文件夹失败", true);
                return;
            }
            if (result.cancelled) return;
            setValue("rules-panel-folder-path", result.folder_path || "");
        }).catch(function () {
            if (isCurrentRulesPanelSession(sessionToken)) {
                showPanelStatus("选择文件夹失败", true);
            }
        }).then(function () {
            App.rulesChoosingFolder = false;
            refreshPanelWriteState();
        });
    }
    App.chooseProjectRuleFolder = chooseProjectRuleFolder;

    function refreshRulesPanelTargets(preferredProjectId) {
        var select = document.getElementById("rules-panel-target-project");
        if (!select) return;
        var currentProjectId = parsePositiveInt(select.value);
        var requestedProjectId = parsePositiveInt(preferredProjectId) || currentProjectId;
        var projects = ((App.lastProjectRulesData && App.lastProjectRulesData.projects) || []).filter(function (p) {
            return p && !p.is_system && !p.is_excluded && parsePositiveInt(p.id) > 0;
        });
        select.innerHTML = "";
        for (var i = 0; i < projects.length; i++) {
            var option = document.createElement("option");
            option.value = String(projects[i].id);
            option.textContent = App.safeText(projects[i].name, "未命名项目");
            select.appendChild(option);
        }
        App.rulesPanelTargetMissing = false;
        if (requestedProjectId) {
            select.value = String(requestedProjectId);
            if (parsePositiveInt(select.value) !== requestedProjectId) {
                var missing = document.createElement("option");
                missing.value = "";
                missing.textContent = "项目已不存在";
                missing.disabled = true;
                missing.selected = true;
                select.appendChild(missing);
                select.value = "";
                App.rulesPanelTargetMissing = true;
                var panel = document.getElementById("rules-create-panel");
                if (panel && !panel.hidden && App.rulesPanelMode === "rule") {
                    showPanelStatus("所选项目已不存在，请重新选择", true);
                }
            }
        }
        select.disabled = !projects.length || App.rulesCreatingPanelRule || App.rulesPanelTargetMissing;
        refreshPanelWriteState();
    }
    App.refreshRulesPanelTargets = refreshRulesPanelTargets;

    function savePanelProject() {
        if (App.rulesCreatingPanelProject) return;
        var sessionToken = App.rulesPanelSessionToken;
        var editingProjectId = App.rulesPanelEditingProjectId;
        var wasEditing = !!editingProjectId;
        var nameInput = document.getElementById("rules-panel-project-name");
        var descInput = document.getElementById("rules-panel-project-description");
        if (!nameInput) return;
        var identityPayload = App.projectIdentity.buildSavePayload(
            nameInput.value, wasEditing
        );
        if (!identityPayload.ok) {
            showPanelStatus(identityPayload.error, true);
            return;
        }
        var name = identityPayload.name;
        var description = descInput ? (descInput.value || "").trim() : "";
        var language = wasEditing
            ? (App.rulesPanelOriginalLanguage || "中文")
            : readPanelLanguage();
        App.rulesCreatingPanelProject = true;
        refreshPanelWriteState();
        clearPanelStatus();
        var request = wasEditing
            ? App.bridge.updateProjectForRules(
                editingProjectId, name, description, language,
                identityPayload.proof
            )
            : App.bridge.createProjectForRules(
                name, description, language, identityPayload.proof
            );
        request.then(function (result) {
            if (result && result.ok === false) {
                if (isCurrentRulesPanelSession(sessionToken)) {
                    showPanelStatus(result.error || "保存项目失败", true);
                }
                return null;
            }
            var project = (result && result.project) || {};
            var projectId = parsePositiveInt(project.id);
            if (!projectId) {
                if (isCurrentRulesPanelSession(sessionToken)) {
                    showPanelStatus("项目写入结果无法确认，请刷新后检查", true);
                }
                return null;
            }
            var reload = App.reloadProjectRules
                ? App.reloadProjectRules()
                : App.loadProjectRules({ forceFresh: true });
            return reload.then(function (readback) {
                if (!isCurrentRulesPanelSession(sessionToken)) return;
                var projects = (readback && readback.projects) || [];
                var saved = projects.find(function (candidate) {
                    return parsePositiveInt(candidate && candidate.id) === projectId;
                });
                var readbackVerified = App.projectIdentity.verifyPersistence(
                    result, saved, project
                );
                if (!readbackVerified) {
                    showPanelStatus("项目写入结果无法确认，请刷新后检查", true);
                    return;
                }
                if (wasEditing) {
                    resetRulesTransientUi({ restoreFocus: true });
                    if (App.showToast) App.showToast("项目已保存");
                    return;
                }
                App.rulesPanelLastCreatedProjectId = projectId;
                fillProjectFields(null);
                setPanelMode("rule");
                refreshRulesPanelTargets(App.rulesPanelLastCreatedProjectId);
                renderRulesPanelProjectContext(
                    App.rulesPanelLastCreatedProjectId,
                    { isSuccess: true, project: project }
                );
            });
        }).catch(function () {
            if (isCurrentRulesPanelSession(sessionToken)) {
                showPanelStatus("保存项目失败", true);
            }
        }).then(function () {
            App.rulesCreatingPanelProject = false;
            refreshPanelWriteState();
        });
    }
    App.savePanelProject = savePanelProject;

    function savePanelRule() {
        if (App.rulesCreatingPanelRule) return;
        var sessionToken = App.rulesPanelSessionToken;
        var projectSelect = document.getElementById("rules-panel-target-project");
        var projectId = projectSelect ? parsePositiveInt(projectSelect.value) : 0;
        if (!projectId || App.rulesPanelTargetMissing) {
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
        var applyToHistory = !!(backfillEl && backfillEl.checked);
        App.rulesCreatingPanelRule = true;
        refreshPanelWriteState();
        clearPanelStatus();
        var request = isFolder
            ? App.bridge.createProjectFolderRule(projectId, target, recursiveEl ? !!recursiveEl.checked : true)
            : App.bridge.createProjectKeywordRule(projectId, target);
        request.then(function (result) {
            if (result && result.ok === false) {
                if (isCurrentRulesPanelSession(sessionToken)) {
                    showPanelStatus(result.error || "新增规则失败", true);
                }
                return null;
            }
            var rule = (result && result.rule) || {};
            var ruleKind = isFolder ? "folder" : "keyword";
            var ruleId = parsePositiveInt(rule.id);
            var outcome = {
                created: true,
                backfillFailed: false,
                successMessage: "规则已新增"
            };
            if (!applyToHistory) return outcome;
            if (!ruleId || !App.backfillCreatedRule) {
                outcome.backfillFailed = true;
                return outcome;
            }
            return App.backfillCreatedRule(ruleKind, ruleId).then(function (ok) {
                outcome.backfillFailed = !ok;
                if (ok) outcome.successMessage = "规则已新增，并已应用到历史记录";
                return outcome;
            }).catch(function () {
                outcome.backfillFailed = true;
                return outcome;
            });
        }).then(function (outcome) {
            if (!outcome || outcome.created !== true) return false;
            var reload = App.reloadProjectRules
                ? App.reloadProjectRules()
                : App.loadProjectRules({ forceFresh: true });
            return reload.then(function (readback) {
                var currentSession = isCurrentRulesPanelSession(sessionToken);
                if (currentSession) closeRulesPanel();
                if (!readback) {
                    App.showRulesError("规则已新增，但列表刷新失败，请刷新后检查");
                    return false;
                }
                if (outcome.backfillFailed) {
                    App.showRulesError("规则已新增，但应用到历史记录失败");
                    if (App.showToast) App.showToast("规则已新增");
                    return false;
                }
                App.clearRulesError();
                if (App.showToast) App.showToast(outcome.successMessage);
                return true;
            });
        }).catch(function () {
            if (isCurrentRulesPanelSession(sessionToken)) {
                showPanelStatus("新增规则失败", true);
            }
            return false;
        }).then(function (ok) {
            App.rulesCreatingPanelRule = false;
            refreshPanelWriteState();
            return ok;
        });
    }

    function fillProjectFields(project) {
        setValue("rules-panel-project-name", project ? App.safeText(project.name, "") : "");
        setValue("rules-panel-project-description", project ? App.safeText(project.description, "") : "");
        App.projectIdentity.prepareEditor(project);
        if (project && App.rulesPanelEditingProjectId) {
            App.rulesPanelOriginalLanguage = App.safeText(project.language, "中文");
        } else {
            App.rulesPanelOriginalLanguage = null;
        }
        setLanguage(project ? App.safeText(project.language, "中文") : "中文");
    }

    function readPanelLanguage() {
        var select = document.getElementById("rules-panel-project-language");
        var other = document.getElementById("rules-panel-project-language-other");
        if (!select) return "中文";
        if (select.value === "其他") return other && other.value.trim() ? other.value.trim() : "中文";
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
        syncProjectPanelPresentation();
        setDisabled("rules-panel-save-rule", ruleBusy || App.rulesPanelTargetMissing);
        setDisabled("rules-panel-project-name", projectBusy);
        var identityControls = App.projectIdentity.updateControls(projectBusy);
        var saveProject = document.getElementById("rules-panel-save-project");
        if (saveProject) {
            var nameInput = document.getElementById("rules-panel-project-name");
            var hasName = App.projectIdentity.enabled()
                ? identityControls.hasName
                : !!String(nameInput && nameInput.value || "").trim();
            saveProject.disabled = projectBusy || identityControls.pending || !hasName;
        }
        setDisabled("rules-panel-project-description", projectBusy);
        setDisabled("rules-panel-project-language", projectBusy);
        setDisabled("rules-panel-project-language-other", projectBusy);
        setDisabled("rules-panel-target-project", ruleBusy || App.rulesPanelTargetMissing);
        setDisabled("rules-panel-folder-path", ruleBusy);
        setDisabled("rules-panel-choose-folder", ruleBusy || App.rulesChoosingFolder);
        setDisabled("rules-panel-folder-recursive", ruleBusy);
        setDisabled("rules-panel-keyword", ruleBusy);
        setDisabled("rules-panel-backfill", ruleBusy);
    }
    App.refreshRulesPanelWriteState = refreshPanelWriteState;

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

    function clearPanelStatus() { showPanelStatus("", false); }

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
