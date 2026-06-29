// WorkTrace WebView frontend — settings module (Phase 6A).
// Settings / Privacy page: read-only status loading only. No save / toggle /
// export / import / manifest / clear-all / capture-toggle / file-dialog
// action is wired in this phase. Dynamic content is rendered via
// textContent only.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Phase 6A: Settings / Privacy read-only status ------------------

    var ERROR_MESSAGE = "加载设置状态失败";

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

    function setSettingsLoading(loading) {
        App.settingsLoading = loading;
        var el = document.getElementById("settings-loading");
        if (el) el.hidden = !loading;
        // The refresh button is the only control on this page. Disabling it
        // while loading prevents duplicate concurrent read requests.
        var btn = document.getElementById("settings-refresh-btn");
        if (btn) btn.disabled = loading;
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

    function renderSettingsStatus(status) {
        // Phase 6A only renders booleans and the static local-only storage
        // model. No path, no capture content, no passphrase, no DB write.
        if (!status) return;
        var captureEnabled = !!status.clipboard_capture_enabled;
        var exportPathConfigured = !!status.export_path_configured;
        var secureImportInProgress = !!status.secure_import_in_progress;
        // Privacy card lines. The export path is intentionally only shown
        // as 已配置 / 未配置, never the raw path string.
        setLineText(
            "clipboard_capture_enabled",
            "剪贴板记录：" + boolLabel(captureEnabled)
        );
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
        // is already disabled while loading, but this guard also covers
        // programmatic triggers (lazy load on page switch).
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
})();
