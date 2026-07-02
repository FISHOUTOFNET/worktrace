// WorkTrace WebView frontend - Project Rules folder actions.
// Folder rule create / edit / delete.
// Loaded after rules_keyword_actions.js, before project lifecycle actions.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};


    function populateFolderCreateProjectSelector(projects) {
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
        // validate project id + folder_path locally, then call the
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
        // toggle the folder create saving state. The state is
        // intentionally separate from ``rulesSavingRuleKey`` (toggle
        // saving), ``rulesCreatingKeyword`` (keyword create), and
        // ``rulesDeletingRuleKey`` (keyword delete) so the four write
        // paths can never pollute each other's button / input disabled
        // state.
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
        // event-delegated binding for folder edit / delete /
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
        // single delegated click handler for all folder write
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
        // enter inline edit mode for one folder rule row. Only
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
        // save the inline folder edit. Validates the edited
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
        // cancel the inline folder edit. Just clears the editing
        // state and re-renders. No bridge call is made.
        if (!App.rulesEditingFolderKey) return;
        App.setFolderEditing(null);
        App.clearRulesError();
    }
    App.handleFolderEditCancel = handleFolderEditCancel;

    function handleFolderDelete(button) {
        // delete one existing folder rule. Confirms first, then
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
        // enter / leave inline edit mode for one folder rule row.
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
        // toggle the in-flight state for a folder edit save. This
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
        // toggle the folder delete saving state. Updates every
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


    function bindExcludedFolderRuleEvents() {
        // event-delegated binding for the excluded folder create
        // submit button. Bound once per page lifecycle via the data
        // attribute guard, re-using the same #rules-list container as the
        // other rule event delegations.
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-excluded-folder-bound") === "1") return;
        list.setAttribute("data-excluded-folder-bound", "1");
        list.addEventListener("click", function (event) {
            var button = event.target && event.target.closest
                ? event.target.closest("button.rules-excluded-folder-submit")
                : null;
            if (!button) return;
            handleExcludedFolderCreateSubmit();
        });
    }
    App.bindExcludedFolderRuleEvents = bindExcludedFolderRuleEvents;

    function handleExcludedFolderCreateSubmit() {
        if (App.rulesCreatingFolder) return;
        var input = document.querySelector(".rules-excluded-folder-input");
        var recursiveEl = document.querySelector(".rules-excluded-folder-recursive");
        if (!input) return;
        var folderPath = (input.value || "").trim();
        if (!folderPath) {
            App.showRulesError("请输入文件夹路径");
            return;
        }
        var recursive = recursiveEl ? !!recursiveEl.checked : true;
        App.setFolderCreateCreating(true);
        App.clearRulesError();
        App.callBridge("create_excluded_folder_rule", folderPath, recursive).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "新增排除文件夹规则失败");
                return;
            }
            input.value = "";
            if (recursiveEl) recursiveEl.checked = true;
            App.clearRulesError();
            return App.loadProjectRules().then(function () {
                App.showRulesError("排除文件夹规则已新增");
            });
        }).catch(function () {
            App.showRulesError("新增排除文件夹规则失败");
        }).then(function () {
            App.setFolderCreateCreating(false);
        });
    }
    App.handleExcludedFolderCreateSubmit = handleExcludedFolderCreateSubmit;

})();
