// WorkTrace WebView frontend — Settings page coordinator.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var presentation = App.settingsPresentation;
    var transientUi = App.settingsTransientUi;

    var ERROR_MESSAGE = "加载设置状态失败";
    var FIRST_RUN_NOTICE_LOAD_ERROR = "隐私说明加载失败。为保护隐私，有迹暂不会启动记录。请点击“重新加载”重试。";
    var FIRST_RUN_NOTICE_ACCEPT_ERROR = "确认隐私说明失败";

    var settingsSnapshot = null;
    var settingsLoaded = false;
    var settingsLoading = false;
    var settingsRequestToken = 0;
    var settingsLoadPromise = null;
    var settingsRefreshPending = false;

    var privacyGateState = "loading";
    var privacyNoticeLoaded = false;
    var privacyNoticeLoading = false;
    var privacyNoticeAccepting = false;
    var privacyNoticeRequestToken = 0;

    function settingsViewState(fdWorkStatus) {
        return {
            fdWorkStatus: fdWorkStatus || App.fdWorkStatus
                || settingsSnapshot && settingsSnapshot.fd_work || null,
            blockingOperation: operations ? operations.hasBlockingOperation() : false,
            loaded: settingsLoaded,
            loading: settingsLoading,
            operation: operations ? operations.operationName() : "",
            operations: operations ? operations.operationNames() : []
        };
    }

    function syncSettingsPresentation() {
        presentation.setSettingsLoading(settingsLoading);
        presentation.setSettingsControlsState(settingsSnapshot, settingsViewState());
    }

    function renderSettingsSnapshot() {
        if (settingsSnapshot) {
            presentation.renderSettingsStatus(settingsSnapshot, settingsViewState());
        } else {
            syncSettingsPresentation();
        }
    }

    function acceptSettingsSnapshot(status) {
        if (!status || typeof status !== "object") return false;
        settingsSnapshot = status;
        settingsLoaded = true;
        if (status.fd_work && typeof App.receiveFDWorkStatus === "function") {
            App.receiveFDWorkStatus(status.fd_work);
        }
        presentation.renderSettingsStatus(settingsSnapshot, settingsViewState());
        presentation.clearSettingsError();
        return true;
    }

    function requestSettingsRefresh() {
        settingsRefreshPending = true;
    }

    function settingsRefreshBlocked() {
        return settingsLoading || operations.isBusy();
    }

    function loadSettingsPrivacyStatus(options) {
        options = options || {};
        var showLoading = options.showLoading === true
            || (!settingsLoaded && options.showLoading !== false);
        if (settingsLoadPromise) return settingsLoadPromise;
        if (operations.isBusy()) {
            requestSettingsRefresh();
            return Promise.resolve(null);
        }
        if (showLoading) {
            settingsLoading = true;
            syncSettingsPresentation();
        }
        presentation.clearSettingsError();
        var token = ++settingsRequestToken;
        var request = App.bridge.getSettingsPrivacyStatus().then(function (result) {
            if (token !== settingsRequestToken) return null;
            var data = App.handleResult(result, function (message) {
                presentation.showSettingsError(message || ERROR_MESSAGE);
            });
            if (!data) return null;
            acceptSettingsSnapshot(data.status);
            settingsRefreshPending = false;
            return data.status;
        }).catch(function () {
            if (token === settingsRequestToken) presentation.showSettingsError(ERROR_MESSAGE);
            return null;
        }).finally(function () {
            if (settingsLoadPromise === request) settingsLoadPromise = null;
            if (showLoading && token === settingsRequestToken) {
                settingsLoading = false;
                syncSettingsPresentation();
            }
        });
        settingsLoadPromise = request;
        return request;
    }

    function refreshSettingsSilently() {
        return loadSettingsPrivacyStatus({ showLoading: false });
    }

    function drainSettingsRefresh() {
        if (
            settingsRefreshPending !== true
            || App.currentPage !== "settings"
            || settingsRefreshBlocked()
        ) {
            return Promise.resolve(null);
        }
        return refreshSettingsSilently();
    }

    function onSettingsDataChanged(change) {
        change = change || {};
        if (change.settingsChanged !== true) return Promise.resolve(null);
        requestSettingsRefresh();
        if (change.source !== "refresh-state" || App.currentPage !== "settings") {
            return Promise.resolve(null);
        }
        return drainSettingsRefresh();
    }

    function onSettingsPageEntered() {
        if (!settingsLoaded) return loadSettingsPrivacyStatus({ showLoading: true });
        return refreshSettingsSilently();
    }

    function onOperationStateChanged() {
        syncSettingsPresentation();
    }

    function onOperationSettled() {
        syncSettingsPresentation();
        drainSettingsRefresh().catch(function () {});
    }

    function afterDataReplacement() {
        App.resetClientGeneration("database_replacement");
        requestSettingsRefresh();
        if (typeof App.refreshAll === "function") return Promise.resolve(App.refreshAll());
        return Promise.resolve();
    }

    var operations = App.createSettingsDataOperations({
        acceptSettingsSnapshot: acceptSettingsSnapshot,
        isLoading: function () { return settingsLoading; },
        onOperationSettled: onOperationSettled,
        onOperationStateChanged: onOperationStateChanged,
        presentation: presentation,
        renderSettingsSnapshot: renderSettingsSnapshot
    });

    var backupRecovery = App.createSettingsBackupRecovery({
        afterDataReplacement: afterDataReplacement,
        operations: operations,
        presentation: presentation,
        requestSettingsRefresh: requestSettingsRefresh,
        viewState: settingsViewState
    });

    function transientContext() {
        return {
            cancelManifestPreview: backupRecovery.cancelManifestPreview,
            openPrivacyNotice: openPrivacyNoticeFromSettings,
            operationIs: operations.operationIs
        };
    }

    function setPrivacyGateState(state) {
        privacyGateState = String(state || "loading");
    }

    function privacyGateReady() { return privacyGateState === "accepted_ready"; }

    function loadFirstRunNotice(options) {
        var force = !!(options && options.force);
        if (privacyNoticeLoading) return Promise.resolve(privacyGateReady());
        if (privacyNoticeLoaded && !force) return Promise.resolve(privacyGateReady());
        privacyNoticeLoading = true;
        setPrivacyGateState("loading");
        var token = ++privacyNoticeRequestToken;
        return App.bridge.getFirstRunNotice().then(function (result) {
            if (token !== privacyNoticeRequestToken) return false;
            privacyNoticeLoading = false;
            if (!result || result.ok === false) {
                setPrivacyGateState("load_failed");
                transientUi.showFirstRunNoticeBlockingError(
                    App.extractBridgeError(result, FIRST_RUN_NOTICE_LOAD_ERROR),
                    "gate"
                );
                return false;
            }
            privacyNoticeLoaded = true;
            var notice = result.notice || {};
            if (notice.accepted === true) {
                setPrivacyGateState("accepted_ready");
                transientUi.settleFirstRunNoticeAcceptedUi();
                return true;
            }
            setPrivacyGateState("acceptance_required");
            transientUi.showFirstRunNotice(notice, "gate");
            return false;
        }).catch(function () {
            if (token !== privacyNoticeRequestToken) return false;
            privacyNoticeLoading = false;
            setPrivacyGateState("load_failed");
            transientUi.showFirstRunNoticeBlockingError(
                FIRST_RUN_NOTICE_LOAD_ERROR,
                "gate"
            );
            return false;
        });
    }

    function acceptFirstRunNotice() {
        if (privacyNoticeAccepting) return Promise.resolve(false);
        privacyNoticeAccepting = true;
        presentation.setFirstRunNoticeAcceptDisabled(true);
        presentation.setFirstRunNoticeError("");
        setPrivacyGateState("accepted_starting");
        return App.bridge.acceptFirstRunNotice().then(function (result) {
            var accepted = !!(result && result.accepted === true);
            if (accepted && result.ok === true) {
                setPrivacyGateState("accepted_ready");
                transientUi.settleFirstRunNoticeAcceptedUi();
                if (typeof App.continueStartupAfterPrivacyGate === "function") {
                    App.continueStartupAfterPrivacyGate();
                }
                loadSettingsPrivacyStatus();
                return true;
            }
            if (accepted && result.ok === false) {
                setPrivacyGateState("accepted_start_failed");
                transientUi.settleFirstRunNoticeAcceptedUi();
                var message = App.extractBridgeError(
                    result,
                    "隐私说明已确认，但记录功能未能启动。可前往设置查看原因或重试。"
                );
                if (App.showGlobalAlert) App.showGlobalAlert(message);
                if (typeof App.continueStartupAfterPrivacyGate === "function") {
                    App.continueStartupAfterPrivacyGate();
                }
                loadSettingsPrivacyStatus();
                return true;
            }
            setPrivacyGateState("acceptance_required");
            presentation.setFirstRunNoticeError(
                App.extractBridgeError(result, FIRST_RUN_NOTICE_ACCEPT_ERROR)
            );
            return false;
        }).catch(function () {
            setPrivacyGateState("acceptance_required");
            presentation.setFirstRunNoticeError(FIRST_RUN_NOTICE_ACCEPT_ERROR);
            return false;
        }).then(function (accepted) {
            privacyNoticeAccepting = false;
            presentation.setFirstRunNoticeAcceptDisabled(false);
            return accepted;
        });
    }

    function retryFirstRunNotice() {
        if (privacyNoticeLoading) return Promise.resolve(false);
        privacyNoticeLoaded = false;
        return loadFirstRunNotice({ force: true }).then(function (ready) {
            if (ready && typeof App.continueStartupAfterPrivacyGate === "function") {
                return App.continueStartupAfterPrivacyGate();
            }
            return false;
        });
    }

    function openPrivacyNoticeFromSettings() {
        var token = transientUi.beginPrivacyNoticeViewRequest();
        return App.bridge.getFirstRunNotice().then(function (result) {
            if (!transientUi.privacyNoticeViewRequestCurrent(token)) return false;
            if (!result || result.ok === false) {
                transientUi.showFirstRunNoticeBlockingError(
                    result && result.error || FIRST_RUN_NOTICE_LOAD_ERROR,
                    "view"
                );
                return false;
            }
            transientUi.showFirstRunNotice(result.notice || {}, "view");
            return true;
        }).catch(function () {
            if (!transientUi.privacyNoticeViewRequestCurrent(token)) return false;
            transientUi.showFirstRunNoticeBlockingError(
                FIRST_RUN_NOTICE_LOAD_ERROR,
                "view"
            );
            return false;
        });
    }

    function bindSettingsEvents() {
        operations.bindEvents();
        backupRecovery.bindEvents();
        transientUi.bindEvents(transientContext());
    }

    function settingsRuntimeRefreshIdentity(runtime) {
        if (!runtime) return "";
        var collector = runtime.collector || {};
        return [
            String(collector.status || ""),
            collector.paused === true ? "paused" : "running",
            String(collector.display || ""),
            String(runtime.runtimePhase || ""),
            (Array.isArray(runtime.errorCodes) ? runtime.errorCodes : []).join(",")
        ].join("|");
    }

    function resetSettingsGeneration() {
        settingsLoaded = false;
        settingsRefreshPending = false;
        settingsLoadPromise = null;
        settingsLoading = false;
        settingsRequestToken += 1;
        privacyNoticeLoaded = false;
        privacyNoticeLoading = false;
        privacyNoticeRequestToken += 1;
        transientUi.resetSettingsTransientUi(
            { restoreFocus: false },
            transientContext()
        );
        syncSettingsPresentation();
    }

    function onFDWorkStatusChanged(status) {
        presentation.renderFDWorkToggle(
            settingsSnapshot || {},
            settingsViewState(status)
        );
    }

    var privacyCapability = Object.freeze({
        accept: acceptFirstRunNotice,
        isReady: privacyGateReady,
        load: loadFirstRunNotice,
        requiresAcceptance: function () { return privacyGateState === "acceptance_required"; },
        retry: retryFirstRunNotice,
        state: function () { return privacyGateState; }
    });

    App.settings = Object.freeze({
        bindEvents: bindSettingsEvents,
        hasLoadedData: function () { return settingsLoaded; },
        isLoading: function () { return settingsLoading; },
        onDataChanged: onSettingsDataChanged,
        onFDWorkStatusChanged: onFDWorkStatusChanged,
        onPageEntered: onSettingsPageEntered,
        onPageLeft: function () {
            transientUi.resetSettingsTransientUi(
                { restoreFocus: false },
                transientContext()
            );
        },
        onRefreshRequested: onSettingsPageEntered,
        operationName: operations.operationName,
        privacy: privacyCapability,
        refreshEvidence: function () { return settingsSnapshot; },
        refreshPending: function () { return settingsRefreshPending; },
        refreshPolicy: Object.freeze({
            entryGenerations: Object.freeze(["settings", "privacy_catalog"]),
            automaticGenerations: Object.freeze(["settings", "privacy_catalog"]),
            deferred: false
        }),
        resetGeneration: resetSettingsGeneration,
        runtimeRefreshIdentity: settingsRuntimeRefreshIdentity,
        snapshot: function () { return settingsSnapshot; }
    });

    App.loadSettingsPrivacyStatus = loadSettingsPrivacyStatus;
    App.loadFirstRunNotice = loadFirstRunNotice;
    App.acceptFirstRunNotice = acceptFirstRunNotice;
    App.retryFirstRunNotice = retryFirstRunNotice;
    App.openPrivacyNoticeFromSettings = openPrivacyNoticeFromSettings;
    App.setCaptureEnabled = operations.setCaptureEnabled;
    App.setLaunchAtLoginEnabled = operations.setLaunchAtLoginEnabled;
    App.setFDWorkEnabled = operations.setFDWorkEnabled;
    App.reconnectFDWork = operations.reconnectFDWork;
    App.setSettingsBackupControlsDisabled = function (disabled) {
        presentation.setSettingsBackupControlsDisabled(disabled);
        if (disabled) transientUi.hideAllPasswordFields();
    };
    App.exportEncryptedBackup = backupRecovery.exportEncryptedBackup;
    App.previewEncryptedBackupManifest = backupRecovery.previewEncryptedBackupManifest;
    App.importEncryptedBackup = backupRecovery.importEncryptedBackup;
    App.clearAllLocalData = backupRecovery.clearAllLocalData;
    App.recoverDatabaseMaintenance = backupRecovery.recoverDatabaseMaintenance;
})();
