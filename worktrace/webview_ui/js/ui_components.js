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
        if (header.style) header.style.alignItems = "center";
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

    function normalizeOptionRow(input, labelText) {
        if (!input) return;
        var row = input.closest ? input.closest("label") : input.parentElement;
        if (!row) return;
        if (row.style) {
            row.style.display = "flex";
            row.style.alignItems = "center";
            row.style.gap = "8px";
            row.style.minHeight = "24px";
        }
        if (input.style) {
            input.style.width = "14px";
            input.style.height = "14px";
            input.style.minHeight = "0";
            input.style.flex = "0 0 14px";
            input.style.margin = "0";
        }
        var copy = row.querySelector && row.querySelector("span");
        if (copy && labelText) copy.textContent = labelText;
    }

    function normalizeRulesOptionRows() {
        var recursive = document.getElementById("rules-panel-folder-recursive");
        var recursiveRow = recursive && (recursive.closest ? recursive.closest("label") : recursive.parentElement);
        if (recursiveRow && recursiveRow.querySelector) {
            var small = recursiveRow.querySelector("small");
            if (small && small.parentNode) small.parentNode.removeChild(small);
        }
        normalizeOptionRow(recursive, "包含子文件夹");
        normalizeOptionRow(document.getElementById("rules-panel-backfill"), "应用到历史记录");
    }
    App.normalizeRulesOptionRows = normalizeRulesOptionRows;

    function stripRepeatedPrefix(target, prefix) {
        if (!target) return;
        var current = String(target.textContent || "").trim();
        if (current.indexOf(prefix) === 0) target.textContent = current.slice(prefix.length);
    }

    function normalizeSettingsStatusCopy() {
        stripRepeatedPrefix(
            document.querySelector('[data-settings-key="export_path_configured"]'),
            "导出目录："
        );
        stripRepeatedPrefix(
            document.getElementById("settings-privacy-notice-status"),
            "隐私说明："
        );
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

        normalizeRulesOptionRows();
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
        hideEmptyStateDetails(document.getElementById("rules-empty"));
        normalizeSettingsStatusCopy();
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
        var rulesEmpty = document.getElementById("rules-empty");
        observeConciseCopy(rulesEmpty, { childList: true, subtree: true }, function () {
            hideEmptyStateDetails(rulesEmpty);
        });
        observeConciseCopy(
            document.querySelector('[data-settings-key="export_path_configured"]'),
            { childList: true, characterData: true, subtree: true },
            normalizeSettingsStatusCopy
        );
        observeConciseCopy(
            document.getElementById("settings-privacy-notice-status"),
            { childList: true, characterData: true, subtree: true },
            normalizeSettingsStatusCopy
        );
    }

    function applyConciseCopyPolicy() {
        applyStaticConciseCopy();
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
        group.className = "dialog-choice-group";
        group.setAttribute("role", "radiogroup");
        if (group.style) {
            group.style.display = "grid";
            group.style.gap = "8px";
            group.style.marginTop = "8px";
        }
        choices.forEach(function (choice, index) {
            var row = document.createElement("label");
            row.className = "dialog-choice-row";
            if (row.style) {
                row.style.display = "grid";
                row.style.gridTemplateColumns = "14px minmax(0, 1fr)";
                row.style.gap = "8px";
                row.style.alignItems = "start";
                row.style.textAlign = "left";
            }
            var input = document.createElement("input");
            input.type = "radio";
            input.name = "confirm-dialog-choice";
            input.value = choice.value;
            if (input.style) {
                input.style.width = "14px";
                input.style.height = "14px";
                input.style.minHeight = "0";
                input.style.margin = "2px 0 0";
            }
            var selected = dialogState.choice || options.defaultChoice || choices[0].value;
            input.checked = choice.value === selected;
            if (input.checked) dialogState.choice = choice.value;
            input.addEventListener("change", function () {
                if (input.checked && dialogState) dialogState.choice = choice.value;
            });
            var copy = document.createElement("span");
            copy.className = "dialog-choice-copy";
            if (copy.style) {
                copy.style.minWidth = "0";
                copy.style.display = "grid";
                copy.style.gap = "2px";
                copy.style.lineHeight = "1.35";
            }
            var title = document.createElement("span");
            title.textContent = choice.label;
            if (title.style) title.style.fontWeight = "500";
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
            ? (options.secondTitle || "确认操作")
            : (options.title || "确认操作");
        dialogBody.innerHTML = "";
        if (second && options.secondIntro) {
            var secondIntro = document.createElement("p");
            secondIntro.textContent = options.secondIntro;
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

    function conciseDeleteConfirmLabel(label, fallback) {
        var text = String(label || fallback || "");
        text = text.replace(/永久/g, "").replace(/^再次确认/, "").replace(/^确认/, "");
        return text || fallback || "删除";
    }

    App.openDeleteDialog = function (options) {
        var normalized = Object.assign({}, options || {});
        var hasChoices = Array.isArray(normalized.choices) && normalized.choices.length > 0;
        var title = String(normalized.title || "确认删除");

        if (hasChoices && title === "删除规则") normalized.objectLabel = "";
        if (normalized.objectLabel === "当前选中的时间段"
                || normalized.objectLabel === "当前时间段中的这个活动") {
            normalized.objectLabel = "";
        }

        if (!hasChoices) {
            normalized.warning = "此操作不可撤销。";
            normalized.secondIntro = normalized.objectLabel ? "即将删除：" : "此操作不可撤销。";
        }

        var fallbackConfirm = title.indexOf("删除") === 0 ? title : "删除";
        normalized.confirmLabel = conciseDeleteConfirmLabel(
            normalized.confirmLabel,
            fallbackConfirm
        );
        if (normalized.twoStep === true) {
            normalized.secondTitle = String(normalized.secondTitle || ("确认" + fallbackConfirm))
                .replace(/永久/g, "")
                .replace(/^再次确认/, "确认");
        } else if (typeof normalized.secondTitle === "string") {
            normalized.secondTitle = normalized.secondTitle.replace(/永久/g, "");
        }

        return App.openConfirmDialog(Object.assign({
            title: "确认删除",
            secondTitle: "确认删除",
            secondIntro: "此操作不可撤销。",
            confirmLabel: "删除",
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

    applyConciseCopyPolicy();
    installConciseCopyObservers();
})();
