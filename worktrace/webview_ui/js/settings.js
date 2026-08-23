// WorkTrace WebView frontend — Settings page coordinator.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var presentation = App.settingsPresentation;
    var transientUi = App.settingsTransientUi;

    var ERROR_MESSAGE = "加载设置状态失败";
    var settingsSnapshot = null;
    var settingsLoaded = false;
    var settingsLoading = false;
    var settingsRequestToken = 0;
    var settingsLoadPromise = null;
    var settingsRefreshPending = false;

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
            closePrivacyNotice: function () {
                App.privacyNotice.closeView({ restoreFocus: false });
            },
            openPrivacyNotice: App.privacyNotice.openFromSettings,
            operationIs: operations.operationIs
        };
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

    App.settings = Object.freeze({
        bindEvents: bindSettingsEvents,
        hasLoadedData: function () { return settingsLoaded; },
        isLoading: function () { return settingsLoading; },
        onDataChanged: onSettingsDataChanged,
        onFDWorkStatusChanged: onFDWorkStatusChanged,
        onPageEntered: onSettingsPageEntered,
        onPageLeft: function () {
            App.privacyNotice.closeView({ restoreFocus: false });
            transientUi.resetSettingsTransientUi(
                { restoreFocus: false },
                transientContext()
            );
        },
        onRefreshRequested: onSettingsPageEntered,
        operationName: operations.operationName,
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
