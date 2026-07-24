// WorkTrace WebView frontend — Settings and Privacy capabilities.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    var ERROR_MESSAGE = "加载设置状态失败";
    var WRITE_ERROR_MESSAGE = "设置剪贴板记录失败";
    var BACKUP_EXPORT_ERROR_MESSAGE = "导出加密备份失败";
    var BACKUP_MANIFEST_ERROR_MESSAGE = "读取备份清单失败";
    var BACKUP_IMPORT_ERROR_MESSAGE = "导入加密备份失败";
    var CLEAR_ALL_ERROR_MESSAGE = "清空本地数据失败";
    var FIRST_RUN_NOTICE_LOAD_ERROR = "隐私说明加载失败。为保护隐私，WorkTrace 暂不会启动记录。请点击“重新加载”重试。";
    var FIRST_RUN_NOTICE_ACCEPT_ERROR = "确认隐私说明失败";
    var IMPORT_CONFIRM_LITERAL = "导入并替换";
    var CLEAR_CONFIRM_LITERAL = "清空本地数据";

    function element(id) { return document.getElementById(id); }

    function showSettingsError(message) {
        var banner = element("settings-error");
        if (!banner) return;
        banner.hidden = !message;
        banner.textContent = message || ERROR_MESSAGE;
    }
    App.showSettingsError = showSettingsError;
    App.clearSettingsError = function () { showSettingsError(""); };

    function anySettingsOperationInProgress() {
        return !!(
            App.settingsLoading
            || App.settingsWriteInProgress
            || App.settingsBackupExportInProgress
            || App.settingsBackupManifestInProgress
            || App.settingsBackupImportInProgress
            || App.settingsClearAllInProgress
            || App.recoveryInProgress
        );
    }
    App.anySettingsOperationInProgress = anySettingsOperationInProgress;

    function setDisabled(id, disabled) {
        var target = element(id);
        if (target) target.disabled = !!disabled;
    }

    function setSettingsBackupControlsDisabled(disabled) {
        [
            "settings-backup-export-btn",
            "settings-backup-manifest-btn",
            "settings-backup-passphrase",
            "settings-backup-passphrase-confirm",
            "settings-backup-import-passphrase",
            "settings-backup-import-confirm",
            "settings-backup-import-btn"
        ].forEach(function (id) { setDisabled(id, disabled); });
    }
    App.setSettingsBackupControlsDisabled = setSettingsBackupControlsDisabled;

    function setSettingsDangerControlsDisabled(disabled) {
        setDisabled("settings-clear-confirm", disabled);
        setDisabled("settings-clear-local-data-btn", disabled);
    }
    App.setSettingsDangerControlsDisabled = setSettingsDangerControlsDisabled;

    // Recovery button enabled = backend reports recovery_blocked AND no
    // Settings operation in progress. The frontend never clears
    // recovery_blocked locally; it reads the latest authoritative status.
    function syncRecoveryButtonState(status) {
        var button = element("settings-recovery-btn");
        if (!button) return;
        var authoritative = status || App.lastSettingsStatus || {};
        button.disabled = anySettingsOperationInProgress()
            || authoritative.recovery_blocked !== true;
    }
    App.syncRecoveryButtonState = syncRecoveryButtonState;

    function setSettingsControlsDisabled(disabled) {
        var toggle = element("settings-clipboard-toggle");
        if (toggle) toggle.disabled = !!disabled || !App.settingsLoaded;
        setSettingsBackupControlsDisabled(disabled);
        setSettingsDangerControlsDisabled(disabled);
        // The recovery button participates in the unified control sync,
        // but its final state is derived from the authoritative backend
        // status, not the generic ``disabled`` flag.
        syncRecoveryButtonState();
    }
    App.setSettingsControlsDisabled = setSettingsControlsDisabled;

    function setSettingsLoading(loading) {
        App.settingsLoading = !!loading;
        var loadingEl = element("settings-loading");
        if (loadingEl) loadingEl.hidden = !loading;
        setSettingsControlsDisabled(anySettingsOperationInProgress());
    }
    App.setSettingsLoading = setSettingsLoading;

    function boolLabel(value) { return value ? "是" : "否"; }

    function setLineText(key, text) {
        var target = document.querySelector('#settings-status [data-settings-key="' + key + '"]');
        if (target) target.textContent = text;
    }

    function setCaptureToggleStatus(text) {
        var target = element("settings-clipboard-toggle-status");
        if (target) target.textContent = text;
    }
    App.setCaptureToggleStatus = setCaptureToggleStatus;

    function renderCaptureToggle(status) {
        var toggle = element("settings-clipboard-toggle");
        if (!toggle) return;
        var enabled = !!(status && status.clipboard_capture_enabled);
        toggle.checked = enabled;
        toggle.disabled = anySettingsOperationInProgress() || !App.settingsLoaded;
        setCaptureToggleStatus(enabled ? "开启" : "关闭");
    }
    App.renderCaptureToggle = renderCaptureToggle;

    function renderSettingsStatus(status) {
        if (!status) return;
        renderCaptureToggle(status);
        setLineText(
            "export_path_configured",
            status.export_path_configured ? "导出目录：已配置" : "导出目录：未配置"
        );
        setLineText(
            "maintenance_in_progress",
            "数据库维护进行中：" + boolLabel(!!status.maintenance_in_progress)
        );
        setLineText(
            "maintenance_restored",
            "维护恢复完成：" + boolLabel(!!status.maintenance_restored)
        );
        setLineText(
            "recovery_blocked",
            "维护恢复阻断：" + boolLabel(!!status.recovery_blocked)
        );
        setLineText(
            "blocked_reason",
            "阻断原因：" + (status.blocked_reason ? String(status.blocked_reason) : "无")
        );
        setLineText(
            "collector_running",
            "采集器运行中：" + boolLabel(!!status.collector_running)
        );
        setLineText(
            "collector_status",
            "采集器状态：" + String(status.collector_status || "stopped")
        );
        setLineText(
            "user_paused",
            "用户暂停：" + boolLabel(!!status.user_paused)
        );
        renderRecoveryCard(status);
        var health = element("settings-health-summary");
        if (health) {
            var title = "记录正常";
            var detail = "采集和本地存储可用";
            if (status.recovery_blocked) {
                title = "恢复尚未完成";
                detail = "请在高级诊断中查看阻断原因";
            } else if (status.maintenance_in_progress) {
                title = "正在维护数据";
                detail = "维护期间其他数据操作暂时不可用";
            } else if (!status.collector_running && !status.user_paused) {
                title = "记录服务未运行";
                detail = "请重启应用后再次检查";
            }
            var strong = health.querySelector("strong");
            var small = health.querySelector("small");
            var badge = health.querySelector(".badge");
            if (strong) strong.textContent = title;
            if (small) small.textContent = detail;
            if (badge) badge.textContent = title;
        }
        if (status.storage_model === "local_only") {
            setLineText("storage_model", "本地优先：所有数据仅存储在本机，不上传任何远端服务器。");
        }
        var accepted = !!(
            status.first_run_notice
            && typeof status.first_run_notice === "object"
            && status.first_run_notice.accepted
        );
        var noticeStatus = element("settings-privacy-notice-status");
        if (noticeStatus) noticeStatus.textContent = "隐私说明：" + (accepted ? "已确认" : "未确认");
        var statusEl = element("settings-status");
        if (statusEl) statusEl.hidden = false;
    }
    App.renderSettingsStatus = renderSettingsStatus;

    function setRecoveryStatus(message) {
        var statusEl = element("settings-recovery-status");
        if (!statusEl) return;
        statusEl.hidden = !message;
        statusEl.textContent = message || "";
    }

    function renderRecoveryCard(status) {
        var card = element("settings-recovery-card");
        var reason = element("settings-recovery-reason");
        if (!card) return;
        var blocked = !!status.recovery_blocked;
        var inProgress = !!status.maintenance_in_progress;
        card.hidden = !blocked && !inProgress;
        if (reason) {
            reason.textContent = "阻断原因："
                + (status.blocked_reason ? String(status.blocked_reason) : (inProgress ? "维护进行中" : "无"));
        }
        // The button enabled state is derived solely from the authoritative
        // backend status and the unified busy flag via syncRecoveryButtonState.
        // The frontend never clears recovery_blocked locally.
        syncRecoveryButtonState(status);
    }
    App.renderRecoveryCard = renderRecoveryCard;

    function recoverDatabaseMaintenance() {
        // Symmetric mutex: any Settings operation in progress blocks
        // recovery, not only recovery itself. This is the reverse direction
        // of the guard the other operations already perform.
        if (anySettingsOperationInProgress()) return Promise.resolve(false);
        App.recoveryInProgress = true;
        // Disable all settings controls via the unified mutex during recovery.
        setSettingsControlsDisabled(anySettingsOperationInProgress());
        var button = element("settings-recovery-btn");
        if (button) button.disabled = true;
        setRecoveryStatus("正在尝试恢复，请勿关闭应用……");
        App.clearGlobalAlert();
        return App.bridge.recoverDatabaseMaintenance().then(function (result) {
            if (!result || result.ok === false) {
                var message = App.extractBridgeError(
                    result,
                    "数据库维护恢复失败，请稍后重试或联系支持。"
                );
                setRecoveryStatus(message);
                if (App.showGlobalAlert) App.showGlobalAlert(message);
                // On failure, prefer the maintenance status embedded in the
                // response to refresh the recovery card; otherwise reload the
                // full settings status. Never clear recovery_blocked here.
                var maintenance = result && result.maintenance;
                if (maintenance) {
                    App.lastSettingsStatus = maintenance;
                    return false;
                }
                if (typeof App.loadSettingsPrivacyStatus === "function") {
                    return App.loadSettingsPrivacyStatus().then(function () { return false; });
                }
                return false;
            }
            setRecoveryStatus("恢复已提交，正在重新加载状态……");
            // Refresh settings status and current page so the user sees
            // authoritative state without manual reload.
            return Promise.all([
                App.loadSettingsPrivacyStatus(),
                App.refreshAll ? App.refreshAll() : Promise.resolve()
            ]).then(function () {
                setRecoveryStatus("数据库维护恢复已完成，状态已刷新。");
                if (App.showToast) App.showToast("数据库维护恢复已完成");
                return true;
            });
        }).catch(function () {
            // Transport rejection: frontend cannot know if recovery applied.
            // Re-read authoritative backend status before releasing busy.
            var message = "恢复结果未知，正在重新读取状态……";
            setRecoveryStatus(message);
            if (App.showGlobalAlert) App.showGlobalAlert(message);
            if (typeof App.loadSettingsPrivacyStatus !== "function") {
                return false;
            }
            return App.loadSettingsPrivacyStatus().then(function () {
                return false;
            }, function () {
                // Status read itself failed: keep the conservative error,
                // but still release the busy flag downstream to avoid a
                // permanent UI deadlock. Do not claim success.
                return false;
            });
        }).then(function (ok) {
            // Single release path: clear busy flag and re-render controls
            // from the latest authoritative backend status.
            App.recoveryInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
            if (App.lastSettingsStatus) renderRecoveryCard(App.lastSettingsStatus);
            return ok;
        });
    }
    App.recoverDatabaseMaintenance = recoverDatabaseMaintenance;

    function initSettingsCategories() {
        var buttons = document.querySelectorAll("[data-settings-section]");
        for (var index = 0; index < buttons.length; index++) {
            buttons[index].addEventListener("click", function () {
                var section = this.getAttribute("data-settings-section");
                for (var i = 0; i < buttons.length; i++) {
                    buttons[i].removeAttribute("aria-current");
                    var panel = element("settings-section-" + buttons[i].getAttribute("data-settings-section"));
                    if (panel) { panel.hidden = true; panel.classList.remove("active"); }
                }
                this.setAttribute("aria-current", "true");
                var target = element("settings-section-" + section);
                if (target) { target.hidden = false; target.classList.add("active"); }
            });
        }
    }
    App.initSettingsCategories = initSettingsCategories;

    function loadSettingsPrivacyStatus() {
        if (App.settingsLoading) return Promise.resolve();
        setSettingsLoading(true);
        App.clearSettingsError();
        var token = ++App.settingsRequestToken;
        return App.bridge.getSettingsPrivacyStatus().then(function (result) {
            if (token !== App.settingsRequestToken) return;
            var data = App.handleResult(result, function (message) {
                showSettingsError(message || ERROR_MESSAGE);
            });
            if (!data) return;
            App.settingsLoaded = true;
            App.lastSettingsStatus = data.status;
            renderSettingsStatus(data.status);
            App.clearSettingsError();
        }).catch(function () {
            if (token === App.settingsRequestToken) showSettingsError(ERROR_MESSAGE);
        }).then(function () {
            if (token === App.settingsRequestToken) setSettingsLoading(false);
        });
    }
    App.loadSettingsPrivacyStatus = loadSettingsPrivacyStatus;

    function setCaptureEnabled(enabled) {
        // Symmetric mutex: gate direct programmatic callers and tests so
        // clipboard writes cannot bypass the unified Settings mutex.
        if (anySettingsOperationInProgress()) return Promise.resolve();
        App.settingsWriteInProgress = true;
        setSettingsControlsDisabled(true);
        var toggle = element("settings-clipboard-toggle");
        return App.bridge.setClipboardCaptureEnabled(enabled).then(function (result) {
            var data = App.handleResult(result, function (message) {
                showSettingsError(message || WRITE_ERROR_MESSAGE);
            });
            if (!data) {
                if (toggle) toggle.checked = !enabled;
                setCaptureToggleStatus(!enabled ? "开启" : "关闭");
                return;
            }
            renderSettingsStatus(data.status);
            App.clearSettingsError();
        }).catch(function () {
            showSettingsError(WRITE_ERROR_MESSAGE);
            if (toggle) toggle.checked = !enabled;
            setCaptureToggleStatus(!enabled ? "开启" : "关闭");
        }).then(function () {
            App.settingsWriteInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.setCaptureEnabled = setCaptureEnabled;

    function handleCaptureToggleChange(event) {
        var toggle = event ? event.target : element("settings-clipboard-toggle");
        if (!toggle || toggle.disabled || App.settingsWriteInProgress) return;
        setCaptureEnabled(!!toggle.checked);
    }
    App.handleCaptureToggleChange = handleCaptureToggleChange;

    function setStatusLine(id, text) {
        var target = element(id);
        if (!target) return;
        target.hidden = !text;
        target.textContent = text || "";
    }

    function setSettingsBackupStatus(text) { setStatusLine("settings-backup-status", text); }
    function setSettingsImportStatus(text) { setStatusLine("settings-backup-import-status", text); }
    function setSettingsClearStatus(text) { setStatusLine("settings-clear-status", text); }
    App.setSettingsBackupStatus = setSettingsBackupStatus;
    App.clearSettingsBackupStatus = function () { setSettingsBackupStatus(""); };
    App.setSettingsImportStatus = setSettingsImportStatus;
    App.clearSettingsImportStatus = function () { setSettingsImportStatus(""); };
    App.setSettingsClearStatus = setSettingsClearStatus;
    App.clearSettingsClearStatus = function () { setSettingsClearStatus(""); };

    function renderBackupManifest(manifest, filename) {
        var container = element("settings-backup-manifest");
        if (!container) return;
        var filenameEl = container.querySelector(".settings-backup-manifest-filename");
        var fieldsEl = container.querySelector(".settings-backup-manifest-fields");
        if (!manifest) {
            container.hidden = true;
            if (filenameEl) filenameEl.textContent = "";
            if (fieldsEl) fieldsEl.textContent = "";
            return;
        }
        if (filenameEl) filenameEl.textContent = "文件：" + (filename || "");
        if (fieldsEl) {
            fieldsEl.textContent = "";
            [
                ["清单版本", manifest.version],
                ["应用版本", manifest.app_version],
                ["创建时间", manifest.created_at],
                ["KDF 算法", manifest.kdf_algorithm],
                ["载荷格式", manifest.payload_format],
                ["载荷算法", manifest.payload_alg]
            ].forEach(function (field) {
                var dt = document.createElement("dt");
                var dd = document.createElement("dd");
                dt.textContent = field[0];
                dd.textContent = field[1] === undefined || field[1] === null ? "" : String(field[1]);
                fieldsEl.appendChild(dt);
                fieldsEl.appendChild(dd);
            });
        }
        container.hidden = false;
    }
    App.renderBackupManifest = renderBackupManifest;
    App.clearBackupManifestPreview = function () { renderBackupManifest(null, ""); };

    function exportEncryptedBackup() {
        if (anySettingsOperationInProgress()) return;
        var passInput = element("settings-backup-passphrase");
        var confirmInput = element("settings-backup-passphrase-confirm");
        var passphrase = passInput ? String(passInput.value || "") : "";
        var confirmation = confirmInput ? String(confirmInput.value || "") : "";
        if (!passphrase.trim()) return setSettingsBackupStatus("请输入备份口令");
        if (confirmation !== passphrase) return setSettingsBackupStatus("两次输入的备份口令不一致");
        App.settingsBackupExportInProgress = true;
        setSettingsControlsDisabled(true);
        setSettingsBackupStatus("正在导出加密备份…");
        App.bridge.exportEncryptedBackup(passphrase, confirmation).then(function (result) {
            var data = App.handleResult(result, function (message) {
                setSettingsBackupStatus(message || BACKUP_EXPORT_ERROR_MESSAGE);
            });
            if (data) setSettingsBackupStatus(data.message || ("已导出：" + (data.filename || "")));
        }).catch(function () {
            setSettingsBackupStatus(BACKUP_EXPORT_ERROR_MESSAGE);
        }).then(function () {
            if (passInput) passInput.value = "";
            if (confirmInput) confirmInput.value = "";
            App.settingsBackupExportInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.exportEncryptedBackup = exportEncryptedBackup;

    function previewEncryptedBackupManifest() {
        if (anySettingsOperationInProgress()) return;
        App.settingsBackupManifestInProgress = true;
        setSettingsControlsDisabled(true);
        setSettingsBackupStatus("正在读取备份清单…");
        App.bridge.previewEncryptedBackupManifest().then(function (result) {
            var data = App.handleResult(result, function (message) {
                setSettingsBackupStatus(message || BACKUP_MANIFEST_ERROR_MESSAGE);
                renderBackupManifest(null, "");
            });
            if (!data) return;
            setSettingsBackupStatus("");
            renderBackupManifest(data.manifest, data.filename);
        }).catch(function () {
            setSettingsBackupStatus(BACKUP_MANIFEST_ERROR_MESSAGE);
            renderBackupManifest(null, "");
        }).then(function () {
            App.settingsBackupManifestInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.previewEncryptedBackupManifest = previewEncryptedBackupManifest;

    function importEncryptedBackup() {
        if (anySettingsOperationInProgress()) return;
        var passInput = element("settings-backup-import-passphrase");
        var confirmInput = element("settings-backup-import-confirm");
        var passphrase = passInput ? String(passInput.value || "") : "";
        var confirmation = confirmInput ? String(confirmInput.value || "") : "";
        if (!passphrase.trim()) return setSettingsImportStatus("请输入备份口令");
        if (confirmation.trim() !== IMPORT_CONFIRM_LITERAL) {
            return setSettingsImportStatus("请输入确认文字：" + IMPORT_CONFIRM_LITERAL);
        }
        App.settingsBackupImportInProgress = true;
        setSettingsControlsDisabled(true);
        setSettingsImportStatus("正在导入加密备份…");
        App.bridge.importEncryptedBackup(passphrase, confirmation).then(function (result) {
            var data = App.handleResult(result, function (message) {
                setSettingsImportStatus(message || BACKUP_IMPORT_ERROR_MESSAGE);
            });
            if (!data) return;
            var tableCount = Number(data.imported_table_count || 0);
            var rowCount = Number(data.imported_row_count || 0);
            var message = data.message || "加密备份已导入";
            if (tableCount > 0 || rowCount > 0) {
                message += "（已导入：" + tableCount + " 个数据组 / " + rowCount + " 条记录）";
            }
            setSettingsImportStatus(message);
            App.resetClientGeneration("database_replacement");
            renderBackupManifest(null, "");
            return loadSettingsPrivacyStatus().then(function () {
                if (typeof App.refreshAll === "function") App.refreshAll();
            });
        }).catch(function () {
            setSettingsImportStatus(BACKUP_IMPORT_ERROR_MESSAGE);
        }).then(function () {
            if (passInput) passInput.value = "";
            if (confirmInput) confirmInput.value = "";
            App.settingsBackupImportInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.importEncryptedBackup = importEncryptedBackup;

    function clearAllLocalData() {
        if (anySettingsOperationInProgress()) return;
        var confirmInput = element("settings-clear-confirm");
        var confirmation = confirmInput ? String(confirmInput.value || "") : "";
        if (confirmation.trim() !== CLEAR_CONFIRM_LITERAL) {
            return setSettingsClearStatus("请输入确认文字：" + CLEAR_CONFIRM_LITERAL);
        }
        App.settingsClearAllInProgress = true;
        setSettingsControlsDisabled(true);
        setSettingsClearStatus("正在清空本地数据…");
        App.bridge.clearAllLocalData(confirmation).then(function (result) {
            var data = App.handleResult(result, function (message) {
                setSettingsClearStatus(message || CLEAR_ALL_ERROR_MESSAGE);
            });
            if (!data) return;
            setSettingsClearStatus(data.message || "本地数据已清空");
            App.resetClientGeneration("database_replacement");
            renderBackupManifest(null, "");
            return loadSettingsPrivacyStatus().then(function () {
                if (typeof App.refreshAll === "function") App.refreshAll();
            });
        }).catch(function () {
            setSettingsClearStatus(CLEAR_ALL_ERROR_MESSAGE);
        }).then(function () {
            if (confirmInput) confirmInput.value = "";
            App.settingsClearAllInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.clearAllLocalData = clearAllLocalData;

    function setFirstRunNoticeError(message) { setStatusLine("first-run-notice-error", message); }

    function clearChildren(target) {
        if (!target) return;
        while (target.firstChild) target.removeChild(target.firstChild);
    }

    function renderFirstRunNotice(notice, mode) {
        if (!notice) return;
        var title = element("first-run-notice-title");
        var highlights = element("first-run-notice-highlights");
        var text = element("first-run-notice-text");
        var accept = element("first-run-notice-accept-btn");
        var close = element("first-run-notice-close-btn");
        var retry = element("first-run-notice-retry-btn");
        if (title) title.textContent = String(notice.title || "WorkTrace 隐私说明");
        clearChildren(highlights);
        if (highlights && Array.isArray(notice.highlights)) {
            notice.highlights.forEach(function (item) {
                var li = document.createElement("li");
                li.textContent = String(item || "");
                highlights.appendChild(li);
            });
        }
        if (text) text.textContent = String(notice.text || "");
        if (accept) { accept.hidden = mode === "view"; accept.disabled = false; }
        if (close) close.hidden = mode !== "view";
        // The retry button is only for load-failure recovery; hide it in
        // normal gate and view modes.
        if (retry) retry.hidden = true;
        setFirstRunNoticeError("");
    }
    App.renderFirstRunNotice = renderFirstRunNotice;

    function showFirstRunNotice(notice, mode) {
        App.firstRunNoticeViewingFromSettings = mode === "view";
        renderFirstRunNotice(notice, mode);
        var overlay = element("first-run-notice-overlay");
        if (overlay) overlay.hidden = false;
    }
    App.showFirstRunNotice = showFirstRunNotice;

    function showFirstRunNoticeBlockingError(message) {
        var title = element("first-run-notice-title");
        var highlights = element("first-run-notice-highlights");
        var text = element("first-run-notice-text");
        var accept = element("first-run-notice-accept-btn");
        var close = element("first-run-notice-close-btn");
        var retry = element("first-run-notice-retry-btn");
        if (title) title.textContent = "";
        clearChildren(highlights);
        if (text) text.textContent = "";
        if (accept) { accept.hidden = true; accept.disabled = true; }
        if (close) close.hidden = true;
        // On load failure the overlay stays open (fail-closed) and only the
        // retry button is available — the user cannot close the overlay or
        // bypass authorization. The retry button re-issues the real
        // getFirstRunNotice without clearing any persisted authorization.
        if (retry) { retry.hidden = false; retry.disabled = false; }
        setFirstRunNoticeError(message || FIRST_RUN_NOTICE_LOAD_ERROR);
        var overlay = element("first-run-notice-overlay");
        if (overlay) overlay.hidden = false;
    }
    App.showFirstRunNoticeBlockingError = showFirstRunNoticeBlockingError;

    function hideFirstRunNotice() {
        var overlay = element("first-run-notice-overlay");
        if (overlay) overlay.hidden = true;
        App.firstRunNoticeViewingFromSettings = false;
    }
    App.hideFirstRunNotice = hideFirstRunNotice;

    // Single accepted-UI settlement helper: closes the blocking overlay and
    // clears residual load-failure UI. Does NOT start heartbeat, load
    // projects, call the Bridge, or change persisted authorization.
    function settleFirstRunNoticeAcceptedUi() {
        var retry = element("first-run-notice-retry-btn");
        var accept = element("first-run-notice-accept-btn");
        var close = element("first-run-notice-close-btn");

        setFirstRunNoticeError("");

        if (retry) {
            retry.hidden = true;
            retry.disabled = false;
        }

        if (accept) {
            accept.hidden = false;
            accept.disabled = false;
        }

        if (close) close.hidden = true;

        hideFirstRunNotice();
    }
    App.settleFirstRunNoticeAcceptedUi = settleFirstRunNoticeAcceptedUi;

    function setPrivacyGateState(state) {
        App.privacyGateState = state;
        App.firstRunNoticeRequired = state === "acceptance_required";
    }
    App.setPrivacyGateState = setPrivacyGateState;

    function loadFirstRunNotice(options) {
        var force = !!(options && options.force);
        if (App.firstRunNoticeLoading) return Promise.resolve(App.privacyGateState === "accepted_ready");
        if (App.firstRunNoticeLoaded && !force) {
            return Promise.resolve(App.privacyGateState === "accepted_ready");
        }
        App.firstRunNoticeLoading = true;
        setPrivacyGateState("loading");
        return App.bridge.getFirstRunNotice().then(function (result) {
            App.firstRunNoticeLoading = false;
            if (!result || result.ok === false) {
                setPrivacyGateState("load_failed");
                showFirstRunNoticeBlockingError(
                    App.extractBridgeError(result, FIRST_RUN_NOTICE_LOAD_ERROR)
                );
                return false;
            }
            App.firstRunNoticeLoaded = true;
            var notice = result.notice || {};
            var accepted = notice.accepted === true;
            if (accepted) {
                setPrivacyGateState("accepted_ready");
                // Close any residual blocking overlay from a prior load
                // failure and clear retry/error UI. The post-privacy startup
                // entry (init.js) continues startup based on this state.
                settleFirstRunNoticeAcceptedUi();
                return true;
            }
            setPrivacyGateState("acceptance_required");
            showFirstRunNotice(notice, "gate");
            return true;
        }).catch(function () {
            App.firstRunNoticeLoading = false;
            setPrivacyGateState("load_failed");
            showFirstRunNoticeBlockingError(FIRST_RUN_NOTICE_LOAD_ERROR);
            return false;
        });
    }
    App.loadFirstRunNotice = loadFirstRunNotice;

    function acceptFirstRunNotice() {
        if (App.firstRunNoticeAcceptInProgress) return;
        App.firstRunNoticeAcceptInProgress = true;
        var accept = element("first-run-notice-accept-btn");
        if (accept) accept.disabled = true;
        setFirstRunNoticeError("");
        setPrivacyGateState("accepted_starting");
        App.bridge.acceptFirstRunNotice().then(function (result) {
            var accepted = !!(result && result.accepted === true);
            if (accepted && result.ok === true) {
                // Full success: authorization persisted and collector started.
                // Continue through the single idempotent startup entry so that
                // project catalog, refresh state, page refresh, and heartbeat
                // are owned by init.js — no second startup path here.
                setPrivacyGateState("accepted_ready");
                App.firstRunNoticeRequired = false;
                settleFirstRunNoticeAcceptedUi();
                if (typeof App.continueStartupAfterPrivacyGate === "function") {
                    App.continueStartupAfterPrivacyGate();
                }
                loadSettingsPrivacyStatus();
                return;
            }
            if (accepted && result.ok === false) {
                // Authorization persisted but collector failed; close gate, enter app.
                setPrivacyGateState("accepted_start_failed");
                App.firstRunNoticeRequired = false;
                settleFirstRunNoticeAcceptedUi();
                var message = App.extractBridgeError(
                    result,
                    "隐私说明已确认，但记录功能未能启动。可前往设置查看原因或重试。"
                );
                if (App.showGlobalAlert) App.showGlobalAlert(message);
                if (typeof App.continueStartupAfterPrivacyGate === "function") {
                    App.continueStartupAfterPrivacyGate();
                }
                loadSettingsPrivacyStatus();
                return;
            }
            // Authorization persistence failed: keep the gate open and let the
            // user retry. Do not continue startup or start heartbeat.
            setPrivacyGateState("acceptance_required");
            setFirstRunNoticeError(
                App.extractBridgeError(result, FIRST_RUN_NOTICE_ACCEPT_ERROR)
            );
        }).catch(function () {
            setPrivacyGateState("acceptance_required");
            setFirstRunNoticeError(FIRST_RUN_NOTICE_ACCEPT_ERROR);
        }).then(function () {
            App.firstRunNoticeAcceptInProgress = false;
            if (accept) accept.disabled = false;
        });
    }
    App.acceptFirstRunNotice = acceptFirstRunNotice;

    function openPrivacyNoticeFromSettings() {
        App.bridge.getFirstRunNotice().then(function (result) {
            if (!result || result.ok === false) {
                showFirstRunNoticeBlockingError(
                    (result && result.error) || FIRST_RUN_NOTICE_LOAD_ERROR
                );
                var accept = element("first-run-notice-accept-btn");
                var close = element("first-run-notice-close-btn");
                if (accept) accept.hidden = true;
                if (close) close.hidden = false;
                App.firstRunNoticeViewingFromSettings = true;
                return;
            }
            showFirstRunNotice(result.notice || {}, "view");
        }).catch(function () {
            showFirstRunNoticeBlockingError(FIRST_RUN_NOTICE_LOAD_ERROR);
            var accept = element("first-run-notice-accept-btn");
            var close = element("first-run-notice-close-btn");
            if (accept) accept.hidden = true;
            if (close) close.hidden = false;
            App.firstRunNoticeViewingFromSettings = true;
        });
    }
    App.openPrivacyNoticeFromSettings = openPrivacyNoticeFromSettings;
})();
