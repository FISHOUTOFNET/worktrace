// WorkTrace WebView frontend — application-level privacy notice owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    var FIRST_RUN_NOTICE_LOAD_ERROR = "隐私说明加载失败。为保护隐私，有迹暂不会启动记录。请点击“重新加载”重试。";
    var FIRST_RUN_NOTICE_ACCEPT_ERROR = "确认隐私说明失败";

    var gateState = "loading";
    var noticeLoaded = false;
    var noticeLoading = false;
    var noticeAccepting = false;
    var gateRequestToken = 0;
    var viewRequestToken = 0;
    var returnFocus = null;
    var noticeMode = "";
    var lifecycleBound = false;

    function element(id) { return document.getElementById(id); }

    function clearChildren(target) {
        if (!target) return;
        while (target.firstChild) target.removeChild(target.firstChild);
    }

    function setError(message) {
        var target = element("first-run-notice-error");
        if (!target) return;
        target.hidden = !message;
        target.textContent = message || "";
    }

    function setAcceptDisabled(disabled) {
        var target = element("first-run-notice-accept-btn");
        if (target) target.disabled = !!disabled;
    }

    function renderNotice(notice, mode) {
        notice = notice || {};
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
                var entry = document.createElement("li");
                entry.textContent = String(item || "");
                highlights.appendChild(entry);
            });
        }
        if (text) text.textContent = String(notice.text || "");
        if (accept) { accept.hidden = mode === "view"; accept.disabled = false; }
        if (close) close.hidden = mode !== "view";
        if (retry) { retry.hidden = true; retry.disabled = false; }
        setError("");
    }

    function renderBlockingError(message, mode) {
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
        if (close) close.hidden = mode !== "view";
        if (retry) { retry.hidden = mode === "view"; retry.disabled = false; }
        setError(message);
    }

    function settleAcceptedUi() {
        var retry = element("first-run-notice-retry-btn");
        var accept = element("first-run-notice-accept-btn");
        var close = element("first-run-notice-close-btn");
        setError("");
        if (retry) { retry.hidden = true; retry.disabled = false; }
        if (accept) { accept.hidden = false; accept.disabled = false; }
        if (close) close.hidden = true;
        hideNotice({ restoreFocus: false });
    }

    function viewOpen() {
        var overlay = element("first-run-notice-overlay");
        return noticeMode === "view" && overlay && overlay.hidden === false;
    }

    function restoreViewFocus(target) {
        if (!target || typeof target.focus !== "function") return;
        var root = document.documentElement;
        if (!root || typeof root.contains !== "function" || root.contains(target)) target.focus();
    }

    function focusCloseButton() {
        var close = element("first-run-notice-close-btn");
        if (close && !close.hidden && typeof close.focus === "function") close.focus();
    }

    function hideNotice(options) {
        options = options || {};
        var wasView = noticeMode === "view";
        var restore = returnFocus;
        var overlay = element("first-run-notice-overlay");
        if (overlay) overlay.hidden = true;
        noticeMode = "";
        if (wasView) {
            returnFocus = null;
            if (options.restoreFocus !== false) restoreViewFocus(restore);
        }
    }

    function showNotice(notice, mode) {
        noticeMode = mode === "view" ? "view" : "gate";
        renderNotice(notice, noticeMode);
        var overlay = element("first-run-notice-overlay");
        if (overlay) overlay.hidden = false;
        if (noticeMode === "view") focusCloseButton();
    }

    function showBlockingError(message, mode) {
        noticeMode = mode === "view" ? "view" : "gate";
        renderBlockingError(message, noticeMode);
        var overlay = element("first-run-notice-overlay");
        if (overlay) overlay.hidden = false;
        if (noticeMode === "view") focusCloseButton();
    }

    function setGateState(state) { gateState = String(state || "loading"); }

    function isReady() {
        return gateState === "accepted_ready" || gateState === "accepted_start_failed";
    }

    function loadGate(options) {
        var force = !!(options && options.force);
        if (noticeLoading) return Promise.resolve(isReady());
        if (noticeLoaded && !force) return Promise.resolve(isReady());
        noticeLoading = true;
        setGateState("loading");
        var token = ++gateRequestToken;
        return App.bridge.getFirstRunNotice().then(function (result) {
            if (token !== gateRequestToken) return false;
            noticeLoading = false;
            if (!result || result.ok === false) {
                setGateState("load_failed");
                showBlockingError(
                    App.extractBridgeError(result, FIRST_RUN_NOTICE_LOAD_ERROR),
                    "gate"
                );
                return false;
            }
            noticeLoaded = true;
            var notice = result.notice || {};
            if (notice.accepted === true) {
                setGateState("accepted_ready");
                settleAcceptedUi();
                return true;
            }
            setGateState("acceptance_required");
            showNotice(notice, "gate");
            return false;
        }).catch(function () {
            if (token !== gateRequestToken) return false;
            noticeLoading = false;
            setGateState("load_failed");
            showBlockingError(FIRST_RUN_NOTICE_LOAD_ERROR, "gate");
            return false;
        });
    }

    function acceptGate() {
        if (noticeAccepting) return Promise.resolve(false);
        noticeAccepting = true;
        setAcceptDisabled(true);
        setError("");
        setGateState("accepted_starting");
        return App.bridge.acceptFirstRunNotice().then(function (result) {
            var accepted = !!(result && result.accepted === true);
            if (accepted && result.ok === true) {
                setGateState("accepted_ready");
                settleAcceptedUi();
                return true;
            }
            if (accepted && result.ok === false) {
                setGateState("accepted_start_failed");
                settleAcceptedUi();
                var message = App.extractBridgeError(
                    result,
                    "隐私说明已确认，但记录功能未能启动。可前往设置查看原因或重试。"
                );
                if (App.showGlobalAlert) App.showGlobalAlert(message);
                return true;
            }
            setGateState("acceptance_required");
            setError(App.extractBridgeError(result, FIRST_RUN_NOTICE_ACCEPT_ERROR));
            return false;
        }).catch(function () {
            setGateState("acceptance_required");
            setError(FIRST_RUN_NOTICE_ACCEPT_ERROR);
            return false;
        }).then(function (accepted) {
            noticeAccepting = false;
            setAcceptDisabled(false);
            return accepted;
        });
    }

    function retryGate() {
        if (noticeLoading) return Promise.resolve(false);
        noticeLoaded = false;
        return loadGate({ force: true });
    }

    function viewRequestCurrent(token) {
        return token === viewRequestToken
            && (!App.currentPage || App.currentPage === "settings");
    }

    function openFromSettings() {
        returnFocus = element("settings-privacy-notice-btn") || document.activeElement;
        var token = ++viewRequestToken;
        return App.bridge.getFirstRunNotice().then(function (result) {
            if (!viewRequestCurrent(token)) return false;
            if (!result || result.ok === false) {
                showBlockingError(
                    App.extractBridgeError(result, FIRST_RUN_NOTICE_LOAD_ERROR),
                    "view"
                );
                return false;
            }
            showNotice(result.notice || {}, "view");
            return true;
        }).catch(function () {
            if (!viewRequestCurrent(token)) return false;
            showBlockingError(FIRST_RUN_NOTICE_LOAD_ERROR, "view");
            return false;
        });
    }

    function closeView(options) {
        viewRequestToken += 1;
        if (noticeMode === "view") hideNotice(options);
        else returnFocus = null;
    }

    function bindEvents() {
        if (lifecycleBound) return;
        lifecycleBound = true;
        var close = element("first-run-notice-close-btn");
        if (close) close.addEventListener("click", function () { closeView(); });
        var overlay = element("first-run-notice-overlay");
        if (overlay) {
            overlay.addEventListener("click", function (event) {
                if (viewOpen() && event.target === overlay) closeView();
            });
        }
        document.addEventListener("keydown", function (event) {
            if (!viewOpen()) return;
            if (event.key === "Escape") {
                event.preventDefault();
                closeView();
                return;
            }
            var dialog = element("first-run-notice-dialog");
            if (dialog && App.trapFocus) App.trapFocus(event, dialog);
        });
    }

    App.privacyNotice = Object.freeze({
        acceptGate: acceptGate,
        bindEvents: bindEvents,
        closeView: closeView,
        isReady: isReady,
        loadGate: loadGate,
        openFromSettings: openFromSettings,
        requiresAcceptance: function () { return gateState === "acceptance_required"; },
        retryGate: retryGate,
        state: function () { return gateState; }
    });
})();
