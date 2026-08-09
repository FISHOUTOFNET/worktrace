// WorkTrace WebView frontend — rule history backfill and per-rule enabled state.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    App.rulesTogglingRuleKey = App.rulesTogglingRuleKey || null;

    function backfillCreatedRule(ruleType, ruleId) {
        if (ruleType !== "folder" && ruleType !== "keyword") return Promise.resolve(false);
        var parsedId = parseInt(ruleId, 10);
        if (!(parsedId > 0)) return Promise.resolve(false);
        App.rulesBackfillingRuleKey = ruleType + ":" + parsedId;
        return App.bridge.backfillProjectRule(ruleType, parsedId).then(function (result) {
            return !(result && result.ok === false);
        }).catch(function () {
            return false;
        }).then(function (ok) {
            App.rulesBackfillingRuleKey = null;
            return ok;
        });
    }
    App.backfillCreatedRule = backfillCreatedRule;

    function bindProjectRuleEnabledEvents() {
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-enabled-bound") === "1") return;
        list.setAttribute("data-rules-enabled-bound", "1");
        list.addEventListener("change", handleProjectRuleEnabledChange);
    }
    App.bindProjectRuleEnabledEvents = bindProjectRuleEnabledEvents;

    function handleProjectRuleEnabledChange(event) {
        var input = event.target && event.target.closest
            ? event.target.closest(".rules-rule-enabled-toggle") : null;
        if (!input) return;
        var ruleType = String(input.getAttribute("data-rule-kind") || "");
        var rawId = String(input.getAttribute("data-rule-id") || "").trim();
        var ruleId = parseInt(rawId, 10);
        var enabled = !!input.checked;
        if ((ruleType !== "folder" && ruleType !== "keyword")
                || !(ruleId > 0) || String(ruleId) !== rawId) {
            input.checked = !enabled;
            if (App.showRulesError) App.showRulesError("更新规则状态失败");
            return;
        }
        setProjectRuleEnabled(ruleType, ruleId, enabled, input);
    }
    App.handleProjectRuleEnabledChange = handleProjectRuleEnabledChange;

    function setProjectRuleEnabled(ruleType, ruleId, enabled, input) {
        if (App.rulesTogglingRuleKey) {
            if (input) input.checked = !enabled;
            return Promise.resolve(false);
        }
        var key = ruleType + ":" + ruleId;
        setRuleToggling(key);
        if (App.clearRulesError) App.clearRulesError();
        return App.bridge.setProjectRuleEnabled(ruleType, ruleId, enabled).then(function (result) {
            if (!result || result.ok === false) {
                if (input) input.checked = !enabled;
                if (App.showRulesError) App.showRulesError(
                    (result && result.error) || "更新规则状态失败"
                );
                return false;
            }
            return App.loadProjectRules().then(function () {
                if (App.clearRulesError) App.clearRulesError();
                if (App.showToast) App.showToast(
                    enabled
                        ? "规则已启用；已有历史归类保持不变"
                        : "规则已停用；已有历史归类保持不变"
                );
                return true;
            });
        }).catch(function () {
            if (input) input.checked = !enabled;
            if (App.showRulesError) App.showRulesError("更新规则状态失败");
            return false;
        }).finally(function () {
            setRuleToggling(null);
        });
    }
    App.setProjectRuleEnabled = setProjectRuleEnabled;

    function setRuleToggling(ruleKey) {
        App.rulesTogglingRuleKey = ruleKey || null;
        var toggles = document.querySelectorAll(".rules-rule-enabled-toggle");
        Array.prototype.forEach.call(toggles, function (toggle) {
            toggle.disabled = !!App.rulesTogglingRuleKey;
        });
    }
    App.setRuleToggling = setRuleToggling;

    bindProjectRuleEnabledEvents();
})();
