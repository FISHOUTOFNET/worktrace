// WorkTrace frontend composition root for cross-surface capability notifications.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

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

    function handleAcceptedRuntimeTransition(previous, accepted, source) {
        var current = App.liveRuntimeStore && App.liveRuntimeStore.get
            ? App.liveRuntimeStore.get()
            : null;
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
        // Cross-surface invalidation still applies, but current-page transient
        // interlocks are reserved for heartbeat refresh-state transitions.
        if (source !== "refresh-state") return accepted;

        if (page === "timeline" && App.timeline
            && typeof App.timeline.onRuntimeTransition === "function") {
            App.timeline.onRuntimeTransition({
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
            var previous = App.liveRuntimeStore && App.liveRuntimeStore.get
                ? App.liveRuntimeStore.get()
                : null;
            var accepted = base.apply(App, arguments);
            return handleAcceptedRuntimeTransition(previous, accepted, source);
        };
    }

    wrapRuntimeAcceptance("acceptRefreshStateRuntime", "refresh-state");
    wrapRuntimeAcceptance("acceptPagePayloadRuntime", "page-payload");

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
