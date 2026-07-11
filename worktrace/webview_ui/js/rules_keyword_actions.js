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
            return;
        }
        var rawId = button.getAttribute("data-rule-id");
        var ruleId = parseInt(rawId, 10);
        if (!rawId || String(ruleId) !== String(rawId).trim() || ruleId <= 0) {
            App.showRulesError("删除关键词规则失败");
            return;
        }
        App.openProjectRuleDeleteModal("keyword", ruleId);
    }
    App.handleProjectRuleDelete = handleProjectRuleDelete;

    function initProjectRuleDeleteModal() {
        var modal = document.getElementById("rules-delete-modal");
        if (!modal || modal.getAttribute("data-rules-delete-modal-bound") === "1") return;
        modal.setAttribute("data-rules-delete-modal-bound", "1");
        document.getElementById("rules-delete-cancel").addEventListener("click", closeModal);
        modal.addEventListener("click", function (event) {
            if (event.target && event.target.getAttribute("data-rules-delete-close") === "1") closeModal();
        });
        document.getElementById("rules-delete-confirm").addEventListener("click", confirmDelete);
    }

    function openProjectRuleDeleteModal(kind, ruleId) {
        initProjectRuleDeleteModal();
        var modal = document.getElementById("rules-delete-modal");
        if (!modal || App.rulesDeletingRuleKey || App.rulesDeletingFolderKey) return;
        App.rulesDeleteModalRule = { kind: kind, id: ruleId };
        var checkbox = document.getElementById("rules-delete-history");
        if (checkbox) checkbox.checked = false;
        modal.hidden = false;
    }
    App.openProjectRuleDeleteModal = openProjectRuleDeleteModal;

    function closeModal() {
        var modal = document.getElementById("rules-delete-modal");
        if (modal) modal.hidden = true;
        App.rulesDeleteModalRule = null;
    }

    function confirmDelete() {
        var pending = App.rulesDeleteModalRule;
        if (!pending) return;
        var checkbox = document.getElementById("rules-delete-history");
        var applyToHistory = checkbox ? !!checkbox.checked : false;
        closeModal();
        deleteRule(pending.kind, pending.id, applyToHistory);
    }

    function deleteRule(kind, ruleId, applyToHistory) {
        App.setRuleDeleting("keyword:" + ruleId);
        if (kind === "folder" && App.setFolderDeleting) App.setFolderDeleting("folder:" + ruleId);
        App.clearRulesError();
        var method = kind === "folder" ? "delete_project_folder_rule" : "delete_project_keyword_rule";
        App.callBridge(method, ruleId, applyToHistory).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "删除规则失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.showRulesError(applyToHistory ? "规则已删除，并已更新受影响的历史记录。" : "规则已删除，历史记录保持不变。");
            });
        }).catch(function () {
            App.showRulesError("删除规则失败");
        }).then(function () {
            App.setRuleDeleting(null);
            if (App.setFolderDeleting) App.setFolderDeleting(null);
        });
    }

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
