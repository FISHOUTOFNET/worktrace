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

    function focusable(container) {
        if (!container) return [];
        return Array.prototype.slice.call(container.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), '
            + 'textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
        )).filter(function (element) {
            return !element.hidden && element.getAttribute("aria-hidden") !== "true";
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

    App.openManagedDrawer = function (layer, trigger, initialFocus) {
        if (!layer) return;
        layer._returnFocus = trigger || document.activeElement;
        layer.hidden = false;
        var target = initialFocus || focusable(layer)[0];
        if (target) target.focus();
    };

    App.closeManagedDrawer = function (layer) {
        if (!layer || layer.hidden) return;
        var target = layer._returnFocus;
        layer.hidden = true;
        layer._returnFocus = null;
        restoreFocus(target);
    };

    function renderDialogStep() {
        if (!dialogState) return;
        var options = dialogState.options;
        var second = dialogState.step === 2;
        dialogTitle.textContent = second
            ? (options.secondTitle || "再次确认删除")
            : (options.title || "确认删除");
        dialogBody.innerHTML = "";
        if (second) {
            var secondIntro = document.createElement("p");
            secondIntro.textContent = options.secondIntro || "即将永久删除：";
            dialogBody.appendChild(secondIntro);
        }
        var object = document.createElement("div");
        object.className = "dialog-object";
        object.textContent = options.objectLabel || "";
        dialogBody.appendChild(object);
        if (!second && options.warning) {
            var warning = document.createElement("p");
            warning.className = "dialog-warning";
            warning.textContent = options.warning;
            dialogBody.appendChild(warning);
        }
        dialogSecondary.textContent = second ? "返回" : "取消";
        dialogPrimary.textContent = second
            ? (options.confirmLabel || "确认删除")
            : (options.twoStep === false ? (options.confirmLabel || "确认删除") : "继续");
        dialogPrimary.classList.toggle("danger", second || options.twoStep === false);
        dialogSecondary.focus();
    }

    function finishDialog(confirmed) {
        if (!dialogState) return;
        var state = dialogState;
        dialogState = null;
        dialogLayer.hidden = true;
        restoreFocus(state.returnFocus);
        state.resolve(!!confirmed);
    }

    App.openDeleteDialog = function (options) {
        options = options || {};
        if (dialogState) return Promise.resolve(false);
        return new Promise(function (resolve) {
            dialogState = {
                options: options,
                step: 1,
                returnFocus: options.trigger || document.activeElement,
                resolve: resolve
            };
            dialogLayer.hidden = false;
            renderDialogStep();
        });
    };

    if (dialogPrimary) dialogPrimary.addEventListener("click", function () {
        if (!dialogState) return;
        if (dialogState.options.twoStep !== false && dialogState.step === 1) {
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
            App.closeManagedDrawer(drawer);
            return;
        }
        trapFocus(event, drawer.querySelector(".drawer"));
    });
})();
