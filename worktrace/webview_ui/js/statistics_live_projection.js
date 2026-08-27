// WorkTrace WebView frontend — lightweight Statistics live projection owner.
// Keeps authoritative snapshot/rendering semantics in statistics.js while
// making the 1-second local projection proportional to visible changes.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var baseCapability = App.statistics;
    if (!baseCapability || typeof baseCapability !== "object") return;

    var rowIndex = null;
    var runtimeSyncState = null;

    function element(id) { return document.getElementById(id); }

    function nonNegativeInt(value) {
        var parsed = parseInt(value, 10);
        return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
    }

    function statisticsGroupKey(group, index) {
        group = group || {};
        var key = String(group.key || "");
        if (key) return key;
        return "display:" + String(group.display_name || "未知") + "|" + String(index || 0);
    }

    function liveTargetElapsedSeconds(target, nowMs) {
        var sampledSeconds = nonNegativeInt(target && target.elapsed_seconds_at_sample);
        if (!target || target.enabled !== true || target.ticking !== true) return sampledSeconds;
        var sampledAt = nonNegativeInt(target.sampled_at_epoch_ms);
        if (!sampledAt) return sampledSeconds;
        return sampledSeconds + Math.max(0, Math.floor((nowMs - sampledAt) / 1000));
    }

    function liveTargetFresh(target, nowMs) {
        if (!target || target.enabled !== true || target.ticking !== true) return true;
        if (typeof App.liveSampleFresh !== "function") return false;
        return App.liveSampleFresh(nonNegativeInt(target.sampled_at_epoch_ms), nowMs);
    }

    function runtimeLiveEligibility() {
        var store = App.liveRuntimeStore;
        if (!store || typeof store.get !== "function") return null;
        var runtime = store.get();
        var collector = runtime && runtime.collector;
        if (!collector || typeof collector.live_eligible !== "boolean") return null;
        return collector.live_eligible;
    }

    function runtimeLiveEligible() {
        var value = runtimeLiveEligibility();
        return value === null ? true : value;
    }

    function normalizeRuntimeSync(value) {
        if (!value || typeof value !== "object" || Array.isArray(value)) return null;
        return {
            runtimeConsistent: value.runtime_consistent === true,
            needsFullRefresh: value.needs_full_refresh === true,
            collectionLiveEligible: value.collection_live_eligible === true
        };
    }

    function runtimeSyncPending() {
        return !!(runtimeSyncState && runtimeSyncState.needsFullRefresh === true);
    }

    function invalidateRowIndex() {
        rowIndex = null;
    }

    function observeStatisticsRuntimeSync(data) {
        if (!data || typeof data !== "object" || !data.summary || !data.export_ticket) return;
        var sync = normalizeRuntimeSync(data.runtime_sync);
        if (!sync) return;
        runtimeSyncState = sync;
        if (sync.needsFullRefresh) {
            App.statisticsLiveTickerSuspended = true;
            invalidateRowIndex();
        }
    }

    var baseHandleResult = App.handleResult;
    if (typeof baseHandleResult === "function") {
        App.handleResult = function () {
            var data = baseHandleResult.apply(App, arguments);
            observeStatisticsRuntimeSync(data);
            return data;
        };
    }

    function buildGroupIndex(tbodyId, groups) {
        var body = element(tbodyId);
        if (!body || typeof body.querySelectorAll !== "function") return null;
        var rows = body.querySelectorAll("tr");
        groups = Array.isArray(groups) ? groups : [];
        if (rows.length !== groups.length) return null;
        var entries = [];
        for (var index = 0; index < rows.length; index++) {
            var row = rows[index];
            var expectedKey = statisticsGroupKey(groups[index], index);
            if (typeof row.getAttribute === "function"
                && String(row.getAttribute("data-statistics-key") || "") !== expectedKey) {
                return null;
            }
            var cells = row.children;
            var bar = typeof row.querySelector === "function"
                ? row.querySelector(".stats-share-bar i")
                : null;
            if (!cells || cells.length < 4 || !bar || !bar.style) return null;
            entries.push({
                key: expectedKey,
                cells: cells,
                bar: bar
            });
        }
        return entries;
    }

    function buildRowIndex(summary, owner) {
        var project = buildGroupIndex("stats-by-project", summary.by_project || []);
        var file = buildGroupIndex("stats-by-file", summary.by_file || []);
        var app = buildGroupIndex("stats-by-app", summary.by_app || []);
        if (!project || !file || !app) return null;
        return {
            owner: owner,
            project: project,
            file: file,
            app: app
        };
    }

    function ensureRowIndex(summary) {
        var owner = App.statisticsAcceptedPayload || summary;
        if (rowIndex && rowIndex.owner === owner) return rowIndex;
        rowIndex = buildRowIndex(summary, owner);
        return rowIndex;
    }

    function writeText(target, value) {
        if (target && target.textContent !== value) target.textContent = value;
    }

    function writeWidth(target, value) {
        if (target && target.style && target.style.width !== value) target.style.width = value;
    }

    function patchGroup(entries, groups, liveKey, delta, totalSeconds) {
        groups = Array.isArray(groups) ? groups : [];
        if (!entries || entries.length !== groups.length) return false;
        var normalizedLiveKey = String(liveKey || "");
        var matchedLiveKey = !normalizedLiveKey;
        for (var index = 0; index < groups.length; index++) {
            var group = groups[index] || {};
            var expectedKey = statisticsGroupKey(group, index);
            var entry = entries[index];
            if (!entry || entry.key !== expectedKey) return false;

            var rawKey = String(group.key || "");
            var isLive = !!normalizedLiveKey && rawKey === normalizedLiveKey;
            if (isLive) matchedLiveKey = true;
            var seconds = nonNegativeInt(group.duration_seconds) + (isLive ? delta : 0);
            var duration = isLive && delta > 0
                ? App.formatDuration(seconds)
                : String(group.duration || App.formatDuration(seconds));
            var percentage = totalSeconds > 0
                ? Math.round(seconds / totalSeconds * 1000) / 10
                : 0;
            var percentageText = String(percentage || 0) + "%";
            var width = Math.max(0, Math.min(100, percentage)) + "%";

            writeText(entry.cells[1], duration);
            writeText(entry.cells[3], percentageText);
            writeWidth(entry.bar, width);
        }
        return matchedLiveKey;
    }

    function patchLiveProjection(summary, target, delta) {
        if (!summary) return false;
        var total = element("stats-total");
        var index = ensureRowIndex(summary);
        if (!total || !index) return false;

        var totalSeconds = nonNegativeInt(summary.total_duration_seconds) + delta;
        writeText(total, App.formatDuration(totalSeconds));
        if (!patchGroup(index.project, summary.by_project || [], target.project_key, delta, totalSeconds)) {
            return false;
        }
        if (!patchGroup(index.file, summary.by_file || [], target.file_key, delta, totalSeconds)) {
            return false;
        }
        if (!patchGroup(index.app, summary.by_app || [], target.app_key, delta, totalSeconds)) {
            return false;
        }
        return true;
    }

    function freezeStatisticsProjection(reason) {
        App.statisticsLiveTickerSuspended = true;
        invalidateRowIndex();
        return {
            refreshRequired: true,
            reason: String(reason || "statistics_live_projection_stale")
        };
    }

    function runtimeLivenessChanged() {
        if (!runtimeSyncState || runtimeSyncState.needsFullRefresh) return false;
        var current = runtimeLiveEligibility();
        return current !== null
            && current !== runtimeSyncState.collectionLiveEligible;
    }

    function applyStatisticsLocalTick() {
        if (App.currentPage !== "statistics") return null;
        if (runtimeSyncPending()) {
            return freezeStatisticsProjection("statistics_runtime_sync_pending");
        }
        if (runtimeLivenessChanged()) {
            return freezeStatisticsProjection("statistics_runtime_liveness_changed");
        }
        if (App.statisticsLiveTickerSuspended === true) return null;
        var accepted = App.statisticsAcceptedPayload;
        if (!accepted || !accepted.summary || !accepted.filters) return null;
        var target = accepted.exportTicket && accepted.exportTicket.live_target;
        if (!target || target.enabled !== true) return null;

        var nowMs = Date.now();
        if (target.ticking === true && runtimeLiveEligible() !== true) {
            return freezeStatisticsProjection("statistics_runtime_not_live");
        }
        if (!liveTargetFresh(target, nowMs)) {
            return freezeStatisticsProjection("statistics_live_target_stale");
        }

        var sampledSeconds = nonNegativeInt(target.elapsed_seconds_at_sample);
        var currentSeconds = liveTargetElapsedSeconds(target, nowMs);
        var delta = Math.max(0, currentSeconds - sampledSeconds);
        var renderKey = [
            String(accepted.summary.snapshot_revision
                || accepted.exportTicket && accepted.exportTicket.revision || ""),
            String(delta)
        ].join("|");
        if (App.statisticsLastLiveRenderKey === renderKey) return null;

        if (patchLiveProjection(accepted.summary, target, delta)) {
            App.statisticsLastLiveRenderKey = renderKey;
            return null;
        }
        invalidateRowIndex();
        if (delta > 0) {
            return {
                refreshRequired: true,
                reason: "statistics_live_projection_mismatch"
            };
        }
        return null;
    }

    function onStatisticsRuntimeTransition(change) {
        change = change || {};
        if (change.source !== "refresh-state" || change.reportStructureChanged !== true) return;
        if (App.statisticsLiveTickerSuspended === true) return;
        App.statisticsLiveTickerSuspended = true;
        invalidateRowIndex();
    }

    var refreshPolicy = Object.assign({}, baseCapability.refreshPolicy || {}, {
        deferred: false,
        preservePresentation: true
    });
    var capability = {};
    Object.keys(baseCapability).forEach(function (key) {
        capability[key] = baseCapability[key];
    });
    var baseHasLoadedData = baseCapability.hasLoadedData;
    var baseResetGeneration = baseCapability.resetGeneration;
    capability.applyLocalTick = applyStatisticsLocalTick;
    capability.hasLoadedData = function () {
        if (runtimeSyncPending()) return false;
        return typeof baseHasLoadedData === "function"
            ? baseHasLoadedData.call(baseCapability)
            : true;
    };
    capability.onRuntimeTransition = onStatisticsRuntimeTransition;
    capability.refreshPolicy = Object.freeze(refreshPolicy);
    capability.resetGeneration = function () {
        runtimeSyncState = null;
        invalidateRowIndex();
        if (typeof baseResetGeneration === "function") {
            return baseResetGeneration.call(baseCapability);
        }
    };

    App.applyStatisticsLocalTicker = applyStatisticsLocalTick;
    App.statistics = Object.freeze(capability);
    App.statisticsLiveProjection = Object.freeze({
        invalidateRowIndex: invalidateRowIndex,
        runtimeSyncPending: runtimeSyncPending,
        runtimeSyncState: function () { return runtimeSyncState; }
    });
})();
