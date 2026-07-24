// WorkTrace WebView frontend - folder rule delete.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function bindProjectRuleFolderEvents() {
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-folder-bound") === "1") return;
        list.setAttribute("data-rules-folder-bound", "1");
        list.addEventListener("click", App.handleProjectRuleFolderEvent);
    }
    App.bindProjectRuleFolderEvents = bindProjectRuleFolderEvents;

    function handleProjectRuleFolderEvent(event) {
        var button = event.target && event.target.closest
            ? event.target.closest(".rules-folder-delete-button")
            : null;
        if (!button) return;
        handleFolderDelete(button);
    }
    App.handleProjectRuleFolderEvent = handleProjectRuleFolderEvent;

    function handleFolderDelete(button) {
        if (App.rulesDeletingFolderKey) return;
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
        if (App.openProjectRuleDeleteModal) App.openProjectRuleDeleteModal("folder", ruleId, button);
    }
    App.handleFolderDelete = handleFolderDelete;

    function setFolderDeleting(folderKey) {
        App.rulesDeletingFolderKey = folderKey || null;
        var buttons = document.querySelectorAll(".rules-folder-delete-button");
        Array.prototype.forEach.call(buttons, function (button) {
            var currentKey = "folder:" + button.getAttribute("data-rule-id");
            var busy = currentKey === App.rulesDeletingFolderKey;
            button.disabled = !!App.rulesDeletingFolderKey;
            button.classList.toggle("is-busy", busy);
            button.setAttribute("aria-label", busy ? "正在删除规则" : "删除规则");
            button.setAttribute("data-tooltip", busy ? "正在删除" : "删除规则");
        });
    }
    App.setFolderDeleting = setFolderDeleting;

})();
