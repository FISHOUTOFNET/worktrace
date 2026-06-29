// WorkTrace WebView frontend — settings module (Phase 6B).
// Settings / Privacy page: read-only status loading + capture toggle
// write foundation. Export / import / manifest / clear-all / save /
// file-dialog actions are NOT opened in this phase. Dynamic content is
// rendered via textContent only.

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

    function setSettingsControlsDisabled(disabled) {
        // Shared disable for the refresh button and the capture toggle.
        // The toggle carries an additional "not yet loaded" guard so it
        // stays disabled until the first successful status read.
        var btn = document.getElementById("settings-refresh-btn");
        if (btn) btn.disabled = disabled;
        var toggle = document.getElementById("settings-clipboard-toggle");
        if (toggle) toggle.disabled = disabled || !App.settingsLoaded;
    }
    App.setSettingsControlsDisabled = setSettingsControlsDisabled;

    function setSettingsLoading(loading) {
        App.settingsLoading = loading;
        var el = document.getElementById("settings-loading");
        if (el) el.hidden = !loading;
        // Both the refresh button and the toggle must be disabled while a
        // read is in flight or a write is in progress.
        setSettingsControlsDisabled(loading || App.settingsWriteInProgress);
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
        // latest status snapshot. The toggle stays disabled while a read
        // or write is in flight, or before the first successful load.
        var toggle = document.getElementById("settings-clipboard-toggle");
        if (!toggle) return;
        var captureEnabled = !!(status && status.clipboard_capture_enabled);
        toggle.checked = captureEnabled;
        toggle.disabled = App.settingsLoading || App.settingsWriteInProgress || !App.settingsLoaded;
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
            // controls unless a read is still in flight.
            App.settingsWriteInProgress = false;
            setSettingsControlsDisabled(App.settingsLoading);
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
})();
