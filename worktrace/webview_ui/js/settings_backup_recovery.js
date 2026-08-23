// WorkTrace WebView frontend — Settings backup, replacement, and recovery owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    var BACKUP_EXPORT_ERROR_MESSAGE = "导出加密备份失败";
    var BACKUP_MANIFEST_ERROR_MESSAGE = "读取备份清单失败";
    var BACKUP_IMPORT_ERROR_MESSAGE = "导入加密备份失败";
    var CLEAR_ALL_ERROR_MESSAGE = "清空本地数据失败";
    var IMPORT_CONFIRM_LITERAL = "导入并替换";
    var CLEAR_CONFIRM_LITERAL = "清空本地数据";

    function createSettingsBackupRecovery(deps) {
        var backupManifestViewToken = 0;
        var presentation = deps.presentation;
        var operations = deps.operations;

        function element(id) { return document.getElementById(id); }

        function cancelManifestPreview() {
            backupManifestViewToken += 1;
            presentation.renderBackupManifest(null, "");
        }

        function exportEncryptedBackup() {
            if (operations.isUnavailable()) return Promise.resolve(false);
            var passInput = element("settings-backup-passphrase");
            var confirmInput = element("settings-backup-passphrase-confirm");
            var passphrase = passInput ? String(passInput.value || "") : "";
            var confirmation = confirmInput ? String(confirmInput.value || "") : "";
            if (!passphrase.trim()) {
                presentation.setSettingsBackupStatus("请输入备份口令");
                return Promise.resolve(false);
            }
            if (confirmation !== passphrase) {
                presentation.setSettingsBackupStatus("两次输入的备份口令不一致");
                return Promise.resolve(false);
            }
            return operations.runExclusive("backup_export", function () {
                presentation.setSettingsBackupStatus("正在导出加密备份…");
                return App.bridge.exportEncryptedBackup(passphrase, confirmation).then(function (result) {
                    var data = App.handleResult(result, function (message) {
                        presentation.setSettingsBackupStatus(
                            message || BACKUP_EXPORT_ERROR_MESSAGE
                        );
                    });
                    if (!data) return false;
                    presentation.setSettingsBackupStatus(
                        data.message || ("已导出：" + (data.filename || ""))
                    );
                    return true;
                }).catch(function () {
                    presentation.setSettingsBackupStatus(BACKUP_EXPORT_ERROR_MESSAGE);
                    return false;
                }).then(function (ok) {
                    if (passInput) passInput.value = "";
                    if (confirmInput) confirmInput.value = "";
                    return ok;
                });
            });
        }

        function previewEncryptedBackupManifest() {
            if (operations.isUnavailable()) return Promise.resolve(false);
            var viewToken = ++backupManifestViewToken;
            return operations.runExclusive("backup_manifest", function () {
                presentation.setSettingsBackupStatus("正在读取备份清单…");
                return App.bridge.previewEncryptedBackupManifest().then(function (result) {
                    if (viewToken !== backupManifestViewToken) return false;
                    var data = App.handleResult(result, function (message) {
                        presentation.setSettingsBackupStatus(
                            message || BACKUP_MANIFEST_ERROR_MESSAGE
                        );
                        presentation.renderBackupManifest(null, "");
                    });
                    if (!data) return false;
                    presentation.setSettingsBackupStatus("");
                    presentation.renderBackupManifest(data.manifest, data.filename);
                    return true;
                }).catch(function () {
                    if (viewToken !== backupManifestViewToken) return false;
                    presentation.setSettingsBackupStatus(BACKUP_MANIFEST_ERROR_MESSAGE);
                    presentation.renderBackupManifest(null, "");
                    return false;
                });
            });
        }

        function importEncryptedBackup() {
            if (operations.isUnavailable()) return Promise.resolve(false);
            var passInput = element("settings-backup-import-passphrase");
            var passphrase = passInput ? String(passInput.value || "") : "";
            if (!passphrase.trim()) {
                presentation.setSettingsImportStatus("请输入备份口令");
                return Promise.resolve(false);
            }
            if (typeof App.openConfirmDialog !== "function") return Promise.resolve(false);
            return App.openConfirmDialog({
                trigger: element("settings-backup-import-btn"),
                title: "导入并替换本地数据",
                confirmLabel: "选择备份并替换",
                objectLabel: "当前项目、规则、时间记录和设置",
                warning: "这些本地数据将被备份文件替换，且操作不可撤销。建议先导出当前数据备份。",
                twoStep: false,
                danger: true
            }).then(function (confirmed) {
                if (!confirmed || operations.isUnavailable()) return false;
                return operations.runExclusive("backup_import", function () {
                    presentation.setSettingsImportStatus("正在导入加密备份…");
                    return App.bridge.importEncryptedBackup(
                        passphrase,
                        IMPORT_CONFIRM_LITERAL
                    ).then(function (result) {
                        var data = App.handleResult(result, function (message) {
                            presentation.setSettingsImportStatus(
                                message || BACKUP_IMPORT_ERROR_MESSAGE
                            );
                        });
                        if (!data) return false;
                        var tableCount = Number(data.imported_table_count || 0);
                        var rowCount = Number(data.imported_row_count || 0);
                        var message = data.message || "加密备份已导入";
                        if (tableCount > 0 || rowCount > 0) {
                            message += "（已导入：" + tableCount + " 个数据组 / "
                                + rowCount + " 条记录）";
                        }
                        presentation.setSettingsImportStatus(message);
                        cancelManifestPreview();
                        return deps.afterDataReplacement().then(function () { return true; });
                    }).catch(function () {
                        presentation.setSettingsImportStatus(BACKUP_IMPORT_ERROR_MESSAGE);
                        return false;
                    }).then(function (ok) {
                        if (passInput) passInput.value = "";
                        return ok;
                    });
                });
            });
        }

        function clearAllLocalData() {
            if (operations.isUnavailable()) return Promise.resolve(false);
            var confirmInput = element("settings-clear-confirm");
            var confirmation = confirmInput ? String(confirmInput.value || "") : "";
            if (confirmation.trim() !== CLEAR_CONFIRM_LITERAL) {
                presentation.setSettingsClearStatus(
                    "请输入确认文字：" + CLEAR_CONFIRM_LITERAL
                );
                return Promise.resolve(false);
            }
            return operations.runExclusive("clear_all", function () {
                presentation.setSettingsClearStatus("正在清空本地数据…");
                return App.bridge.clearAllLocalData(confirmation).then(function (result) {
                    var data = App.handleResult(result, function (message) {
                        presentation.setSettingsClearStatus(message || CLEAR_ALL_ERROR_MESSAGE);
                    });
                    if (!data) return false;
                    presentation.setSettingsClearStatus(data.message || "本地数据已清空");
                    cancelManifestPreview();
                    return deps.afterDataReplacement().then(function () { return true; });
                }).catch(function () {
                    presentation.setSettingsClearStatus(CLEAR_ALL_ERROR_MESSAGE);
                    return false;
                }).then(function (ok) {
                    if (confirmInput) confirmInput.value = "";
                    return ok;
                });
            });
        }

        function requestAuthoritativeRecoveryRefresh() {
            if (typeof deps.requestSettingsRefresh === "function") {
                deps.requestSettingsRefresh();
            }
            if (typeof App.refreshAll === "function") return App.refreshAll();
            return Promise.resolve();
        }

        function recoverDatabaseMaintenance() {
            if (operations.isUnavailable()) return Promise.resolve(false);
            return operations.runExclusive("recovery", function () {
                presentation.setSettingsRecoveryStatus("正在尝试恢复，请勿关闭应用……");
                if (App.clearGlobalAlert) App.clearGlobalAlert();
                return App.bridge.recoverDatabaseMaintenance().then(function (result) {
                    if (!result || result.ok === false) {
                        var message = App.extractBridgeError(
                            result,
                            "数据库维护恢复失败，请稍后重试或联系支持。"
                        );
                        presentation.setSettingsRecoveryStatus(message);
                        if (App.showGlobalAlert) App.showGlobalAlert(message);
                        if (result && result.maintenance) {
                            presentation.renderRecoveryCard(
                                result.maintenance,
                                deps.viewState()
                            );
                        }
                        return requestAuthoritativeRecoveryRefresh().then(function () {
                            return false;
                        });
                    }
                    presentation.setSettingsRecoveryStatus("恢复已提交，正在重新加载状态……");
                    return requestAuthoritativeRecoveryRefresh().then(function () {
                        presentation.setSettingsRecoveryStatus(
                            "数据库维护恢复已完成，状态已刷新。"
                        );
                        if (App.showToast) App.showToast("数据库维护恢复已完成");
                        return true;
                    });
                }).catch(function () {
                    var message = "恢复结果未知，正在重新读取状态……";
                    presentation.setSettingsRecoveryStatus(message);
                    if (App.showGlobalAlert) App.showGlobalAlert(message);
                    return requestAuthoritativeRecoveryRefresh().then(function () {
                        return false;
                    }, function () {
                        return false;
                    });
                });
            });
        }

        function bind(id, handler) {
            var target = element(id);
            if (target) target.addEventListener("click", handler);
        }

        function bindEvents() {
            bind("settings-backup-export-btn", exportEncryptedBackup);
            bind("settings-backup-manifest-btn", previewEncryptedBackupManifest);
            bind("settings-backup-import-btn", importEncryptedBackup);
            bind("settings-clear-local-data-btn", clearAllLocalData);
            bind("settings-clear-all-btn", clearAllLocalData);
            bind("settings-recovery-btn", recoverDatabaseMaintenance);
        }

        return Object.freeze({
            bindEvents: bindEvents,
            cancelManifestPreview: cancelManifestPreview,
            clearAllLocalData: clearAllLocalData,
            exportEncryptedBackup: exportEncryptedBackup,
            importEncryptedBackup: importEncryptedBackup,
            previewEncryptedBackupManifest: previewEncryptedBackupManifest,
            recoverDatabaseMaintenance: recoverDatabaseMaintenance
        });
    }

    App.createSettingsBackupRecovery = createSettingsBackupRecovery;
})();
