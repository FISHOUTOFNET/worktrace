// WorkTrace WebView frontend — shell visibility lifecycle coordinator.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function capabilities() {
        return [
            App.uiPrimitives,
            App.projectAutocomplete,
            App.timelineTransientUi
        ].filter(function (owner) {
            return owner && typeof owner === "object";
        });
    }

    function dispatch(method) {
        capabilities().forEach(function (owner) {
            if (typeof owner[method] !== "function") return;
            try {
                owner[method]();
            } catch (error) {
                if (window.console && typeof window.console.debug === "function") {
                    window.console.debug("shell lifecycle handler failed", method, error);
                }
            }
        });
        if (method === "onShellHidden"
                && App.privacyNotice
                && typeof App.privacyNotice.closeView === "function") {
            try {
                App.privacyNotice.closeView({ restoreFocus: false });
            } catch (error) {
                if (window.console && typeof window.console.debug === "function") {
                    window.console.debug("shell privacy view cleanup failed", error);
                }
            }
        }
    }

    function installVisibilityBridge() {
        var original = App.setShellVisibility;
        if (typeof original !== "function") return false;
        if (original._shellLifecycleWrapped === true) return true;

        function wrappedSetShellVisibility(visible) {
            visible = visible === true;
            if (App.shellVisible === visible) return original.call(App, visible);

            if (!visible) {
                var hiddenResult = original.call(App, false);
                dispatch("onShellHidden");
                return hiddenResult;
            }

            var visibleResult = original.call(App, true);
            dispatch("onShellVisible");
            return visibleResult;
        }

        wrappedSetShellVisibility._shellLifecycleWrapped = true;
        wrappedSetShellVisibility._shellLifecycleOriginal = original;
        App.setShellVisibility = wrappedSetShellVisibility;
        return true;
    }

    App.shellLifecycle = Object.freeze({
        installVisibilityBridge: installVisibilityBridge,
        onShellHidden: function () { dispatch("onShellHidden"); },
        onShellVisible: function () { dispatch("onShellVisible"); }
    });

    installVisibilityBridge();
})();
