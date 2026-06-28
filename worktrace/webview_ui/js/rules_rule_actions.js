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

})();
