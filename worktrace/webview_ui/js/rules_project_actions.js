// WorkTrace WebView frontend - Project Rules project-lifecycle actions (Phase 5G).
// Project create / edit / toggle / archive; loaded after rules.js, before init.js.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Phase 5G: Project lifecycle (create / edit / toggle / archive) ---

    function showProjectCreateStatus(message, isError) {
        var el = document.getElementById("rules-project-create-status");
        if (!el) return;
        if (!message) {
            el.hidden = true;
            el.textContent = "";
            el.className = "rules-project-create-status";
            return;
        }
        el.hidden = false;
        el.textContent = message;
        el.className = "rules-project-create-status" + (isError ? " is-error" : " is-success");
    }
    App.showProjectCreateStatus = showProjectCreateStatus;

    function clearProjectCreateStatus() {
        App.showProjectCreateStatus("", false);
    }
    App.clearProjectCreateStatus = clearProjectCreateStatus;

    function setProjectCreateCreating(creating) {
        // Phase 5G: toggle the project create saving state. The state is
        // intentionally separate from all rule write states and from the
        // other project lifecycle states so the write paths can never
        // pollute each other's button / input disabled state.
        App.rulesCreatingProject = creating;
        var btn = document.getElementById("rules-project-create-submit");
        var input = document.getElementById("rules-project-create-input");
        var descInput = document.getElementById("rules-project-create-description");
        if (btn) {
            btn.disabled = creating;
            btn.textContent = creating ? "正在新增…" : "新增项目";
        }
        if (input) input.disabled = creating;
        if (descInput) descInput.disabled = creating;
    }
    App.setProjectCreateCreating = setProjectCreateCreating;

    function handleProjectCreateSubmit() {
        // Phase 5G: validate name + description locally, then call the
        // bridge. Only one project create may be in flight at a time. The
        // name is trimmed before validation and before the bridge call.
        // On success both inputs are cleared and the Project Rules list is
        // refreshed; on failure the inputs are preserved so the user can
        // edit and retry. The catch path never reads .message.
        if (App.rulesCreatingProject) return;
        var input = document.getElementById("rules-project-create-input");
        var descInput = document.getElementById("rules-project-create-description");
        if (!input) return;
        var name = (input.value || "").trim();
        if (!name) {
            App.showProjectCreateStatus("请输入项目名称", true);
            return;
        }
        var description = descInput ? (descInput.value || "").trim() : "";
        App.setProjectCreateCreating(true);
        App.clearProjectCreateStatus();
        App.callBridge("create_project_for_rules", name, description).then(function (result) {
            if (result && result.ok === false) {
                App.showProjectCreateStatus(result.error || "新增项目失败", true);
                return;
            }
            input.value = "";
            if (descInput) descInput.value = "";
            App.clearProjectCreateStatus();
            return App.loadProjectRules().then(function () {
                App.showProjectCreateStatus("项目已新增", false);
            });
        }).catch(function () {
            App.showProjectCreateStatus("新增项目失败", true);
        }).then(function () {
            App.setProjectCreateCreating(false);
        });
    }
    App.handleProjectCreateSubmit = handleProjectCreateSubmit;

    function bindProjectLifecycleEvents() {
        // Phase 5G: event-delegated binding for project edit / toggle /
        // archive / edit-save / edit-cancel. Re-uses the same #rules-list
        // container as the other rule bindings so no extra per-card
        // listeners are needed. Bound once per page lifecycle via the data
        // attribute guard.
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-project-lifecycle-bound") === "1") return;
        list.setAttribute("data-rules-project-lifecycle-bound", "1");
        list.addEventListener("click", App.handleProjectLifecycleEvent);
    }
    App.bindProjectLifecycleEvents = bindProjectLifecycleEvents;

    function handleProjectLifecycleEvent(event) {
        // Phase 5G: single delegated click handler for all project lifecycle
        // operations (edit start, edit save, edit cancel, toggle, archive).
        // Routes to the matching sub-handler based on the button class. The
        // catch path never reads .message.
        var button = event.target && event.target.closest ? event.target.closest("button") : null;
        if (!button) return;
        if (button.classList.contains("rules-project-edit-button")) {
            App.handleProjectEditStart(button);
            return;
        }
        if (button.classList.contains("rules-project-edit-save")) {
            App.handleProjectEditSave(button);
            return;
        }
        if (button.classList.contains("rules-project-edit-cancel")) {
            App.handleProjectEditCancel(button);
            return;
        }
        if (button.classList.contains("rules-project-toggle-button")) {
            App.handleProjectToggle(button);
            return;
        }
        if (button.classList.contains("rules-project-archive-button")) {
            App.handleProjectArchive(button);
            return;
        }
    }
    App.handleProjectLifecycleEvent = handleProjectLifecycleEvent;

    function _parseProjectId(button) {
        var rawId = button.getAttribute("data-project-id");
        var projectId = parseInt(rawId, 10);
        if (!rawId || String(projectId) !== String(rawId).trim() || projectId <= 0) {
            return 0;
        }
        return projectId;
    }

    function handleProjectEditStart(button) {
        // Phase 5G: enter inline edit mode for one user project. Only one
        // project edit may be in flight at a time. Setting the editing id
        // triggers a re-render of that card into the edit form.
        if (App.rulesEditingProjectId) return;
        if (App.rulesUpdatingProjectId) return;
        var projectId = _parseProjectId(button);
        if (!projectId) {
            App.showRulesError("保存项目失败");
            return;
        }
        App.setProjectEditing(projectId);
        App.clearRulesError();
    }
    App.handleProjectEditStart = handleProjectEditStart;

    function handleProjectEditSave(button) {
        // Phase 5G: save the inline project edit. Validates the edited name
        // locally, then calls the bridge. On success the editing state
        // clears and the Project Rules list refreshes; on failure the
        // editing form is preserved so the user can retry. The catch path
        // never reads .message.
        if (!App.rulesEditingProjectId) return;
        var projectId = _parseProjectId(button);
        if (!projectId || projectId !== App.rulesEditingProjectId) {
            App.showRulesError("保存项目失败");
            return;
        }
        var card = button.closest(".rules-project-card");
        var nameInput = card ? card.querySelector(".rules-project-edit-name") : null;
        var descInput = card ? card.querySelector(".rules-project-edit-description") : null;
        if (!nameInput) {
            App.showRulesError("保存项目失败");
            return;
        }
        var name = (nameInput.value || "").trim();
        if (!name) {
            App.showRulesError("请输入项目名称");
            return;
        }
        var description = descInput ? (descInput.value || "").trim() : "";
        App.setProjectSaving(projectId);
        App.clearRulesError();
        App.callBridge("update_project_for_rules", projectId, name, description).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "保存项目失败");
                return;
            }
            App.setProjectEditing(null);
            return App.loadProjectRules().then(function () {
                App.showRulesError("项目已保存");
            });
        }).catch(function () {
            App.showRulesError("保存项目失败");
        }).then(function () {
            App.setProjectSaving(null);
        });
    }
    App.handleProjectEditSave = handleProjectEditSave;

    function handleProjectEditCancel(button) {
        // Phase 5G: cancel the inline project edit. Just clears the editing
        // state and re-renders. No bridge call is made.
        if (!App.rulesEditingProjectId) return;
        App.setProjectEditing(null);
        App.clearRulesError();
    }
    App.handleProjectEditCancel = handleProjectEditCancel;

    function handleProjectToggle(button) {
        // Phase 5G: enable/disable one user project. Validates the project
        // id locally, then calls the bridge. On success the Project Rules
        // list refreshes; on failure the rendered list is kept. The catch
        // path never reads .message.
        if (App.rulesTogglingProjectId) return;
        var projectId = _parseProjectId(button);
        if (!projectId) {
            App.showRulesError("更新项目状态失败");
            return;
        }
        // Determine the next enabled state from the cached data so the
        // user sees the correct confirmation message.
        var nextEnabled = true;
        var projects = (App.lastProjectRulesData && App.lastProjectRulesData.projects) || [];
        for (var i = 0; i < projects.length; i++) {
            if (projects[i] && projects[i].id === projectId) {
                nextEnabled = !projects[i].enabled;
                break;
            }
        }
        if (!nextEnabled && !window.confirm("确定停用这个项目吗？停用后它将不再用于自动归类。")) {
            return;
        }
        App.setProjectToggling(projectId);
        App.clearRulesError();
        App.callBridge("set_project_enabled_for_rules", projectId, nextEnabled).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "更新项目状态失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.showRulesError("项目状态已更新");
            });
        }).catch(function () {
            App.showRulesError("更新项目状态失败");
        }).then(function () {
            App.setProjectToggling(null);
        });
    }
    App.handleProjectToggle = handleProjectToggle;

    function handleProjectArchive(button) {
        // Phase 5G: archive one user project. Confirms first, then
        // validates the project id locally before calling the bridge. On
        // success the Project Rules list refreshes; on failure the rendered
        // list is kept. The catch path never reads .message.
        if (App.rulesArchivingProjectId) return;
        var projectId = _parseProjectId(button);
        if (!projectId) {
            App.showRulesError("归档项目失败");
            return;
        }
        if (!window.confirm("确定归档这个项目吗？归档后它将不再用于自动归类，但项目及其规则不会被删除。")) {
            return;
        }
        App.setProjectArchiving(projectId);
        App.clearRulesError();
        App.callBridge("archive_project_for_rules", projectId).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "归档项目失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.showRulesError("项目已归档");
            });
        }).catch(function () {
            App.showRulesError("归档项目失败");
        }).then(function () {
            App.setProjectArchiving(null);
        });
    }
    App.handleProjectArchive = handleProjectArchive;

    function setProjectEditing(projectId) {
        // Phase 5G: enter / leave inline edit mode for one user project.
        // Setting the id triggers a re-render of the list from cached data
        // so the edit form appears / disappears immediately.
        App.rulesEditingProjectId = projectId || null;
        App.rerenderProjectRulesList();
    }
    App.setProjectEditing = setProjectEditing;

    function setProjectSaving(projectId) {
        // Phase 5G: toggle the in-flight state for a project edit save.
        // Flips the save / cancel button disabled state on the edit form
        // so the user cannot double-submit. State is separate from the
        // editing id (which stays set until success clears it).
        App.rulesUpdatingProjectId = projectId || null;
        var saveButtons = document.querySelectorAll(".rules-project-edit-save");
        var cancelButtons = document.querySelectorAll(".rules-project-edit-cancel");
        Array.prototype.forEach.call(saveButtons, function (btn) {
            btn.disabled = !!App.rulesUpdatingProjectId;
            if (App.rulesUpdatingProjectId) btn.textContent = "正在保存…";
            else btn.textContent = "保存";
        });
        Array.prototype.forEach.call(cancelButtons, function (btn) {
            btn.disabled = !!App.rulesUpdatingProjectId;
        });
    }
    App.setProjectSaving = setProjectSaving;

    function setProjectToggling(projectId) {
        // Phase 5G: toggle the project enable/disable saving state. Updates
        // every project lifecycle button disabled state so the four write
        // paths cannot run concurrently.
        App.rulesTogglingProjectId = projectId || null;
        _refreshProjectLifecycleButtons();
    }
    App.setProjectToggling = setProjectToggling;

    function setProjectArchiving(projectId) {
        // Phase 5G: toggle the project archive saving state. Updates every
        // project lifecycle button disabled state so the four write paths
        // cannot run concurrently.
        App.rulesArchivingProjectId = projectId || null;
        _refreshProjectLifecycleButtons();
    }
    App.setProjectArchiving = setProjectArchiving;

    function _refreshProjectLifecycleButtons() {
        // Phase 5G: internal helper that disables all project lifecycle
        // buttons while any project lifecycle write is in flight, and
        // flips the matching button's label to its in-progress text.
        var writeInProgress = !!(
            App.rulesCreatingProject ||
            App.rulesEditingProjectId ||
            App.rulesUpdatingProjectId ||
            App.rulesTogglingProjectId ||
            App.rulesArchivingProjectId
        );
        var toggleButtons = document.querySelectorAll(".rules-project-toggle-button");
        Array.prototype.forEach.call(toggleButtons, function (button) {
            var pid = parseInt(button.getAttribute("data-project-id"), 10);
            button.disabled = writeInProgress;
            if (pid === App.rulesTogglingProjectId) {
                button.textContent = "正在更新…";
            }
        });
        var archiveButtons = document.querySelectorAll(".rules-project-archive-button");
        Array.prototype.forEach.call(archiveButtons, function (button) {
            var pid = parseInt(button.getAttribute("data-project-id"), 10);
            button.disabled = writeInProgress;
            if (pid === App.rulesArchivingProjectId) {
                button.textContent = "正在归档…";
            }
        });
        var editButtons = document.querySelectorAll(".rules-project-edit-button");
        Array.prototype.forEach.call(editButtons, function (button) {
            button.disabled = writeInProgress;
        });
    }

})();
