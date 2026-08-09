// WorkTrace shared UI primitives: focus management, Drawer, Dialog, Toast, and concise presentation copy.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var dialogLayer = document.getElementById("confirm-dialog-layer");
    var dialog = document.getElementById("confirm-dialog");
    var dialogTitle = document.getElementById("confirm-dialog-title");
    var dialogBody = document.getElementById("confirm-dialog-body");
    var dialogPrimary = document.getElementById("confirm-dialog-primary");
    var dialogSecondary = document.getElementById("confirm-dialog-secondary");
    var dialogState = null;
    var toastTimer = null;
    var conciseCopyObservers = [];

    function compactPageHeader(pageSelector) {
        var header = document.querySelector(pageSelector + " .page-header");
        if (!header) return;
        var subtitle = header.querySelector("p");
        if (subtitle) subtitle.hidden = true;
        header.style.alignItems = "center";
    }

    function hideSelector(selector) {
        var target = document.querySelector(selector);
        if (target) target.hidden = true;
    }

    function setSelectorText(selector, text) {
        var target = document.querySelector(selector);
        if (target) target.textContent = text;
    }

    function hideEmptyStateDetails(container) {
        if (!container) return;
        var details = container.querySelectorAll(".empty-state span");
        Array.prototype.forEach.call(details, function (detail) {
            detail.hidden = true;
        });
    }

    function applyStaticConciseCopy() {
        compactPageHeader("#page-overview");
        compactPageHeader("#page-timeline");
        compactPageHeader("#page-rules");
        compactPageHeader("#page-settings");
        setSelectorText("#page-statistics .page-header p", "仅统计已完成时段");
        setSelectorText("#timeline-readonly-notice", "进行中时段不可编辑");

        var readonlyHint = document.getElementById("rules-readonly-hint");
        if (readonlyHint) {
            readonlyHint.textContent = "";
            readonlyHint.hidden = true;
        }
        var fdWorkHelp = document.getElementById("rules-panel-fd-work-help");
        if (fdWorkHelp) {
            fdWorkHelp.textContent = "";
            fdWorkHelp.hidden = true;
        }

        hideSelector("#rules-panel-folder-recursive small");
        hideSelector('label[for="settings-launch-at-login-toggle"] small');
        hideSelector("#settings-privacy-card small");
        hideSelector('label[for="settings-fd-work-toggle"] small');
        hideSelector("#settings-storage-card small");
        hideSelector("#settings-section-data .maintenance-section > h3 + p");
        setSelectorText("#settings-danger-card small", "此操作不可撤销。");
        setSelectorText("#settings-section-advanced details > summary", "技术诊断");

        var statsScopeRow = document.querySelector(".stats-scope-row");
        if (statsScopeRow) statsScopeRow.hidden = true;

        hideEmptyStateDetails(document.getElementById("recent-list"));
        hideEmptyStateDetails(document.getElementById("timeline-details-list"));
    }

    function normalizeIdentityStatus() {
        var target = document.getElementById("rules-panel-fd-work-status");
        if (!target) return;
        var current = String(target.textContent || "").trim();
        var replacements = {
            "本地项目": "",
            "将作为本地项目保存": "",
            "本地项目；也可选择 FD Work 案件": "",
            "已取消 FD Work 关联，将作为本地项目保存": "已取消 FD Work 关联",
            "正在打开 FD Work 案件选择器……": "正在打开案件选择器…",
            "请在 FD Work 原生案件框中选择并确认": "请在 FD Work 中选择案件",
            "请在 FD Work 窗口完成登录并选择案件": "请登录 FD Work 并选择案件"
        };
        var next = Object.prototype.hasOwnProperty.call(replacements, current)
            ? replacements[current] : current;
        if (next !== current) target.textContent = next;
        target.hidden = !next;
    }

    function normalizeTimelineFDWorkStatus() {
        var button = document.getElementById("fd-work-entry-btn");
        var status = document.getElementById("fd-work-status");
        if (!button || !status) return;
        if (String(button.textContent || "").trim() === "非 FD Work 项目"
                && String(status.textContent || "").trim() === "此项目未关联 FD Work") {
            status.textContent = "";
            status.hidden = true;
        }
    }

    function normalizeRulesProjectContext() {
        var target = document.getElementById("rules-panel-project-context");
        if (!target) return;
        var current = String(target.textContent || "").trim();
        if (current.indexOf("项目已新增：") === 0) target.textContent = "项目已新增";
    }

    function observeConciseCopy(target, options, callback) {
        if (!target || typeof MutationObserver !== "function") return;
        var observer = new MutationObserver(function () { callback(); });
        observer.observe(target, options);
        conciseCopyObservers.push(observer);
    }

    function installConciseCopyObservers() {
        var identityStatus = document.getElementById("rules-panel-fd-work-status");
        observeConciseCopy(identityStatus, { childList: true, characterData: true, subtree: true }, normalizeIdentityStatus);

        var fdWorkStatus = document.getElementById("fd-work-status");
        var fdWorkButton = document.getElementById("fd-work-entry-btn");
        observeConciseCopy(fdWorkStatus, { childList: true, characterData: true, subtree: true }, normalizeTimelineFDWorkStatus);
        observeConciseCopy(fdWorkButton, { childList: true, characterData: true, subtree: true }, normalizeTimelineFDWorkStatus);

        var rulesContext = document.getElementById("rules-panel-project-context");
        observeConciseCopy(rulesContext, { childList: true, characterData: true, subtree: true }, normalizeRulesProjectContext);

        var recentList = document.getElementById("recent-list");
        observeConciseCopy(recentList, { childList: true, subtree: true }, function () {
            hideEmptyStateDetails(recentList);
        });
        var detailList = document.getElementById("timeline-details-list");
        observeConciseCopy(detailList, { childList: true, subtree: true }, function () {
            hideEmptyStateDetails(detailList);
        });
    }

    function applyConciseCopyPolicy() {
        applyStaticConciseCopy();
        normalizeIdentityStatus();
        normalizeTimelineFDWorkStatus();
        normalizeRulesProjectContext();
    }
    App.applyConciseCopyPolicy = applyConciseCopyPolicy;

    function isWithinHiddenAncestor(element) {
        var node = element;
        while (node && node !== document.body) {
            if (node.hidden) return true;
            if (node.getAttribute && node.getAttribute("aria-hidden") === "true") return true;
            node = node.parentNode;
        }
        return false;
    }

    function hasVisibleLayoutBox(element) {
        if (typeof element.getClientRects === "function") {
            try {
                if (element.getClientRects().length === 0) return false;
            } catch (error) {
                // Fall through to offsetParent fallback for test environments.
            }
        } else if (typeof element.offsetParent !== "undefined") {
            return element.offsetParent !== null;
        }
        return true;
    }

    function focusable(container) {
        if (!container) return [];
        return Array.prototype.slice.call(container.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), '
            + 'textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
        )).filter(function (element) {
            return !isWithinHiddenAncestor(element) && hasVisibleLayoutBox(element);
        });
    }
    App.focusableElements = focusable;

    function trapFocus(event, container) {
        if (event.key !== "Tab") return;
        var items = focusable(container);
        if (!items.length) return;
        var first = items[0];
        var last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }
    App.trapFocus = trapFocus;

    function restoreFocus(target) {
        if (target && document.documentElement.contains(target)
                && typeof target.focus === "function") target.focus();
    }

    App.openManagedDrawer = function (layer, trigger, initialFocus, options) {
        if (!layer) return;
        options = typeof options === "function" ? { requestClose: options } : (options || {});
        layer._returnFocus = trigger || document.activeElement;
        layer._requestClose = typeof options.requestClose === "function"
            ? options.requestClose : null;
        layer.hidden = false;
        var target = initialFocus || focusable(layer)[0];
        if (target) target.focus();
    };

    App.closeManagedDrawer = function (layer, options) {
        if (!layer) return;
        options = options || {};
        var target = layer._returnFocus;
        layer.hidden = true;
        layer._returnFocus = null;
        layer._requestClose = null;
        if (options.restoreFocus !== false) restoreFocus(target);
    };

    function normalizedDialogChoices(options) {
        if (!Array.isArray(options.choices)) return [];
        return options.choices.filter(function (choice) {
            return choice && typeof choice.value === "string" && choice.value
                && typeof choice.label === "string" && choice.label;
        });
    }

    function renderDialogChoices(options) {
        var choices = normalizedDialogChoices(options);
        if (!choices.length) return;
        var group = document.createElement("div");
        group.className = "field";
        group.setAttribute("role", "radiogroup");
        choices.forEach(function (choice, index) {
            var row = document.createElement("label");
            row.className = "checkbox-row";
            var input = document.createElement("input");
            input.type = "radio";
            input.name = "confirm-dialog-choice";
            input.value = choice.value;
            var selected = dialogState.choice || options.defaultChoice || choices[0].value;
            input.checked = choice.value === selected;
            if (input.checked) dialogState.choice = choice.value;
            input.addEventListener("change", function () {
                if (input.checked && dialogState) dialogState.choice = choice.value;
            });
            var copy = document.createElement("span");
            copy.className = "field";
            var title = document.createElement("strong");
            title.textContent = choice.label;
            copy.appendChild(title);
            if (choice.description) {
                var description = document.createElement("span");
                description.className = "field-hint";
                description.textContent = String(choice.description);
                copy.appendChild(description);
            }
            row.appendChild(input);
            row.appendChild(copy);
            group.appendChild(row);
            if (index === 0 && !dialogState.choice) dialogState.choice = choice.value;
        });
        dialogBody.appendChild(group);
    }

    function renderDialogStep() {
        if (!dialogState) return;
        var options = dialogState.options;
        var second = dialogState.step === 2;
        dialogTitle.textContent = second
            ? (options.secondTitle || "再次确认操作")
            : (options.title || "确认操作");
        dialogBody.innerHTML = "";
        if (second) {
            var secondIntro = document.createElement("p");
            secondIntro.textContent = options.secondIntro || "即将执行：";
            dialogBody.appendChild(secondIntro);
        }
        if (options.objectLabel) {
            var object = document.createElement("div");
            object.className = "dialog-object";
            object.textContent = options.objectLabel;
            dialogBody.appendChild(object);
        }
        if (!second && options.warning) {
            var warning = document.createElement("p");
            warning.className = "dialog-warning";
            warning.textContent = options.warning;
            dialogBody.appendChild(warning);
        }
        if (!second) renderDialogChoices(options);
        dialogSecondary.textContent = second ? "返回" : "取消";
        dialogPrimary.textContent = second
            ? (options.confirmLabel || "确认")
            : (options.twoStep === true ? "继续" : (options.confirmLabel || "确认"));
        dialogPrimary.classList.toggle(
            "danger",
            second || (options.twoStep !== true && options.danger === true)
        );
        dialogSecondary.focus();
    }

    function finishDialog(confirmed) {
        if (!dialogState) return;
        var state = dialogState;
        dialogState = null;
        dialogLayer.hidden = true;
        restoreFocus(state.returnFocus);
        if (!confirmed) {
            state.resolve(false);
            return;
        }
        var choices = normalizedDialogChoices(state.options);
        state.resolve(choices.length ? (state.choice || choices[0].value) : true);
    }

    function conciseConfirmOptions(options) {
        var normalized = Object.assign({}, options || {});
        if (String(normalized.title || "").indexOf("导入并替换") === 0) {
            normalized.objectLabel = "";
            normalized.warning = "当前数据将被备份替换，且不可撤销。";
        }
        return normalized;
    }

    App.openConfirmDialog = function (options) {
        options = conciseConfirmOptions(options);
        if (dialogState) return Promise.resolve(false);
        return new Promise(function (resolve) {
            dialogState = {
                options: options,
                step: 1,
                choice: options.defaultChoice || null,
                returnFocus: options.trigger || document.activeElement,
                resolve: resolve
            };
            dialogLayer.hidden = false;
            renderDialogStep();
        });
    };

    App.openDeleteDialog = function (options) {
        var normalized = Object.assign({}, options || {});
        var hasChoices = Array.isArray(normalized.choices) && normalized.choices.length > 0;
        if (!hasChoices) {
            normalized.warning = "此操作不可撤销。";
            normalized.secondIntro = "即将删除：";
        }
        if (typeof normalized.secondTitle === "string") {
            normalized.secondTitle = normalized.secondTitle.replace(/永久/g, "");
        }
        if (typeof normalized.confirmLabel === "string") {
            normalized.confirmLabel = normalized.confirmLabel.replace(/永久/g, "");
        }
        return App.openConfirmDialog(Object.assign({
            title: "确认删除",
            secondTitle: "再次确认删除",
            secondIntro: "即将删除：",
            confirmLabel: "确认删除",
            twoStep: true,
            danger: true
        }, normalized));
    };

    if (dialogPrimary) dialogPrimary.addEventListener("click", function () {
        if (!dialogState) return;
        if (dialogState.options.twoStep === true && dialogState.step === 1) {
            dialogState.step = 2;
            renderDialogStep();
            return;
        }
        finishDialog(true);
    });
    if (dialogSecondary) dialogSecondary.addEventListener("click", function () {
        if (!dialogState) return;
        if (dialogState.step === 2) {
            dialogState.step = 1;
            renderDialogStep();
            return;
        }
        finishDialog(false);
    });
    if (dialogLayer) dialogLayer.addEventListener("click", function (event) {
        if (event.target === dialogLayer) finishDialog(false);
    });

    function conciseToastMessage(message) {
        var text = String(message || "");
        if (text.indexOf("项目已永久删除") === 0) return "项目已删除";
        if (text.indexOf("规则已删除，") === 0) return "规则已删除";
        return text;
    }

    App.showToast = function (message) {
        var toast = document.getElementById("app-toast");
        if (!toast) return;
        clearTimeout(toastTimer);
        var copy = conciseToastMessage(message);
        toast.textContent = copy;
        toast.hidden = !copy;
        if (copy) toastTimer = setTimeout(function () {
            toast.hidden = true;
            toast.textContent = "";
        }, 3200);
    };

    document.addEventListener("keydown", function (event) {
        if (dialogState) {
            if (event.key === "Escape") {
                event.preventDefault();
                finishDialog(false);
                return;
            }
            trapFocus(event, dialog);
            return;
        }
        var drawer = document.querySelector(".drawer-layer:not([hidden])");
        if (!drawer) return;
        if (event.key === "Escape") {
            event.preventDefault();
            if (typeof drawer._requestClose === "function") drawer._requestClose();
            else App.closeManagedDrawer(drawer);
            return;
        }
        trapFocus(event, drawer.querySelector(".drawer"));
    });

    applyStaticConciseCopy();
    document.addEventListener("DOMContentLoaded", function () {
        applyConciseCopyPolicy();
        installConciseCopyObservers();
    });
})();
