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
            warning: "删除后，该规则将不再用于新的自动归类。请选择如何处理该规则已经产生的历史归类。",
            choices: [
                {
                    value: "preserve",
                    label: "保留已有归类",
                    description: "仅删除规则，不改变已经由该规则归类的历史时间。"
                },
                {
                    value: "restore",
                    label: "恢复原状",
                    description: "撤销当前规则产生的历史自动归类，并在排除该规则后按其他现有规则重新判断；没有其他规则匹配时恢复为“未归类”。手动修改过的归属不受影响。"
                }
            ],
            defaultChoice: "preserve",
            twoStep: false,
            danger: true,
            confirmLabel: "删除规则"
        }).then(function (historyMode) {
            if (!historyMode) return;
            deleteRule(kind, ruleId, historyMode === "restore");
        });
    }
    App.openProjectRuleDeleteModal = openProjectRuleDeleteModal;

    function deleteRule(kind, ruleId, restoreHistory) {
        App.setRuleDeleting("keyword:" + ruleId);
        if (kind === "folder" && App.setFolderDeleting) App.setFolderDeleting("folder:" + ruleId);
        App.clearRulesError();
        var request = kind === "folder"
            ? App.bridge.deleteProjectFolderRule(ruleId, restoreHistory)
            : App.bridge.deleteProjectKeywordRule(ruleId, restoreHistory);
        request.then(function (result) {
            if (result && result.ok === false) { App.showRulesError(result.error || "删除规则失败"); return; }
            return App.loadProjectRules().then(function () {
                App.clearRulesError();
                if (App.showToast) App.showToast(restoreHistory
                    ? "规则已删除，相关历史归类已恢复；无其他规则匹配的记录已变为未归类"
                    : "规则已删除，已有历史归类保持不变");
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
            var currentKey = "keyword:" + button.getAttribute("data-rule-id");
            var busy = currentKey === App.rulesDeletingRuleKey;
            button.disabled = !!App.rulesDeletingRuleKey;
            button.classList.toggle("is-busy", busy);
            button.setAttribute("aria-label", busy ? "正在删除规则" : "删除规则");
            button.setAttribute("data-tooltip", busy ? "正在删除" : "删除规则");
        });
    }
    App.setRuleDeleting = setRuleDeleting;
})();
