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
    App.rulesChoosingFolder = false;
    App.rulesCreatingPanelProject = false;
    App.rulesCreatingPanelRule = false;
    App.rulesFDWorkSelectionToken = null;
    App.rulesFDWorkSelectedLabel = "";
    App.rulesFDWorkOriginalName = "";
    App.rulesFDWorkOriginalBound = false;
    App.rulesFDWorkPickerRequestId = null;
    App.rulesFDWorkPickerDrawerSession = null;
    App.rulesFDWorkPickerPending = false;
    App.rulesFDWorkPickerCounter = 0;

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
        var languageSelect = document.getElementById("rules-panel-project-language");
        if (languageSelect) languageSelect.addEventListener("change", refreshLanguageOther);
        initFDWorkCaseEvents();
        syncFDWorkCasePickerStatus();
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

    function deleteProject(button) {
        var projectId = parsePositiveInt(button.getAttribute("data-project-id"));
        var project = findProject(projectId);
        if (!projectId || !App.openDeleteDialog) return;
        App.openDeleteDialog({
            trigger: button,
            title: "删除项目",
            objectLabel: App.safeText(project && project.name, "当前项目"),
            warning: "项目会从项目规则中移除，既有活动事实不会被删除。",
            twoStep: false,
            confirmLabel: "删除项目"
        }).then(function (confirmed) {
            if (!confirmed) return null;
            return App.bridge.deleteProjectForRules(projectId);
        }).then(function (result) {
            if (!result) return;
            if (result && result.ok === false) {
                App.showRulesError(result.error || "删除项目失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.clearRulesError();
                if (App.showToast) App.showToast("项目已删除");
            });
        }).catch(function () { App.showRulesError("删除项目失败"); });
    }

    function openRulesPanel(mode, options) {
        options = options || {};
        App.rulesPanelSessionToken += 1;
        App.rulesPanelEditingProjectId = options.project ? parsePositiveInt(options.project.id) : null;
        var panel = document.getElementById("rules-create-panel");
        setValue("rules-panel-folder-path", "");
        setValue("rules-panel-keyword", "");
        var backfill = document.getElementById("rules-panel-backfill");
        if (backfill) backfill.checked = true;
        fillProjectFields(options.project || null);
        syncFDWorkCasePickerStatus();
        setRuleType(options.ruleType || "folder");
        setPanelMode(mode === "project" ? "project" : "rule");
        refreshRulesPanelTargets(options.projectId || App.rulesPanelLastCreatedProjectId || null);
        renderRulesPanelProjectContext(options.projectId || 0, {});
        clearPanelStatus();
        if (panel && App.openManagedDrawer) {
            var fdWorkEnabled = (App.fdWorkStatus || {}).enabled === true;
            var focus = document.getElementById(mode === "project"
                ? (fdWorkEnabled ? "rules-panel-fd-work-pick" : "rules-panel-project-name")
                : "rules-panel-choose-folder");
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

    function resetRulesTransientUi(options) {
        options = options || {};
        App.rulesPanelSessionToken += 1;
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
        fillProjectFields(null);
        setValue("rules-panel-folder-path", "");
        setValue("rules-panel-keyword", "");
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
        resetFDWorkCasePicker();
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
        if (recursive) recursive.checked = true;
        if (keywordRow) keywordRow.hidden = isFolder;
    }
    App.setRulesPanelRuleType = setRuleType;

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
            ? "项目已新增：“" + projectName + "”。请继续添加自动归类规则。"
            : "为项目“" + projectName + "”添加规则。";
        context.classList.toggle("is-success", !!options.isSuccess);
    }
    App.renderRulesPanelProjectContext = renderRulesPanelProjectContext;

    function initFDWorkCaseEvents() {
        bindClick("rules-panel-fd-work-pick", openFDWorkCasePicker);
        bindClick("rules-panel-fd-work-clear", clearFDWorkCaseSelection);
    }

    function openFDWorkCasePicker() {
        if (App.rulesFDWorkPickerPending || App.rulesCreatingPanelProject) return;
        var status = App.fdWorkStatus || {};
        if (status.enabled !== true) return;
        var drawerSession = App.rulesPanelSessionToken;
        var requestId = "rules-picker-" + drawerSession + "-" + (++App.rulesFDWorkPickerCounter);
        App.rulesFDWorkPickerPending = true;
        App.rulesFDWorkPickerRequestId = requestId;
        App.rulesFDWorkPickerDrawerSession = drawerSession;
        showFDWorkCaseStatus("正在打开 FD Work 案件选择器……", false);
        refreshPanelWriteState();
        App.bridge.openFDWorkCasePicker(requestId).then(function (result) {
            if (!isCurrentPickerRequest(requestId, drawerSession)) return;
            if (!result || result.ok === false) {
                App.rulesFDWorkPickerPending = false;
                App.rulesFDWorkPickerRequestId = null;
                showFDWorkCaseStatus(result && result.message || "打开案件选择器失败", true);
                refreshPanelWriteState();
                return;
            }
            showFDWorkCaseStatus(
                result.operation_status === "authentication_required"
                    ? "请在 FD Work 窗口完成登录并选择案件"
                    : "请在 FD Work 原生案件框中选择并确认",
                false
            );
        }).catch(function () {
            if (!isCurrentPickerRequest(requestId, drawerSession)) return;
            App.rulesFDWorkPickerPending = false;
            App.rulesFDWorkPickerRequestId = null;
            showFDWorkCaseStatus("打开案件选择器失败", true);
            refreshPanelWriteState();
        });
    }

    function isCurrentPickerRequest(requestId, drawerSession) {
        return requestId === App.rulesFDWorkPickerRequestId
            && drawerSession === App.rulesFDWorkPickerDrawerSession
            && drawerSession === App.rulesPanelSessionToken;
    }

    function clearFDWorkCaseSelection() {
        if (App.rulesFDWorkPickerPending) return;
        if (App.rulesFDWorkOriginalBound && App.rulesPanelEditingProjectId) {
            var drawerSession = App.rulesPanelSessionToken;
            App.rulesFDWorkPickerPending = true;
            refreshPanelWriteState();
            App.bridge.clearFDWorkBindingForRules(
                App.rulesPanelEditingProjectId
            ).then(function (result) {
                if (!isCurrentRulesPanelSession(drawerSession)) return;
                App.rulesFDWorkPickerPending = false;
                if (!result || result.ok === false) {
                    showFDWorkCaseStatus(result && result.error || "取消关联失败", true);
                    refreshPanelWriteState();
                    return;
                }
                App.rulesFDWorkOriginalBound = false;
                showFDWorkCaseStatus("已取消 FD Work 关联", false);
                if (App.loadProjectRules) App.loadProjectRules();
                refreshPanelWriteState();
            }).catch(function () {
                if (!isCurrentRulesPanelSession(drawerSession)) return;
                App.rulesFDWorkPickerPending = false;
                showFDWorkCaseStatus("取消关联失败", true);
                refreshPanelWriteState();
            });
            return;
        }
        App.rulesFDWorkSelectionToken = null;
        App.rulesFDWorkSelectedLabel = "";
        var selected = document.getElementById("rules-panel-fd-work-selected-label");
        if (selected) selected.value = "";
        showFDWorkCaseStatus("尚未选择 FD Work 案件", false);
        refreshPanelWriteState();
    }

    function showFDWorkCaseStatus(message, isError) {
        var target = document.getElementById("rules-panel-fd-work-status");
        if (!target) return;
        target.hidden = !message;
        target.textContent = message || "";
        target.className = "inline-status" + (isError ? " edit-status-error" : "");
    }

    function resetFDWorkCasePicker() {
        App.rulesFDWorkSelectionToken = null;
        App.rulesFDWorkSelectedLabel = "";
        App.rulesFDWorkPickerRequestId = null;
        App.rulesFDWorkPickerDrawerSession = null;
        App.rulesFDWorkPickerPending = false;
        var selected = document.getElementById("rules-panel-fd-work-selected-label");
        if (selected) selected.value = "";
        showFDWorkCaseStatus("", false);
    }
    App.resetFDWorkCasePicker = resetFDWorkCasePicker;

    function syncFDWorkCasePickerStatus() {
        var status = App.fdWorkStatus || {};
        var enabled = status.enabled === true;
        var label = document.getElementById("rules-panel-project-name-label");
        var help = document.getElementById("rules-panel-fd-work-help");
        var input = document.getElementById("rules-panel-project-name");
        if (label) label.textContent = enabled ? "FD Work 案件" : "项目名称";
        if (help) help.hidden = !enabled;
        if (input) {
            input.hidden = enabled;
            input.readOnly = enabled;
        }
        var picker = document.getElementById("rules-panel-fd-work-picker");
        if (picker) picker.hidden = !enabled;
        if (!enabled) resetFDWorkCasePicker();
        refreshPanelWriteState();
    }
    App.syncFDWorkCasePickerStatus = syncFDWorkCasePickerStatus;

    function receiveFDWorkCasePickerResult(result) {
        if (!result || typeof result !== "object") return false;
        var requestId = result.request_id;
        var drawerSession = App.rulesFDWorkPickerDrawerSession;
        if (!isCurrentPickerRequest(requestId, drawerSession)) return false;
        App.rulesFDWorkPickerPending = false;
        App.rulesFDWorkPickerRequestId = null;
        if (result.ok !== true) {
            showFDWorkCaseStatus(
                result.error === "picker_canceled" ? "案件选择已取消" : "案件选择已失效",
                result.error !== "picker_canceled"
            );
            refreshPanelWriteState();
            return true;
        }
        if (typeof result.selected_label !== "string"
            || !result.selected_label
            || typeof result.selection_token !== "string"
            || !result.selection_token) {
            showFDWorkCaseStatus("案件选择结果无效", true);
            refreshPanelWriteState();
            return false;
        }
        App.rulesFDWorkSelectedLabel = result.selected_label;
        App.rulesFDWorkSelectionToken = result.selection_token;
        var selected = document.getElementById("rules-panel-fd-work-selected-label");
        if (selected) selected.value = result.selected_label;
        showFDWorkCaseStatus("已选择 FD Work 案件", false);
        refreshPanelWriteState();
        return true;
    }
    App.receiveFDWorkCasePickerResult = receiveFDWorkCasePickerResult;

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
        if (preferredProjectId) select.value = String(preferredProjectId);
        select.disabled = !projects.length || App.rulesCreatingPanelRule;
    }
    App.refreshRulesPanelTargets = refreshRulesPanelTargets;

    function savePanelProject() {
        if (App.rulesCreatingPanelProject) return;
        var sessionToken = App.rulesPanelSessionToken;
        var editingProjectId = App.rulesPanelEditingProjectId;
        var wasEditing = !!editingProjectId;
        var nameInput = document.getElementById("rules-panel-project-name");
        var selectedInput = document.getElementById("rules-panel-fd-work-selected-label");
        var descInput = document.getElementById("rules-panel-project-description");
        if (!nameInput) return;
        var fdWorkEnabled = (App.fdWorkStatus || {}).enabled === true;
        var selectedLabel = String(App.rulesFDWorkSelectedLabel || "").trim();
        var displayedLabel = String(selectedInput && selectedInput.value || "").trim();
        if (fdWorkEnabled && App.rulesFDWorkSelectionToken && displayedLabel !== selectedLabel) {
            showPanelStatus("案件选择结果已被修改，请重新选择", true);
            return;
        }
        if (fdWorkEnabled && !wasEditing && !App.rulesFDWorkSelectionToken) {
            showPanelStatus("请先选择 FD Work 案件", true);
            return;
        }
        var name = fdWorkEnabled
            ? (App.rulesFDWorkSelectionToken ? selectedLabel : App.rulesFDWorkOriginalName)
            : (nameInput.value || "").trim();
        if (!name) {
            showPanelStatus(fdWorkEnabled ? "请先选择 FD Work 案件" : "请输入项目名称", true);
            return;
        }
        var description = descInput ? (descInput.value || "").trim() : "";
        // When editing an existing project, pass back the original language
        // verbatim instead of reading from the hidden select (which only
        // offers ``中文`` and would overwrite non-中文 projects). New
        // projects default to ``中文`` via readPanelLanguage().
        var language = wasEditing
            ? (App.rulesPanelOriginalLanguage || "中文")
            : readPanelLanguage();
        App.rulesCreatingPanelProject = true;
        refreshPanelWriteState();
        clearPanelStatus();
        var request = wasEditing
            ? App.bridge.updateProjectForRules(
                editingProjectId, name, description, language,
                App.rulesFDWorkSelectionToken
            )
            : App.bridge.createProjectForRules(
                name, description, language, App.rulesFDWorkSelectionToken
            );
        request.then(function (result) {
            if (result && result.ok === false) {
                if (isCurrentRulesPanelSession(sessionToken)) {
                    showPanelStatus(result.error || "保存项目失败", true);
                }
                return null;
            }
            var project = (result && result.project) || {};
            var binding = (result && result.fd_work_binding) || { bound: false };
            var bindingWarning = String(binding.warning || "");
            if (binding.warning && isCurrentRulesPanelSession(sessionToken)) {
                showPanelStatus(bindingWarning, true);
            }
            return App.loadProjectRules().then(function () {
                if (!isCurrentRulesPanelSession(sessionToken)) return;
                if (wasEditing) {
                    resetRulesTransientUi({ restoreFocus: true });
                    if (App.showToast) App.showToast(bindingWarning || "项目已保存");
                    return;
                }
                App.rulesPanelLastCreatedProjectId = parsePositiveInt(project.id);
                fillProjectFields(null);
                setPanelMode("rule");
                refreshRulesPanelTargets(App.rulesPanelLastCreatedProjectId);
                renderRulesPanelProjectContext(
                    App.rulesPanelLastCreatedProjectId,
                    { isSuccess: true, project: project }
                );
                if (bindingWarning) showPanelStatus(bindingWarning, true);
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
            if (applyToHistory && ruleId && App.backfillCreatedRule) {
                return App.backfillCreatedRule(ruleKind, ruleId).then(function (ok) {
                    if (!ok && isCurrentRulesPanelSession(sessionToken)) {
                        showPanelStatus("规则已新增，但应用到历史记录失败", true);
                        return null;
                    }
                    if (isCurrentRulesPanelSession(sessionToken)) {
                        showPanelStatus("规则已新增，并已应用到历史记录。", false);
                    }
                    return true;
                });
            }
            if (isCurrentRulesPanelSession(sessionToken)) {
                showPanelStatus("规则已新增。", false);
            }
            return true;
        }).then(function () {
            return App.loadProjectRules();
        }).catch(function () {
            if (isCurrentRulesPanelSession(sessionToken)) {
                showPanelStatus("新增规则失败", true);
            }
        }).then(function () {
            App.rulesCreatingPanelRule = false;
            refreshPanelWriteState();
        });
    }

    function fillProjectFields(project) {
        setValue("rules-panel-project-name", project ? App.safeText(project.name, "") : "");
        setValue("rules-panel-project-description", project ? App.safeText(project.description, "") : "");
        resetFDWorkCasePicker();
        App.rulesFDWorkOriginalName = project ? App.safeText(project.name, "") : "";
        App.rulesFDWorkOriginalBound = !!(project && project.fd_work_bound === true);
        setValue(
            "rules-panel-fd-work-selected-label",
            project ? App.rulesFDWorkOriginalName : ""
        );
        if (project && App.rulesFDWorkOriginalBound) {
            showFDWorkCaseStatus("已关联 FD Work", false);
        } else if (project) {
            showFDWorkCaseStatus("历史本地项目：名称不变时可继续维护其他信息", false);
        }
        var pick = document.getElementById("rules-panel-fd-work-pick");
        if (pick) pick.textContent = project ? "更换案件" : "选择案件";
        // Preserve the original language when editing. The hidden select
        // only offers ``中文``; reading from it on save would overwrite
        // non-中文 projects. We store the original language and pass it
        // back verbatim on update. New projects default to ``中文``.
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
        var fdWorkEnabled = (App.fdWorkStatus || {}).enabled === true;
        syncProjectPanelPresentation();
        setDisabled("rules-panel-save-rule", ruleBusy);
        setDisabled("rules-panel-project-name", projectBusy);
        setDisabled(
            "rules-panel-fd-work-pick",
            projectBusy || App.rulesFDWorkPickerPending
        );
        setDisabled(
            "rules-panel-fd-work-clear",
            projectBusy || App.rulesFDWorkPickerPending
        );
        var pick = document.getElementById("rules-panel-fd-work-pick");
        if (pick) {
            pick.textContent = App.rulesFDWorkPickerPending
                ? "正在打开……"
                : (App.rulesFDWorkOriginalName || App.rulesFDWorkSelectedLabel ? "更换案件" : "选择案件");
        }
        var clear = document.getElementById("rules-panel-fd-work-clear");
        if (clear) {
            clear.hidden = !(
                App.rulesFDWorkSelectionToken || App.rulesFDWorkOriginalBound
            );
        }
        var saveProject = document.getElementById("rules-panel-save-project");
        if (saveProject) {
            var nameInput = document.getElementById("rules-panel-project-name");
            var hasName = fdWorkEnabled
                ? !!(
                    App.rulesFDWorkSelectionToken
                    || (App.rulesPanelEditingProjectId && App.rulesFDWorkOriginalName)
                )
                : !!String(nameInput && nameInput.value || "").trim();
            saveProject.disabled = projectBusy || App.rulesFDWorkPickerPending || !hasName;
        }
        setDisabled("rules-panel-project-description", projectBusy);
        setDisabled("rules-panel-project-language", projectBusy);
        setDisabled("rules-panel-project-language-other", projectBusy);
        setDisabled("rules-panel-target-project", ruleBusy);
        setDisabled("rules-panel-folder-path", ruleBusy);
        setDisabled("rules-panel-choose-folder", ruleBusy || App.rulesChoosingFolder);
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
