// WorkTrace shared UI primitives: focus management, Drawer, Dialog, Toast, Tooltip.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var dialogLayer = document.getElementById("confirm-dialog-layer");
    var dialog = document.getElementById("confirm-dialog");
    var dialogTitle = document.getElementById("confirm-dialog-title");
    var dialogBody = document.getElementById("confirm-dialog-body");
    var dialogPrimary = document.getElementById("confirm-dialog-primary");
    var dialogSecondary = document.getElementById("confirm-dialog-secondary");
    var tooltip = document.getElementById("app-tooltip");
    var dialogState = null;
    var toastTimer = null;
    var tooltipTarget = null;
    var tooltipPendingTarget = null;
    var tooltipTimer = null;
    var inputModality = "none";
    var transientFocusSuppressed = false;
    var TOOLTIP_HOVER_DELAY_MS = 450;

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

    function cancelPendingTooltip() {
        if (tooltipTimer !== null) clearTimeout(tooltipTimer);
        tooltipTimer = null;
        tooltipPendingTarget = null;
    }

    function hideTooltip() {
        cancelPendingTooltip();
        tooltipTarget = null;
        if (!tooltip) return;
        tooltip.hidden = true;
        tooltip.textContent = "";
    }
    App.hideTooltip = hideTooltip;

    function focusWithoutTransientUi(target) {
        if (!target || typeof target.focus !== "function") return;
        var previous = transientFocusSuppressed;
        transientFocusSuppressed = true;
        hideTooltip();
        try {
            target.focus();
        } finally {
            transientFocusSuppressed = previous;
        }
    }
    App.focusWithoutTransientUi = focusWithoutTransientUi;
    App.isTransientFocusSuppressed = function () { return transientFocusSuppressed; };
    App.transientInputModality = function () { return inputModality; };

    function restoreFocus(target) {
        if (target && document.documentElement.contains(target)) {
            focusWithoutTransientUi(target);
        }
    }

    App.openManagedDrawer = function (layer, trigger, initialFocus, options) {
        if (!layer) return;
        options = typeof options === "function" ? { requestClose: options } : (options || {});
        layer._returnFocus = trigger || document.activeElement;
        layer._requestClose = typeof options.requestClose === "function"
            ? options.requestClose : null;
        layer.hidden = false;
        var target = initialFocus || focusable(layer)[0];
        if (target) focusWithoutTransientUi(target);
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
        choices.forEach(function (choice) {
            var row = document.createElement("label");
            row.className = "dialog-choice-row";
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
            copy.className = "dialog-choice-copy";
            var title = document.createElement("span");
            title.className = "dialog-choice-title";
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
        focusWithoutTransientUi(dialogSecondary);
    }

    function finishDialog(confirmed, options) {
        if (!dialogState) return;
        options = options || {};
        var state = dialogState;
        dialogState = null;
        if (dialogLayer) dialogLayer.hidden = true;
        if (options.restoreFocus !== false) restoreFocus(state.returnFocus);
        if (!confirmed) {
            state.resolve(false);
            return;
        }
        var choices = normalizedDialogChoices(state.options);
        state.resolve(choices.length ? (state.choice || choices[0].value) : true);
    }

    App.openConfirmDialog = function (options) {
        options = Object.assign({}, options || {});
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
        return App.openConfirmDialog(Object.assign({
            title: "确认删除",
            secondTitle: "确认删除",
            secondIntro: "此操作不可撤销。",
            confirmLabel: "删除",
            twoStep: true,
            danger: true
        }, options || {}));
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

    function clearToast() {
        if (toastTimer !== null) clearTimeout(toastTimer);
        toastTimer = null;
        var toast = document.getElementById("app-toast");
        if (!toast) return;
        toast.hidden = true;
        toast.textContent = "";
    }
    App.clearToast = clearToast;

    App.showToast = function (message) {
        var toast = document.getElementById("app-toast");
        if (!toast) return;
        clearToast();
        var copy = String(message || "");
        toast.textContent = copy;
        toast.hidden = !copy;
        if (copy) toastTimer = setTimeout(function () {
            toastTimer = null;
            toast.hidden = true;
            toast.textContent = "";
        }, 3200);
    };

    function tooltipOwner(target) {
        if (!target || !target.closest) return null;
        return target.closest("[data-tooltip]");
    }

    function tooltipDisclosureAllowed() {
        return App.shellVisible !== false && transientFocusSuppressed !== true;
    }

    function positionTooltip(target) {
        if (!tooltip || !target || typeof target.getBoundingClientRect !== "function") return;
        var rect = target.getBoundingClientRect();
        var width = Number(tooltip.offsetWidth || 0);
        var height = Number(tooltip.offsetHeight || 0);
        var viewportWidth = Number(window.innerWidth || 10000);
        var viewportHeight = Number(window.innerHeight || 10000);
        var gap = 6;
        var left = rect.left + rect.width / 2 - width / 2;
        left = Math.max(6, Math.min(left, viewportWidth - width - 6));
        var top = rect.bottom + gap;
        if (top + height + 6 > viewportHeight) top = Math.max(6, rect.top - height - gap);
        tooltip.style.left = Math.round(left) + "px";
        tooltip.style.top = Math.round(top) + "px";
    }

    function showTooltip(target) {
        cancelPendingTooltip();
        if (!tooltip || !target || !tooltipDisclosureAllowed()) return;
        var text = String(target.getAttribute("data-tooltip") || "").trim();
        if (!text) return;
        tooltipTarget = target;
        tooltip.textContent = text;
        tooltip.hidden = false;
        positionTooltip(target);
    }

    function scheduleTooltip(target) {
        if (!target || !tooltipDisclosureAllowed()) return;
        if (tooltipPendingTarget === target && tooltipTimer !== null) return;
        cancelPendingTooltip();
        tooltipPendingTarget = target;
        tooltipTimer = setTimeout(function () {
            tooltipTimer = null;
            if (tooltipPendingTarget !== target || inputModality !== "pointer") return;
            tooltipPendingTarget = null;
            showTooltip(target);
        }, TOOLTIP_HOVER_DELAY_MS);
    }

    function handleTooltipPointerMove(event) {
        inputModality = "pointer";
        if (!tooltipDisclosureAllowed()) {
            hideTooltip();
            return;
        }
        var target = tooltipOwner(event.target);
        if (!target) {
            hideTooltip();
            return;
        }
        if (tooltipTarget === target) return;
        if (tooltipTarget && tooltipTarget !== target) hideTooltip();
        scheduleTooltip(target);
    }

    function handleTooltipFocusIn(event) {
        if (inputModality !== "keyboard" || !tooltipDisclosureAllowed()) return;
        var target = tooltipOwner(event.target);
        if (target) showTooltip(target);
    }

    function leftTooltipTarget(event) {
        var target = tooltipOwner(event.target);
        if (!target) return;
        var related = event.relatedTarget;
        if (related && target.contains && target.contains(related)) return;
        if (tooltipPendingTarget === target) cancelPendingTooltip();
        if (tooltipTarget === target) hideTooltip();
    }

    function focusLeftTooltipTarget(event) {
        var target = tooltipOwner(event.target);
        if (target && target === tooltipTarget) hideTooltip();
    }

    document.addEventListener("mousemove", handleTooltipPointerMove);
    document.addEventListener("focusin", handleTooltipFocusIn);
    document.addEventListener("mouseout", leftTooltipTarget);
    document.addEventListener("focusout", focusLeftTooltipTarget);
    document.addEventListener("pointerdown", function () {
        inputModality = "pointer";
        hideTooltip();
    });
    document.addEventListener("click", hideTooltip);

    function resetTransientInteractionIntent() {
        inputModality = "none";
        hideTooltip();
    }

    if (typeof window.addEventListener === "function") {
        window.addEventListener("scroll", hideTooltip, true);
        window.addEventListener("resize", hideTooltip);
        window.addEventListener("blur", resetTransientInteractionIntent);
    }

    function onShellHidden() {
        resetTransientInteractionIntent();
        clearToast();
        if (dialogState) finishDialog(false, { restoreFocus: false });
    }

    function onShellVisible() {
        resetTransientInteractionIntent();
    }

    App.uiPrimitives = Object.freeze({
        onShellHidden: onShellHidden,
        onShellVisible: onShellVisible
    });

    document.addEventListener("keydown", function (event) {
        inputModality = "keyboard";
        if (event.key === "Escape") hideTooltip();
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
