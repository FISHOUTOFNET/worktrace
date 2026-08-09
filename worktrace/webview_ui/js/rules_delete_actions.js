// WorkTrace WebView frontend — unified keyword/folder rule deletion.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function ruleButtonFromEvent(event) {
        var button = event.target && event.target.closest
            ? event.target.closest("button") : null;
        if (!button) return null;
        return button.classList.contains("rules-keyword-delete-button")
            || button.classList.contains("rules-folder-delete-button")
            ? button : null;
    }

    function ruleKind(button) {
        var declared = button.getAttribute("data-rule-kind");
        if (declared === "keyword" || declared === "folder") return declared;
        return button.classList.contains("rules-folder-delete-button") ? "folder" : "keyword";
    }

    function positiveRuleId(button) {
        var raw = String(button.getAttribute("data-rule-id") || "").trim();
        var parsed = parseInt(raw, 10);
        return raw && String(parsed) === raw && parsed > 0 ? parsed : 0;
    }

    function bindProjectRuleDeleteEvents() {
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-delete-bound") === "1") return;
        list.setAttribute("data-rules-delete-bound", "1");
        list.addEventListener("click", handleProjectRuleDeleteEvent);
    }
    App.bindProjectRuleDeleteEvents = bindProjectRuleDeleteEvents;

    function handleProjectRuleDeleteEvent(event) {
        var button = ruleButtonFromEvent(event);
        if (!button || App.rulesDeletingRuleKey) return;
        var kind = ruleKind(button);
        var ruleId = positiveRuleId(button);
        if (!ruleId) {
            App.showRulesError("删除规则失败");
            return;
        }
        openProjectRuleDeleteModal(kind, ruleId, button);
    }
    App.handleProjectRuleDeleteEvent = handleProjectRuleDeleteEvent;

    function openProjectRuleDeleteModal(kind, ruleId, trigger) {
        if (!App.openDeleteDialog || App.rulesDeletingRuleKey) return Promise.resolve(false);
        return App.openDeleteDialog({
            trigger: trigger,
            title: "删除规则",
            warning: "如何处理已有归类？",
            choices: [
                { value: "preserve", label: "保留已有归类" },
                { value: "restore", label: "视同规则不存在" }
            ],
            defaultChoice: "preserve",
            twoStep: false,
            danger: true,
            confirmLabel: "删除规则"
        }).then(function (historyMode) {
            if (!historyMode) return false;
            return deleteRule(kind, ruleId, historyMode === "restore");
        });
    }
    App.openProjectRuleDeleteModal = openProjectRuleDeleteModal;

    function deleteRule(kind, ruleId, restoreHistory) {
        setRuleDeleting(kind + ":" + ruleId);
        App.clearRulesError();
        var request = kind === "folder"
            ? App.bridge.deleteProjectFolderRule(ruleId, restoreHistory)
            : App.bridge.deleteProjectKeywordRule(ruleId, restoreHistory);
        return request.then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "删除规则失败");
                return false;
            }
            return App.loadProjectRules().then(function () {
                App.clearRulesError();
                if (App.showToast) App.showToast("规则已删除");
                return true;
            });
        }).catch(function () {
            App.showRulesError("删除规则失败");
            return false;
        }).finally(function () {
            setRuleDeleting(null);
        });
    }

    function setRuleDeleting(ruleKey) {
        App.rulesDeletingRuleKey = ruleKey || null;
        var buttons = document.querySelectorAll(
            ".rules-keyword-delete-button, .rules-folder-delete-button"
        );
        Array.prototype.forEach.call(buttons, function (button) {
            var currentKey = ruleKind(button) + ":" + button.getAttribute("data-rule-id");
            var busy = currentKey === App.rulesDeletingRuleKey;
            button.disabled = !!App.rulesDeletingRuleKey;
            button.classList.toggle("is-busy", busy);
            button.setAttribute("aria-label", busy ? "正在删除规则" : "删除规则");
            button.setAttribute("data-tooltip", busy ? "正在删除" : "删除规则");
        });
    }
    App.setRuleDeleting = setRuleDeleting;
})();
