// WorkTrace WebView frontend - Project Rules rule toggle actions (Phase 5B, MC2 split).
// Existing rule enable/disable toggle via event delegation on #rules-list.
// Loaded after rules_render.js, before keyword / folder / project action modules.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Phase 5B: existing rule enable / disable toggle ----------------

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

    // --- Phase 5H: rule impact preview + safe single-rule backfill ------

    function bindProjectRuleImpactEvents() {
        var list = document.getElementById("rules-list");
        if (list && list.getAttribute("data-rules-impact-bound") !== "1") {
            list.setAttribute("data-rules-impact-bound", "1");
            list.addEventListener("click", handleProjectRuleImpactClick);
        }
        var panel = document.getElementById("rules-impact-panel");
        if (panel && panel.getAttribute("data-rules-impact-panel-bound") !== "1") {
            panel.setAttribute("data-rules-impact-panel-bound", "1");
            panel.addEventListener("click", handleProjectRuleImpactPanelClick);
        }
    }
    App.bindProjectRuleImpactEvents = bindProjectRuleImpactEvents;

    function handleProjectRuleImpactClick(event) {
        var target = event.target;
        if (!target || !target.closest) return;
        var previewBtn = target.closest(".rules-preview-impact-button");
        var backfillBtn = target.closest(".rules-backfill-button");
        if (previewBtn) {
            handleProjectRuleImpactPreview(previewBtn);
            return;
        }
        if (backfillBtn) {
            handleProjectRuleBackfill(backfillBtn);
            return;
        }
    }
    App.handleProjectRuleImpactClick = handleProjectRuleImpactClick;

    function handleProjectRuleImpactPanelClick(event) {
        var target = event.target;
        if (!target || !target.closest) return;
        var closeBtn = target.closest(".rules-impact-close-button");
        if (!closeBtn) return;
        clearProjectRuleImpactPanel();
    }
    App.handleProjectRuleImpactPanelClick = handleProjectRuleImpactPanelClick;

    function handleProjectRuleImpactPreview(button) {
        if (App.rulesPreviewingImpactKey || App.rulesBackfillingRuleKey) return;
        var ruleType = button.getAttribute("data-rule-kind");
        var ruleId = parseInt(button.getAttribute("data-rule-id"), 10);
        if ((ruleType !== "folder" && ruleType !== "keyword") || !ruleId) {
            App.showRulesError("预览规则影响失败");
            return;
        }
        var ruleKey = ruleType + ":" + ruleId;
        App.rulesPreviewingImpactKey = ruleKey;
        App.rulesImpactPreviewKey = null;
        App.rulesImpactPreviewData = null;
        App.rerenderProjectRulesList();
        App.clearRulesError();
        App.callBridge("preview_project_rule_impact", ruleType, ruleId).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "预览规则影响失败");
                return;
            }
            var impact = (result && result.impact) || {};
            App.rulesImpactPreviewKey = ruleKey;
            App.rulesImpactPreviewData = impact;
            showProjectRuleImpactPanel(ruleKey, impact);
        }).catch(function () {
            App.showRulesError("预览规则影响失败");
        }).then(function () {
            App.rulesPreviewingImpactKey = null;
            App.rerenderProjectRulesList();
        });
    }
    App.handleProjectRuleImpactPreview = handleProjectRuleImpactPreview;

    function handleProjectRuleBackfill(button) {
        if (App.rulesBackfillingRuleKey || App.rulesPreviewingImpactKey) return;
        var ruleType = button.getAttribute("data-rule-kind");
        var ruleId = parseInt(button.getAttribute("data-rule-id"), 10);
        if ((ruleType !== "folder" && ruleType !== "keyword") || !ruleId) {
            App.showRulesError("应用规则失败");
            return;
        }
        var ruleKey = ruleType + ":" + ruleId;
        var confirmed = window.confirm(
            "确定将这条规则应用到符合条件的历史记录吗？手动修改过的记录不会被覆盖。"
        );
        if (!confirmed) return;
        App.rulesBackfillingRuleKey = ruleKey;
        clearProjectRuleImpactPanel();
        App.rerenderProjectRulesList();
        App.clearRulesError();
        App.callBridge("backfill_project_rule", ruleType, ruleId).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "应用规则失败");
                return;
            }
            var backfillResult = (result && result.result) || {};
            showProjectRuleBackfillResult(ruleKey, backfillResult);
            return App.loadProjectRules().then(function () {
                App.showRulesError("规则已应用到历史记录");
            });
        }).catch(function () {
            App.showRulesError("应用规则失败");
        }).then(function () {
            App.rulesBackfillingRuleKey = null;
            App.rerenderProjectRulesList();
        });
    }
    App.handleProjectRuleBackfill = handleProjectRuleBackfill;

    function showProjectRuleImpactPanel(ruleKey, impact) {
        var panel = document.getElementById("rules-impact-panel");
        if (!panel) return;
        panel.innerHTML = App.renderProjectRuleImpactPreview(ruleKey, impact);
        panel.hidden = false;
    }
    App.showProjectRuleImpactPanel = showProjectRuleImpactPanel;

    function showProjectRuleBackfillResult(ruleKey, result) {
        var panel = document.getElementById("rules-impact-panel");
        if (!panel) return;
        panel.innerHTML = App.renderProjectRuleBackfillResult(ruleKey, result);
        panel.hidden = false;
    }
    App.showProjectRuleBackfillResult = showProjectRuleBackfillResult;

    function clearProjectRuleImpactPanel() {
        var panel = document.getElementById("rules-impact-panel");
        if (!panel) return;
        panel.innerHTML = "";
        panel.hidden = true;
        App.rulesImpactPreviewKey = null;
        App.rulesImpactPreviewData = null;
    }
    App.clearProjectRuleImpactPanel = clearProjectRuleImpactPanel;

    // --- Phase 5I: selected-rule batch operations ----------------------

    function bindProjectRuleBatchEvents() {
        // Phase 5I: bind delegated listeners for the batch toolbar buttons
        // (on #rules-batch-toolbar), the batch panel close button (on
        // #rules-batch-panel), and the per-row batch checkboxes (on
        // #rules-list). Each container is bound once (guarded by a
        // data-*-bound attribute) so re-renders of the inner HTML do not
        // double-bind.
        var list = document.getElementById("rules-list");
        if (list && list.getAttribute("data-rules-batch-checkbox-bound") !== "1") {
            list.setAttribute("data-rules-batch-checkbox-bound", "1");
            list.addEventListener("change", handleProjectRuleBatchCheckboxChange);
        }
        var toolbar = document.getElementById("rules-batch-toolbar");
        if (toolbar && toolbar.getAttribute("data-rules-batch-toolbar-bound") !== "1") {
            toolbar.setAttribute("data-rules-batch-toolbar-bound", "1");
            toolbar.addEventListener("click", handleProjectRuleBatchToolbarClick);
        }
        var panel = document.getElementById("rules-batch-panel");
        if (panel && panel.getAttribute("data-rules-batch-panel-bound") !== "1") {
            panel.setAttribute("data-rules-batch-panel-bound", "1");
            panel.addEventListener("click", handleProjectRuleBatchPanelClick);
        }
    }
    App.bindProjectRuleBatchEvents = bindProjectRuleBatchEvents;

    function handleProjectRuleBatchCheckboxChange(event) {
        // Phase 5I: delegated change handler for per-row batch checkboxes.
        // Toggles the selection in ``App.rulesBatchSelectedKeys`` (JS memory
        // only) and refreshes the toolbar so the selected count + button
        // disabled state update immediately. Refuses to act while any batch
        // operation is in flight (the checkbox should already be disabled,
        // but this is a defensive guard).
        var target = event.target;
        if (!target || !target.classList || !target.classList.contains("rules-batch-checkbox")) return;
        if (App.rulesBatchInFlight) return;
        var ruleType = target.getAttribute("data-rule-kind");
        var ruleId = parseInt(target.getAttribute("data-rule-id"), 10);
        if ((ruleType !== "folder" && ruleType !== "keyword") || !ruleId) return;
        var ruleKey = ruleType + ":" + ruleId;
        if (target.checked) {
            App.rulesBatchSelectedKeys[ruleKey] = true;
        } else {
            delete App.rulesBatchSelectedKeys[ruleKey];
        }
        App.refreshProjectRulesBatchToolbar();
    }
    App.handleProjectRuleBatchCheckboxChange = handleProjectRuleBatchCheckboxChange;

    function handleProjectRuleBatchToolbarClick(event) {
        // Phase 5I: delegated click handler for the batch toolbar buttons.
        var target = event.target;
        if (!target || !target.closest) return;
        if (target.closest(".rules-batch-preview-button")) {
            handleProjectRulesBatchPreview();
            return;
        }
        if (target.closest(".rules-batch-apply-button")) {
            handleProjectRulesBatchApply();
            return;
        }
        if (target.closest(".rules-batch-enable-button")) {
            handleProjectRulesBatchToggle(true);
            return;
        }
        if (target.closest(".rules-batch-disable-button")) {
            handleProjectRulesBatchToggle(false);
            return;
        }
        if (target.closest(".rules-batch-clear-button")) {
            handleProjectRulesBatchClear();
            return;
        }
    }
    App.handleProjectRuleBatchToolbarClick = handleProjectRuleBatchToolbarClick;

    function handleProjectRuleBatchPanelClick(event) {
        var target = event.target;
        if (!target || !target.closest) return;
        if (target.closest(".rules-batch-panel-close-button")) {
            clearProjectRulesBatchPanel();
        }
    }
    App.handleProjectRuleBatchPanelClick = handleProjectRuleBatchPanelClick;

    function getProjectRulesBatchSelectedRules() {
        // Returns a list of ``{rule_type, rule_id}`` dicts from the current
        // selection, in insertion order (Object.keys preserves insertion
        // order for string keys in modern JS engines). The bridge / API
        // re-validates and de-duplicates, so this is a best-effort
        // projection of the JS-side selection state.
        var rules = [];
        var keys = Object.keys(App.rulesBatchSelectedKeys || {});
        for (var i = 0; i < keys.length; i++) {
            var parts = keys[i].split(":");
            if (parts.length !== 2) continue;
            var ruleType = parts[0];
            var ruleId = parseInt(parts[1], 10);
            if ((ruleType !== "folder" && ruleType !== "keyword") || !ruleId) continue;
            rules.push({ rule_type: ruleType, rule_id: ruleId });
        }
        return rules;
    }
    App.getProjectRulesBatchSelectedRules = getProjectRulesBatchSelectedRules;

    function clearProjectRulesBatchSelection() {
        App.rulesBatchSelectedKeys = {};
        App.refreshProjectRulesBatchToolbar();
        App.rerenderProjectRulesList();
    }
    App.clearProjectRulesBatchSelection = clearProjectRulesBatchSelection;

    function handleProjectRulesBatchClear() {
        if (App.rulesBatchInFlight) return;
        App.rulesBatchSelectedKeys = {};
        App.refreshProjectRulesBatchToolbar();
        App.rerenderProjectRulesList();
    }
    App.handleProjectRulesBatchClear = handleProjectRulesBatchClear;

    function setProjectRulesBatchInFlight(flag) {
        App.rulesBatchInFlight = !!flag;
        App.refreshProjectRulesBatchToolbar();
        App.rerenderProjectRulesList();
    }
    App.setProjectRulesBatchInFlight = setProjectRulesBatchInFlight;

    function refreshProjectRulesBatchToolbar() {
        var toolbar = document.getElementById("rules-batch-toolbar");
        if (!toolbar) return;
        var selectedCount = Object.keys(App.rulesBatchSelectedKeys || {}).length;
        // Hide the toolbar entirely when there are no rules loaded at all
        // (the list is empty). Otherwise show it so the user can see the
        // selected count even when selection is empty.
        toolbar.innerHTML = App.renderProjectRulesBatchToolbar();
        toolbar.hidden = false;
        // The "no selection" state still shows the toolbar (with all action
        // buttons disabled) so the user knows the batch surface exists.
        // Hiding it only when the rules list itself is empty is handled in
        // rules.js showProjectRules.
        if (!App.lastProjectRulesData || !((App.lastProjectRulesData.projects || []).length)) {
            toolbar.hidden = true;
        } else {
            toolbar.hidden = false;
        }
        // Suppress unused-var lint: selectedCount is referenced inside
        // renderProjectRulesBatchToolbar via App.rulesBatchSelectedKeys.
        void selectedCount;
    }
    App.refreshProjectRulesBatchToolbar = refreshProjectRulesBatchToolbar;

    function showProjectRulesBatchPanel(data) {
        var panel = document.getElementById("rules-batch-panel");
        if (!panel) return;
        panel.innerHTML = App.renderProjectRulesBatchPanel(data);
        panel.hidden = false;
        App.rulesBatchPanelData = data;
    }
    App.showProjectRulesBatchPanel = showProjectRulesBatchPanel;

    function clearProjectRulesBatchPanel() {
        var panel = document.getElementById("rules-batch-panel");
        if (!panel) return;
        panel.innerHTML = "";
        panel.hidden = true;
        App.rulesBatchPanelData = null;
    }
    App.clearProjectRulesBatchPanel = clearProjectRulesBatchPanel;

    function handleProjectRulesBatchPreview() {
        if (App.rulesBatchInFlight) return;
        var rules = getProjectRulesBatchSelectedRules();
        if (!rules.length) {
            App.showRulesError("请先选择规则");
            return;
        }
        setProjectRulesBatchInFlight(true);
        clearProjectRulesBatchPanel();
        App.clearRulesError();
        App.callBridge("preview_project_rules_batch_impact", rules).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "批量预览失败");
                return;
            }
            var impact = (result && result.impact) || {};
            showProjectRulesBatchPanel({ mode: "preview", payload: impact });
        }).catch(function () {
            App.showRulesError("批量预览失败");
        }).then(function () {
            setProjectRulesBatchInFlight(false);
        });
    }
    App.handleProjectRulesBatchPreview = handleProjectRulesBatchPreview;

    function handleProjectRulesBatchApply() {
        if (App.rulesBatchInFlight) return;
        var rules = getProjectRulesBatchSelectedRules();
        if (!rules.length) {
            App.showRulesError("请先选择规则");
            return;
        }
        var confirmed = window.confirm(
            "确定将选中的规则应用到符合条件的历史记录吗？手动修改过的记录不会被覆盖；命中记录过多时不会写入。"
        );
        if (!confirmed) return;
        setProjectRulesBatchInFlight(true);
        clearProjectRulesBatchPanel();
        App.clearRulesError();
        App.callBridge("backfill_project_rules_batch", rules).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "批量应用失败");
                return;
            }
            var applyResult = (result && result.result) || {};
            showProjectRulesBatchPanel({ mode: "apply", payload: applyResult });
            // Phase 5I: clear selection on successful batch write so the
            // user must re-confirm before another batch write. Refresh the
            // list so the new project assignments are reflected.
            App.rulesBatchSelectedKeys = {};
            return App.loadProjectRules().then(function () {
                App.showRulesError("选中规则已应用到历史记录");
            });
        }).catch(function () {
            App.showRulesError("批量应用失败");
        }).then(function () {
            setProjectRulesBatchInFlight(false);
        });
    }
    App.handleProjectRulesBatchApply = handleProjectRulesBatchApply;

    function handleProjectRulesBatchToggle(enabled) {
        if (App.rulesBatchInFlight) return;
        var rules = getProjectRulesBatchSelectedRules();
        if (!rules.length) {
            App.showRulesError("请先选择规则");
            return;
        }
        var actionLabel = enabled ? "启用" : "停用";
        var confirmed = window.confirm(
            "确定" + actionLabel + "选中的规则吗？"
        );
        if (!confirmed) return;
        setProjectRulesBatchInFlight(true);
        clearProjectRulesBatchPanel();
        App.clearRulesError();
        App.callBridge("set_project_rules_batch_enabled", rules, enabled).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "批量操作失败");
                return;
            }
            var toggleResult = (result && result.result) || {};
            showProjectRulesBatchPanel({ mode: "toggle", payload: toggleResult });
            // Phase 5I: clear selection on successful batch write so the
            // user must re-confirm before another batch write. Refresh the
            // list so the new enabled states are reflected.
            App.rulesBatchSelectedKeys = {};
            return App.loadProjectRules().then(function () {
                App.showRulesError("选中规则已" + actionLabel);
            });
        }).catch(function () {
            App.showRulesError("批量操作失败");
        }).then(function () {
            setProjectRulesBatchInFlight(false);
        });
    }
    App.handleProjectRulesBatchToggle = handleProjectRulesBatchToggle;

})();
