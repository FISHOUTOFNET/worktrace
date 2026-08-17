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
        summary.by_app = cloneGroups(baseSummary.by_app);
        summary.by_status = cloneGroups(baseSummary.by_status);
        summary.total_duration_seconds = nonNegativeInt(baseSummary.total_duration_seconds) + delta;
        summary.total_duration = App.formatDuration(summary.total_duration_seconds);

        if (target.contributes_project_duration === true) {
            summary.project_duration_seconds = nonNegativeInt(baseSummary.project_duration_seconds) + delta;
            summary.project_duration = App.formatDuration(summary.project_duration_seconds);
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

    function runtimeGeneration(runtime, name) {
        var generations = runtime && runtime.generations;
        return nonNegativeInt(generations && generations[name]);
    }

    function runtimeRefreshIdentity(runtime) {
        runtime = runtime || (App.liveRuntimeStore && typeof App.liveRuntimeStore.get === "function"
            ? App.liveRuntimeStore.get()
            : null);
        if (!runtime) return "";
        return [
            String(runtime.structureRevision || ""),
            String(runtime.liveRevision || "")
        ].join("|");
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
        var appPatched = patchStatisticsGroupTable("stats-by-app", summary.by_app || []);
        return projectPatched && appPatched;
    }
    App.patchStatisticsLiveSummary = patchStatisticsLiveSummary;

    function applyStatisticsLocalTicker() {
        if (App.currentPage !== "statistics") return;
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

    function backgroundRulesRefresh() {
        if (!App.bridge || typeof App.bridge.getProjectRules !== "function") return Promise.resolve(null);
        if (App.rulesLoading) return App.rulesLoadPromise || Promise.resolve(null);
        if (App.rulesBackgroundRefreshPromise) return App.rulesBackgroundRefreshPromise;
        var token = App.requestCoordinator.beginLatest("rules", "background");
        var request = App.bridge.getProjectRules().then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            var data = App.handleResult(result, function (message) {
                if (typeof App.showRulesError === "function") App.showRulesError(message);
            });
            if (!data) return null;
            if (typeof App.showProjectRules === "function") App.showProjectRules(data);
            App.rulesLoaded = true;
            App.rulesRefreshPending = false;
            if (typeof App.clearRulesError === "function") App.clearRulesError();
            return data;
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token) && typeof App.showRulesError === "function") {
                App.showRulesError("加载项目规则失败");
            }
            return null;
        }).finally(function () {
            if (App.rulesBackgroundRefreshPromise === request) {
                App.rulesBackgroundRefreshPromise = null;
            }
        });
        App.rulesBackgroundRefreshPromise = request;
        return request;
    }
    App.backgroundRulesRefresh = backgroundRulesRefresh;

    function backgroundStatisticsRefresh() {
        if (!App.bridge || typeof App.bridge.getStatisticsExportSummary !== "function"
            || typeof App.selectedStatisticsFilters !== "function") {
            return Promise.resolve(null);
        }
        if (App.statisticsLoading) return App.statisticsLoadPromise || Promise.resolve(null);
        var filters = App.selectedStatisticsFilters();
        var key = "background|" + JSON.stringify(filters || {});
        var requestIdentity = runtimeRefreshIdentity();
        var token = App.requestCoordinator.beginLatest("statistics", key);
        return App.bridge.getStatisticsExportSummary(
            filters.dateFrom, filters.dateTo, filters.projectId
        ).then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            var data = App.handleResult(result, function (message) {
                if (typeof App.showStatisticsError === "function") App.showStatisticsError(message);
            });
            if (!data || !data.summary || !data.export_ticket) return null;
            App.statisticsAcceptedPayload = {
                summary: data.summary,
                exportTicket: data.export_ticket,
                filters: filters
            };
            App.statisticsSnapshotRevision = String(data.export_ticket.revision || "");
            App.statisticsAcceptedRefreshIdentity = requestIdentity;
            App.statisticsLastLiveRenderKey = "";
            if (typeof App.showStatistics === "function") App.showStatistics(data.summary, filters);
            App.statisticsLoaded = true;
            if (typeof App.clearStatisticsError === "function") App.clearStatisticsError();
            return data;
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token) && typeof App.showStatisticsError === "function") {
                App.showStatisticsError("加载统计失败");
            }
            return null;
        });
    }
    App.backgroundStatisticsRefresh = backgroundStatisticsRefresh;

    function backgroundSettingsRefresh() {
        if (!App.bridge || typeof App.bridge.getSettingsPrivacyStatus !== "function") {
            return Promise.resolve(null);
        }
        if (App.settingsLoading) return App.settingsLoadPromise || Promise.resolve(null);
        if (App.settingsBackgroundRefreshPromise) return App.settingsBackgroundRefreshPromise;
        if (typeof App.anySettingsOperationInProgress === "function"
            && App.anySettingsOperationInProgress()) {
            App.settingsRefreshPending = true;
            return Promise.resolve(null);
        }
        var token = ++App.settingsRequestToken;
        var request = App.bridge.getSettingsPrivacyStatus().then(function (result) {
            if (token !== App.settingsRequestToken) return null;
            var data = App.handleResult(result, function (message) {
                if (typeof App.showSettingsError === "function") App.showSettingsError(message);
            });
            if (!data || !data.status) return null;
            App.settingsLoaded = true;
            App.lastSettingsStatus = data.status;
            if (typeof App.renderSettingsStatus === "function") App.renderSettingsStatus(data.status);
            App.settingsRefreshPending = false;
            if (typeof App.clearSettingsError === "function") App.clearSettingsError();
            return data;
        }).catch(function () {
            if (token === App.settingsRequestToken && typeof App.showSettingsError === "function") {
                App.showSettingsError("加载设置状态失败");
            }
            return null;
        }).finally(function () {
            if (App.settingsBackgroundRefreshPromise === request) {
                App.settingsBackgroundRefreshPromise = null;
            }
        });
        App.settingsBackgroundRefreshPromise = request;
        return request;
    }
    App.backgroundSettingsRefresh = backgroundSettingsRefresh;

    function refreshComposedPage(page, reason) {
        page = String(page || App.currentPage || "");
        reason = String(reason || "manual");
        if (page === "rules" && typeof App.loadProjectRules === "function") {
            if (!App.rulesLoaded) return App.loadProjectRules();
            return backgroundRulesRefresh();
        }
        if (page === "statistics" && typeof App.loadStatisticsExportSummary === "function") {
            if (App.statisticsLoading) return App.statisticsLoadPromise || Promise.resolve(null);
            App.statisticsLastLiveRenderKey = "";
            if (reason === "manual" || !App.statisticsLoaded) return App.loadStatisticsExportSummary();
            return backgroundStatisticsRefresh();
        }
        if (page === "settings" && typeof App.loadSettingsPrivacyStatus === "function") {
            if (App.settingsLoading) return App.settingsLoadPromise || Promise.resolve(null);
            if (!App.settingsLoaded) return App.loadSettingsPrivacyStatus();
            return backgroundSettingsRefresh();
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

    var baseRefreshTimeline = App.refreshTimeline;
    if (typeof baseRefreshTimeline === "function") {
        App.refreshTimeline = function () {
            if (App.currentPage === "timeline" && App.suppressNextTimelineCollectionRefresh === true) {
                App.suppressNextTimelineCollectionRefresh = false;
                return Promise.resolve(null);
            }
            return baseRefreshTimeline.apply(App, arguments);
        };
    }

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
        var classificationChanged = runtimeGeneration(previous, "classification_catalog")
            !== runtimeGeneration(current, "classification_catalog");
        var settingsChanged = runtimeGeneration(previous, "settings")
            !== runtimeGeneration(current, "settings");
        var rulesDataChanged = structureChanged || classificationChanged;
        var page = String(App.currentPage || "");

        // Project-rule presentation includes activity-backed last_used_at, so it
        // depends on report structure as well as on the classification catalog.
        if (rulesDataChanged) App.rulesRefreshPending = true;
        if (settingsChanged) App.settingsRefreshPending = true;

        // A page payload is itself the authoritative refresh for the active page.
        // Cross-surface invalidation still applies, but current-page reconcile is
        // reserved for heartbeat refresh-state transitions to avoid double fetches.
        if (source !== "refresh-state") return accepted;

        if (page === "timeline") {
            App.suppressNextTimelineCollectionRefresh = !structureChanged && liveChanged;
        } else if (page === "overview") {
            App.suppressNextOverviewCollectionRefresh = !structureChanged && liveChanged;
        }

        if (page === "timeline" && structureChanged
            && typeof App._timelineEditingActive === "function"
            && App._timelineEditingActive()) {
            App.timelineStructuralRefreshPending = true;
        } else if (page === "rules" && rulesDataChanged) {
            refreshComposedPage("rules", "runtime-dependency");
        } else if (page === "statistics" && (structureChanged || liveChanged)) {
            refreshComposedPage("statistics", "runtime-revision");
        } else if (page === "settings" && settingsChanged) {
            refreshComposedPage("settings", "settings-generation");
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
            // A user-initiated refresh must never inherit a one-shot suppression
            // token from a preceding passive runtime transition.
            if (page === "timeline") App.suppressNextTimelineCollectionRefresh = false;
            if (page === "overview") App.suppressNextOverviewCollectionRefresh = false;
            return baseRefreshAll.apply(App, arguments);
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
                if (navPage === "rules" && App.rulesRefreshPending === true) {
                    refreshComposedPage("rules", "page-entry");
                } else if (navPage === "settings") {
                    refreshComposedPage("settings", "page-entry");
                } else if (navPage === "statistics" && statisticsNeedsEntryRefresh()) {
                    refreshComposedPage("statistics", "page-entry");
                }
            }
            if (App.timelineStructuralRefreshPending) {
                drainTimelineStructuralRefresh().catch(function () {});
            }
        }, 0);
    }
    if (document && typeof document.addEventListener === "function") {
        document.addEventListener("click", afterUiInteraction);
        document.addEventListener("change", afterUiInteraction);
        document.addEventListener("focusout", afterUiInteraction);
    }

    if (App.fdWork && typeof App.fdWork.bindStatusHost === "function") {
        App.fdWork.bindStatusHost({ onStatusChanged: syncFDWorkConsumers });
    }
    if (App.fdWorkStatus) syncFDWorkConsumers(App.fdWorkStatus);
})();
