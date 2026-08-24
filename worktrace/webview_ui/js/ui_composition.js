// WorkTrace frontend composition root for cross-surface capability notifications.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var RUNTIME_FRESHNESS_LEASE_MS = 10000;
    var runtimeLeaseExpired = false;
    var runtimeRebasePending = false;
    var LIVE_PROJECTION_PAGES = Object.freeze(["overview", "timeline", "statistics"]);

    function syncFDWorkConsumers(status) {
        if (App.settings && typeof App.settings.onFDWorkStatusChanged === "function") {
            App.settings.onFDWorkStatusChanged(status || App.fdWorkStatus || null);
        }
        if (App.timelineFDWork && typeof App.timelineFDWork.onStatusChanged === "function") {
            App.timelineFDWork.onStatusChanged(status || App.fdWorkStatus || null);
        }
        if (typeof App.updateFDWorkEntryButton === "function") {
            App.updateFDWorkEntryButton();
        }
        if (App.projectIdentity && typeof App.projectIdentity.syncStatus === "function") {
            App.projectIdentity.syncStatus();
        }
    }
    App.syncFDWorkConsumers = syncFDWorkConsumers;

    function nonNegativeInt(value) {
        var parsed = parseInt(value, 10);
        return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
    }

    function runtimeGeneration(runtime, name) {
        var generations = runtime && runtime.generations;
        return nonNegativeInt(generations && generations[name]);
    }

    function currentRuntime() {
        return App.liveRuntimeStore && typeof App.liveRuntimeStore.get === "function"
            ? App.liveRuntimeStore.get()
            : null;
    }

    function pageUsesLiveProjection(page) {
        return LIVE_PROJECTION_PAGES.indexOf(String(page || "")) >= 0;
    }

    function runtimeLiveEligible(runtime) {
        if (!runtime || typeof runtime !== "object") return false;
        var collector = runtime.collector;
        if (collector && typeof collector.live_eligible === "boolean") {
            return collector.live_eligible;
        }
        var clock = runtime.liveClock;
        if (clock && typeof clock.is_live === "boolean") return clock.is_live;
        // Compatibility for narrow test/embedded runtimes. Shipping runtime v2
        // always supplies collector liveness and an exact LiveClock.
        return true;
    }

    function runtimeFresh(runtime, nowMs) {
        if (!runtimeLiveEligible(runtime)) return true;
        var acceptedAt = nonNegativeInt(runtime && runtime.acceptedAtEpochMs);
        if (!acceptedAt) return true;
        var now = nonNegativeInt(nowMs || Date.now());
        if (Math.max(0, now - acceptedAt) <= RUNTIME_FRESHNESS_LEASE_MS) return true;
        runtimeLeaseExpired = true;
        return false;
    }

    function runtimeProjectionAllowed(nowMs) {
        var runtime = currentRuntime();
        if (!runtimeLiveEligible(runtime)) return false;
        if (!runtimeFresh(runtime, nowMs)) return false;
        return runtimeRebasePending !== true;
    }

    function noteAcceptedRuntime(previous, current, source) {
        if (!current) return;
        if (source === "page-payload") {
            // A page payload is the authoritative visual rebase itself.
            runtimeLeaseExpired = false;
            runtimeRebasePending = false;
            return;
        }
        if (source !== "refresh-state") return;

        var page = String(App.currentPage || "overview");
        if (runtimeRebasePending
            && typeof App.pageNeedsRefresh === "function"
            && App.pageNeedsRefresh(page) === false) {
            // The central coordinator has completed the forced page refresh.
            // Clear only on a later authoritative refresh-state acceptance so
            // the first recovery response cannot release stale DOM targets.
            runtimeRebasePending = false;
        }

        var currentLive = runtimeLiveEligible(current);
        if (!currentLive) {
            runtimeLeaseExpired = false;
            runtimeRebasePending = false;
            return;
        }

        var previousLive = runtimeLiveEligible(previous);
        var needsRebase = runtimeLeaseExpired || (!!previous && !previousLive);
        runtimeLeaseExpired = false;
        if (needsRebase && pageUsesLiveProjection(page)) {
            runtimeRebasePending = true;
            // Reuse the existing coordinator path: mark the current page dirty
            // and fetch one authoritative page model before local extrapolation
            // may resume. No second timer or fetch owner is introduced here.
            App.liveClockContractRefreshRequested = true;
        }
    }

    App.RUNTIME_FRESHNESS_LEASE_MS = RUNTIME_FRESHNESS_LEASE_MS;
    App.isLiveRuntimeFresh = function (runtime, nowMs) {
        return runtimeFresh(runtime, nowMs);
    };
    App.isLiveRuntimeProjectionAllowed = function (nowMs) {
        return runtimeProjectionAllowed(nowMs);
    };

    function handleAcceptedRuntimeTransition(previous, accepted, source) {
        var current = currentRuntime();
        if (!accepted || !previous || !current) return accepted;

        var structureChanged = String(previous.structureRevision || "")
            !== String(current.structureRevision || "");
        var liveChanged = String(previous.liveRevision || "")
            !== String(current.liveRevision || "");
        var reportStructureChanged = runtimeGeneration(previous, "report_structure")
            !== runtimeGeneration(current, "report_structure");
        var classificationChanged = runtimeGeneration(previous, "classification_catalog")
            !== runtimeGeneration(current, "classification_catalog");
        var settingsChanged = runtimeGeneration(previous, "settings")
            !== runtimeGeneration(current, "settings");
        var rulesDataChanged = structureChanged || classificationChanged;
        var page = String(App.currentPage || "");

        // Project-rule presentation includes activity-backed last_used_at, so it
        // depends on report structure as well as on the classification catalog.
        if (rulesDataChanged && App.rules && typeof App.rules.onDataChanged === "function") {
            App.rules.onDataChanged({
                source: source,
                structureChanged: structureChanged,
                classificationChanged: classificationChanged
            });
        }
        if (settingsChanged && App.settings && typeof App.settings.onDataChanged === "function") {
            App.settings.onDataChanged({
                source: source,
                settingsChanged: true
            });
        }

        // A page payload is itself the authoritative refresh for the active page.
        // Cross-surface invalidation still applies, but current-page reconcile is
        // reserved for heartbeat refresh-state transitions to avoid double fetches.
        if (source !== "refresh-state") return accepted;

        if (page === "timeline" && App.timeline
            && typeof App.timeline.onRuntimeTransition === "function") {
            App.timeline.onRuntimeTransition({
                source: source,
                structureChanged: structureChanged,
                liveChanged: liveChanged
            });
        }

        if (page === "overview" && App.overview
            && typeof App.overview.onRuntimeTransition === "function") {
            App.overview.onRuntimeTransition({
                source: source,
                structureChanged: structureChanged,
                liveChanged: liveChanged
            });
        }

        if (page === "statistics" && App.statistics
            && typeof App.statistics.onRuntimeTransition === "function") {
            App.statistics.onRuntimeTransition({
                source: source,
                structureChanged: structureChanged,
                liveChanged: liveChanged,
                reportStructureChanged: reportStructureChanged
            });
        }

        return accepted;
    }

    function wrapRuntimeAcceptance(methodName, source) {
        var base = App[methodName];
        if (typeof base !== "function") return;
        App[methodName] = function () {
            var previous = currentRuntime();
            var accepted = base.apply(App, arguments);
            var current = currentRuntime();
            if (accepted && current) noteAcceptedRuntime(previous, current, source);
            return handleAcceptedRuntimeTransition(previous, accepted, source);
        };
    }

    wrapRuntimeAcceptance("acceptRefreshStateRuntime", "refresh-state");
    wrapRuntimeAcceptance("acceptPagePayloadRuntime", "page-payload");

    // The init module remains the sole heartbeat/ticker owner. These wrappers
    // only fail closed when its last accepted runtime is no longer trustworthy.
    var baseApplyLocalTicker = App.applyLocalTicker;
    if (typeof baseApplyLocalTicker === "function") {
        App.applyLocalTicker = function () {
            if (pageUsesLiveProjection(App.currentPage || "overview")) {
                runtimeFresh(currentRuntime(), Date.now());
            }
            return baseApplyLocalTicker.apply(App, arguments);
        };
    }

    var baseRenderLiveDurationTarget = App.renderLiveDurationTarget;
    if (typeof baseRenderLiveDurationTarget === "function") {
        App.renderLiveDurationTarget = function () {
            if (!runtimeProjectionAllowed(Date.now())) return;
            return baseRenderLiveDurationTarget.apply(App, arguments);
        };
    }

    var baseGetActiveLiveClock = App.getActiveLiveClock;
    if (typeof baseGetActiveLiveClock === "function") {
        App.getActiveLiveClock = function () {
            if (!runtimeProjectionAllowed(Date.now())) return null;
            return baseGetActiveLiveClock.apply(App, arguments);
        };
    }

    var statisticsOwner = App.statistics;
    if (statisticsOwner && typeof statisticsOwner.applyLocalTick === "function") {
        var baseStatisticsLocalTick = statisticsOwner.applyLocalTick;
        App.statistics = Object.freeze(Object.assign({}, statisticsOwner, {
            applyLocalTick: function () {
                if (!runtimeProjectionAllowed(Date.now())) return null;
                return baseStatisticsLocalTick.apply(statisticsOwner, arguments);
            }
        }));
    }

    var baseShowStatus = App.showStatus;
    if (typeof baseShowStatus === "function") {
        App.showStatus = function (statusResult) {
            if (!statusResult) return;
            var signature = JSON.stringify([
                String(statusResult.status || ""),
                statusResult.paused === true,
                String(statusResult.display || "")
            ]);
            if (App.lastStatusRenderSignature === signature) return;
            App.lastStatusRenderSignature = signature;
            return baseShowStatus.apply(App, arguments);
        };
    }

    if (App.fdWork && typeof App.fdWork.bindStatusHost === "function") {
        App.fdWork.bindStatusHost({ onStatusChanged: syncFDWorkConsumers });
    }
    if (App.fdWorkStatus) syncFDWorkConsumers(App.fdWorkStatus);
})();
