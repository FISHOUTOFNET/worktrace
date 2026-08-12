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
        if (typeof App.renderFDWorkToggle === "function") {
            App.renderFDWorkToggle(App.lastSettingsStatus || {});
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
        groups.sort(function (left, right) {
            var durationDelta = nonNegativeInt(right.duration_seconds)
                - nonNegativeInt(left.duration_seconds);
            if (durationDelta) return durationDelta;
            return String(left.display_name || "").localeCompare(String(right.display_name || ""), "zh-Hans-CN");
        });
    }

    function liveTargetElapsedSeconds(target, nowMs) {
        var sampledSeconds = nonNegativeInt(target && target.elapsed_seconds_at_sample);
        if (!target || target.enabled !== true || target.ticking !== true) return sampledSeconds;
        var sampledAt = nonNegativeInt(target.sampled_at_epoch_ms);
        if (!sampledAt) return sampledSeconds;
        return sampledSeconds + Math.max(0, Math.floor((nowMs - sampledAt) / 1000));
    }

    function statisticsLiveSummaryAtNow(baseSummary, nowMs) {
        if (!baseSummary || typeof baseSummary !== "object") return baseSummary;
        var target = baseSummary.live_target;
        if (!target || target.enabled !== true) return baseSummary;
        var sampledSeconds = nonNegativeInt(target.elapsed_seconds_at_sample);
        var currentSeconds = liveTargetElapsedSeconds(target, nowMs);
        var delta = Math.max(0, currentSeconds - sampledSeconds);
        if (!delta) return baseSummary;

        var summary = Object.assign({}, baseSummary);
        summary.by_project = cloneGroups(baseSummary.by_project);
        summary.by_app = cloneGroups(baseSummary.by_app);
        summary.by_status = cloneGroups(baseSummary.by_status);
        summary.total_duration_seconds = nonNegativeInt(baseSummary.total_duration_seconds) + delta;
        summary.total_duration = App.formatDuration(summary.total_duration_seconds);

        if (target.contributes_project_duration === true) {
            summary.project_duration_seconds = nonNegativeInt(baseSummary.project_duration_seconds) + delta;
            summary.project_duration = App.formatDuration(summary.project_duration_seconds);
            summary.classified_duration_seconds = nonNegativeInt(baseSummary.classified_duration_seconds) + delta;
        } else if (target.is_uncategorized === true) {
            summary.uncategorized_duration_seconds = nonNegativeInt(baseSummary.uncategorized_duration_seconds) + delta;
        }
        if (target.is_excluded_status === true) {
            summary.excluded_duration_seconds = nonNegativeInt(baseSummary.excluded_duration_seconds) + delta;
        }

        updateLiveGroup(summary.by_project, target.project_key, delta, summary.total_duration_seconds);
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

    function runtimeRefreshIdentity() {
        var runtime = App.liveRuntimeStore && typeof App.liveRuntimeStore.get === "function"
            ? App.liveRuntimeStore.get()
            : null;
        if (!runtime) return "";
        return [
            String(runtime.structureRevision || ""),
            String(runtime.liveRevision || "")
        ].join("|");
    }

    function applyStatisticsLocalTicker() {
        if (App.currentPage !== "statistics") return;
        var accepted = App.statisticsAcceptedPayload;
        if (!accepted || !accepted.summary || !accepted.filters || typeof App.showStatistics !== "function") return;
        var identity = runtimeRefreshIdentity();
        if (identity) App.statisticsAcceptedRefreshIdentity = identity;
        var summary = statisticsLiveSummaryAtNow(accepted.summary, Date.now());
        var delta = nonNegativeInt(summary && summary._live_delta_seconds);
        var renderKey = [
            String(accepted.summary.snapshot_revision || accepted.exportTicket && accepted.exportTicket.revision || ""),
            String(delta)
        ].join("|");
        if (App.statisticsLastLiveRenderKey === renderKey) return;
        App.statisticsLastLiveRenderKey = renderKey;
        App.showStatistics(summary, accepted.filters);
    }
    App.applyStatisticsLocalTicker = applyStatisticsLocalTicker;

    function refreshComposedPage(page, reason) {
        page = String(page || App.currentPage || "");
        if (page === "rules" && typeof App.loadProjectRules === "function") {
            return App.loadProjectRules();
        }
        if (page === "statistics" && typeof App.loadStatisticsExportSummary === "function") {
            if (App.statisticsLoading) return App.statisticsLoadPromise || Promise.resolve(null);
            App.statisticsLastLiveRenderKey = "";
            return App.loadStatisticsExportSummary();
        }
        if (page === "settings" && typeof App.loadSettingsPrivacyStatus === "function") {
            if (App.settingsLoading) return App.settingsLoadPromise || Promise.resolve(null);
            return App.loadSettingsPrivacyStatus();
        }
        return Promise.resolve(null);
    }
    App.refreshComposedPage = refreshComposedPage;

    function statisticsNeedsEntryRefresh() {
        if (!App.statisticsLoaded || !App.statisticsAcceptedPayload) return true;
        var currentIdentity = runtimeRefreshIdentity();
        if (!currentIdentity || !App.statisticsAcceptedRefreshIdentity) return true;
        return currentIdentity !== App.statisticsAcceptedRefreshIdentity;
    }

    function drainTimelineStructuralRefresh() {
        if (!App.timelineStructuralRefreshPending || App.currentPage !== "timeline") {
            return Promise.resolve(false);
        }
        if (typeof App._timelineEditingActive === "function" && App._timelineEditingActive()) {
            return Promise.resolve(false);
        }
        if (typeof App.refreshTimeline !== "function") {
            App.timelineStructuralRefreshPending = false;
            return Promise.resolve(false);
        }
        App.timelineStructuralRefreshPending = false;
        return Promise.resolve(App.refreshTimeline()).then(function () {
            return true;
        }).catch(function (error) {
            App.timelineStructuralRefreshPending = true;
            throw error;
        });
    }
    App.drainTimelineStructuralRefresh = drainTimelineStructuralRefresh;

    function runtimeStatusSignature(runtime) {
        if (!runtime) return "";
        var collector = runtime.collector || {};
        return JSON.stringify([
            runtime.runtimePhase || "",
            collector.status || "",
            collector.paused === true,
            collector.collector_running === true,
            collector.user_paused === true,
            collector.maintenance_in_progress === true,
            collector.blocked_reason || ""
        ]);
    }

    var baseAcceptRefreshStateRuntime = App.acceptRefreshStateRuntime;
    if (typeof baseAcceptRefreshStateRuntime === "function") {
        App.acceptRefreshStateRuntime = function (state) {
            var previous = App.liveRuntimeStore && App.liveRuntimeStore.get
                ? App.liveRuntimeStore.get()
                : null;
            var accepted = baseAcceptRefreshStateRuntime.apply(App, arguments);
            var current = App.liveRuntimeStore && App.liveRuntimeStore.get
                ? App.liveRuntimeStore.get()
                : null;
            if (!accepted || !previous || !current) return accepted;

            var structureChanged = String(previous.structureRevision || "")
                !== String(current.structureRevision || "");
            var liveChanged = String(previous.liveRevision || "")
                !== String(current.liveRevision || "");
            var pageChanged = String(previous.pageRevision || "")
                !== String(current.pageRevision || "");
            var page = String(App.currentPage || "");

            if (page === "timeline" && pageChanged
                && typeof App._timelineEditingActive === "function"
                && App._timelineEditingActive()) {
                App.timelineStructuralRefreshPending = true;
            } else if (page === "rules" && (structureChanged || liveChanged)) {
                refreshComposedPage("rules", "runtime-revision");
            } else if (page === "statistics" && (structureChanged || liveChanged)) {
                refreshComposedPage("statistics", "runtime-revision");
            } else if (page === "settings"
                && runtimeStatusSignature(previous) !== runtimeStatusSignature(current)) {
                refreshComposedPage("settings", "runtime-status");
            }
            return accepted;
        };
    }

    var baseApplyLocalTicker = App.applyLocalTicker;
    if (typeof baseApplyLocalTicker === "function") {
        App.applyLocalTicker = function () {
            baseApplyLocalTicker.apply(App, arguments);
            applyStatisticsLocalTicker();
            if (App.timelineStructuralRefreshPending) {
                drainTimelineStructuralRefresh().catch(function () {});
            }
        };
    }

    var baseRefreshAll = App.refreshAll;
    if (typeof baseRefreshAll === "function") {
        App.refreshAll = function () {
            var page = String(App.currentPage || "");
            if (page === "rules" || page === "statistics" || page === "settings") {
                return refreshComposedPage(page, "manual");
            }
            return baseRefreshAll.apply(App, arguments);
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
                if (navPage === "rules" || navPage === "settings") {
                    refreshComposedPage(navPage, "page-entry");
                } else if (navPage === "statistics" && statisticsNeedsEntryRefresh()) {
                    refreshComposedPage("statistics", "page-entry");
                }
            }
            if (App.timelineStructuralRefreshPending) {
                drainTimelineStructuralRefresh().catch(function () {});
            }
        }, 0);
    }
    document.addEventListener("click", afterUiInteraction);
    document.addEventListener("change", afterUiInteraction);
    document.addEventListener("focusout", afterUiInteraction);

    if (App.fdWork && typeof App.fdWork.bindStatusHost === "function") {
        App.fdWork.bindStatusHost({ onStatusChanged: syncFDWorkConsumers });
    }
    if (App.fdWorkStatus) syncFDWorkConsumers(App.fdWorkStatus);
})();
