// WorkTrace WebView frontend — Settings-only transient UI owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var presentation = App.settingsPresentation;

    var privacyNoticeViewToken = 0;
    var privacyNoticeReturnFocus = null;
    var privacyNoticeMode = "";
    var privacyNoticeLifecycleBound = false;
    var passwordRevealControlsBound = false;
    var settingsCategoriesBound = false;

    function element(id) { return document.getElementById(id); }

    function preservePasswordSelection(input, action) {
        if (!input) return;
        var start = input.selectionStart;
        var end = input.selectionEnd;
        var direction = input.selectionDirection;
        action();
        if (
            typeof input.setSelectionRange === "function"
            && typeof start === "number"
            && typeof end === "number"
        ) {
            try { input.setSelectionRange(start, end, direction || "none"); } catch (error) {}
        }
    }

    function setPasswordFieldVisible(button, visible) {
        if (!button) return false;
        var input = element(button.dataset ? button.dataset.passwordInput : "");
        var allowed = !!visible && !button.disabled && !!input && !input.disabled;
        if (input) {
            preservePasswordSelection(input, function () {
                input.type = allowed ? "text" : "password";
            });
        }
        button.setAttribute("aria-pressed", allowed ? "true" : "false");
        return allowed;
    }

    function hideAllPasswordFields() {
        if (typeof document.querySelectorAll !== "function") return;
        var buttons = document.querySelectorAll(".password-reveal-button");
        for (var index = 0; index < buttons.length; index++) {
            setPasswordFieldVisible(buttons[index], false);
        }
    }

    function initPasswordRevealControls() {
        if (passwordRevealControlsBound) return;
        passwordRevealControlsBound = true;
        if (typeof document.querySelectorAll !== "function") return;
        var buttons = document.querySelectorAll(".password-reveal-button");
        Array.prototype.forEach.call(buttons, function (button) {
            button.addEventListener("pointerdown", function (event) {
                if (!setPasswordFieldVisible(button, true)) return;
                event.preventDefault();
                if (typeof button.setPointerCapture === "function") {
                    try { button.setPointerCapture(event.pointerId); } catch (error) {}
                }
            });
            ["pointerup", "pointercancel", "pointerleave", "lostpointercapture", "blur"]
                .forEach(function (eventName) {
                    button.addEventListener(eventName, function () {
                        setPasswordFieldVisible(button, false);
                    });
                });
            button.addEventListener("keydown", function (event) {
                if (event.key === " " || event.key === "Enter") {
                    event.preventDefault();
                    setPasswordFieldVisible(button, true);
                } else if (event.key === "Escape") {
                    setPasswordFieldVisible(button, false);
                }
            });
            button.addEventListener("keyup", function (event) {
                if (event.key === " " || event.key === "Enter") {
                    event.preventDefault();
                    setPasswordFieldVisible(button, false);
                }
            });
            button.addEventListener("click", function (event) {
                event.preventDefault();
                setPasswordFieldVisible(button, false);
            });
        });
        if (typeof window.addEventListener === "function") {
            window.addEventListener("blur", hideAllPasswordFields);
            window.addEventListener("pagehide", hideAllPasswordFields);
        }
    }

    function settingsPrivacyNoticeViewOpen() {
        var overlay = element("first-run-notice-overlay");
        return privacyNoticeMode === "view" && overlay && overlay.hidden === false;
    }

    function restoreSettingsPrivacyNoticeFocus(target) {
        if (!target || typeof target.focus !== "function") return;
        var root = document.documentElement;
        if (!root || typeof root.contains !== "function" || root.contains(target)) target.focus();
    }

    function focusSettingsPrivacyNoticeClose() {
        var close = element("first-run-notice-close-btn");
        if (close && !close.hidden && typeof close.focus === "function") close.focus();
    }

    function hideFirstRunNotice(options) {
        options = options || {};
        var wasSettingsView = privacyNoticeMode === "view";
        var restore = privacyNoticeReturnFocus;
        var overlay = element("first-run-notice-overlay");
        if (overlay) overlay.hidden = true;
        privacyNoticeMode = "";
        if (wasSettingsView) {
            privacyNoticeReturnFocus = null;
            if (options.restoreFocus !== false) restoreSettingsPrivacyNoticeFocus(restore);
        }
    }

    function initPrivacyNoticeViewLifecycle() {
        if (privacyNoticeLifecycleBound) return;
        privacyNoticeLifecycleBound = true;
        var overlay = element("first-run-notice-overlay");
        if (overlay) {
            overlay.addEventListener("click", function (event) {
                if (settingsPrivacyNoticeViewOpen() && event.target === overlay) {
                    hideFirstRunNotice();
                }
            });
        }
        document.addEventListener("keydown", function (event) {
            if (!settingsPrivacyNoticeViewOpen()) return;
            if (event.key === "Escape") {
                event.preventDefault();
                hideFirstRunNotice();
                return;
            }
            var dialog = element("first-run-notice-dialog");
            if (dialog && App.trapFocus) App.trapFocus(event, dialog);
        });
    }

    function showFirstRunNotice(notice, mode) {
        privacyNoticeMode = mode === "view" ? "view" : "gate";
        presentation.renderFirstRunNotice(notice, privacyNoticeMode);
        var overlay = element("first-run-notice-overlay");
        if (overlay) overlay.hidden = false;
        if (privacyNoticeMode === "view") focusSettingsPrivacyNoticeClose();
    }

    function showFirstRunNoticeBlockingError(message, mode) {
        privacyNoticeMode = mode === "view" ? "view" : "gate";
        presentation.showFirstRunNoticeBlockingError(message);
        if (privacyNoticeMode === "view") {
            var close = element("first-run-notice-close-btn");
            if (close) close.hidden = false;
        }
        var overlay = element("first-run-notice-overlay");
        if (overlay) overlay.hidden = false;
        if (privacyNoticeMode === "view") focusSettingsPrivacyNoticeClose();
    }

    function settleFirstRunNoticeAcceptedUi() {
        presentation.settleFirstRunNoticeControls();
        hideFirstRunNotice({ restoreFocus: false });
    }

    function beginPrivacyNoticeViewRequest() {
        privacyNoticeReturnFocus = element("settings-privacy-notice-btn")
            || document.activeElement;
        return ++privacyNoticeViewToken;
    }

    function privacyNoticeViewRequestCurrent(token) {
        return token === privacyNoticeViewToken
            && (!App.currentPage || App.currentPage === "settings");
    }

    function operationActive(context, name) {
        return !!(
            context
            && typeof context.operationIs === "function"
            && context.operationIs(name)
        );
    }

    function resetSettingsSectionTransientUi(section, context) {
        section = String(section || "");
        if (section === "data") {
            hideAllPasswordFields();
            if (context && typeof context.cancelManifestPreview === "function") {
                context.cancelManifestPreview();
            } else {
                presentation.renderBackupManifest(null, "");
            }
            if (!operationActive(context, "backup_export")) presentation.setSettingsBackupStatus("");
            if (!operationActive(context, "backup_import")) presentation.setSettingsImportStatus("");
            if (!operationActive(context, "clear_all")) presentation.setSettingsClearStatus("");
            return;
        }
        if (section === "advanced") {
            var diagnostics = document.querySelector("#settings-section-advanced details");
            if (diagnostics) diagnostics.open = false;
            if (!operationActive(context, "recovery")) presentation.setSettingsRecoveryStatus("");
            return;
        }
        if (section === "privacy") {
            privacyNoticeViewToken += 1;
            if (privacyNoticeMode === "view") hideFirstRunNotice({ restoreFocus: false });
            privacyNoticeReturnFocus = null;
        }
    }

    function initSettingsCategories(context) {
        initPrivacyNoticeViewLifecycle();
        if (settingsCategoriesBound) return;
        settingsCategoriesBound = true;
        var buttons = document.querySelectorAll("[data-settings-section]");
        for (var index = 0; index < buttons.length; index++) {
            buttons[index].addEventListener("click", function () {
                var section = this.getAttribute("data-settings-section");
                var previousSection = "";
                for (var current = 0; current < buttons.length; current++) {
                    if (buttons[current].getAttribute("aria-current") === "true") {
                        previousSection = buttons[current].getAttribute("data-settings-section") || "";
                        break;
                    }
                }
                if (previousSection && previousSection !== section) {
                    resetSettingsSectionTransientUi(previousSection, context);
                }
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

    function resetSettingsTransientUi(options, context) {
        options = options || {};
        privacyNoticeViewToken += 1;
        [
            "settings-backup-passphrase",
            "settings-backup-passphrase-confirm",
            "settings-backup-import-passphrase",
            "settings-clear-confirm"
        ].forEach(function (id) {
            var input = element(id);
            if (input) input.value = "";
        });
        hideAllPasswordFields();
        presentation.setSettingsBackupStatus("");
        presentation.setSettingsImportStatus("");
        presentation.setSettingsClearStatus("");
        if (context && typeof context.cancelManifestPreview === "function") {
            context.cancelManifestPreview();
        } else {
            presentation.renderBackupManifest(null, "");
        }
        var diagnostics = document.querySelector("#settings-section-advanced details");
        if (diagnostics) diagnostics.open = false;
        if (privacyNoticeMode === "view") {
            hideFirstRunNotice({ restoreFocus: options.restoreFocus !== false });
        }
        privacyNoticeReturnFocus = null;
        if (!operationActive(context, "recovery")) presentation.setSettingsRecoveryStatus("");
    }

    function bindSettingsControl(id, event, handler) {
        var target = element(id);
        if (target) target.addEventListener(event, handler);
    }

    function bindEvents(context) {
        initSettingsCategories(context);
        initPasswordRevealControls();
        bindSettingsControl("settings-privacy-notice-btn", "click", function () {
            if (context && typeof context.openPrivacyNotice === "function") {
                context.openPrivacyNotice();
            }
        });
        bindSettingsControl("first-run-notice-close-btn", "click", function () {
            if (privacyNoticeMode === "view") hideFirstRunNotice();
        });
    }

    App.settingsTransientUi = Object.freeze({
        beginPrivacyNoticeViewRequest: beginPrivacyNoticeViewRequest,
        bindEvents: bindEvents,
        hideAllPasswordFields: hideAllPasswordFields,
        hideFirstRunNotice: hideFirstRunNotice,
        initPasswordRevealControls: initPasswordRevealControls,
        initSettingsCategories: initSettingsCategories,
        isNoticeViewOpen: settingsPrivacyNoticeViewOpen,
        privacyNoticeViewRequestCurrent: privacyNoticeViewRequestCurrent,
        resetSettingsSectionTransientUi: resetSettingsSectionTransientUi,
        resetSettingsTransientUi: resetSettingsTransientUi,
        setPasswordFieldVisible: setPasswordFieldVisible,
        settleFirstRunNoticeAcceptedUi: settleFirstRunNoticeAcceptedUi,
        showFirstRunNotice: showFirstRunNotice,
        showFirstRunNoticeBlockingError: showFirstRunNoticeBlockingError
    });

    App.setPasswordFieldVisible = setPasswordFieldVisible;
    App.hideAllPasswordFields = hideAllPasswordFields;
    App.initPasswordRevealControls = initPasswordRevealControls;
    App.initSettingsCategories = initSettingsCategories;
    App.resetSettingsSectionTransientUi = resetSettingsSectionTransientUi;
    App.resetSettingsTransientUi = resetSettingsTransientUi;
    App.showFirstRunNotice = showFirstRunNotice;
    App.hideFirstRunNotice = hideFirstRunNotice;
    App.settleFirstRunNoticeAcceptedUi = settleFirstRunNoticeAcceptedUi;
})();
