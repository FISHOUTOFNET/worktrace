// WorkTrace WebView frontend — Settings mutation and exclusive-operation owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    var WRITE_ERROR_MESSAGE = "设置剪贴板记录失败";
    var LAUNCH_AT_LOGIN_ERROR_MESSAGE = "设置登录启动失败";
    var FD_WORK_ERROR_MESSAGE = "设置 FD Work 插件失败";

    function createSettingsDataOperations(deps) {
        var activeOperations = {};
        var blockingOperation = "";
        var operationSerial = 0;
        var fdWorkReconnectErrorMessage = "";

        function operationNames() { return Object.keys(activeOperations); }

        function isBusy() { return operationNames().length > 0; }

        function operationName() {
            return blockingOperation || operationNames()[0] || "";
        }

        function operationIs(name) { return !!activeOperations[name]; }

        function notifyStateChanged() {
            if (typeof deps.onOperationStateChanged === "function") {
                deps.onOperationStateChanged();
            }
        }

        function unavailable() {
            return isBusy() || (typeof deps.isLoading === "function" && deps.isLoading());
        }

        function finishOperation(name, token) {
            if (!activeOperations[name] || activeOperations[name] !== token) return;
            delete activeOperations[name];
            if (blockingOperation === name) blockingOperation = "";
            notifyStateChanged();
            if (typeof deps.onOperationSettled === "function") deps.onOperationSettled();
        }

        function runOperation(name, executor, exclusive) {
            if (
                (typeof deps.isLoading === "function" && deps.isLoading())
                || blockingOperation
                || activeOperations[name]
                || (exclusive && isBusy())
            ) return Promise.resolve(false);
            var token = ++operationSerial;
            name = String(name || "settings_command");
            activeOperations[name] = token;
            if (exclusive) blockingOperation = name;
            notifyStateChanged();
            return Promise.resolve().then(executor).then(function (result) {
                finishOperation(name, token);
                return result;
            }, function (error) {
                finishOperation(name, token);
                throw error;
            });
        }

        function runExclusive(name, executor) {
            return runOperation(name, executor, true);
        }

        function runMutation(name, executor) {
            return runOperation(name, executor, false);
        }

        function acceptResultStatus(result) {
            if (result && result.status && typeof deps.acceptSettingsSnapshot === "function") {
                deps.acceptSettingsSnapshot(result.status);
                return true;
            }
            return false;
        }

        function renderAuthoritativeSnapshot() {
            if (typeof deps.renderSettingsSnapshot === "function") deps.renderSettingsSnapshot();
        }

        function setCaptureEnabled(enabled) {
            if (operationIs("fd_work_write")) return Promise.resolve(false);
            return runMutation("clipboard_write", function () {
                return App.bridge.setClipboardCaptureEnabled(enabled).then(function (result) {
                    var data = App.handleResult(result, function (message) {
                        deps.presentation.showSettingsError(message || WRITE_ERROR_MESSAGE);
                    });
                    if (!data) {
                        renderAuthoritativeSnapshot();
                        return false;
                    }
                    acceptResultStatus(data);
                    deps.presentation.clearSettingsError();
                    return true;
                }).catch(function () {
                    deps.presentation.showSettingsError(WRITE_ERROR_MESSAGE);
                    renderAuthoritativeSnapshot();
                    return false;
                });
            });
        }

        function setLaunchAtLoginEnabled(enabled) {
            return runMutation("launch_at_login_write", function () {
                return App.bridge.setLaunchAtLogin(enabled).then(function (result) {
                    var statusAccepted = acceptResultStatus(result);
                    var data = App.handleResult(result, function (message) {
                        deps.presentation.showSettingsError(
                            message || LAUNCH_AT_LOGIN_ERROR_MESSAGE
                        );
                    });
                    if (!data) {
                        if (!statusAccepted) renderAuthoritativeSnapshot();
                        return false;
                    }
                    if (!statusAccepted) acceptResultStatus(data);
                    deps.presentation.clearSettingsError();
                    return true;
                }).catch(function () {
                    deps.presentation.showSettingsError(LAUNCH_AT_LOGIN_ERROR_MESSAGE);
                    renderAuthoritativeSnapshot();
                    return false;
                });
            });
        }

        function setFDWorkEnabled(enabled) {
            return runMutation("fd_work_write", function () {
                return App.bridge.setFDWorkEnabled(enabled).then(function (result) {
                    var statusAccepted = acceptResultStatus(result);
                    var data = App.handleResult(result, function (message) {
                        deps.presentation.showSettingsError(message || FD_WORK_ERROR_MESSAGE);
                    });
                    if (!data) {
                        if (!statusAccepted) renderAuthoritativeSnapshot();
                        return false;
                    }
                    if (!statusAccepted) acceptResultStatus(data);
                    deps.presentation.clearSettingsError();
                    return true;
                }).catch(function () {
                    deps.presentation.showSettingsError(FD_WORK_ERROR_MESSAGE);
                    renderAuthoritativeSnapshot();
                    return false;
                });
            });
        }

        function showFDWorkReconnectError(message) {
            fdWorkReconnectErrorMessage = String(message || "打开 FD Work 失败");
            deps.presentation.showSettingsError(fdWorkReconnectErrorMessage);
        }

        function reconnectFDWork() {
            if (!App.fdWork || typeof App.fdWork.ensureSession !== "function") {
                showFDWorkReconnectError("打开 FD Work 失败");
                return Promise.resolve(false);
            }
            return App.fdWork.ensureSession().then(function (result) {
                if (!result || result.ok !== true) {
                    showFDWorkReconnectError(
                        result && result.message || "打开 FD Work 失败"
                    );
                    return false;
                }
                fdWorkReconnectErrorMessage = "";
                deps.presentation.clearSettingsError();
                return true;
            }).catch(function () {
                showFDWorkReconnectError("打开 FD Work 失败");
                return false;
            });
        }

        function onFDWorkStatusChanged(status) {
            if (!fdWorkReconnectErrorMessage || !status) return;
            var settled = status.enabled !== true
                || (status.session_state === "ready" && status.ready === true);
            if (!settled) return;
            if (typeof deps.presentation.clearSettingsErrorIf === "function") {
                deps.presentation.clearSettingsErrorIf(fdWorkReconnectErrorMessage);
            }
            fdWorkReconnectErrorMessage = "";
        }

        function bind(id, eventName, handler) {
            var target = document.getElementById(id);
            if (target) target.addEventListener(eventName, handler);
        }

        function bindEvents() {
            bind("settings-clipboard-toggle", "change", function (event) {
                var toggle = event && event.target;
                if (!toggle || toggle.disabled) return;
                setCaptureEnabled(!!toggle.checked);
            });
            bind("settings-launch-at-login-toggle", "change", function (event) {
                var toggle = event && event.target;
                if (!toggle || toggle.disabled) return;
                setLaunchAtLoginEnabled(!!toggle.checked);
            });
            bind("settings-fd-work-toggle", "change", function (event) {
                var toggle = event && event.target;
                if (!toggle || toggle.disabled) return;
                setFDWorkEnabled(!!toggle.checked);
            });
            bind("settings-fd-work-reconnect", "click", reconnectFDWork);
        }

        return Object.freeze({
            bindEvents: bindEvents,
            hasBlockingOperation: function () { return !!blockingOperation; },
            isBusy: isBusy,
            isUnavailable: unavailable,
            onFDWorkStatusChanged: onFDWorkStatusChanged,
            operationIs: operationIs,
            operationName: operationName,
            operationNames: operationNames,
            reconnectFDWork: reconnectFDWork,
            runExclusive: runExclusive,
            setCaptureEnabled: setCaptureEnabled,
            setFDWorkEnabled: setFDWorkEnabled,
            setLaunchAtLoginEnabled: setLaunchAtLoginEnabled
        });
    }

    App.createSettingsDataOperations = createSettingsDataOperations;
})();