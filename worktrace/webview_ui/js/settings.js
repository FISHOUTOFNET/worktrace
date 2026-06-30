// WorkTrace WebView frontend — settings module (Phase 6D).
// Settings / Privacy: status load, capture toggle, encrypted backup
// export / manifest preview / import (replace-only), clear-all-local-data.
// Save-settings / set_setting_value / arbitrary file-dialog NOT opened.
// Dynamic content uses textContent only; passphrase never persisted.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Phase 6A: Settings / Privacy read-only status ------------------

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
        // manifest preview / backup import / clear-all is in flight. Used to
        // keep all Settings controls disabled together so no two operations
        // can race. Phase 6D adds the two new flags at the end.
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
        // Backup-specific controls: passphrase inputs, export button,
        // manifest preview button, and the Phase 6D import controls
        // (import passphrase / import confirm / import button).
        //
        // Phase 6G: these inputs do NOT depend on ``App.settingsLoaded``.
        // The backup passphrase / import passphrase / confirm inputs must
        // remain editable even when the first ``get_settings_privacy_status``
        // read failed; otherwise a failed status load would permanently
        // lock the user out of backup / import / clear-local-data. They
        // are only disabled while a Settings operation is in flight (so
        // concurrent ops cannot race) or when explicitly requested by the
        // caller. The capture toggle continues to depend on
        // ``settingsLoaded`` because it needs the current state to render.
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
        // Phase 6D: clear-all controls (confirm input + clear button).
        //
        // Phase 6G: like the backup controls, these do NOT depend on
        // ``App.settingsLoaded``. The clear-confirm input must remain
        // editable even when the first status read failed; otherwise a
        // failed status load would permanently block the danger-zone
        // reset. They are only disabled while a Settings operation is in
        // flight. The backend re-validates the confirmation literal, so
        // allowing the input to be edited before status loads is safe.
        var dangerDisabled = !!disabled;
        var clearConfirmInput = document.getElementById("settings-clear-confirm");
        var clearBtn = document.getElementById("settings-clear-local-data-btn");
        if (clearConfirmInput) clearConfirmInput.disabled = dangerDisabled;
        if (clearBtn) clearBtn.disabled = dangerDisabled;
    }
    App.setSettingsDangerControlsDisabled = setSettingsDangerControlsDisabled;

    function setSettingsControlsDisabled(disabled) {
        // Shared disable for the capture toggle, the backup controls
        // (export / manifest / import), and the danger controls (clear-all).
        // While any read or write is in flight, all Settings controls are
        // disabled to prevent races between the capture toggle, backup
        // operations, and destructive reset.
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
        // All Settings controls (refresh / toggle / backup) must be
        // disabled while a read is in flight or any write is in progress.
        setSettingsControlsDisabled(anySettingsOperationInProgress());
    }
    App.setSettingsLoading = setSettingsLoading;

    function boolLabel(value) {
        // Boolean rendering only. Never returns the raw value or any
        // sensitive payload; used for the capture-enabled flag /
        // export_path_configured / secure_import_in_progress display.
        return value ? "开启" : "关闭";
    }

    function setLineText(key, text) {
        // Render dynamic text via textContent only. The data-settings-key
        // attribute is the stable lookup key; the leading label is part of
        // the rendered text so the line stays self-describing.
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
        // Sync the toggle's checked / disabled / status text from the
        // latest status snapshot. The toggle stays disabled while any
        // Settings op is in flight, or before the first successful load.
        var toggle = document.getElementById("settings-clipboard-toggle");
        if (!toggle) return;
        var captureEnabled = !!(status && status.clipboard_capture_enabled);
        toggle.checked = captureEnabled;
        toggle.disabled = anySettingsOperationInProgress() || !App.settingsLoaded;
        setCaptureToggleStatus(boolLabel(captureEnabled));
    }
    App.renderCaptureToggle = renderCaptureToggle;

    function renderSettingsStatus(status) {
        // Phase 6B renders booleans, the static local-only storage model,
        // and the capture toggle. Phase 6E also renders the display-safe
        // first-run notice status line. No path, no capture content,
        // no passphrase, no DB write.
        if (!status) return;
        var exportPathConfigured = !!status.export_path_configured;
        var secureImportInProgress = !!status.secure_import_in_progress;
        renderCaptureToggle(status);
        // Privacy card lines. The export path is intentionally only shown
        // as 已配置 / 未配置, never the raw path string.
        setLineText(
            "export_path_configured",
            exportPathConfigured ? "导出目录：已配置" : "导出目录：未配置"
        );
        setLineText(
            "secure_import_in_progress",
            "加密备份导入进行中：" + boolLabel(secureImportInProgress)
        );
        // The storage card line is static; the bridge confirms the storage
        // model is local_only so we re-affirm the local-first statement.
        if (status.storage_model === "local_only") {
            setLineText(
                "storage_model",
                "本地优先：所有数据仅存储在本机，不上传任何远端服务器。"
            );
        }
        // Phase 6E: render the display-safe first-run notice status line.
        // The raw DB setting key name is never exposed; only the accepted
        // boolean is shown. The "查看隐私说明" button stays enabled so the
        // user can re-read the notice read-only; it does NOT re-accept or
        // re-trigger collector start.
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
        // Phase 6A hardening: refuse concurrent loads. The refresh button
        // and toggle are already disabled while loading, but this guard
        // also covers programmatic triggers (lazy load on page switch).
        // Phase 6D: returns a Promise so import / clear success paths can
        // chain a status refresh and only then re-enable controls. When a
        // load is already in flight the call returns a resolved Promise so
        // the caller's chain still runs (the in-flight load will refresh
        // the UI when it settles).
        if (App.settingsLoading) return Promise.resolve();
        setSettingsLoading(true);
        clearSettingsError();
        var token = ++App.settingsRequestToken;
        return App.callBridge("get_settings_privacy_status").then(function (result) {
            if (token !== App.settingsRequestToken) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                // Never surface raw exception text; the bridge already
                // collapsed to a stable Chinese message.
                showSettingsError(msg || ERROR_MESSAGE);
            });
            setSettingsLoading(false);
            if (!data) {
                // Keep the prior status hidden on first load error so the
                // user does not see stale cards after a failure.
                return;
            }
            App.settingsLoaded = true;
            renderSettingsStatus(data.status);
            clearSettingsError();
        }).catch(function () {
            if (token !== App.settingsRequestToken) return;  // stale response
            setSettingsLoading(false);
            // Keep prior data on screen; just surface the error.
            showSettingsError(ERROR_MESSAGE);
        });
    }
    App.loadSettingsPrivacyStatus = loadSettingsPrivacyStatus;

    // --- Phase 6B: capture toggle write --------------------------------

    function setCaptureEnabled(enabled) {
        // Write the clipboard_capture_enabled flag through the bridge.
        // The toggle is already flipped by the browser before the change
        // event fires, so `enabled` is the new desired value. On failure
        // the previous checked state (the opposite of `enabled`) is
        // restored so the UI never shows a stale toggle state.
        App.settingsWriteInProgress = true;
        setSettingsControlsDisabled(true);
        var toggle = document.getElementById("settings-clipboard-toggle");
        return App.callBridge("set_clipboard_capture_enabled", enabled).then(function (result) {
            var data = App.handleResult(result, function (msg) {
                // Never surface raw exception text; the bridge already
                // collapsed to a stable Chinese message.
                showSettingsError(msg || WRITE_ERROR_MESSAGE);
            });
            if (!data) {
                // Failure: restore the previous checked state and status
                // text so the toggle reflects the actual setting.
                if (toggle) toggle.checked = !enabled;
                setCaptureToggleStatus(boolLabel(!enabled));
                return;
            }
            // Success: render the updated status (re-syncs the toggle
            // from the server-side truth) and clear any prior error.
            renderSettingsStatus(data.status);
            clearSettingsError();
        }).catch(function () {
            // Never read .message; show stable Chinese error.
            showSettingsError(WRITE_ERROR_MESSAGE);
            if (toggle) toggle.checked = !enabled;
            setCaptureToggleStatus(boolLabel(!enabled));
        }).then(function () {
            // finally semantics: clear the write flag and re-enable
            // controls unless another Settings op is still in flight.
            App.settingsWriteInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.setCaptureEnabled = setCaptureEnabled;

    function handleCaptureToggleChange(event) {
        var toggle = event ? event.target : document.getElementById("settings-clipboard-toggle");
        if (!toggle) return;
        // Guard: ignore change events while disabled (should not happen,
        // but defensive). Also ignore if a write is already in flight.
        if (toggle.disabled || App.settingsWriteInProgress) {
            return;
        }
        var enabled = !!toggle.checked;
        setCaptureEnabled(enabled);
    }
    App.handleCaptureToggleChange = handleCaptureToggleChange;

    // --- Phase 6C: encrypted backup export + manifest preview -----------

    var BACKUP_EXPORT_ERROR_MESSAGE = "导出加密备份失败";
    var BACKUP_MANIFEST_ERROR_MESSAGE = "读取备份清单失败";

    function setSettingsBackupStatus(text) {
        // Backup-specific status line (separate from the page-level
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
        // manifest dict only carries version / app_version / created_at /
        // kdf_algorithm / payload_format / payload_alg; no salt, ciphertext,
        // payload, or path is ever rendered.
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
        // inputs. Do NOT persist either value in App global state; the
        // values are only used as call arguments and cleared on finally.
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
            // and re-enable controls unless another op is still in flight.
            if (passInput) passInput.value = "";
            if (passConfirmInput) passConfirmInput.value = "";
            App.settingsBackupExportInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.exportEncryptedBackup = exportEncryptedBackup;

    function previewEncryptedBackupManifest() {
        // No passphrase required; the bridge opens a native open file
        // dialog and the API only reads the non-sensitive manifest.
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

    // --- Phase 6D: encrypted backup import + clear-all-local-data ------

    var BACKUP_IMPORT_ERROR_MESSAGE = "导入加密备份失败";
    var CLEAR_ALL_ERROR_MESSAGE = "清空本地数据失败";
    var IMPORT_CONFIRM_LITERAL = "导入并替换";
    var CLEAR_CONFIRM_LITERAL = "清空本地数据";

    function setSettingsImportStatus(text) {
        // Import-specific status line (separate from the page-level
        // settings-error banner and from the export status line). Renders
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
        // Hide and clear any previously-rendered manifest preview so the
        // user does not see stale manifest data after an import / clear
        // replaces the local DB. Reuses renderBackupManifest(null, "").
        renderBackupManifest(null, "");
    }
    App.clearBackupManifestPreview = clearBackupManifestPreview;

    function resetFrontendAfterLocalDataReplacement() {
        // After an encrypted backup import or a clear-all-local-data the
        // local DB has been replaced. The frontend caches Timeline /
        // Statistics / Project Rules data and per-session selection state
        // that now points at activities / sessions / projects / rules that
        // no longer exist (or whose ids have changed). This helper clears
        // those caches and selections so the user does not operate on
        // stale data when they switch back to Timeline / Statistics /
        // Project Rules. The Settings page itself is NOT torn down: the
        // caller chains a Settings status refresh after this so the
        // Settings cards reflect the post-replacement state.
        App.timelineLoaded = false;
        App.statisticsLoaded = false;
        App.rulesLoaded = false;
        App.projectsCache = null;
        App.currentSessions = [];
        // Clear per-session / per-activity selection state so a stale id
        // cannot be operated on by the next click on an old button.
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
        App.rulesImpactPreviewKey = null;
        App.rulesImpactPreviewData = null;
        App.rulesBatchSelectedKeys = {};
        App.rulesBatchPanelData = null;
        // The Settings status refresh is intentionally NOT done here; the
        // caller chains App.loadSettingsPrivacyStatus() after this so the
        // Settings cards re-render with the post-replacement status.
    }
    App.resetFrontendAfterLocalDataReplacement = resetFrontendAfterLocalDataReplacement;

    function importEncryptedBackup() {
        // Read passphrase + confirm text from the import inputs. Do NOT
        // persist the passphrase in App / DOM attribute / browser storage;
        // it is only used as a call argument and cleared on finally.
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
            // Render display-safe counts only: imported table count +
            // imported row count. Table names / paths / payload never
            // appear in the bridge payload.
            var tableCount = Number(data.imported_table_count || 0);
            var rowCount = Number(data.imported_row_count || 0);
            var statusText = (data.message || "加密备份已导入");
            if (tableCount > 0 || rowCount > 0) {
                statusText += "（已导入：" + tableCount + " 个数据组 / " + rowCount + " 条记录）";
            }
            setSettingsImportStatus(statusText);
            // Reset frontend caches so stale Timeline / Statistics /
            // Project Rules data is not operated on after the replacement.
            resetFrontendAfterLocalDataReplacement();
            // Hide any previously-rendered manifest preview; it referred
            // to a different file / a pre-import state.
            clearBackupManifestPreview();
            // Chain a Settings status refresh so the cards reflect the
            // post-import paused state, then refresh the global overview
            // / recent / status so the main UI does not keep showing the
            // pre-import data.
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
            // in-flight flag, and re-enable controls unless another
            // Settings op is still in flight.
            if (passInput) passInput.value = "";
            if (confirmInput) confirmInput.value = "";
            App.settingsBackupImportInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.importEncryptedBackup = importEncryptedBackup;

    function clearAllLocalData() {
        // Read the explicit Chinese confirmation literal. No native dialog
        // is opened; the API facade rejects anything that is not the
        // literal phrase after strip.
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
            // Project Rules data is not operated on after the reset.
            resetFrontendAfterLocalDataReplacement();
            // Hide any previously-rendered manifest preview; it referred
            // to a pre-clear backup file.
            clearBackupManifestPreview();
            // Chain a Settings status refresh so the cards reflect the
            // post-clear paused state, then refresh the global overview
            // / recent / status so the main UI does not keep showing the
            // pre-clear data.
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
            // and re-enable controls unless another Settings op is still
            // in flight.
            if (confirmInput) confirmInput.value = "";
            App.settingsClearAllInProgress = false;
            setSettingsControlsDisabled(anySettingsOperationInProgress());
        });
    }
    App.clearAllLocalData = clearAllLocalData;

    // --- Phase 6E: First-run privacy notice -----------------------------
    // The first-run notice overlay has two modes:
    //   - "gate" (blocking): shown on first run when the backend reports
    //     ``accepted === false``. The close button is hidden; only the
    //     accept button is visible. Sidebar pause/resume must not start
    //     the collector while the gate is active.
    //   - "view" (read-only): opened from the Settings / Privacy
    //     "查看隐私说明" button. The close button is shown; closing only
    //     hides the overlay and does NOT write any setting or re-accept.
    // All dynamic content is rendered with textContent / text nodes only.
    // The notice text is never persisted to browser storage; it is held
    // in JS memory only for the duration of the overlay display.

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
        // ``mode`` is "gate" or "view". The accept button is always
        // rendered; the close button is only visible in "view" mode.
        // All dynamic content uses textContent / text nodes only.
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
            // preserves whitespace / newlines.
            textEl.textContent = String(data.notice_text || "");
        }
        var acceptBtn = document.getElementById("first-run-notice-accept-btn");
        var closeBtn = document.getElementById("first-run-notice-close-btn");
        if (mode === "view") {
            // Read-only view from Settings: show close, hide accept.
            // The user has already accepted (or the gate would be active).
            // Showing close lets them dismiss the overlay without any
            // setting write or collector start.
            if (acceptBtn) acceptBtn.hidden = true;
            if (closeBtn) closeBtn.hidden = false;
        } else {
            // Gate mode (blocking): show accept, hide close. The only way
            // to dismiss the gate is to accept; no skip / later / cancel.
            if (acceptBtn) acceptBtn.hidden = false;
            if (closeBtn) closeBtn.hidden = true;
        }
        setFirstRunNoticeError("");
    }
    App.renderFirstRunNotice = renderFirstRunNotice;

    function showFirstRunNotice(data, mode) {
        // Show the overlay in the requested mode. ``data`` is the payload
        // returned by ``get_first_run_notice``. ``mode`` is "gate" or
        // "view". Sets the in-memory viewing flag so the close button
        // handler knows whether closing is allowed.
        App.firstRunNoticeViewingFromSettings = (mode === "view");
        renderFirstRunNotice(data, mode);
        var overlay = document.getElementById("first-run-notice-overlay");
        if (overlay) overlay.hidden = false;
    }
    App.showFirstRunNotice = showFirstRunNotice;

    function showFirstRunNoticeBlockingError(message) {
        // Strict fail-closed: show the overlay with NO notice body, NO
        // highlights, NO title, and the accept button disabled / hidden.
        // The user cannot accept and cannot bypass the gate. Only the
        // stable error message is displayed.
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
        // Hide the overlay. In "view" mode this is the close button's
        // handler. In "gate" mode this is only called after a successful
        // accept (never from the close button, which is hidden in gate
        // mode). Never writes any setting; never starts the collector.
        var overlay = document.getElementById("first-run-notice-overlay");
        if (overlay) overlay.hidden = true;
        App.firstRunNoticeViewingFromSettings = false;
        // Do NOT clear firstRunNoticeRequired here in gate mode: it is
        // only cleared after a successful accept response. The close
        // button is only ever visible in "view" mode, so reaching this
        // path via the close button implies view mode.
    }
    App.hideFirstRunNotice = hideFirstRunNotice;

    function loadFirstRunNotice() {
        // Initial first-run notice load. Called once during init. Returns a
        // Promise that resolves to ``true`` when the backend notice state
        // was successfully confirmed (whether accepted or not), and
        // ``false`` when the load failed. The caller (init) uses the
        // boolean to decide whether to start the main UI refresh /
        // auto-refresh / local ticker: only start them when the notice
        // state is confirmed.
        //
        // Failure handling:
        //   - Backend ``ok:false`` (real backend read failure): strict
        //     fail-closed. Show blocking error with no notice body and
        //     disabled accept. Set ``firstRunNoticeLoaded = true`` so the
        //     state is locked; the backend is broken and retrying from the
        //     frontend will not help.
        //   - Bridge rejection (bridge unavailable / transient error):
        //     show the same blocking error overlay so the user is not
        //     left looking at a blank UI, but do NOT set
        //     ``firstRunNoticeLoaded = true``. This leaves the door open
        //     for a retry (e.g. after the bridge recovers or after an app
        //     restart) so the frontend state is not permanently locked.
        if (App.firstRunNoticeLoading || App.firstRunNoticeLoaded) return Promise.resolve(true);
        App.firstRunNoticeLoading = true;
        return App.callBridge("get_first_run_notice").then(function (result) {
            App.firstRunNoticeLoading = false;
            App.firstRunNoticeLoaded = true;
            if (!result || result.ok === false) {
                // Backend returned ok:false (e.g. accepted-state read
                // failure). Strict fail-closed: show blocking error,
                // no notice body, accept disabled.
                App.firstRunNoticeRequired = true;
                showFirstRunNoticeBlockingError(
                    (result && result.error) || FIRST_RUN_NOTICE_LOAD_ERROR
                );
                return false;
            }
            if (result.accepted === false) {
                // First run: show the blocking gate with the official
                // notice body from the backend. The close button is
                // hidden; only accept can dismiss it.
                App.firstRunNoticeRequired = true;
                showFirstRunNotice(result, "gate");
            } else {
                // Already accepted: keep the overlay hidden. The user
                // can still view the notice read-only from Settings.
                App.firstRunNoticeRequired = false;
            }
            return true;
        }).catch(function () {
            // Bridge rejection: show the blocking error overlay
            // (fail-closed UI) but do NOT set ``firstRunNoticeLoaded =
            // true``. A bridge rejection may be transient (bridge not
            // yet injected, temporary unavailability); permanently
            // marking the notice as loaded would prevent any retry and
            // lock the user out. The caller (init) receives ``false``
            // and does not start the main UI refresh. The backend
            // ``ok:false`` path above is the strict fail-closed path
            // that does lock the state.
            App.firstRunNoticeLoading = false;
            App.firstRunNoticeRequired = true;
            showFirstRunNoticeBlockingError(FIRST_RUN_NOTICE_LOAD_ERROR);
            return false;
        });
    }
    App.loadFirstRunNotice = loadFirstRunNotice;

    function acceptFirstRunNotice() {
        // Accept handler for the gate-mode accept button. Calls the
        // bridge ``accept_first_run_notice`` method; on success the
        // backend persists the accept and starts the collector. The
        // frontend hides the gate, clears the required flag, and
        // refreshes the global status / overview / recent data so the
        // sidebar reflects the now-running collector.
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
            // Refresh the global status / overview / recent activities
            // so the sidebar reflects the now-running collector. Also
            // refresh the Settings / Privacy status so the notice line
            // shows "已确认".
            if (typeof App.refreshAll === "function") {
                App.refreshAll();
            }
            // Best-effort Settings refresh; ignore failures so the
            // successful accept is not masked.
            try {
                App.loadSettingsPrivacyStatus();
            } catch (e) {
                // Swallow: refreshAll already updated the sidebar.
            }
        }).catch(function () {
            // Never read .message; show stable Chinese error.
            setFirstRunNoticeError(FIRST_RUN_NOTICE_ACCEPT_ERROR);
        }).then(function () {
            // finally: clear the in-flight flag and re-enable the
            // accept button (the gate stays open until a successful
            // accept, so the button must remain usable on retry).
            App.firstRunNoticeAcceptInProgress = false;
            if (acceptBtn) acceptBtn.disabled = false;
        });
    }
    App.acceptFirstRunNotice = acceptFirstRunNotice;

    function openPrivacyNoticeFromSettings() {
        // Read-only "查看隐私说明" entry on the Settings / Privacy page.
        // Loads the notice payload and shows the overlay in "view" mode:
        // the close button is visible, the accept button is hidden, and
        // closing does NOT write any setting or start the collector. The
        // notice text is held in JS memory only for the duration of the
        // display; no browser storage APIs are used.
        //
        // On failure (ok:false or bridge rejection): show the overlay
        // with a stable error message and NO notice body. The close
        // button is shown so the user can dismiss the overlay; the
        // accept button is hidden so no re-accept can occur. Closing
        // does NOT change the accepted state or start the collector.
        App.callBridge("get_first_run_notice").then(function (result) {
            if (!result || result.ok === false) {
                // Backend returned ok:false. Show the overlay in view
                // mode with only the error message and a close button.
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
            // the error message and a close button. No notice body.
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
