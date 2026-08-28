// WorkTrace WebView frontend — timeline transient UI owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function focusTransientTarget(target) {
        if (!target || typeof target.focus !== "function") return;
        if (typeof App.focusWithoutTransientUi === "function") {
            App.focusWithoutTransientUi(target);
            return;
        }
        target.focus();
    }

    function openTimelineDrawer(focusTarget) {
        if (!window.matchMedia || !window.matchMedia("(max-width: 767px)").matches) return;
        var pane = document.getElementById("timeline-details-pane");
        var backdrop = document.getElementById("timeline-drawer-backdrop");
        if (!pane) return;
        App.timelineDrawerRestoreFocus = document.activeElement;
        pane.classList.add("drawer-open");
        if (backdrop) { backdrop.hidden = false; backdrop.classList.add("open"); }
        var target = focusTarget || document.getElementById("timeline-details-close");
        focusTransientTarget(target);
    }
    App.openTimelineDrawer = openTimelineDrawer;

    function closeTimelineDrawer(options) {
        options = options || {};
        var pane = document.getElementById("timeline-details-pane");
        var backdrop = document.getElementById("timeline-drawer-backdrop");
        if (pane) pane.classList.remove("drawer-open");
        if (backdrop) { backdrop.classList.remove("open"); backdrop.hidden = true; }
        var restore = App.timelineDrawerRestoreFocus;
        App.timelineDrawerRestoreFocus = null;
        if (options.restoreFocus !== false) focusTransientTarget(restore);
    }
    App.closeTimelineDrawer = closeTimelineDrawer;

    function closeTimelineAdvancedMenu(options) {
        options = options || {};
        var menu = document.getElementById("timeline-session-actions");
        var button = document.getElementById("timeline-advanced-toggle");
        if (menu) menu.hidden = true;
        if (button) button.setAttribute("aria-expanded", "false");
        if (options.restoreFocus !== false) focusTransientTarget(button);
    }
    App.closeTimelineAdvancedMenu = closeTimelineAdvancedMenu;

    function dismissTimelineContextTransientUi() {
        closeTimelineAdvancedMenu({ restoreFocus: false });
    }
    App.dismissTimelineContextTransientUi = dismissTimelineContextTransientUi;

    App.toggleTimelineAdvancedMenu = function () {
        var menu = document.getElementById("timeline-session-actions");
        var button = document.getElementById("timeline-advanced-toggle");
        if (!menu || !button) return;
        if (!menu.hidden) {
            closeTimelineAdvancedMenu({ restoreFocus: true });
            return;
        }
        menu.hidden = false;
        button.setAttribute("aria-expanded", "true");
        var first = menu.querySelector("button:not([hidden]):not([disabled])");
        if (first) focusTransientTarget(first);
    };

    App.initTimelineAccessibility = function () {
        if (document.documentElement.getAttribute("data-timeline-a11y-bound") === "1") return;
        document.documentElement.setAttribute("data-timeline-a11y-bound", "1");
        function dismissAdvancedMenuOutsideTarget(target) {
            var menu = document.getElementById("timeline-session-actions");
            if (!menu || menu.hidden) return;
            var button = document.getElementById("timeline-advanced-toggle");
            if (target && menu.contains && menu.contains(target)) return;
            if (target && button && button.contains && button.contains(target)) return;
            dismissTimelineContextTransientUi();
        }
        document.addEventListener("pointerdown", function (event) {
            dismissAdvancedMenuOutsideTarget(event.target);
        });
        document.addEventListener("focusin", function (event) {
            dismissAdvancedMenuOutsideTarget(event.target);
        });
        document.addEventListener("keydown", function (event) {
            var pane = document.getElementById("timeline-details-pane");
            var menu = document.getElementById("timeline-session-actions");
            if (event.key === "Escape" && menu && !menu.hidden) {
                event.preventDefault();
                closeTimelineAdvancedMenu({ restoreFocus: true });
                return;
            }
            if (!pane || !pane.classList.contains("drawer-open")) return;
            if (event.key === "Escape") {
                event.preventDefault();
                closeTimelineDrawer();
                return;
            }
            if (App.trapFocus) App.trapFocus(event, pane);
        });
    };

    function resetTimelineTransientUi() {
        closeTimelineAdvancedMenu({ restoreFocus: false });
        closeTimelineDrawer({ restoreFocus: false });
        if (!App.timelineEditMutation || !App.timelineEditMutation.isSaving()) {
            App.timelineEditorState.showStatus("", false);
        }
    }
    App.resetTimelineTransientUi = resetTimelineTransientUi;

    App.timelineTransientUi = Object.freeze({
        onShellHidden: function () {
            // Shell hide dismisses only presentation-only context menus. The
            // responsive drawer and editor draft are user work and must survive.
            dismissTimelineContextTransientUi();
        },
        onShellVisible: function () {}
    });
})();
