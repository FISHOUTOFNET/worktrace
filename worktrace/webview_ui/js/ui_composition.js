// WorkTrace frontend composition root for cross-surface capability notifications.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function clearSettledFDWorkAuthOverride(status) {
        if (!status || status.operation !== "none") return;
        if (["ready", "idle", "error", "disabled", "shutdown"].indexOf(status.session_state) < 0) {
            return;
        }
        var override = App.fdWorkStatusOverride;
        var reason = String(override && override.reason || "");
        if (/登录|连接 FD Work/.test(reason)) App.fdWorkStatusOverride = null;
    }

    function syncFDWorkConsumers(status) {
        clearSettledFDWorkAuthOverride(status || App.fdWorkStatus);
        if (App.settings && typeof App.settings.onFDWorkStatusChanged === "function") {
            App.settings.onFDWorkStatusChanged(status || App.fdWorkStatus || null);
        }
        if (typeof App.updateFDWorkEntryButton === "function") {
            App.updateFDWorkEntryButton();
        }
        if (App.projectIdentity && typeof App.projectIdentity.syncStatus === "function") {
            App.projectIdentity.syncStatus();
        }
    }
    App.syncFDWorkConsumers = syncFDWorkConsumers;

    function reconnectFDWorkThroughSharedSession() {
        if (!App.fdWork || typeof App.fdWork.ensureSession !== "function") {
            if (typeof App.showSettingsError === "function") {
                App.showSettingsError("打开 FD Work 失败");
            }
            return Promise.resolve(false);
        }
        return App.fdWork.ensureSession().then(function (result) {
            if (!result || result.ok !== true) {
                if (typeof App.showSettingsError === "function") {
                    App.showSettingsError(result && result.message || "打开 FD Work 失败");
                }
                return false;
            }
            if (typeof App.clearSettingsError === "function") App.clearSettingsError();
            return true;
        }).catch(function () {
            if (typeof App.showSettingsError === "function") {
                App.showSettingsError("打开 FD Work 失败");
            }
            return false;
        });
    }
    App.reconnectFDWork = reconnectFDWorkThroughSharedSession;

    function nonNegativeInt(value) {
        var parsed = parseInt(value, 10);
        return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
    }

    function cloneGroups(groups) {
        return (Array.isArray(groups) ? groups : []).map(function (group) {
            return Object.assign({}, group || {});
        });
    }

    function updateLiveGroup(groups, key, delta, totalSeconds) {
        if (!key || !delta) return;
        var target = null;
        for (var i = 0; i < groups.length; i++) {
            if (String(groups[i].key || "") === String(key)) {
                target = groups[i];
                break;
            }
        }
        if (!target) return;
        target.duration_seconds = nonNegativeInt(target.duration_seconds) + delta;
        target.duration = App.formatDuration(target.duration_seconds);
        for (var j = 0; j < groups.length; j++) {
            var seconds = nonNegativeInt(groups[j].duration_seconds);
            groups[j].percentage = totalSeconds > 0
                ? Math.round(seconds / totalSeconds * 1000) / 10
                : 0;
        }
        // Keep authoritative row order stable while the local clock ticks.
    }

    function liveTargetElapsedSeconds(target, nowMs) {
        var sampledSeconds = nonNegativeInt(target && target.elapsed_seconds_at_sample);
        if (!target || target.enabled !== true || target.ticking !== true) return sampledSeconds;
        var sampledAt = nonNegativeInt(target.sampled_at_epoch_ms);
        if (!sampledAt) return sampledSeconds;
        return sampledSeconds + Math.max(0, Math.floor((nowMs - sampledAt) / 1000));
    }

    function statisticsLiveSummaryAtNow(baseSummary, nowMs, targetOverride) {
        if (!baseSummary || typeof baseSummary !== "object") return baseSummary;
        var target = targetOverride || baseSummary.live_target;
        if (!target || target.enabled !== true) return baseSummary;
        var sampledSeconds = nonNegativeInt(target.elapsed_seconds_at_sample);
        var currentSeconds = liveTargetElapsedSeconds(target, nowMs);
        var delta = Math.max(0, currentSeconds - sampledSeconds);
        if (!delta) return baseSummary;

        var summary = Object.assign({}, baseSummary);
        summary.by_project = cloneGroups(baseSummary.by_project);
        summary.by_file = cloneGroups(baseSummary.by_file);
        summary.by_app = cloneGroups(baseSummary.by_app);
        summary.by_status = cloneGroups(baseSummary.by_status);
        summary.total_duration_seconds = nonNegativeInt(baseSummary.total_duration_seconds) + delta;
        summary.total_duration = App.formatDuration(summary.total_duration_seconds);

        if (target.contributes_project_duration === true) {
            summary.project_duration_seconds = nonNegativeInt(baseSummary.project_duration_seconds) + delta;
            summary.project_duration = App.formatDuration(summary.project_duration_seconds);
        }

        updateLiveGroup(summary.by_project, target.project_key, delta, summary.total_duration_seconds);
        updateLiveGroup(summary.by_file, target.file_key, delta, summary.total_duration_seconds);
        updateLiveGroup(summary.by_app, target.app_key, delta, summary.total_duration_seconds);
        updateLiveGroup(summary.by_status, target.status_key, delta, summary.total_duration_seconds);

        if (baseSummary.export_preview && typeof baseSummary.export_preview === "object") {
            summary.export_preview = Object.assign({}, baseSummary.export_preview);
            summary.export_preview.included_duration_seconds =
                nonNegativeInt(baseSummary.export_preview.included_duration_seconds) + delta;
            summary.export_preview.included_duration = App.formatDuration(
                summary.export_preview.included_duration_seconds
            );
        }
        summary._live_delta_seconds = delta;
        return summary;
    }
    App.statisticsLiveSummaryAtNow = statisticsLiveSummaryAtNow;

    function runtimeGeneration(runtime, name) {
        var generations = runtime && runtime.generations;
        return nonNegativeInt(generations && generations[name]);
    }

    function patchStatisticsGroupTable(tbodyId, groups) {
        var body = document.getElementById(tbodyId);
        if (!body || typeof body.querySelectorAll !== "function") return false;
        var rows = body.querySelectorAll("tr");
        groups = Array.isArray(groups) ? groups : [];
        if (rows.length !== groups.length) return false;
        for (var i = 0; i < rows.length; i++) {
            var cells = rows[i].children;
            if (!cells || cells.length < 4) return false;
            var group = groups[i] || {};
            var duration = group.duration || App.formatDuration(group.duration_seconds || 0);
            var percentage = Math.max(0, Math.min(100, parseFloat(group.percentage) || 0));
            if (cells[1].textContent !== duration) cells[1].textContent = duration;
            var percentageText = String(group.percentage || 0) + "%";
            if (cells[3].textContent !== percentageText) cells[3].textContent = percentageText;
            var bar = typeof rows[i].querySelector === "function"
                ? rows[i].querySelector(".stats-share-bar i")
                : null;
            if (bar && bar.style) bar.style.width = percentage + "%";
        }
        return true;
    }

    function patchStatisticsLiveSummary(summary) {
        if (!summary || typeof document.getElementById !== "function") return false;
        var total = document.getElementById("stats-total");
        if (total) total.textContent = summary.total_duration || "00:00:00";
        var projectPatched = patchStatisticsGroupTable("stats-by-project", summary.by_project || []);
        var filePatched = patchStatisticsGroupTable("stats-by-file", summary.by_file || []);
        var appPatched = patchStatisticsGroupTable("stats-by-app", summary.by_app || []);
        return projectPatched && filePatched && appPatched;
    }
    App.patchStatisticsLiveSummary = patchStatisticsLiveSummary;

    function applyStatisticsLocalTicker() {
        if (App.currentPage !== "statistics" || App.statisticsLiveTickerSuspended === true) return;
        var accepted = App.statisticsAcceptedPayload;
        if (!accepted || !accepted.summary || !accepted.filters) return;
        var liveTarget = accepted.exportTicket && accepted.exportTicket.live_target;
        var summary = statisticsLiveSummaryAtNow(accepted.summary, Date.now(), liveTarget);
        var delta = nonNegativeInt(summary && summary._live_delta_seconds);
        var renderKey = [
            String(accepted.summary.snapshot_revision || accepted.exportTicket && accepted.exportTicket.revision || ""),
            String(delta)
        ].join("|");
        if (App.statisticsLastLiveRenderKey === renderKey) return;
        App.statisticsLastLiveRenderKey = renderKey;
        patchStatisticsLiveSummary(summary);
    }
    App.applyStatisticsLocalTicker = applyStatisticsLocalTicker;

    var baseShowOverview = App.showOverview;
    if (typeof baseShowOverview === "function") {
        App.showOverview = function () {
            if (App.currentPage === "overview" && App.suppressNextOverviewCollectionRefresh === true) {
                App.suppressNextOverviewCollectionRefresh = false;
                return;
            }
            return baseShowOverview.apply(App, arguments);
        };
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

        if (page === "overview") {
            App.suppressNextOverviewCollectionRefresh = !structureChanged && liveChanged;
        }

        // Statistics query ownership belongs to init_fd_work_v5.js. Composition
        // only freezes the old live target immediately at an activity boundary;
        // the central generation coordinator performs the debounced silent sync.
        if (page === "statistics" && reportStructureChanged
            && typeof App.suspendStatisticsLiveTicker === "function") {
            App.suspendStatisticsLiveTicker();
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

    var baseApplyLocalTicker = App.applyLocalTicker;
    if (typeof baseApplyLocalTicker === "function") {
        App.applyLocalTicker = function () {
            baseApplyLocalTicker.apply(App, arguments);
            applyStatisticsLocalTicker();
            if (App.currentPage === "timeline" && App.timeline
                && typeof App.timeline.applyLocalTick === "function") {
                App.timeline.applyLocalTick().catch(function () {});
            }
        };
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

    function navPageFromTarget(target) {
        var node = target;
        while (node && node !== document) {
            if (typeof node.getAttribute === "function") {
                var page = node.getAttribute("data-page");
                if (page) return String(page);
            }
            node = node.parentNode;
        }
        return "";
    }

    function afterUiInteraction(event) {
        var navPage = event && event.type === "click" ? navPageFromTarget(event.target) : "";
        window.setTimeout(function () {
            if (navPage && App.currentPage === navPage) {
                if (navPage === "rules" && App.rules
                    && typeof App.rules.onPageEntered === "function") {
                    App.rules.onPageEntered();
                } else if (navPage === "settings" && App.settings
                    && typeof App.settings.onPageEntered === "function") {
                    App.settings.onPageEntered();
                }
            }
        }, 0);
    }
    if (document && typeof document.addEventListener === "function") {
        document.addEventListener("click", afterUiInteraction);
    }

    if (App.fdWork && typeof App.fdWork.bindStatusHost === "function") {
        App.fdWork.bindStatusHost({ onStatusChanged: syncFDWorkConsumers });
    }
    if (App.fdWorkStatus) syncFDWorkConsumers(App.fdWorkStatus);
})();
