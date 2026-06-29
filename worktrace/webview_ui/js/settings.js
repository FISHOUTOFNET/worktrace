// WorkTrace WebView frontend — settings module (Phase 6C).
// Settings / Privacy page: read-only status loading, capture toggle
// write, encrypted backup export, and encrypted backup manifest preview.
// Import / clear-all / save / arbitrary file-dialog actions are NOT
// opened in this phase. Dynamic content is rendered via textContent only.

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
        // manifest preview is in flight. Used to keep all Settings controls
        // disabled together so no two operations can race.
        return !!(
            App.settingsLoading
            || App.settingsWriteInProgress
            || App.settingsBackupExportInProgress
            || App.settingsBackupManifestInProgress
        );
    }
    App.anySettingsOperationInProgress = anySettingsOperationInProgress;

    function setSettingsBackupControlsDisabled(disabled) {
        // Backup-specific controls: passphrase inputs, export button, and
        // manifest preview button. They stay disabled until the first
        // successful status read and during any in-flight Settings op.
        var backupDisabled = disabled || !App.settingsLoaded;
        var exportBtn = document.getElementById("settings-backup-export-btn");
        var manifestBtn = document.getElementById("settings-backup-manifest-btn");
        var passInput = document.getElementById("settings-backup-passphrase");
        var passConfirmInput = document.getElementById("settings-backup-passphrase-confirm");
        if (exportBtn) exportBtn.disabled = backupDisabled;
        if (manifestBtn) manifestBtn.disabled = backupDisabled;
        if (passInput) passInput.disabled = backupDisabled;
        if (passConfirmInput) passConfirmInput.disabled = backupDisabled;
    }
    App.setSettingsBackupControlsDisabled = setSettingsBackupControlsDisabled;

    function setSettingsControlsDisabled(disabled) {
        // Shared disable for the refresh button, the capture toggle, and
        // the backup controls. While any read or write is in flight, all
        // Settings controls are disabled to prevent races between the
        // capture toggle and backup operations.
        var btn = document.getElementById("settings-refresh-btn");
        if (btn) btn.disabled = disabled;
        var toggle = document.getElementById("settings-clipboard-toggle");
        if (toggle) toggle.disabled = disabled || !App.settingsLoaded;
        setSettingsBackupControlsDisabled(disabled);
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
        // and the capture toggle. No path, no capture content,
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
        var statusEl = document.getElementById("settings-status");
        if (statusEl) statusEl.hidden = false;
    }
    App.renderSettingsStatus = renderSettingsStatus;

    function loadSettingsPrivacyStatus() {
        // Phase 6A hardening: refuse concurrent loads. The refresh button
        // and toggle are already disabled while loading, but this guard
        // also covers programmatic triggers (lazy load on page switch).
        if (App.settingsLoading) return;
        setSettingsLoading(true);
        clearSettingsError();
        var token = ++App.settingsRequestToken;
        App.callBridge("get_settings_privacy_status").then(function (result) {
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
})();
