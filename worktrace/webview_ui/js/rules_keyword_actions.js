// WorkTrace WebView frontend - Project Rules keyword actions.
// Keyword rule create / edit / delete.
// Loaded after rules_rule_actions.js, before folder / project action modules.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- keyword rule deletion -------------------------------

    function bindProjectRuleDelete() {
        // event-delegated binding for keyword delete buttons.
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
        // delete one existing keyword rule. Confirms first, then
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
        // toggle the keyword delete saving state. Updates every
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

    // --- keyword rule edit -----------------------------------

    function bindProjectRuleKeywordEditEvents() {
        // event-delegated binding for keyword edit / edit-save /
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
        // single delegated click handler for all keyword edit
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
        // enter inline edit mode for one keyword rule row. Only
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
        // save the inline keyword edit. Validates the edited
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
        // cancel the inline keyword edit. Just clears the editing
        // state and re-renders. No bridge call is made.
        if (!App.rulesEditingKeywordKey) return;
        App.setKeywordEditing(null);
        App.clearRulesError();
    }
    App.handleKeywordEditCancel = handleKeywordEditCancel;

    function setKeywordEditing(keywordKey) {
        // enter / leave inline edit mode for one keyword rule row.
        // Setting the key triggers a re-render of the list from cached data
        // so the edit form appears / disappears immediately.
        App.rulesEditingKeywordKey = keywordKey || null;
        App.rerenderProjectRulesList();
    }
    App.setKeywordEditing = setKeywordEditing;

    function setKeywordSaving(keywordKey) {
        // toggle the in-flight state for a keyword edit save.
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

    // --- keyword rule creation -------------------------------

    function populateKeywordCreateProjectSelector(projects) {
        // populate the keyword-create project selector from the
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
        // validate project id + keyword locally, then call the
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
        // toggle the keyword create saving state. The state is
        // intentionally separate from ``rulesSavingRuleKey`` (toggle
        // saving) so the two write paths can never pollute each
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

    // --- excluded keyword rule creation ----------------------

    function bindExcludedKeywordRuleEvents() {
        // event-delegated binding for the excluded keyword
        // create submit button. Bound once per page lifecycle via the
        // data attribute guard, re-using the same #rules-list container
        // as the other rule event delegations.
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-excluded-keyword-bound") === "1") return;
        list.setAttribute("data-excluded-keyword-bound", "1");
        list.addEventListener("click", function (event) {
            var button = event.target && event.target.closest
                ? event.target.closest("button.rules-excluded-keyword-submit")
                : null;
            if (!button) return;
            handleExcludedKeywordCreateSubmit();
        });
    }
    App.bindExcludedKeywordRuleEvents = bindExcludedKeywordRuleEvents;

    function handleExcludedKeywordCreateSubmit() {
        // validate the excluded keyword locally, then call the
        // dedicated ``create_excluded_keyword_rule`` bridge method. This
        // method does NOT pass a project_id — the API pins it to
        // EXCLUDED_PROJECT internally. On success the keyword input is
        // cleared and the Project Rules list is refreshed; on failure the
        // keyword input is preserved so the user can edit and retry.
        if (App.rulesCreatingKeyword) return;
        var input = document.querySelector(".rules-excluded-keyword-input");
        if (!input) return;
        var keyword = (input.value || "").trim();
        if (!keyword) {
            App.showRulesError("请输入关键词");
            return;
        }
        App.setKeywordCreateCreating(true);
        App.callBridge("create_excluded_keyword_rule", keyword).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "新增排除关键词规则失败");
                return;
            }
            input.value = "";
            App.clearRulesError();
            return App.loadProjectRules().then(function () {
                App.showRulesError("排除关键词规则已新增");
            });
        }).catch(function () {
            App.showRulesError("新增排除关键词规则失败");
        }).then(function () {
            App.setKeywordCreateCreating(false);
        });
    }
    App.handleExcludedKeywordCreateSubmit = handleExcludedKeywordCreateSubmit;

})();
