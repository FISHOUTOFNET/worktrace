// WorkTrace frontend composition root for cross-surface capability notifications.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function clearSettledFDWorkAuthOverride(status) {
        if (!status || status.operation !== "none") return;
        if (["ready", "idle", "error", "disabled", "shutdown"].indexOf(status.session_state) < 0) {
            return;
        }
        var override = App.fdWorkStatusOverride;
        var reason = String(override && override.reason || "");
        if (/登录|连接 FD Work/.test(reason)) App.fdWorkStatusOverride = null;
    }

    function syncFDWorkConsumers(status) {
        clearSettledFDWorkAuthOverride(status || App.fdWorkStatus);
        if (typeof App.renderFDWorkToggle === "function") {
            App.renderFDWorkToggle(App.lastSettingsStatus || {});
        }
        if (typeof App.updateFDWorkEntryButton === "function") {
            App.updateFDWorkEntryButton();
        }
        if (App.projectIdentity && typeof App.projectIdentity.syncStatus === "function") {
            App.projectIdentity.syncStatus();
        }
    }
    App.syncFDWorkConsumers = syncFDWorkConsumers;

    function reconnectFDWorkThroughSharedSession() {
        if (!App.fdWork || typeof App.fdWork.ensureSession !== "function") {
            if (typeof App.showSettingsError === "function") {
                App.showSettingsError("打开 FD Work 失败");
            }
            return Promise.resolve(false);
        }
        return App.fdWork.ensureSession().then(function (result) {
            if (!result || result.ok !== true) {
                if (typeof App.showSettingsError === "function") {
                    App.showSettingsError(result && result.message || "打开 FD Work 失败");
                }
                return false;
            }
            if (typeof App.clearSettingsError === "function") App.clearSettingsError();
            return true;
        }).catch(function () {
            if (typeof App.showSettingsError === "function") {
                App.showSettingsError("打开 FD Work 失败");
            }
            return false;
        });
    }
    App.reconnectFDWork = reconnectFDWorkThroughSharedSession;

    if (App.fdWork && typeof App.fdWork.bindStatusHost === "function") {
        App.fdWork.bindStatusHost({ onStatusChanged: syncFDWorkConsumers });
    }
    if (App.fdWorkStatus) syncFDWorkConsumers(App.fdWorkStatus);
})();
