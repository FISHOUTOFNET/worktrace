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
    App.rulesFDWorkRequestToken = 0;
    App.rulesFDWorkSearchOptions = [];
    App.rulesFDWorkActiveOption = -1;
    App.rulesFDWorkLastQuery = "";
    App.rulesFDWorkLoginRetryPending = false;
    var rulesFDWorkDebounceTimer = null;

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
        syncFDWorkCaseSearchStatus();
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
        syncFDWorkCaseSearchStatus();
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
        resetFDWorkCaseSearch();
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

    function fdWorkCaseSelectionRequired() {
        var status = App.fdWorkStatus || {};
        if (status.enabled !== true) return false;
        var input = document.getElementById("rules-panel-project-name");
        var value = String(input && input.value || "").trim();
        return !App.rulesPanelEditingProjectId || value !== App.rulesFDWorkOriginalName;
    }

    function initFDWorkCaseEvents() {
        var input = document.getElementById("rules-panel-project-name");
        var listbox = document.getElementById("rules-panel-fd-work-options");
        var login = document.getElementById("rules-panel-fd-work-login");
        if (input && input.getAttribute("data-fd-work-bound") !== "1") {
            input.setAttribute("data-fd-work-bound", "1");
            input.addEventListener("input", handleFDWorkCaseInput);
            input.addEventListener("keydown", handleFDWorkCaseKeydown);
            input.addEventListener("blur", closeFDWorkCaseOptions);
        }
        if (listbox && listbox.getAttribute("data-fd-work-bound") !== "1") {
            listbox.setAttribute("data-fd-work-bound", "1");
            listbox.addEventListener("mousedown", function (event) { event.preventDefault(); });
            listbox.addEventListener("click", function (event) {
                var option = event.target && event.target.closest
                    ? event.target.closest("[role='option']") : null;
                var index = option ? parseInt(option.getAttribute("data-option-index"), 10) : -1;
                if (index >= 0) selectFDWorkCaseOption(index);
            });
        }
        if (login && login.getAttribute("data-fd-work-bound") !== "1") {
            login.setAttribute("data-fd-work-bound", "1");
            login.addEventListener("click", function () {
                App.rulesFDWorkLoginRetryPending = true;
                App.bridge.showFDWorkLogin().catch(function () {
                    showFDWorkCaseStatus("打开 FD Work 登录页失败", true);
                });
            });
        }
        if (!App.rulesFDWorkOutsideBound) {
            App.rulesFDWorkOutsideBound = true;
            document.addEventListener("mousedown", function (event) {
                var inputNode = document.getElementById("rules-panel-project-name");
                var popup = document.getElementById("rules-panel-fd-work-options");
                if (event.target !== inputNode && !(popup && popup.contains(event.target))) {
                    closeFDWorkCaseOptions();
                }
            });
        }
    }

    function handleFDWorkCaseInput() {
        App.rulesFDWorkSelectionToken = null;
        App.rulesFDWorkSelectedLabel = "";
        App.rulesFDWorkLoginRetryPending = false;
        closeFDWorkCaseOptions();
        if (rulesFDWorkDebounceTimer) clearTimeout(rulesFDWorkDebounceTimer);
        rulesFDWorkDebounceTimer = null;
        refreshPanelWriteState();
        var status = App.fdWorkStatus || {};
        if (status.enabled !== true) {
            showFDWorkCaseStatus("", false);
            return;
        }
        var query = String(this.value || "").trim();
        App.rulesFDWorkLastQuery = query;
        if (query.length < App.FD_WORK_QUERY_MIN_LENGTH) {
            showFDWorkCaseStatus("至少输入 2 个字符后搜索", false);
            return;
        }
        if (query.length > App.FD_WORK_QUERY_MAX_LENGTH) {
            showFDWorkCaseStatus("案件关键词过长", true);
            return;
        }
        var session = App.rulesPanelSessionToken;
        rulesFDWorkDebounceTimer = setTimeout(function () {
            rulesFDWorkDebounceTimer = null;
            searchFDWorkCases(query, session);
        }, 300);
    }

    function searchFDWorkCases(query, sessionToken) {
        if (!isCurrentRulesPanelSession(sessionToken)) return;
        var status = App.fdWorkStatus || {};
        if (status.login_required === true) {
            App.rulesFDWorkLoginRetryPending = true;
            showFDWorkCaseStatus("请先登录 FD Work", true);
            syncFDWorkCaseSearchStatus();
            return;
        }
        var requestToken = ++App.rulesFDWorkRequestToken;
        var requestId = "rules-" + sessionToken + "-" + requestToken;
        showFDWorkCaseStatus("正在搜索…", false);
        App.bridge.searchFDWorkCases(query, requestId).then(function (result) {
            if (!isCurrentRulesPanelSession(sessionToken)
                || requestToken !== App.rulesFDWorkRequestToken
                || query !== App.rulesFDWorkLastQuery) return;
            if (!result || result.ok === false) {
                showFDWorkCaseStatus(result && result.message || "搜索 FD Work 案件失败", true);
                return;
            }
            App.rulesFDWorkSearchOptions = Array.isArray(result.options)
                ? result.options.filter(function (item) {
                    return item && typeof item.label === "string"
                        && item.label.length <= App.FD_WORK_CASE_LABEL_MAX_LENGTH
                        && typeof item.selection_token === "string";
                }).slice(0, 20)
                : [];
            App.rulesFDWorkActiveOption = App.rulesFDWorkSearchOptions.length ? 0 : -1;
            renderFDWorkCaseOptions();
            showFDWorkCaseStatus(
                App.rulesFDWorkSearchOptions.length ? "请选择一个 FD Work 案件" : "暂无结果",
                false
            );
        }).catch(function () {
            if (isCurrentRulesPanelSession(sessionToken)
                && requestToken === App.rulesFDWorkRequestToken) {
                showFDWorkCaseStatus("搜索 FD Work 案件失败", true);
            }
        });
    }

    function renderFDWorkCaseOptions() {
        var listbox = document.getElementById("rules-panel-fd-work-options");
        var input = document.getElementById("rules-panel-project-name");
        if (!listbox || !input) return;
        listbox.innerHTML = "";
        App.rulesFDWorkSearchOptions.forEach(function (item, index) {
            var option = document.createElement("button");
            option.type = "button";
            option.setAttribute("role", "option");
            option.setAttribute("data-option-index", String(index));
            option.setAttribute("aria-selected", index === App.rulesFDWorkActiveOption ? "true" : "false");
            option.textContent = item.label;
            listbox.appendChild(option);
        });
        listbox.hidden = !App.rulesFDWorkSearchOptions.length;
        input.setAttribute("aria-expanded", listbox.hidden ? "false" : "true");
    }

    function selectFDWorkCaseOption(index) {
        var item = App.rulesFDWorkSearchOptions[index];
        var input = document.getElementById("rules-panel-project-name");
        if (!item || !input) return;
        input.value = item.label;
        App.rulesFDWorkSelectionToken = item.selection_token;
        App.rulesFDWorkSelectedLabel = item.label;
        App.rulesFDWorkLastQuery = item.label;
        closeFDWorkCaseOptions();
        showFDWorkCaseStatus("已匹配 FD Work 案件", false);
        refreshPanelWriteState();
    }

    function handleFDWorkCaseKeydown(event) {
        var count = App.rulesFDWorkSearchOptions.length;
        if (event.key === "Escape") {
            closeFDWorkCaseOptions();
            return;
        }
        if (event.key === "Tab") {
            closeFDWorkCaseOptions();
            return;
        }
        if (!count) return;
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            var delta = event.key === "ArrowDown" ? 1 : -1;
            App.rulesFDWorkActiveOption = (App.rulesFDWorkActiveOption + delta + count) % count;
            renderFDWorkCaseOptions();
        } else if (event.key === "Enter" && App.rulesFDWorkActiveOption >= 0) {
            event.preventDefault();
            selectFDWorkCaseOption(App.rulesFDWorkActiveOption);
        }
    }

    function closeFDWorkCaseOptions() {
        App.rulesFDWorkSearchOptions = [];
        App.rulesFDWorkActiveOption = -1;
        renderFDWorkCaseOptions();
    }

    function showFDWorkCaseStatus(message, isError) {
        var target = document.getElementById("rules-panel-fd-work-status");
        if (!target) return;
        target.hidden = !message;
        target.textContent = message || "";
        target.className = "inline-status" + (isError ? " edit-status-error" : "");
    }

    function resetFDWorkCaseSearch() {
        if (rulesFDWorkDebounceTimer) clearTimeout(rulesFDWorkDebounceTimer);
        rulesFDWorkDebounceTimer = null;
        App.rulesFDWorkRequestToken += 1;
        App.rulesFDWorkSelectionToken = null;
        App.rulesFDWorkSelectedLabel = "";
        App.rulesFDWorkLastQuery = "";
        App.rulesFDWorkLoginRetryPending = false;
        closeFDWorkCaseOptions();
        showFDWorkCaseStatus("", false);
    }
    App.resetFDWorkCaseSearch = resetFDWorkCaseSearch;

    function syncFDWorkCaseSearchStatus() {
        var status = App.fdWorkStatus || {};
        var enabled = status.enabled === true;
        var label = document.getElementById("rules-panel-project-name-label");
        var help = document.getElementById("rules-panel-fd-work-help");
        var login = document.getElementById("rules-panel-fd-work-login");
        var input = document.getElementById("rules-panel-project-name");
        if (label) label.textContent = enabled ? "FD Work 案件" : "项目名称";
        if (help) help.hidden = !enabled;
        if (login) login.hidden = !(enabled && status.login_required === true);
        if (input) {
            if (enabled) {
                input.setAttribute("role", "combobox");
                input.setAttribute("aria-autocomplete", "list");
                input.setAttribute("aria-controls", "rules-panel-fd-work-options");
            } else {
                input.removeAttribute("role");
                input.removeAttribute("aria-autocomplete");
                input.removeAttribute("aria-controls");
                input.removeAttribute("aria-expanded");
            }
        }
        if (!enabled) resetFDWorkCaseSearch();
        if (enabled && status.ready !== true) {
            App.rulesFDWorkSelectionToken = null;
            App.rulesFDWorkSelectedLabel = "";
            closeFDWorkCaseOptions();
        }
        if (enabled && status.ready === true && App.rulesFDWorkLoginRetryPending) {
            App.rulesFDWorkLoginRetryPending = false;
            var query = App.rulesFDWorkLastQuery;
            if (query.length >= App.FD_WORK_QUERY_MIN_LENGTH) {
                searchFDWorkCases(query, App.rulesPanelSessionToken);
            }
        }
        refreshPanelWriteState();
    }
    App.syncFDWorkCaseSearchStatus = syncFDWorkCaseSearchStatus;

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
        var descInput = document.getElementById("rules-panel-project-description");
        if (!nameInput) return;
        var name = (nameInput.value || "").trim();
        if (!name) {
            showPanelStatus("请输入项目名称", true);
            return;
        }
        if (fdWorkCaseSelectionRequired() && !App.rulesFDWorkSelectionToken) {
            showPanelStatus("请从 FD Work 案件列表中选择", true);
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
            return App.loadProjectRules().then(function () {
                if (!isCurrentRulesPanelSession(sessionToken)) return;
                if (wasEditing) {
                    resetRulesTransientUi({ restoreFocus: true });
                    if (App.showToast) App.showToast("项目已保存");
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
        resetFDWorkCaseSearch();
        App.rulesFDWorkOriginalName = project ? App.safeText(project.name, "") : "";
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
        syncProjectPanelPresentation();
        setDisabled("rules-panel-save-rule", ruleBusy);
        setDisabled("rules-panel-project-name", projectBusy);
        var saveProject = document.getElementById("rules-panel-save-project");
        if (saveProject && fdWorkCaseSelectionRequired()) {
            saveProject.disabled = projectBusy || !App.rulesFDWorkSelectionToken;
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
