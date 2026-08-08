// WorkTrace shared UI primitives: focus management, Drawer, Dialog, and Toast.
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

    App.openConfirmDialog = function (options) {
        options = options || {};
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
        options = options || {};
        return App.openConfirmDialog(Object.assign({
            title: "确认删除",
            secondTitle: "再次确认删除",
            secondIntro: "即将永久删除：",
            confirmLabel: "确认删除",
            twoStep: true,
            danger: true
        }, options));
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

    App.showToast = function (message) {
        var toast = document.getElementById("app-toast");
        if (!toast) return;
        clearTimeout(toastTimer);
        toast.textContent = String(message || "");
        toast.hidden = !message;
        if (message) toastTimer = setTimeout(function () {
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
})();
