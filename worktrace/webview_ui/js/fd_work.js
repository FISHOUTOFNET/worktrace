// Shared frontend owner for the optional FD Work capability.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    App.fdWorkStatus = null;
    App.FD_WORK_CASE_LABEL_MAX_LENGTH = 100;
    App.FD_WORK_QUERY_MIN_LENGTH = 0;
    App.FD_WORK_QUERY_MAX_LENGTH = 100;

    var sessionStates = ["disabled", "deferred_by_privacy", "idle", "probing", "starting", "login_required", "ready", "error", "shutdown"];
    var operations = ["none", "searching", "filling"];
    var pagePhases = ["none", "login_credentials", "login_confirmation", "work_shell", "work_interactive", "unauthorized", "error", "unknown"];

    function validStatus(status) {
        return !!status
            && typeof status === "object"
            && typeof status.supported === "boolean"
            && typeof status.enabled === "boolean"
            && sessionStates.indexOf(status.session_state) >= 0
            && operations.indexOf(status.operation) >= 0
            && typeof status.ready === "boolean"
            && typeof status.login_required === "boolean"
            && (status.error_code === null || typeof status.error_code === "string")
            && (status.page_phase === undefined || pagePhases.indexOf(status.page_phase) >= 0)
            && (status.navigation_generation === undefined
                || (Number.isInteger(status.navigation_generation)
                    && status.navigation_generation >= 0));
    }

    App.receiveFDWorkStatus = function (status) {
        if (!validStatus(status)) return false;
        var incomingGeneration = Number.isInteger(status.navigation_generation)
            ? status.navigation_generation : null;
        var currentGeneration = App.fdWorkStatus
            && Number.isInteger(App.fdWorkStatus.navigation_generation)
            ? App.fdWorkStatus.navigation_generation : null;
        if (incomingGeneration !== null
            && currentGeneration !== null
            && incomingGeneration < currentGeneration) return false;
        var terminalStates = ["login_required", "ready", "error"];
        if (incomingGeneration !== null
            && incomingGeneration === currentGeneration
            && App.fdWorkStatus
            && terminalStates.indexOf(App.fdWorkStatus.session_state) >= 0
            && status.session_state === "starting") return false;
        App.fdWorkStatus = Object.freeze({
            supported: status.supported === true,
            enabled: status.enabled === true,
            session_state: status.session_state,
            operation: status.operation,
            ready: status.ready === true,
            login_required: status.login_required === true,
            error_code: status.error_code || null,
            page_phase: status.page_phase || "none",
            navigation_generation: incomingGeneration
        });
        if (App.lastSettingsStatus) App.lastSettingsStatus.fd_work = App.fdWorkStatus;
        if (typeof App.renderFDWorkToggle === "function") App.renderFDWorkToggle(App.lastSettingsStatus);
        if (typeof App.updateFDWorkEntryButton === "function") App.updateFDWorkEntryButton();
        if (typeof App.syncFDWorkCaseSearchStatus === "function") App.syncFDWorkCaseSearchStatus();
        return true;
    };

    App.fdWorkStatusText = function (status) {
        status = status || App.fdWorkStatus || {};
        if (!status.enabled) return "插件关闭";
        if (status.session_state === "deferred_by_privacy") return "等待隐私授权";
        if (status.operation === "searching") {
            return status.page_phase === "work_interactive" ? "正在搜索" : "正在准备案件搜索";
        }
        if (status.operation === "filling") return "正在填入";
        if (status.session_state === "probing") return "正在检查登录状态";
        if (status.session_state === "starting") return "正在连接";
        if (status.session_state === "ready") return "已连接";
        if (status.page_phase === "login_confirmation") return "请确认登录";
        if (status.session_state === "login_required") return "需要登录";
        if (status.error_code === "session_start_timeout") return "连接超时";
        if (status.error_code === "renderer_unavailable") return "WebView2 不可用";
        if (status.session_state === "error") return "页面不可用";
        return "尚未连接";
    };
})();
