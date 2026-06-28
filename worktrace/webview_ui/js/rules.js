// WorkTrace WebView frontend — Project Rules module (Phase 5B / 5C / 5D / 5E).
// Existing project-bound folder / keyword rules can be enabled or disabled
// (Phase 5B), one new keyword rule can be created on an existing
// rule-target project (Phase 5C), one existing keyword rule can be deleted
// (Phase 5D), and folder rules can be created / edited / deleted (Phase 5E).

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function loadProjectRules() {
        if (App.rulesLoading) {
            return Promise.resolve();
        }
        var token = ++App.rulesRequestToken;
        App.setRulesLoading(true);
        App.clearRulesError();
        return App.callBridge("get_project_rules").then(function (result) {
            if (token !== App.rulesRequestToken) return;
            if (result && result.ok === false) {
                App.showRulesError("加载项目规则失败");
                return;
            }
            App.showProjectRules(result || { projects: [] });
            App.clearRulesError();
        }).catch(function () {
            if (token !== App.rulesRequestToken) return;
            App.showRulesError("加载项目规则失败");
        }).then(function () {
            if (token === App.rulesRequestToken) {
                App.setRulesLoading(false);
            }
        });
    }
    App.loadProjectRules = loadProjectRules;

    function showProjectRules(data) {
        App.rulesLoaded = true;
        // Phase 5E: cache the last-loaded data so the inline folder edit
        // form can re-render the list immediately without a round-trip
        // through loadProjectRules (which would lose input focus).
        App.lastProjectRulesData = data || { projects: [] };
        var list = document.getElementById("rules-list");
        var empty = document.getElementById("rules-empty");
        // Phase 5C: keep the keyword create form's project selector in sync
        // with the freshly loaded Project Rules data. The selector is only
        // re-populated when no keyword create is in flight so an in-flight
        // submit is never displaced by an auto-refresh.
        App.populateKeywordCreateProjectSelector((data && data.projects) || []);
        // Phase 5E: same sync for the folder create form's project selector.
        App.populateFolderCreateProjectSelector((data && data.projects) || []);
        if (!list || !empty) return;
        var projects = (data && data.projects) || [];
        if (!projects.length) {
            list.innerHTML = "";
            empty.hidden = false;
            return;
        }
        empty.hidden = true;
        list.innerHTML = projects.map(function (project) {
            return App.renderProjectRuleProject(project);
        }).join("");
        App.bindProjectRuleToggles();
        App.bindProjectRuleDelete();
        App.bindProjectRuleFolderEvents();
        App.bindProjectRuleKeywordEditEvents();
    }
    App.showProjectRules = showProjectRules;

    function renderProjectRuleProject(project) {
        var name = text(project && project.name, "未命名项目");
        var description = text(project && project.description, "");
        var summary = text(project && project.summary, "暂无规则");
        var enabled = !!(project && project.enabled);
        var isExcluded = !!(project && project.is_excluded);
        var rules = (project && project.rules) || [];
        var stateLabel = enabled ? "已启用" : "已禁用";
        var projectClass = enabled ? "rules-project-card" : "rules-project-card is-disabled";
        var rows = rules.length ? rules.map(function (rule) {
            return App.renderProjectRuleRow(rule);
        }).join("") : '<div class="rules-project-empty">此项目暂无规则</div>';
        return [
            '<article class="' + projectClass + '">',
            '  <div class="rules-project-head">',
            '    <div class="rules-project-title-group">',
            '      <div class="rules-project-title">' + name + '</div>',
            description ? '      <div class="rules-project-description">' + description + '</div>' : "",
            '    </div>',
            '    <div class="rules-project-badges">',
            '      <span class="rules-status ' + (enabled ? "is-enabled" : "is-disabled") + '">' + stateLabel + '</span>',
            isExcluded ? '      <span class="rules-excluded-badge">排除规则</span>' : "",
            '    </div>',
            '  </div>',
            '  <div class="rules-project-summary">' + summary + '</div>',
            '  <div class="rules-count-grid">',
            '    <div><span>规则总数</span><strong>' + count(project && project.rule_count) + '</strong></div>',
            '    <div><span>文件夹规则</span><strong>' + count(project && project.folder_rule_count) + '</strong></div>',
            '    <div><span>关键词规则</span><strong>' + count(project && project.keyword_rule_count) + '</strong></div>',
            '  </div>',
            '  <div class="rules-row-list">' + rows + '</div>',
            '</article>'
        ].join("");
    }
    App.renderProjectRuleProject = renderProjectRuleProject;

    function renderProjectRuleRow(rule) {
        var label = text(rule && rule.kind_label, "规则");
        var target = text(rule && rule.target, "未设置");
        var detail = text(rule && rule.detail, "");
        var enabled = !!(rule && rule.enabled);
        var stateLabel = enabled ? "已启用" : "已禁用";
        var actionLabel = enabled ? "停用" : "启用";
        var kind = ruleKind(rule && rule.kind);
        var ruleId = positiveInt(rule && rule.id);
        var ruleKey = kind + ":" + ruleId;
        var saving = App.rulesSavingRuleKey === ruleKey;
        var deleting = App.rulesDeletingRuleKey === ruleKey;
        // Phase 5D: disable the toggle button while any rule write is in
        // flight on this row (toggle saving or keyword delete) or when the
        // rule id is missing. This keeps the toggle and delete write paths
        // from concurrently polluting the same row.
        var disabledAttr = (App.rulesSavingRuleKey || App.rulesDeletingRuleKey || !ruleId) ? " disabled" : "";
        var buttonLabel = saving ? "正在更新…" : actionLabel;
        // Phase 5D / 5F: only keyword rules get delete + edit buttons. When
        // editing this row, render the inline edit form in place of the
        // normal row body so the user can edit the keyword text without
        // leaving the row. The toggle and delete buttons stay disabled while
        // keyword edit / save is in flight so the write paths cannot pollute
        // each other.
        var deleteButton = "";
        var keywordEditButton = "";
        var keywordEditing = false;
        if (kind === "keyword" && ruleId) {
            keywordEditing = App.rulesEditingKeywordKey === ruleKey;
            var keywordWriteInProgress = !!(
                App.rulesSavingRuleKey ||
                App.rulesDeletingRuleKey ||
                App.rulesEditingKeywordKey ||
                App.rulesUpdatingKeywordKey
            );
            var keywordBtnDisabled = keywordWriteInProgress ? " disabled" : "";
            var editLabel = (App.rulesUpdatingKeywordKey === ruleKey) ? "正在保存…" : "编辑";
            keywordEditButton = '  <button class="rules-keyword-edit-button" type="button" data-rule-kind="keyword" data-rule-id="' + count(ruleId) + '"' + keywordBtnDisabled + '>' + editLabel + '</button>';
            var deleteDisabled = keywordWriteInProgress ? " disabled" : "";
            var deleteLabel = deleting ? "正在删除…" : "删除";
            deleteButton = '  <button class="rules-keyword-delete-button" type="button" data-rule-kind="keyword" data-rule-id="' + count(ruleId) + '"' + deleteDisabled + '>' + deleteLabel + '</button>';
        }
        // Phase 5E: folder rules get inline edit + delete buttons. When
        // editing this row, render the inline edit form in place of the
        // normal row body so the user can edit folder_path and recursive
        // without leaving the row. The toggle button stays disabled while
        // folder edit / delete is in flight so the four write paths cannot
        // pollute each other.
        var folderButtons = "";
        var folderEditing = false;
        if (kind === "folder" && ruleId) {
            folderEditing = App.rulesEditingFolderKey === ruleKey;
            var folderWriteInProgress = !!(
                App.rulesCreatingFolder ||
                App.rulesEditingFolderKey ||
                App.rulesDeletingFolderKey
            );
            var folderBtnDisabled = (folderWriteInProgress || App.rulesSavingRuleKey || App.rulesDeletingRuleKey) ? " disabled" : "";
            var editLabel = saving ? "正在更新…" : "编辑";
            var folderDeleteLabel = App.rulesDeletingFolderKey === ruleKey ? "正在删除…" : "删除";
            folderButtons = '  <button class="rules-folder-edit-button" type="button" data-rule-kind="folder" data-rule-id="' + count(ruleId) + '"' + folderBtnDisabled + '>' + editLabel + '</button>';
            folderButtons += '  <button class="rules-folder-delete-button" type="button" data-rule-kind="folder" data-rule-id="' + count(ruleId) + '"' + folderBtnDisabled + '>' + folderDeleteLabel + '</button>';
        }
        // When this folder row is being edited, render the inline edit form
        // in place of the normal body. The edit form holds its own folder
        // path input + recursive checkbox + save / cancel buttons.
        if (folderEditing) {
            var currentPath = text(rule && rule.target, "");
            var currentRecursive = !!(rule && rule.recursive);
            return [
                '<div class="rules-row is-folder-editing">',
                '  <span class="rules-kind-badge rules-kind-' + kind + '">' + label + '</span>',
                '  <div class="rules-folder-edit-form">',
                '    <input class="rules-folder-edit-input" type="text" maxlength="512" value="' + currentPath + '" placeholder="输入文件夹路径" />',
                '    <label class="rules-folder-edit-recursive-label"><input class="rules-folder-edit-recursive" type="checkbox"' + (currentRecursive ? " checked" : "") + ' /> 包含子文件夹</label>',
                '    <button class="rules-folder-edit-save" type="button" data-rule-kind="folder" data-rule-id="' + count(ruleId) + '">保存</button>',
                '    <button class="rules-folder-edit-cancel" type="button" data-rule-kind="folder" data-rule-id="' + count(ruleId) + '">取消</button>',
                '  </div>',
                '</div>'
            ].join("");
        }
        // Phase 5F: when this keyword row is being edited, render the inline
        // edit form in place of the normal body. The edit form holds its own
        // keyword input + save / cancel buttons. The maxlength matches the
        // keyword create input (200 chars).
        if (keywordEditing) {
            var currentKeyword = text(rule && rule.target, "");
            var keywordSaving = App.rulesUpdatingKeywordKey === ruleKey;
            var keywordSaveLabel = keywordSaving ? "正在保存…" : "保存";
            var keywordEditFormDisabled = keywordSaving ? " disabled" : "";
            return [
                '<div class="rules-row is-keyword-editing">',
                '  <span class="rules-kind-badge rules-kind-' + kind + '">' + label + '</span>',
                '  <div class="rules-keyword-edit-form">',
                '    <input class="rules-keyword-edit-input" type="text" maxlength="200" value="' + currentKeyword + '" placeholder="输入关键词" />',
                '    <button class="rules-keyword-edit-save" type="button" data-rule-kind="keyword" data-rule-id="' + count(ruleId) + '"' + keywordEditFormDisabled + '>' + keywordSaveLabel + '</button>',
                '    <button class="rules-keyword-edit-cancel" type="button" data-rule-kind="keyword" data-rule-id="' + count(ruleId) + '"' + keywordEditFormDisabled + '>取消</button>',
                '  </div>',
                '</div>'
            ].join("");
        }
        return [
            '<div class="rules-row ' + (enabled ? "" : "is-disabled") + '">',
            '  <span class="rules-kind-badge rules-kind-' + kind + '">' + label + '</span>',
            '  <div class="rules-row-main">',
            '    <div class="rules-target">' + target + '</div>',
            '    <div class="rules-detail">' + detail + '</div>',
            '  </div>',
            '  <span class="rules-status ' + (enabled ? "is-enabled" : "is-disabled") + '">' + stateLabel + '</span>',
            '  <button class="rules-toggle-btn" type="button" data-rule-type="' + kind + '" data-rule-id="' + count(ruleId) + '" data-next-enabled="' + (!enabled ? "true" : "false") + '"' + disabledAttr + '>' + buttonLabel + '</button>',
            deleteButton,
            keywordEditButton,
            folderButtons,
            '</div>'
        ].join("");
    }
    App.renderProjectRuleRow = renderProjectRuleRow;

    function bindProjectRuleToggles() {
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-toggle-bound") === "1") return;
        list.setAttribute("data-rules-toggle-bound", "1");
        list.addEventListener("click", App.handleProjectRuleToggle);
    }
    App.bindProjectRuleToggles = bindProjectRuleToggles;

    function handleProjectRuleToggle(event) {
        var button = event.target && event.target.closest ? event.target.closest(".rules-toggle-btn") : null;
        if (!button || App.rulesSavingRuleKey) return;
        var ruleType = button.getAttribute("data-rule-type");
        var ruleId = parseInt(button.getAttribute("data-rule-id"), 10);
        var nextEnabled = button.getAttribute("data-next-enabled") === "true";
        if ((ruleType !== "folder" && ruleType !== "keyword") || !ruleId) {
            App.showRulesError("更新规则状态失败");
            return;
        }
        if (!nextEnabled && !window.confirm("确定停用这条规则吗？停用后它将不再用于自动归类。")) {
            return;
        }
        App.setProjectRuleSaving(ruleType + ":" + ruleId);
        App.clearRulesError();
        App.callBridge("set_project_rule_enabled", ruleType, ruleId, nextEnabled).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "更新规则状态失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.showRulesError("规则状态已更新");
            });
        }).catch(function () {
            App.showRulesError("更新规则状态失败");
        }).then(function () {
            App.setProjectRuleSaving(null);
        });
    }
    App.handleProjectRuleToggle = handleProjectRuleToggle;

    function setProjectRuleSaving(ruleKey) {
        App.rulesSavingRuleKey = ruleKey || null;
        var buttons = document.querySelectorAll(".rules-toggle-btn");
        Array.prototype.forEach.call(buttons, function (button) {
            var currentKey = button.getAttribute("data-rule-type") + ":" + button.getAttribute("data-rule-id");
            button.disabled = !!App.rulesSavingRuleKey;
            if (currentKey === App.rulesSavingRuleKey) {
                button.textContent = "正在更新…";
            }
        });
    }
    App.setProjectRuleSaving = setProjectRuleSaving;

    // --- Phase 5D: keyword rule deletion -------------------------------

    function bindProjectRuleDelete() {
        // Phase 5D: event-delegated binding for keyword delete buttons.
        // Re-uses the same #rules-list container as the toggle binding so
        // no extra per-row listeners are needed. Bound once per page
        // lifecycle via the data attribute guard.
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-delete-bound") === "1") return;
        list.setAttribute("data-rules-delete-bound", "1");
        list.addEventListener("click", App.handleProjectRuleDelete);
    }
    App.bindProjectRuleDelete = bindProjectRuleDelete;

    function handleProjectRuleDelete(event) {
        // Phase 5D: delete one existing keyword rule. Confirms first, then
        // validates the dataset rule id locally before calling the bridge.
        // Only one keyword delete may be in flight at a time. The deleting
        // state is intentionally separate from rulesSavingRuleKey (toggle)
        // and rulesCreatingKeyword (create) so the three write paths can
        // never pollute each other. The catch path never reads .message.
        var button = event.target && event.target.closest ? event.target.closest(".rules-keyword-delete-button") : null;
        if (!button) return;
        if (App.rulesDeletingRuleKey) return;
        var kind = button.getAttribute("data-rule-kind");
        if (kind !== "keyword") {
            App.showRulesError("删除关键词规则失败");
            return;
        }
        var rawId = button.getAttribute("data-rule-id");
        var ruleId = parseInt(rawId, 10);
        // Malformed dataset must not call the bridge.
        if (!rawId || String(ruleId) !== String(rawId).trim() || ruleId <= 0) {
            App.showRulesError("删除关键词规则失败");
            return;
        }
        if (!window.confirm("确定删除这条关键词规则吗？删除后该关键词将不再用于自动归类。")) {
            return;
        }
        App.setRuleDeleting("keyword:" + ruleId);
        App.clearRulesError();
        App.callBridge("delete_project_keyword_rule", ruleId).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "删除关键词规则失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.showRulesError("关键词规则已删除");
            });
        }).catch(function () {
            App.showRulesError("删除关键词规则失败");
        }).then(function () {
            App.setRuleDeleting(null);
        });
    }
    App.handleProjectRuleDelete = handleProjectRuleDelete;

    function setRuleDeleting(ruleKey) {
        // Phase 5D: toggle the keyword delete saving state. Updates every
        // delete button label / disabled state and the matching toggle
        // button disabled state on the same row so the two write paths
        // cannot run concurrently on one row.
        App.rulesDeletingRuleKey = ruleKey || null;
        var deleteButtons = document.querySelectorAll(".rules-keyword-delete-button");
        Array.prototype.forEach.call(deleteButtons, function (button) {
            var currentKey = "keyword:" + button.getAttribute("data-rule-id");
            button.disabled = !!App.rulesDeletingRuleKey;
            if (currentKey === App.rulesDeletingRuleKey) {
                button.textContent = "正在删除…";
            } else if (button.textContent === "正在删除…") {
                button.textContent = "删除";
            }
        });
        var toggleButtons = document.querySelectorAll(".rules-toggle-btn");
        Array.prototype.forEach.call(toggleButtons, function (button) {
            button.disabled = !!(App.rulesSavingRuleKey || App.rulesDeletingRuleKey);
        });
    }
    App.setRuleDeleting = setRuleDeleting;

    // --- Phase 5F: keyword rule edit -----------------------------------

    function bindProjectRuleKeywordEditEvents() {
        // Phase 5F: event-delegated binding for keyword edit / edit-save /
        // edit-cancel. Re-uses the same #rules-list container as the toggle,
        // delete, and folder bindings so no extra per-row listeners are
        // needed. Bound once per page lifecycle via the data attribute guard.
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-keyword-edit-bound") === "1") return;
        list.setAttribute("data-rules-keyword-edit-bound", "1");
        list.addEventListener("click", App.handleProjectRuleKeywordEditEvent);
    }
    App.bindProjectRuleKeywordEditEvents = bindProjectRuleKeywordEditEvents;

    function handleProjectRuleKeywordEditEvent(event) {
        // Phase 5F: single delegated click handler for all keyword edit
        // operations (edit start, edit save, edit cancel). Routes to the
        // matching sub-handler based on the button class.
        var button = event.target && event.target.closest ? event.target.closest("button") : null;
        if (!button) return;
        if (button.classList.contains("rules-keyword-edit-button")) {
            App.handleKeywordEditStart(button);
            return;
        }
        if (button.classList.contains("rules-keyword-edit-save")) {
            App.handleKeywordEditSave(button);
            return;
        }
        if (button.classList.contains("rules-keyword-edit-cancel")) {
            App.handleKeywordEditCancel(button);
            return;
        }
    }
    App.handleProjectRuleKeywordEditEvent = handleProjectRuleKeywordEditEvent;

    function handleKeywordEditStart(button) {
        // Phase 5F: enter inline edit mode for one keyword rule row. Only
        // one keyword edit may be in flight at a time. Setting the editing
        // key triggers a re-render of that row into the edit form.
        if (App.rulesEditingKeywordKey) return;
        if (App.rulesUpdatingKeywordKey) return;
        if (App.rulesDeletingRuleKey) return;
        var kind = button.getAttribute("data-rule-kind");
        if (kind !== "keyword") {
            App.showRulesError("保存关键词规则失败");
            return;
        }
        var rawId = button.getAttribute("data-rule-id");
        var ruleId = parseInt(rawId, 10);
        if (!rawId || String(ruleId) !== String(rawId).trim() || ruleId <= 0) {
            App.showRulesError("保存关键词规则失败");
            return;
        }
        App.setKeywordEditing("keyword:" + ruleId);
        App.clearRulesError();
    }
    App.handleKeywordEditStart = handleKeywordEditStart;

    function handleKeywordEditSave(button) {
        // Phase 5F: save the inline keyword edit. Validates the edited
        // keyword locally, then calls the bridge. On success the editing
        // state clears and the Project Rules list refreshes; on failure
        // the editing form is preserved so the user can retry. The catch
        // path never reads .message.
        if (!App.rulesEditingKeywordKey) return;
        var kind = button.getAttribute("data-rule-kind");
        if (kind !== "keyword") {
            App.showRulesError("保存关键词规则失败");
            return;
        }
        var rawId = button.getAttribute("data-rule-id");
        var ruleId = parseInt(rawId, 10);
        if (!rawId || String(ruleId) !== String(rawId).trim() || ruleId <= 0) {
            App.showRulesError("保存关键词规则失败");
            return;
        }
        var row = button.closest(".rules-row");
        var input = row ? row.querySelector(".rules-keyword-edit-input") : null;
        if (!input) {
            App.showRulesError("保存关键词规则失败");
            return;
        }
        var keyword = (input.value || "").trim();
        if (!keyword) {
            App.showRulesError("请输入关键词");
            return;
        }
        App.setKeywordSaving("keyword:" + ruleId);
        App.clearRulesError();
        App.callBridge("update_project_keyword_rule", ruleId, keyword).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "保存关键词规则失败");
                return;
            }
            App.setKeywordEditing(null);
            return App.loadProjectRules().then(function () {
                App.showRulesError("关键词规则已保存");
            });
        }).catch(function () {
            App.showRulesError("保存关键词规则失败");
        }).then(function () {
            App.setKeywordSaving(null);
        });
    }
    App.handleKeywordEditSave = handleKeywordEditSave;

    function handleKeywordEditCancel(button) {
        // Phase 5F: cancel the inline keyword edit. Just clears the editing
        // state and re-renders. No bridge call is made.
        if (!App.rulesEditingKeywordKey) return;
        App.setKeywordEditing(null);
        App.clearRulesError();
    }
    App.handleKeywordEditCancel = handleKeywordEditCancel;

    function setKeywordEditing(keywordKey) {
        // Phase 5F: enter / leave inline edit mode for one keyword rule row.
        // Setting the key triggers a re-render of the list from cached data
        // so the edit form appears / disappears immediately.
        App.rulesEditingKeywordKey = keywordKey || null;
        App.rerenderProjectRulesList();
    }
    App.setKeywordEditing = setKeywordEditing;

    function setKeywordSaving(keywordKey) {
        // Phase 5F: toggle the in-flight state for a keyword edit save.
        // Flips the save / cancel button disabled state on the edit form
        // so the user cannot double-submit. State is separate from the
        // editing key (which stays set until success clears it).
        App.rulesUpdatingKeywordKey = keywordKey || null;
        var saveButtons = document.querySelectorAll(".rules-keyword-edit-save");
        var cancelButtons = document.querySelectorAll(".rules-keyword-edit-cancel");
        Array.prototype.forEach.call(saveButtons, function (btn) {
            btn.disabled = !!App.rulesUpdatingKeywordKey;
            if (App.rulesUpdatingKeywordKey) btn.textContent = "正在保存…";
            else btn.textContent = "保存";
        });
        Array.prototype.forEach.call(cancelButtons, function (btn) {
            btn.disabled = !!App.rulesUpdatingKeywordKey;
        });
    }
    App.setKeywordSaving = setKeywordSaving;

    // --- Phase 5E: folder rule CRUD -----------------------------------

    function populateFolderCreateProjectSelector(projects) {
        // Phase 5E: populate the folder-create project selector from the
        // freshly loaded Project Rules data. Only enabled, non-excluded
        // projects with a positive id are valid targets — this mirrors the
        // ``project_api.list_rule_target_projects()`` eligibility rule the
        // API uses. Re-population is skipped entirely while a folder create
        // is in flight so the user's selection is never displaced by an
        // auto-refresh, and the previous selection is preserved when the
        // list is re-rendered.
        if (App.rulesCreatingFolder) return;
        var select = document.getElementById("rules-folder-create-project");
        var submitBtn = document.getElementById("rules-folder-create-submit");
        var input = document.getElementById("rules-folder-create-input");
        var emptyHint = document.getElementById("rules-folder-create-empty");
        if (!select || !submitBtn || !input) return;
        var list = projects || [];
        var targets = [];
        for (var i = 0; i < list.length; i++) {
            var p = list[i];
            if (p && p.enabled && !p.is_excluded && p.id > 0) {
                targets.push(p);
            }
        }
        var previousValue = select.value;
        select.innerHTML = "";
        if (!targets.length) {
            if (emptyHint) emptyHint.hidden = false;
            submitBtn.disabled = true;
            input.disabled = true;
            select.disabled = true;
            return;
        }
        if (emptyHint) emptyHint.hidden = true;
        for (var j = 0; j < targets.length; j++) {
            var opt = document.createElement("option");
            opt.value = String(targets[j].id);
            // ``textContent`` is safe here (no HTML parsing) and the name
            // is already display-safe from the bridge projection.
            opt.textContent = targets[j].name;
            select.appendChild(opt);
        }
        if (previousValue) {
            for (var k = 0; k < select.options.length; k++) {
                if (select.options[k].value === previousValue) {
                    select.value = previousValue;
                    break;
                }
            }
        }
        select.disabled = false;
        input.disabled = false;
        submitBtn.disabled = false;
    }
    App.populateFolderCreateProjectSelector = populateFolderCreateProjectSelector;

    function handleFolderCreateSubmit() {
        // Phase 5E: validate project id + folder_path locally, then call the
        // bridge. Only one folder create may be in flight at a time. The
        // folder_path is trimmed before validation and before the bridge
        // call. On success the folder_path input is cleared and the Project
        // Rules list is refreshed; on failure the folder_path input is
        // preserved so the user can edit and retry.
        if (App.rulesCreatingFolder) return;
        var select = document.getElementById("rules-folder-create-project");
        var input = document.getElementById("rules-folder-create-input");
        var recursiveEl = document.getElementById("rules-folder-create-recursive");
        if (!select || !input) return;
        var projectId = parseInt(select.value, 10);
        if (!(projectId > 0)) {
            App.showFolderCreateStatus("请选择有效的项目", true);
            return;
        }
        var folderPath = (input.value || "").trim();
        if (!folderPath) {
            App.showFolderCreateStatus("请输入文件夹路径", true);
            return;
        }
        var recursive = recursiveEl ? !!recursiveEl.checked : true;
        App.setFolderCreateCreating(true);
        App.clearFolderCreateStatus();
        App.callBridge("create_project_folder_rule", projectId, folderPath, recursive).then(function (result) {
            if (result && result.ok === false) {
                App.showFolderCreateStatus(result.error || "新增文件夹规则失败", true);
                return;
            }
            input.value = "";
            if (recursiveEl) recursiveEl.checked = true;
            App.clearFolderCreateStatus();
            return App.loadProjectRules().then(function () {
                App.showFolderCreateStatus("文件夹规则已新增", false);
            });
        }).catch(function () {
            App.showFolderCreateStatus("新增文件夹规则失败", true);
        }).then(function () {
            App.setFolderCreateCreating(false);
        });
    }
    App.handleFolderCreateSubmit = handleFolderCreateSubmit;

    function setFolderCreateCreating(creating) {
        // Phase 5E: toggle the folder create saving state. The state is
        // intentionally separate from ``rulesSavingRuleKey`` (Phase 5B
        // toggle saving), ``rulesCreatingKeyword`` (Phase 5C keyword
        // create), and ``rulesDeletingRuleKey`` (Phase 5D keyword delete)
        // so the four write paths can never pollute each other's button /
        // input disabled state.
        App.rulesCreatingFolder = creating;
        var btn = document.getElementById("rules-folder-create-submit");
        var input = document.getElementById("rules-folder-create-input");
        var select = document.getElementById("rules-folder-create-project");
        var recursiveEl = document.getElementById("rules-folder-create-recursive");
        if (btn) {
            btn.disabled = creating;
            btn.textContent = creating ? "正在新增…" : "新增文件夹规则";
        }
        if (input) input.disabled = creating;
        if (select) select.disabled = creating;
        if (recursiveEl) recursiveEl.disabled = creating;
    }
    App.setFolderCreateCreating = setFolderCreateCreating;

    function showFolderCreateStatus(message, isError) {
        var el = document.getElementById("rules-folder-create-status");
        if (!el) return;
        if (!message) {
            el.hidden = true;
            el.textContent = "";
            el.className = "rules-folder-create-status";
            return;
        }
        el.hidden = false;
        el.textContent = message;
        el.className = "rules-folder-create-status" + (isError ? " is-error" : " is-success");
    }
    App.showFolderCreateStatus = showFolderCreateStatus;

    function clearFolderCreateStatus() {
        App.showFolderCreateStatus("", false);
    }
    App.clearFolderCreateStatus = clearFolderCreateStatus;

    function bindProjectRuleFolderEvents() {
        // Phase 5E: event-delegated binding for folder edit / delete /
        // edit-save / edit-cancel. Re-uses the same #rules-list container
        // as the toggle and keyword delete bindings so no extra per-row
        // listeners are needed. Bound once per page lifecycle via the data
        // attribute guard.
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-folder-bound") === "1") return;
        list.setAttribute("data-rules-folder-bound", "1");
        list.addEventListener("click", App.handleProjectRuleFolderEvent);
    }
    App.bindProjectRuleFolderEvents = bindProjectRuleFolderEvents;

    function handleProjectRuleFolderEvent(event) {
        // Phase 5E: single delegated click handler for all folder write
        // operations (edit start, edit save, edit cancel, delete). Routes
        // to the matching sub-handler based on the button class. The catch
        // path never reads .message.
        var button = event.target && event.target.closest ? event.target.closest("button") : null;
        if (!button) return;
        if (button.classList.contains("rules-folder-edit-button")) {
            App.handleFolderEditStart(button);
            return;
        }
        if (button.classList.contains("rules-folder-delete-button")) {
            App.handleFolderDelete(button);
            return;
        }
        if (button.classList.contains("rules-folder-edit-save")) {
            App.handleFolderEditSave(button);
            return;
        }
        if (button.classList.contains("rules-folder-edit-cancel")) {
            App.handleFolderEditCancel(button);
            return;
        }
    }
    App.handleProjectRuleFolderEvent = handleProjectRuleFolderEvent;

    function handleFolderEditStart(button) {
        // Phase 5E: enter inline edit mode for one folder rule row. Only
        // one folder edit may be in flight at a time. Setting the editing
        // key triggers a re-render of that row into the edit form.
        if (App.rulesEditingFolderKey) return;
        if (App.rulesCreatingFolder || App.rulesDeletingFolderKey) return;
        var kind = button.getAttribute("data-rule-kind");
        if (kind !== "folder") {
            App.showRulesError("保存文件夹规则失败");
            return;
        }
        var rawId = button.getAttribute("data-rule-id");
        var ruleId = parseInt(rawId, 10);
        if (!rawId || String(ruleId) !== String(rawId).trim() || ruleId <= 0) {
            App.showRulesError("保存文件夹规则失败");
            return;
        }
        App.setFolderEditing("folder:" + ruleId);
        App.clearRulesError();
    }
    App.handleFolderEditStart = handleFolderEditStart;

    function handleFolderEditSave(button) {
        // Phase 5E: save the inline folder edit. Validates the edited
        // folder_path locally, then calls the bridge. On success the
        // editing state clears and the Project Rules list refreshes; on
        // failure the editing form is preserved so the user can retry.
        if (!App.rulesEditingFolderKey) return;
        var kind = button.getAttribute("data-rule-kind");
        if (kind !== "folder") {
            App.showRulesError("保存文件夹规则失败");
            return;
        }
        var rawId = button.getAttribute("data-rule-id");
        var ruleId = parseInt(rawId, 10);
        if (!rawId || String(ruleId) !== String(rawId).trim() || ruleId <= 0) {
            App.showRulesError("保存文件夹规则失败");
            return;
        }
        var row = button.closest(".rules-row");
        var input = row ? row.querySelector(".rules-folder-edit-input") : null;
        var recursiveEl = row ? row.querySelector(".rules-folder-edit-recursive") : null;
        if (!input) {
            App.showRulesError("保存文件夹规则失败");
            return;
        }
        var folderPath = (input.value || "").trim();
        if (!folderPath) {
            App.showRulesError("请输入文件夹路径");
            return;
        }
        var recursive = recursiveEl ? !!recursiveEl.checked : true;
        App.setFolderSaving(true);
        App.clearRulesError();
        App.callBridge("update_project_folder_rule", ruleId, folderPath, recursive).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "保存文件夹规则失败");
                return;
            }
            App.setFolderEditing(null);
            return App.loadProjectRules().then(function () {
                App.showRulesError("文件夹规则已保存");
            });
        }).catch(function () {
            App.showRulesError("保存文件夹规则失败");
        }).then(function () {
            App.setFolderSaving(false);
        });
    }
    App.handleFolderEditSave = handleFolderEditSave;

    function handleFolderEditCancel(button) {
        // Phase 5E: cancel the inline folder edit. Just clears the editing
        // state and re-renders. No bridge call is made.
        if (!App.rulesEditingFolderKey) return;
        App.setFolderEditing(null);
        App.clearRulesError();
    }
    App.handleFolderEditCancel = handleFolderEditCancel;

    function handleFolderDelete(button) {
        // Phase 5E: delete one existing folder rule. Confirms first, then
        // validates the dataset rule id locally before calling the bridge.
        // Only one folder delete may be in flight at a time. The deleting
        // state is intentionally separate from the other four write paths
        // so they can never pollute each other. The catch path never
        // reads .message.
        if (App.rulesDeletingFolderKey) return;
        if (App.rulesCreatingFolder || App.rulesEditingFolderKey) return;
        var kind = button.getAttribute("data-rule-kind");
        if (kind !== "folder") {
            App.showRulesError("删除文件夹规则失败");
            return;
        }
        var rawId = button.getAttribute("data-rule-id");
        var ruleId = parseInt(rawId, 10);
        if (!rawId || String(ruleId) !== String(rawId).trim() || ruleId <= 0) {
            App.showRulesError("删除文件夹规则失败");
            return;
        }
        if (!window.confirm("确定删除这条文件夹规则吗？删除后该文件夹将不再用于自动归类。")) {
            return;
        }
        App.setFolderDeleting("folder:" + ruleId);
        App.clearRulesError();
        App.callBridge("delete_project_folder_rule", ruleId).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "删除文件夹规则失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.showRulesError("文件夹规则已删除");
            });
        }).catch(function () {
            App.showRulesError("删除文件夹规则失败");
        }).then(function () {
            App.setFolderDeleting(null);
        });
    }
    App.handleFolderDelete = handleFolderDelete;

    function setFolderEditing(folderKey) {
        // Phase 5E: enter / leave inline edit mode for one folder rule row.
        // Setting the key triggers a full re-render via loadProjectRules
        // is NOT called here (that would lose the input focus); instead
        // the caller relies on the next render cycle (e.g. after a
        // loadProjectRules refresh) to show the edit form. For immediate
        // visual feedback we directly re-render the list when toggling.
        App.rulesEditingFolderKey = folderKey || null;
        App.rerenderProjectRulesList();
    }
    App.setFolderEditing = setFolderEditing;

    function setFolderSaving(saving) {
        // Phase 5E: toggle the in-flight state for a folder edit save. This
        // flips the save / cancel button disabled state on the edit form
        // so the user cannot double-submit. State is separate from the
        // editing key (which stays set until success clears it).
        var saveButtons = document.querySelectorAll(".rules-folder-edit-save");
        var cancelButtons = document.querySelectorAll(".rules-folder-edit-cancel");
        Array.prototype.forEach.call(saveButtons, function (btn) {
            btn.disabled = !!saving;
            if (saving) btn.textContent = "正在保存…";
            else btn.textContent = "保存";
        });
        Array.prototype.forEach.call(cancelButtons, function (btn) {
            btn.disabled = !!saving;
        });
    }
    App.setFolderSaving = setFolderSaving;

    function setFolderDeleting(folderKey) {
        // Phase 5E: toggle the folder delete saving state. Updates every
        // folder delete / edit button label / disabled state and the
        // matching toggle button disabled state on the same row so the
        // write paths cannot run concurrently on one row.
        App.rulesDeletingFolderKey = folderKey || null;
        var deleteButtons = document.querySelectorAll(".rules-folder-delete-button");
        Array.prototype.forEach.call(deleteButtons, function (button) {
            var currentKey = "folder:" + button.getAttribute("data-rule-id");
            button.disabled = !!App.rulesDeletingFolderKey;
            if (currentKey === App.rulesDeletingFolderKey) {
                button.textContent = "正在删除…";
            } else if (button.textContent === "正在删除…") {
                button.textContent = "删除";
            }
        });
        var editButtons = document.querySelectorAll(".rules-folder-edit-button");
        Array.prototype.forEach.call(editButtons, function (button) {
            button.disabled = !!(App.rulesDeletingFolderKey || App.rulesEditingFolderKey || App.rulesCreatingFolder);
        });
        var toggleButtons = document.querySelectorAll(".rules-toggle-btn");
        Array.prototype.forEach.call(toggleButtons, function (button) {
            button.disabled = !!(
                App.rulesSavingRuleKey ||
                App.rulesDeletingRuleKey ||
                App.rulesDeletingFolderKey
            );
        });
    }
    App.setFolderDeleting = setFolderDeleting;

    function rerenderProjectRulesList() {
        // Phase 5E: re-render the rules list from the last-loaded data so
        // the inline folder edit form can appear / disappear immediately
        // without a round-trip through loadProjectRules. Falls back to a
        // loadProjectRules call if no cached data is available.
        var list = document.getElementById("rules-list");
        if (!list) return;
        if (!App.lastProjectRulesData) {
            App.loadProjectRules();
            return;
        }
        var projects = (App.lastProjectRulesData && App.lastProjectRulesData.projects) || [];
        if (!projects.length) {
            return;
        }
        list.innerHTML = projects.map(function (project) {
            return App.renderProjectRuleProject(project);
        }).join("");
        App.bindProjectRuleToggles();
        App.bindProjectRuleDelete();
        App.bindProjectRuleFolderEvents();
        App.bindProjectRuleKeywordEditEvents();
    }
    App.rerenderProjectRulesList = rerenderProjectRulesList;

    function setRulesLoading(loading) {
        App.rulesLoading = loading;
        var el = document.getElementById("rules-loading");
        if (el) el.hidden = !loading;
    }
    App.setRulesLoading = setRulesLoading;

    function showRulesError(message) {
        var banner = document.getElementById("rules-error");
        if (!banner) return;
        if (!message) {
            banner.hidden = true;
            banner.textContent = "加载项目规则失败";
            return;
        }
        banner.hidden = false;
        banner.textContent = message;
    }
    App.showRulesError = showRulesError;

    function clearRulesError() {
        App.showRulesError("");
    }
    App.clearRulesError = clearRulesError;

    // --- Phase 5C: keyword rule creation foundation -------------------

    function populateKeywordCreateProjectSelector(projects) {
        // Phase 5C: populate the keyword-create project selector from the
        // freshly loaded Project Rules data. Only enabled, non-excluded
        // projects with a positive id are valid targets — this mirrors the
        // ``project_api.list_rule_target_projects()`` eligibility rule the
        // API uses, so the selector only ever offers targets the API will
        // accept. Re-population is skipped entirely while a keyword create
        // is in flight so the user's selection is never displaced by an
        // auto-refresh, and the previous selection is preserved when the
        // list is re-rendered.
        if (App.rulesCreatingKeyword) return;
        var select = document.getElementById("rules-keyword-create-project");
        var submitBtn = document.getElementById("rules-keyword-create-submit");
        var input = document.getElementById("rules-keyword-create-input");
        var emptyHint = document.getElementById("rules-keyword-create-empty");
        if (!select || !submitBtn || !input) return;
        var list = projects || [];
        var targets = [];
        for (var i = 0; i < list.length; i++) {
            var p = list[i];
            if (p && p.enabled && !p.is_excluded && p.id > 0) {
                targets.push(p);
            }
        }
        var previousValue = select.value;
        select.innerHTML = "";
        if (!targets.length) {
            if (emptyHint) emptyHint.hidden = false;
            submitBtn.disabled = true;
            input.disabled = true;
            select.disabled = true;
            return;
        }
        if (emptyHint) emptyHint.hidden = true;
        for (var j = 0; j < targets.length; j++) {
            var opt = document.createElement("option");
            opt.value = String(targets[j].id);
            // ``textContent`` is safe here (no HTML parsing) and the name
            // is already display-safe from the bridge projection.
            opt.textContent = targets[j].name;
            select.appendChild(opt);
        }
        // Preserve the user's previous selection when the project list is
        // refreshed without changing the available targets.
        if (previousValue) {
            for (var k = 0; k < select.options.length; k++) {
                if (select.options[k].value === previousValue) {
                    select.value = previousValue;
                    break;
                }
            }
        }
        select.disabled = false;
        input.disabled = false;
        submitBtn.disabled = false;
    }
    App.populateKeywordCreateProjectSelector = populateKeywordCreateProjectSelector;

    function handleKeywordCreateSubmit() {
        // Phase 5C: validate project id + keyword locally, then call the
        // bridge. Only one keyword create may be in flight at a time. The
        // keyword is trimmed before validation and before the bridge call.
        // On success the keyword input is cleared and the Project Rules
        // list is refreshed; on failure the keyword input is preserved so
        // the user can edit and retry.
        if (App.rulesCreatingKeyword) return;
        var select = document.getElementById("rules-keyword-create-project");
        var input = document.getElementById("rules-keyword-create-input");
        if (!select || !input) return;
        var projectId = parseInt(select.value, 10);
        if (!(projectId > 0)) {
            App.showKeywordCreateStatus("请选择有效的项目", true);
            return;
        }
        var keyword = (input.value || "").trim();
        if (!keyword) {
            App.showKeywordCreateStatus("请输入关键词", true);
            return;
        }
        App.setKeywordCreateCreating(true);
        App.clearKeywordCreateStatus();
        App.callBridge("create_project_keyword_rule", projectId, keyword).then(function (result) {
            if (result && result.ok === false) {
                App.showKeywordCreateStatus(result.error || "新增关键词规则失败", true);
                return;
            }
            input.value = "";
            App.clearKeywordCreateStatus();
            return App.loadProjectRules().then(function () {
                App.showKeywordCreateStatus("关键词规则已新增", false);
            });
        }).catch(function () {
            App.showKeywordCreateStatus("新增关键词规则失败", true);
        }).then(function () {
            App.setKeywordCreateCreating(false);
        });
    }
    App.handleKeywordCreateSubmit = handleKeywordCreateSubmit;

    function setKeywordCreateCreating(creating) {
        // Phase 5C: toggle the keyword create saving state. The state is
        // intentionally separate from ``rulesSavingRuleKey`` (Phase 5B
        // toggle saving) so the two write paths can never pollute each
        // other's button / input disabled state.
        App.rulesCreatingKeyword = creating;
        var btn = document.getElementById("rules-keyword-create-submit");
        var input = document.getElementById("rules-keyword-create-input");
        var select = document.getElementById("rules-keyword-create-project");
        if (btn) {
            btn.disabled = creating;
            btn.textContent = creating ? "正在新增…" : "新增关键词规则";
        }
        if (input) input.disabled = creating;
        if (select) select.disabled = creating;
    }
    App.setKeywordCreateCreating = setKeywordCreateCreating;

    function showKeywordCreateStatus(message, isError) {
        var el = document.getElementById("rules-keyword-create-status");
        if (!el) return;
        if (!message) {
            el.hidden = true;
            el.textContent = "";
            el.className = "rules-keyword-create-status";
            return;
        }
        el.hidden = false;
        el.textContent = message;
        el.className = "rules-keyword-create-status" + (isError ? " is-error" : " is-success");
    }
    App.showKeywordCreateStatus = showKeywordCreateStatus;

    function clearKeywordCreateStatus() {
        App.showKeywordCreateStatus("", false);
    }
    App.clearKeywordCreateStatus = clearKeywordCreateStatus;

    function text(value, fallback) {
        return App.escapeHtml(App.safeText(value, fallback));
    }

    function count(value) {
        return App.escapeHtml(String(parseInt(value, 10) || 0));
    }

    function positiveInt(value) {
        var parsed = parseInt(value, 10);
        return parsed > 0 ? parsed : 0;
    }

    function ruleKind(value) {
        return value === "folder" ? "folder" : (value === "keyword" ? "keyword" : "unknown");
    }

})();
