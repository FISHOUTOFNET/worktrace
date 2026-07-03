// WorkTrace WebView frontend — settings module.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};


    var ERROR_MESSAGE = "加载设置状态失败";
    var WRITE_ERROR_MESSAGE = "设置剪贴板记录失败";

    function showSettingsError(message) {
        var banner = document.getElementById("settings-error");
        if (!banner) return;
        if (!message) {
            banner.hidden = true;
            banner.textContent = ERROR_MESSAGE;
            return;
        }
        banner.hidden = false;
        banner.textContent = message;
    }
    App.showSettingsError = showSettingsError;

    function clearSettingsError() {
        showSettingsError("");
    }
    App.clearSettingsError = clearSettingsError;

    function anySettingsOperationInProgress() {
        // True when any Settings read / capture-toggle write / backup export /
        return !!(
            App.settingsLoading
            || App.settingsWriteInProgress
            || App.settingsBackupExportInProgress
            || App.settingsBackupManifestInProgress
            || App.settingsBackupImportInProgress
            || App.settingsClearAllInProgress
        );
    }
    App.anySettingsOperationInProgress = anySettingsOperationInProgress;

    function setSettingsBackupControlsDisabled(disabled) {
        // editable even when the first ``get_settings_privacy_status`` read
        var backupDisabled = !!disabled;
        var exportBtn = document.getElementById("settings-backup-export-btn");
        var manifestBtn = document.getElementById("settings-backup-manifest-btn");
        var passInput = document.getElementById("settings-backup-passphrase");
        var passConfirmInput = document.getElementById("settings-backup-passphrase-confirm");
        var importPassInput = document.getElementById("settings-backup-import-passphrase");
        var importConfirmInput = document.getElementById("settings-backup-import-confirm");
        var importBtn = document.getElementById("settings-backup-import-btn");
        if (exportBtn) exportBtn.disabled = backupDisabled;
        if (manifestBtn) manifestBtn.disabled = backupDisabled;
        if (passInput) passInput.disabled = backupDisabled;
        if (passConfirmInput) passConfirmInput.disabled = backupDisabled;
        if (importPassInput) importPassInput.disabled = backupDisabled;
        if (importConfirmInput) importConfirmInput.disabled = backupDisabled;
        if (importBtn) importBtn.disabled = backupDisabled;
    }
    App.setSettingsBackupControlsDisabled = setSettingsBackupControlsDisabled;

    function setSettingsDangerControlsDisabled(disabled) {
        var dangerDisabled = !!disabled;
        var clearConfirmInput = document.getElementById("settings-clear-confirm");
        var clearBtn = document.getElementById("settings-clear-local-data-btn");
        if (clearConfirmInput) clearConfirmInput.disabled = dangerDisabled;
        if (clearBtn) clearBtn.disabled = dangerDisabled;
    }
    App.setSettingsDangerControlsDisabled = setSettingsDangerControlsDisabled;

    function setSettingsControlsDisabled(disabled) {
        // (export / manifest / import), and the danger controls (clear-all).
        var toggle = document.getElementById("settings-clipboard-toggle");
        if (toggle) toggle.disabled = disabled || !App.settingsLoaded;
        setSettingsBackupControlsDisabled(disabled);
        setSettingsDangerControlsDisabled(disabled);
    }
    App.setSettingsControlsDisabled = setSettingsControlsDisabled;

    function setSettingsLoading(loading) {
        App.settingsLoading = loading;
        var el = document.getElementById("settings-loading");
        if (el) el.hidden = !loading;
        // disabled while a read is in flight or any write is in progress.
        setSettingsControlsDisabled(anySettingsOperationInProgress());
    }
    App.setSettingsLoading = setSettingsLoading;

    function boolLabel(value) {
        // Boolean rendering only. Never returns the raw value or any
        return value ? "开启" : "关闭";
    }

    function setLineText(key, text) {
        // Render dynamic text via textContent only. The data-settings-key
        var el = document.querySelector(
            '#settings-status [data-settings-key="' + key + '"]'
        );
        if (el) el.textContent = text;
    }

    function setCaptureToggleStatus(text) {
        var el = document.getElementById("settings-clipboard-toggle-status");
        if (el) el.textContent = text;
    }
    App.setCaptureToggleStatus = setCaptureToggleStatus;

    function renderCaptureToggle(status) {
        var toggle = document.getElementById("settings-clipboard-toggle");
        if (!toggle) return;
        var captureEnabled = !!(status && status.clipboard_capture_enabled);
        toggle.checked = captureEnabled;
        toggle.disabled = anySettingsOperationInProgress() || !App.settingsLoaded;
        setCaptureToggleStatus(boolLabel(captureEnabled));
    }
    App.renderCaptureToggle = renderCaptureToggle;

    function renderSettingsStatus(status) {
        // Renders booleans, the static local-only storage model, and the
        if (!status) return;
        var exportPathConfigured = !!status.export_path_configured;
        var secureImportInProgress = !!status.secure_import_in_progress;
        renderCaptureToggle(status);
        // Privacy card lines. The export path is intentionally only shown
        setLineText(
            "export_path_configured",
            exportPathConfigured ? "导出目录：已配置" : "导出目录：未配置"
        );
        setLineText(
            "secure_import_in_progress",
            "加密备份导入进行中：" + boolLabel(secureImportInProgress)
        );
        // The storage card line is static; the bridge confirms the storage
        if (status.storage_model === "local_only") {
            setLineText(
                "storage_model",
                "本地优先：所有数据仅存储在本机，不上传任何远端服务器。"
            );
        }
        // Render the display-safe first-run notice status line. The raw DB
        var noticeAccepted = false;
        if (status.first_run_notice && typeof status.first_run_notice === "object") {
            noticeAccepted = !!status.first_run_notice.accepted;
        }
        var noticeStatusEl = document.getElementById("settings-privacy-notice-status");
        if (noticeStatusEl) {
            noticeStatusEl.textContent = "隐私说明：" + (noticeAccepted ? "已确认" : "未确认");
        }
        var statusEl = document.getElementById("settings-status");
        if (statusEl) statusEl.hidden = false;
    }
    App.renderSettingsStatus = renderSettingsStatus;

    function loadSettingsPrivacyStatus() {
        // Promise so import / clear success paths can chain a status
        if (App.settingsLoading) return Promise.resolve();
        setSettingsLoading(true);
        clearSettingsError();
        var token = ++App.settingsRequestToken;
        return App.callBridge("get_settings_privacy_status").then(function (result) {
            if (token !== App.settingsRequestToken) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                // Never surface raw exception text; the bridge already
                showSettingsError(msg || ERROR_MESSAGE);
            });
            setSettingsLoading(false);
            if (!data) {
                // user does not see stale cards after a failure.
                return;
            }
            App.settingsLoaded = true;
            renderSettingsStatus(data.status);
            clearSettingsError();
        }).catch(function () {
            if (token !== App.settingsRequestToken) return;  // stale response
            setSettingsLoading(false);
            showSettingsError(ERROR_MESSAGE);
        });
    }
    App.loadSettingsPrivacyStatus = loadSettingsPrivacyStatus;


    function setCaptureEnabled(enabled) {
        // Write the clipboard_capture_enabled flag through the bridge.
        App.settingsWriteInProgress = true;
        setSettingsControlsDisabled(true);
        var toggle = document.getElementById("settings-clipboard-toggle");
        return App.callBridge("set_clipboard_capture_enabled", enabled).then(function (result) {
            var data = App.handleResult(result, function (msg) {
                // Never surface raw exception text; the bridge already
                showSettingsError(msg || WRITE_ERROR_MESSAGE);
            });
            if (!data) {
                if (toggle) toggle.checked = !enabled;
                setCaptureToggleStatus(boolLabel(!enabled));
                return;
            }
            renderSettingsStatus(data.status);
            clearSettingsError();
        }).catch(function () {
            // Never read .message; show stable Chinese error.
            showSettingsError(WRITE_ERROR_MESSAGE);
            if (toggle) toggle.checked = !enabled;
            setCaptureToggleStatus(boolLabel(!enabled));
        }).then(function () {
            // finally semantics: clear the write flag and re-enable
            App.settingsWriteInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.setCaptureEnabled = setCaptureEnabled;

    function handleCaptureToggleChange(event) {
        var toggle = event ? event.target : document.getElementById("settings-clipboard-toggle");
        if (!toggle) return;
        // but defensive). Also ignore if a write is already in flight.
        if (toggle.disabled || App.settingsWriteInProgress) {
            return;
        }
        var enabled = !!toggle.checked;
        setCaptureEnabled(enabled);
    }
    App.handleCaptureToggleChange = handleCaptureToggleChange;


    var BACKUP_EXPORT_ERROR_MESSAGE = "导出加密备份失败";
    var BACKUP_MANIFEST_ERROR_MESSAGE = "读取备份清单失败";

    function setSettingsBackupStatus(text) {
        // settings-error banner). Renders via textContent only.
        var el = document.getElementById("settings-backup-status");
        if (!el) return;
        if (!text) {
            el.hidden = true;
            el.textContent = "";
            return;
        }
        el.hidden = false;
        el.textContent = text;
    }
    App.setSettingsBackupStatus = setSettingsBackupStatus;

    function clearSettingsBackupStatus() {
        setSettingsBackupStatus("");
    }
    App.clearSettingsBackupStatus = clearSettingsBackupStatus;

    function renderBackupManifest(manifest, filename) {
        // Render display-safe manifest fields via textContent only. The
        var container = document.getElementById("settings-backup-manifest");
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
            var fields = [
                ["清单版本", manifest.version],
                ["应用版本", manifest.app_version],
                ["创建时间", manifest.created_at],
                ["KDF 算法", manifest.kdf_algorithm],
                ["载荷格式", manifest.payload_format],
                ["载荷算法", manifest.payload_alg]
            ];
            for (var i = 0; i < fields.length; i++) {
                var dt = document.createElement("dt");
                dt.textContent = fields[i][0];
                var dd = document.createElement("dd");
                var value = fields[i][1];
                dd.textContent = (value === undefined || value === null) ? "" : String(value);
                fieldsEl.appendChild(dt);
                fieldsEl.appendChild(dd);
            }
        }
        container.hidden = false;
    }
    App.renderBackupManifest = renderBackupManifest;

    function exportEncryptedBackup() {
        // Read passphrase + confirm passphrase from the two password
        if (anySettingsOperationInProgress()) return;
        var passInput = document.getElementById("settings-backup-passphrase");
        var passConfirmInput = document.getElementById("settings-backup-passphrase-confirm");
        var passphrase = passInput ? String(passInput.value || "") : "";
        var confirmPassphrase = passConfirmInput ? String(passConfirmInput.value || "") : "";
        if (!passphrase || !passphrase.trim()) {
            setSettingsBackupStatus("请输入备份口令");
            return;
        }
        if (confirmPassphrase !== passphrase) {
            setSettingsBackupStatus("两次输入的备份口令不一致");
            return;
        }
        App.settingsBackupExportInProgress = true;
        setSettingsControlsDisabled(true);
        setSettingsBackupStatus("正在导出加密备份…");
        App.callBridge("export_encrypted_backup", passphrase, confirmPassphrase).then(function (result) {
            var data = App.handleResult(result, function (msg) {
                // Bridge already collapsed to a stable Chinese message.
                setSettingsBackupStatus(msg || BACKUP_EXPORT_ERROR_MESSAGE);
            });
            if (!data) return;
            setSettingsBackupStatus("已导出：" + (data.filename || ""));
        }).catch(function () {
            // Never read .message; show stable Chinese error.
            setSettingsBackupStatus(BACKUP_EXPORT_ERROR_MESSAGE);
        }).then(function () {
            // finally: clear passphrase inputs, clear in-flight flag,
            if (passInput) passInput.value = "";
            if (passConfirmInput) passConfirmInput.value = "";
            App.settingsBackupExportInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.exportEncryptedBackup = exportEncryptedBackup;

    function previewEncryptedBackupManifest() {
        // No passphrase required; the bridge opens a native open file
        if (anySettingsOperationInProgress()) return;
        App.settingsBackupManifestInProgress = true;
        setSettingsControlsDisabled(true);
        setSettingsBackupStatus("正在读取备份清单…");
        App.callBridge("preview_encrypted_backup_manifest").then(function (result) {
            var data = App.handleResult(result, function (msg) {
                // Bridge already collapsed to a stable Chinese message.
                setSettingsBackupStatus(msg || BACKUP_MANIFEST_ERROR_MESSAGE);
                renderBackupManifest(null, "");
            });
            if (!data) return;
            setSettingsBackupStatus("");
            renderBackupManifest(data.manifest, data.filename);
        }).catch(function () {
            // Never read .message; show stable Chinese error.
            setSettingsBackupStatus(BACKUP_MANIFEST_ERROR_MESSAGE);
            renderBackupManifest(null, "");
        }).then(function () {
            App.settingsBackupManifestInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.previewEncryptedBackupManifest = previewEncryptedBackupManifest;


    var BACKUP_IMPORT_ERROR_MESSAGE = "导入加密备份失败";
    var CLEAR_ALL_ERROR_MESSAGE = "清空本地数据失败";
    var IMPORT_CONFIRM_LITERAL = "导入并替换";
    var CLEAR_CONFIRM_LITERAL = "清空本地数据";

    function setSettingsImportStatus(text) {
        // via textContent only.
        var el = document.getElementById("settings-backup-import-status");
        if (!el) return;
        if (!text) {
            el.hidden = true;
            el.textContent = "";
            return;
        }
        el.hidden = false;
        el.textContent = text;
    }
    App.setSettingsImportStatus = setSettingsImportStatus;

    function clearSettingsImportStatus() {
        setSettingsImportStatus("");
    }
    App.clearSettingsImportStatus = clearSettingsImportStatus;

    function setSettingsClearStatus(text) {
        // Clear-all-specific status line. Renders via textContent only.
        var el = document.getElementById("settings-clear-status");
        if (!el) return;
        if (!text) {
            el.hidden = true;
            el.textContent = "";
            return;
        }
        el.hidden = false;
        el.textContent = text;
    }
    App.setSettingsClearStatus = setSettingsClearStatus;

    function clearSettingsClearStatus() {
        setSettingsClearStatus("");
    }
    App.clearSettingsClearStatus = clearSettingsClearStatus;

    function clearBackupManifestPreview() {
        // Hide and clear any last-rendered manifest preview so the
        renderBackupManifest(null, "");
    }
    App.clearBackupManifestPreview = clearBackupManifestPreview;

    function resetFrontendAfterLocalDataReplacement() {
        App.timelineLoaded = false;
        App.statisticsLoaded = false;
        App.rulesLoaded = false;
        App.projectsCache = null;
        App.currentSessions = [];
        // Clear per-session / per-activity selection state so a stale id
        App.selectedSessionId = null;
        App.editingSession = null;
        App.editingActivityId = null;
        App.editingSplitActivityId = null;
        App.mergingActivityId = null;
        App.hidingActivityId = null;
        App.deletingActivityId = null;
        App.selectedBatchActivityIds = {};
        // Clear cached payloads so the next page visit re-fetches.
        App.lastTimelineData = null;
        App.lastProjectRulesData = null;
        // caller chains App.loadSettingsPrivacyStatus() after this so the
    }
    App.resetFrontendAfterLocalDataReplacement = resetFrontendAfterLocalDataReplacement;

    function importEncryptedBackup() {
        // Read passphrase + confirm text from the import inputs. Do NOT
        if (anySettingsOperationInProgress()) return;
        var passInput = document.getElementById("settings-backup-import-passphrase");
        var confirmInput = document.getElementById("settings-backup-import-confirm");
        var passphrase = passInput ? String(passInput.value || "") : "";
        var confirmText = confirmInput ? String(confirmInput.value || "") : "";
        if (!passphrase || !passphrase.trim()) {
            setSettingsImportStatus("请输入备份口令");
            return;
        }
        if (!confirmText || confirmText.trim() !== IMPORT_CONFIRM_LITERAL) {
            setSettingsImportStatus("请输入确认文字：" + IMPORT_CONFIRM_LITERAL);
            return;
        }
        App.settingsBackupImportInProgress = true;
        setSettingsControlsDisabled(true);
        setSettingsImportStatus("正在导入加密备份…");
        App.callBridge("import_encrypted_backup", passphrase, confirmText).then(function (result) {
            var data = App.handleResult(result, function (msg) {
                // Bridge already collapsed to a stable Chinese message.
                setSettingsImportStatus(msg || BACKUP_IMPORT_ERROR_MESSAGE);
            });
            if (!data) return;
            // imported row count. Table names / paths / payload never
            var tableCount = Number(data.imported_table_count || 0);
            var rowCount = Number(data.imported_row_count || 0);
            var statusText = (data.message || "加密备份已导入");
            if (tableCount > 0 || rowCount > 0) {
                statusText += "（已导入：" + tableCount + " 个数据组 / " + rowCount + " 条记录）";
            }
            setSettingsImportStatus(statusText);
            // Reset frontend caches so stale Timeline / Statistics /
            resetFrontendAfterLocalDataReplacement();
            // Hide any last-rendered manifest preview; it referred
            clearBackupManifestPreview();
            return App.loadSettingsPrivacyStatus().then(function () {
                if (typeof App.refreshAll === "function") {
                    App.refreshAll();
                }
            });
        }).catch(function () {
            // Never read .message; show stable Chinese error.
            setSettingsImportStatus(BACKUP_IMPORT_ERROR_MESSAGE);
        }).then(function () {
            // finally: clear passphrase + confirm inputs, clear the
            if (passInput) passInput.value = "";
            if (confirmInput) confirmInput.value = "";
            App.settingsBackupImportInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.importEncryptedBackup = importEncryptedBackup;

    function clearAllLocalData() {
        // Read the explicit Chinese confirmation literal. No native dialog
        if (anySettingsOperationInProgress()) return;
        var confirmInput = document.getElementById("settings-clear-confirm");
        var confirmText = confirmInput ? String(confirmInput.value || "") : "";
        if (!confirmText || confirmText.trim() !== CLEAR_CONFIRM_LITERAL) {
            setSettingsClearStatus("请输入确认文字：" + CLEAR_CONFIRM_LITERAL);
            return;
        }
        App.settingsClearAllInProgress = true;
        setSettingsControlsDisabled(true);
        setSettingsClearStatus("正在清空本地数据…");
        App.callBridge("clear_all_local_data", confirmText).then(function (result) {
            var data = App.handleResult(result, function (msg) {
                // Bridge already collapsed to a stable Chinese message.
                setSettingsClearStatus(msg || CLEAR_ALL_ERROR_MESSAGE);
            });
            if (!data) return;
            setSettingsClearStatus(data.message || "本地数据已清空");
            // Reset frontend caches so stale Timeline / Statistics /
            resetFrontendAfterLocalDataReplacement();
            // Hide any last-rendered manifest preview; it referred
            clearBackupManifestPreview();
            return App.loadSettingsPrivacyStatus().then(function () {
                if (typeof App.refreshAll === "function") {
                    App.refreshAll();
                }
            });
        }).catch(function () {
            // Never read .message; show stable Chinese error.
            setSettingsClearStatus(CLEAR_ALL_ERROR_MESSAGE);
        }).then(function () {
            // finally: clear the confirm input, clear the in-flight flag,
            if (confirmInput) confirmInput.value = "";
            App.settingsClearAllInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.clearAllLocalData = clearAllLocalData;

    // First-run privacy notice

    var FIRST_RUN_NOTICE_LOAD_ERROR = "隐私说明加载失败。为保护隐私，WorkTrace 暂不会启动记录。请重启应用或重新安装。";
    var FIRST_RUN_NOTICE_ACCEPT_ERROR = "确认隐私说明失败";

    function setFirstRunNoticeError(message) {
        var el = document.getElementById("first-run-notice-error");
        if (!el) return;
        if (!message) {
            el.hidden = true;
            el.textContent = "";
            return;
        }
        el.hidden = false;
        el.textContent = message;
    }

    function renderFirstRunNotice(data, mode) {
        // Render title / highlights / notice text into the overlay DOM.
        if (!data) return;
        var titleEl = document.getElementById("first-run-notice-title");
        if (titleEl) {
            titleEl.textContent = String(data.title || "WorkTrace 隐私说明");
        }
        var highlightsEl = document.getElementById("first-run-notice-highlights");
        if (highlightsEl) {
            // Clear existing highlight items via DOM removal (no markup APIs).
            while (highlightsEl.firstChild) {
                highlightsEl.removeChild(highlightsEl.firstChild);
            }
            var highlights = data.highlights;
            if (Array.isArray(highlights)) {
                for (var i = 0; i < highlights.length; i++) {
                    var li = document.createElement("li");
                    li.textContent = String(highlights[i] || "");
                    highlightsEl.appendChild(li);
                }
            }
        }
        var textEl = document.getElementById("first-run-notice-text");
        if (textEl) {
            // Use the DOM text API for the notice body. The <pre> element
            textEl.textContent = String(data.notice_text || "");
        }
        var acceptBtn = document.getElementById("first-run-notice-accept-btn");
        var closeBtn = document.getElementById("first-run-notice-close-btn");
        if (mode === "view") {
            // The user has already accepted (or the gate would be active).
            if (acceptBtn) acceptBtn.hidden = true;
            if (closeBtn) closeBtn.hidden = false;
        } else {
            // Gate mode (blocking): show accept, hide close. The only way
            if (acceptBtn) acceptBtn.hidden = false;
            if (closeBtn) closeBtn.hidden = true;
        }
        setFirstRunNoticeError("");
    }
    App.renderFirstRunNotice = renderFirstRunNotice;

    function showFirstRunNotice(data, mode) {
        // Show the overlay in the requested mode. ``data`` is the payload
        App.firstRunNoticeViewingFromSettings = (mode === "view");
        renderFirstRunNotice(data, mode);
        var overlay = document.getElementById("first-run-notice-overlay");
        if (overlay) overlay.hidden = false;
    }
    App.showFirstRunNotice = showFirstRunNotice;

    function showFirstRunNoticeBlockingError(message) {
        // Strict fail-closed: show the overlay with NO notice body, NO
        var titleEl = document.getElementById("first-run-notice-title");
        if (titleEl) titleEl.textContent = "";
        var highlightsEl = document.getElementById("first-run-notice-highlights");
        if (highlightsEl) {
            while (highlightsEl.firstChild) {
                highlightsEl.removeChild(highlightsEl.firstChild);
            }
        }
        var textEl = document.getElementById("first-run-notice-text");
        if (textEl) textEl.textContent = "";
        var acceptBtn = document.getElementById("first-run-notice-accept-btn");
        if (acceptBtn) {
            acceptBtn.hidden = true;
            acceptBtn.disabled = true;
        }
        var closeBtn = document.getElementById("first-run-notice-close-btn");
        if (closeBtn) closeBtn.hidden = true;
        setFirstRunNoticeError(message || FIRST_RUN_NOTICE_LOAD_ERROR);
        var overlay = document.getElementById("first-run-notice-overlay");
        if (overlay) overlay.hidden = false;
    }
    App.showFirstRunNoticeBlockingError = showFirstRunNoticeBlockingError;

    function hideFirstRunNotice() {
        // Hides only the overlay; never calls the bridge. Gate dismissal is allowed only after accept succeeds
        // elsewhere; firstRunNoticeRequired remains owned by the accept/load flow.
        var overlay = document.getElementById("first-run-notice-overlay");
        if (overlay) overlay.hidden = true;
        App.firstRunNoticeViewingFromSettings = false;
    }
    App.hideFirstRunNotice = hideFirstRunNotice;

    function loadFirstRunNotice() {
        // Fail closed: a load failure shows an empty blocking error.
        if (App.firstRunNoticeLoading || App.firstRunNoticeLoaded) return Promise.resolve(true);
        App.firstRunNoticeLoading = true;
        return App.callBridge("get_first_run_notice").then(function (result) {
            App.firstRunNoticeLoading = false;
            App.firstRunNoticeLoaded = true;
            if (!result || result.ok === false) {
                // Accepted-state read failure keeps the gate blocking.
                App.firstRunNoticeRequired = true;
                showFirstRunNoticeBlockingError(
                    (result && result.error) || FIRST_RUN_NOTICE_LOAD_ERROR
                );
                return false;
            }
            if (result.accepted === false) {
                // First run: show the blocking gate with the official
                App.firstRunNoticeRequired = true;
                showFirstRunNotice(result, "gate");
            } else {
                // can still view the notice read-only from Settings.
                App.firstRunNoticeRequired = false;
            }
            return true;
        }).catch(function () {
            // Bridge rejection: show the blocking error overlay
            App.firstRunNoticeLoading = false;
            App.firstRunNoticeRequired = true;
            showFirstRunNoticeBlockingError(FIRST_RUN_NOTICE_LOAD_ERROR);
            return false;
        });
    }
    App.loadFirstRunNotice = loadFirstRunNotice;

    function acceptFirstRunNotice() {
        // Accept handler for the gate-mode accept button. Calls the
        if (App.firstRunNoticeAcceptInProgress) return;
        App.firstRunNoticeAcceptInProgress = true;
        var acceptBtn = document.getElementById("first-run-notice-accept-btn");
        if (acceptBtn) acceptBtn.disabled = true;
        setFirstRunNoticeError("");
        App.callBridge("accept_first_run_notice").then(function (result) {
            var data = App.handleResult(result, function (msg) {
                // Bridge already collapsed to a stable Chinese message.
                setFirstRunNoticeError(msg || FIRST_RUN_NOTICE_ACCEPT_ERROR);
            });
            if (!data) return;
            // Success: hide the gate, clear the required flag.
            App.firstRunNoticeRequired = false;
            hideFirstRunNotice();
            // so the sidebar reflects the now-running collector. Also
            if (typeof App.refreshAll === "function") {
                App.refreshAll();
            }
            try {
                App.loadSettingsPrivacyStatus();
            } catch (e) {
            }
        }).catch(function () {
            // Never read .message; show stable Chinese error.
            setFirstRunNoticeError(FIRST_RUN_NOTICE_ACCEPT_ERROR);
        }).then(function () {
            // finally: clear the in-flight flag and re-enable the
            App.firstRunNoticeAcceptInProgress = false;
            if (acceptBtn) acceptBtn.disabled = false;
        });
    }
    App.acceptFirstRunNotice = acceptFirstRunNotice;

    function openPrivacyNoticeFromSettings() {
        // Read-only "查看隐私说明" entry on the Settings / Privacy page.
        App.callBridge("get_first_run_notice").then(function (result) {
            if (!result || result.ok === false) {
                // No notice body, no accept button.
                App.firstRunNoticeViewingFromSettings = true;
                var titleEl = document.getElementById("first-run-notice-title");
                if (titleEl) titleEl.textContent = "";
                var highlightsEl = document.getElementById("first-run-notice-highlights");
                if (highlightsEl) {
                    while (highlightsEl.firstChild) {
                        highlightsEl.removeChild(highlightsEl.firstChild);
                    }
                }
                var textEl = document.getElementById("first-run-notice-text");
                if (textEl) textEl.textContent = "";
                var acceptBtn = document.getElementById("first-run-notice-accept-btn");
                if (acceptBtn) acceptBtn.hidden = true;
                var closeBtn = document.getElementById("first-run-notice-close-btn");
                if (closeBtn) closeBtn.hidden = false;
                setFirstRunNoticeError(
                    (result && result.error) || FIRST_RUN_NOTICE_LOAD_ERROR
                );
                var overlay = document.getElementById("first-run-notice-overlay");
                if (overlay) overlay.hidden = false;
                return;
            }
            showFirstRunNotice(result, "view");
        }).catch(function () {
            // Bridge rejection: show the overlay in view mode with only
            App.firstRunNoticeViewingFromSettings = true;
            var titleEl = document.getElementById("first-run-notice-title");
            if (titleEl) titleEl.textContent = "";
            var highlightsEl = document.getElementById("first-run-notice-highlights");
            if (highlightsEl) {
                while (highlightsEl.firstChild) {
                    highlightsEl.removeChild(highlightsEl.firstChild);
                }
            }
            var textEl = document.getElementById("first-run-notice-text");
            if (textEl) textEl.textContent = "";
            var acceptBtn = document.getElementById("first-run-notice-accept-btn");
            if (acceptBtn) acceptBtn.hidden = true;
            var closeBtn = document.getElementById("first-run-notice-close-btn");
            if (closeBtn) closeBtn.hidden = false;
            setFirstRunNoticeError(FIRST_RUN_NOTICE_LOAD_ERROR);
            var overlay = document.getElementById("first-run-notice-overlay");
            if (overlay) overlay.hidden = false;
        });
    }
    App.openPrivacyNoticeFromSettings = openPrivacyNoticeFromSettings;
})();
