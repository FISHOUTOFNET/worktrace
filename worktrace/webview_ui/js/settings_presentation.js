// WorkTrace WebView frontend — stateless Settings presentation owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    var ERROR_MESSAGE = "加载设置状态失败";

    function element(id) { return document.getElementById(id); }

    function setDisabled(id, disabled) {
        var target = element(id);
        if (target) target.disabled = !!disabled;
    }

    function setStatusLine(id, text) {
        var target = element(id);
        if (!target) return;
        target.hidden = !text;
        target.textContent = text || "";
    }

    function showSettingsError(message) {
        var banner = element("settings-error");
        if (!banner) return;
        banner.hidden = !message;
        banner.textContent = message || ERROR_MESSAGE;
    }

    function clearSettingsError() { showSettingsError(""); }

    function viewBusy(viewState) {
        viewState = viewState || {};
        return viewState.loading === true || !!viewState.operation;
    }

    function pageBlocked(viewState) {
        viewState = viewState || {};
        return viewState.loading === true || viewState.blockingOperation === true;
    }

    function operationIs(viewState, name) {
        var names = viewState && viewState.operations;
        return Array.isArray(names) && names.indexOf(name) >= 0;
    }

    function fdWorkMutationActive(viewState) {
        return operationIs(viewState, "fd_work_write");
    }

    function setSettingsBackupControlsDisabled(disabled) {
        [
            "settings-backup-export-btn",
            "settings-backup-manifest-btn",
            "settings-backup-passphrase",
            "settings-backup-passphrase-reveal",
            "settings-backup-passphrase-confirm",
            "settings-backup-passphrase-confirm-reveal",
            "settings-backup-import-passphrase",
            "settings-backup-import-passphrase-reveal",
            "settings-backup-import-btn"
        ].forEach(function (id) { setDisabled(id, disabled); });
    }

    function setSettingsDangerControlsDisabled(disabled) {
        setDisabled("settings-clear-confirm", disabled);
        setDisabled("settings-clear-local-data-btn", disabled);
    }

    function syncRecoveryButtonState(status, viewState) {
        var button = element("settings-recovery-btn");
        if (!button) return;
        button.disabled = viewBusy(viewState)
            || !(status && status.recovery_blocked === true);
    }

    function setSettingsControlsState(status, viewState) {
        status = status || {};
        viewState = viewState || {};
        var busy = viewBusy(viewState);
        var blocked = pageBlocked(viewState);
        var loaded = viewState.loaded === true;

        var captureToggle = element("settings-clipboard-toggle");
        if (captureToggle) {
            captureToggle.disabled = blocked
                || operationIs(viewState, "clipboard_write")
                || fdWorkMutationActive(viewState)
                || !loaded;
        }

        var launchToggle = element("settings-launch-at-login-toggle");
        var launchStatus = status.launch_at_login || {};
        if (launchToggle) {
            launchToggle.disabled = blocked
                || operationIs(viewState, "launch_at_login_write")
                || fdWorkMutationActive(viewState)
                || !loaded
                || launchStatus.supported !== true;
        }

        var fdWorkToggle = element("settings-fd-work-toggle");
        var fdWorkStatus = viewState.fdWorkStatus || status.fd_work || {};
        if (fdWorkToggle) {
            fdWorkToggle.disabled = blocked
                || operationIs(viewState, "fd_work_write")
                || !loaded
                || fdWorkStatus.supported !== true;
        }

        setSettingsBackupControlsDisabled(busy);
        setSettingsDangerControlsDisabled(busy);
        syncRecoveryButtonState(status, viewState);
    }

    function setSettingsLoading(loading) {
        var loadingEl = element("settings-loading");
        if (loadingEl) loadingEl.hidden = !loading;
    }

    function boolLabel(value) { return value ? "是" : "否"; }

    function setLineText(key, text) {
        var target = document.querySelector('#settings-status [data-settings-key="' + key + '"]');
        if (target) target.textContent = text;
    }

    function renderLocalDataPath(status) {
        var target = element("settings-local-data-path");
        if (!target) return;
        var path = String(status && status.local_data_path || "").trim();
        target.textContent = path || "未加载";
        target.title = path;
    }

    function setCaptureToggleStatus(text) {
        var target = element("settings-clipboard-toggle-status");
        if (target) target.textContent = text;
    }

    function renderCaptureToggle(status, viewState) {
        var toggle = element("settings-clipboard-toggle");
        if (!toggle) return;
        var enabled = !!(status && status.clipboard_capture_enabled);
        toggle.checked = enabled;
        toggle.disabled = pageBlocked(viewState)
            || operationIs(viewState, "clipboard_write")
            || fdWorkMutationActive(viewState)
            || !(viewState && viewState.loaded === true);
        setCaptureToggleStatus(enabled ? "开启" : "关闭");
    }

    function setLaunchAtLoginToggleStatus(text) {
        var target = element("settings-launch-at-login-toggle-status");
        if (target) target.textContent = text;
    }

    function renderLaunchAtLoginToggle(status, viewState) {
        var toggle = element("settings-launch-at-login-toggle");
        if (!toggle) return;
        var launch = status && status.launch_at_login || {};
        var supported = launch.supported === true;
        toggle.checked = supported && launch.enabled === true;
        toggle.disabled = !supported
            || pageBlocked(viewState)
            || operationIs(viewState, "launch_at_login_write")
            || fdWorkMutationActive(viewState)
            || !(viewState && viewState.loaded === true);
        setLaunchAtLoginToggleStatus(
            supported ? (toggle.checked ? "开启" : "关闭") : "仅安装版可用"
        );
    }

    function renderFDWorkToggle(status, viewState) {
        var toggle = element("settings-fd-work-toggle");
        var target = element("settings-fd-work-toggle-status");
        var reconnect = element("settings-fd-work-reconnect");
        if (!toggle) return;
        var fdWork = viewState && viewState.fdWorkStatus || status && status.fd_work || {};
        var supported = fdWork.supported === true;
        toggle.checked = supported && fdWork.enabled === true;
        toggle.disabled = !supported
            || pageBlocked(viewState)
            || operationIs(viewState, "fd_work_write")
            || !(viewState && viewState.loaded === true);
        var statusText = typeof App.fdWorkStatusText === "function"
            ? App.fdWorkStatusText(fdWork)
            : (toggle.checked ? "开启" : "关闭");
        if (statusText === "插件关闭") statusText = "关闭";
        if (target) target.textContent = supported ? statusText : "当前不可用";
        if (reconnect) {
            var recoverable = supported && fdWork.enabled === true
                && (fdWork.session_state === "probing"
                    || fdWork.session_state === "login_required"
                    || fdWork.session_state === "error");
            reconnect.hidden = !recoverable;
            reconnect.disabled = !recoverable
                || pageBlocked(viewState)
                || fdWorkMutationActive(viewState);
            reconnect.textContent = fdWork.session_state === "error"
                ? "重新连接" : "登录 FD Work";
        }
    }

    function renderRecoveryCard(status, viewState) {
        status = status || {};
        var card = element("settings-recovery-card");
        var reason = element("settings-recovery-reason");
        if (!card) return;
        var blocked = !!status.recovery_blocked;
        var maintenance = !!status.maintenance_in_progress;
        card.hidden = !blocked && !maintenance;
        if (reason) {
            reason.textContent = "阻断原因："
                + (status.blocked_reason ? String(status.blocked_reason) : (maintenance ? "维护进行中" : "无"));
        }
        syncRecoveryButtonState(status, viewState);
    }

    function renderSettingsStatus(status, viewState) {
        if (!status) return;
        renderCaptureToggle(status, viewState);
        renderLaunchAtLoginToggle(status, viewState);
        renderFDWorkToggle(status, viewState);
        renderLocalDataPath(status);
        setLineText(
            "export_path_configured",
            status.export_path_configured ? "已配置" : "未配置"
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
        setLineText("user_paused", "用户暂停：" + boolLabel(!!status.user_paused));
        renderRecoveryCard(status, viewState);

        var health = element("settings-health-summary");
        if (health) {
            var badgeText = "正常";
            var detail = "采集和本地存储可用";
            if (status.recovery_blocked) {
                badgeText = "需恢复";
                detail = "请在高级设置中尝试恢复";
            } else if (status.maintenance_in_progress) {
                badgeText = "维护中";
                detail = "维护期间其他数据操作暂时不可用";
            } else if (!status.collector_running && !status.user_paused) {
                badgeText = "异常";
                detail = "请重启应用后再次检查";
            }
            var strong = health.querySelector("strong");
            var small = health.querySelector("small");
            var badge = health.querySelector(".badge");
            if (strong) strong.textContent = "系统状态";
            if (small) small.textContent = detail;
            if (badge) badge.textContent = badgeText;
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
        if (noticeStatus) noticeStatus.textContent = accepted ? "已确认" : "未确认";
        var statusEl = element("settings-status");
        if (statusEl) statusEl.hidden = false;
    }

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

    function clearChildren(target) {
        if (!target) return;
        while (target.firstChild) target.removeChild(target.firstChild);
    }

    function setFirstRunNoticeError(message) {
        setStatusLine("first-run-notice-error", message);
    }

    function renderFirstRunNotice(notice, mode) {
        if (!notice) return;
        var title = element("first-run-notice-title");
        var highlights = element("first-run-notice-highlights");
        var text = element("first-run-notice-text");
        var accept = element("first-run-notice-accept-btn");
        var close = element("first-run-notice-close-btn");
        var retry = element("first-run-notice-retry-btn");
        if (title) title.textContent = String(notice.title || "有迹隐私说明");
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
        if (retry) retry.hidden = true;
        setFirstRunNoticeError("");
    }

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
        if (retry) { retry.hidden = false; retry.disabled = false; }
        setFirstRunNoticeError(message);
    }

    function settleFirstRunNoticeControls() {
        var retry = element("first-run-notice-retry-btn");
        var accept = element("first-run-notice-accept-btn");
        var close = element("first-run-notice-close-btn");
        setFirstRunNoticeError("");
        if (retry) { retry.hidden = true; retry.disabled = false; }
        if (accept) { accept.hidden = false; accept.disabled = false; }
        if (close) close.hidden = true;
    }

    function setFirstRunNoticeAcceptDisabled(disabled) {
        setDisabled("first-run-notice-accept-btn", disabled);
    }

    App.settingsPresentation = Object.freeze({
        clearSettingsError: clearSettingsError,
        renderBackupManifest: renderBackupManifest,
        renderFDWorkToggle: renderFDWorkToggle,
        renderFirstRunNotice: renderFirstRunNotice,
        renderLaunchAtLoginToggle: renderLaunchAtLoginToggle,
        renderRecoveryCard: renderRecoveryCard,
        renderSettingsStatus: renderSettingsStatus,
        setCaptureToggleStatus: setCaptureToggleStatus,
        setFirstRunNoticeAcceptDisabled: setFirstRunNoticeAcceptDisabled,
        setFirstRunNoticeError: setFirstRunNoticeError,
        setSettingsBackupStatus: function (text) { setStatusLine("settings-backup-status", text); },
        setSettingsBackupControlsDisabled: setSettingsBackupControlsDisabled,
        setSettingsClearStatus: function (text) { setStatusLine("settings-clear-status", text); },
        setSettingsControlsState: setSettingsControlsState,
        setSettingsImportStatus: function (text) { setStatusLine("settings-backup-import-status", text); },
        setSettingsLoading: setSettingsLoading,
        setSettingsRecoveryStatus: function (text) { setStatusLine("settings-recovery-status", text); },
        settleFirstRunNoticeControls: settleFirstRunNoticeControls,
        showFirstRunNoticeBlockingError: showFirstRunNoticeBlockingError,
        showSettingsError: showSettingsError
    });

    App.showSettingsError = showSettingsError;
    App.clearSettingsError = clearSettingsError;
    App.renderSettingsStatus = renderSettingsStatus;
    App.renderBackupManifest = renderBackupManifest;
    App.renderFirstRunNotice = renderFirstRunNotice;
    App.renderRecoveryCard = renderRecoveryCard;
    App.setSettingsBackupControlsDisabled = setSettingsBackupControlsDisabled;
})();
