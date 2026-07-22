// WorkTrace WebView frontend — unified Project Rules deletion.
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
            ? event.target.closest(".rules-keyword-delete-button") : null;
        if (!button) return;
        var ruleId = parseInt(button.getAttribute("data-rule-id"), 10);
        if (ruleId > 0) openProjectRuleDeleteModal("keyword", ruleId, button);
    }
    App.handleProjectRuleDelete = handleProjectRuleDelete;

    function openProjectRuleDeleteModal(kind, ruleId, trigger) {
        if (!App.openDeleteDialog || App.rulesDeletingRuleKey || App.rulesDeletingFolderKey) return;
        App.openDeleteDialog({
            trigger: trigger,
            title: "删除规则",
            objectLabel: kind === "folder" ? "当前文件夹规则" : "当前关键词规则",
            warning: "规则删除后不再参与后续自动归类；既有历史归属保持不变。",
            twoStep: false,
            confirmLabel: "删除规则"
        }).then(function (confirmed) {
            if (confirmed) deleteRule(kind, ruleId, false);
        });
    }
    App.openProjectRuleDeleteModal = openProjectRuleDeleteModal;

    function deleteRule(kind, ruleId, applyToHistory) {
        App.setRuleDeleting("keyword:" + ruleId);
        if (kind === "folder" && App.setFolderDeleting) App.setFolderDeleting("folder:" + ruleId);
        App.clearRulesError();
        var request = kind === "folder"
            ? App.bridge.deleteProjectFolderRule(ruleId, applyToHistory)
            : App.bridge.deleteProjectKeywordRule(ruleId, applyToHistory);
        request.then(function (result) {
            if (result && result.ok === false) { App.showRulesError(result.error || "删除规则失败"); return; }
            return App.loadProjectRules().then(function () {
                App.clearRulesError();
                if (App.showToast) App.showToast("规则已删除，历史记录保持不变");
            });
        }).catch(function () { App.showRulesError("删除规则失败"); }).finally(function () {
            App.setRuleDeleting(null);
            if (App.setFolderDeleting) App.setFolderDeleting(null);
        });
    }

    function setRuleDeleting(ruleKey) {
        App.rulesDeletingRuleKey = ruleKey || null;
        var buttons = document.querySelectorAll(".rules-keyword-delete-button");
        Array.prototype.forEach.call(buttons, function (button) {
            button.disabled = !!App.rulesDeletingRuleKey;
            button.textContent = "删除";
        });
    }
    App.setRuleDeleting = setRuleDeleting;
})();
