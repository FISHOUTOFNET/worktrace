// WorkTrace WebView frontend — first-run privacy gate state coordinator.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var rawLoadFirstRunNotice = App.loadFirstRunNotice;

    App.firstRunNoticeState = App.firstRunNoticeState || "unknown";
    App.firstRunNoticePromise = null;

    function loadFirstRunNoticeSingleFlight() {
        if (App.firstRunNoticeState === "accepted"
            || App.firstRunNoticeState === "required") {
            return Promise.resolve(true);
        }
        if (App.firstRunNoticeState === "failed") {
            return Promise.resolve(false);
        }
        if (App.firstRunNoticePromise) return App.firstRunNoticePromise;
        if (typeof rawLoadFirstRunNotice !== "function") {
            App.firstRunNoticeState = "failed";
            return Promise.resolve(false);
        }

        App.firstRunNoticeState = "loading";
        App.firstRunNoticePromise = Promise.resolve().then(function () {
            return rawLoadFirstRunNotice();
        }).then(function (loaded) {
            if (loaded !== true) {
                App.firstRunNoticeState = "failed";
                return false;
            }
            App.firstRunNoticeState = App.firstRunNoticeRequired
                ? "required"
                : "accepted";
            return true;
        }).catch(function () {
            App.firstRunNoticeState = "failed";
            return false;
        }).finally(function () {
            App.firstRunNoticePromise = null;
        });
        return App.firstRunNoticePromise;
    }

    App.loadFirstRunNotice = loadFirstRunNoticeSingleFlight;
})();
