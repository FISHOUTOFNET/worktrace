// WorkTrace WebView frontend - keyword rule delete.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function bindProjectRuleDelete() {
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-delete-bound") === "1") return;
        list.setAttribute("data-rules-delete-bound", "1");
        list.addEventListener("click", App.handleProjectRuleDelete);
    }
    App.bindProjectRuleDelete = bindProjectRuleDelete;

    function handleProjectRuleDelete(event) {
        var button = event.target && event.target.closest
            ? event.target.closest(".rules-keyword-delete-button")
            : null;
        if (!button) return;
        if (App.rulesDeletingRuleKey) return;
        var kind = button.getAttribute("data-rule-kind");
        if (kind !== "keyword") {
            App.showRulesError("删除关键词规则失败");
            return;
        }
        var rawId = button.getAttribute("data-rule-id");
        var ruleId = parseInt(rawId, 10);
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
        App.rulesDeletingRuleKey = ruleKey || null;
        var buttons = document.querySelectorAll(".rules-keyword-delete-button");
        Array.prototype.forEach.call(buttons, function (button) {
            var currentKey = "keyword:" + button.getAttribute("data-rule-id");
            button.disabled = !!App.rulesDeletingRuleKey;
            button.textContent = currentKey === App.rulesDeletingRuleKey ? "正在删除..." : "删除";
        });
    }
    App.setRuleDeleting = setRuleDeleting;

})();
