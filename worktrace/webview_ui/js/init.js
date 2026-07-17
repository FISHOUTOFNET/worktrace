// WorkTrace WebView frontend — initialization, fixed bridge client, and runtime store.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function invokeBridge(method, argsLike) {
        if (!window.pywebview || !window.pywebview.api) {
            return Promise.reject(new Error("bridge unavailable"));
        }
        var fn = window.pywebview.api[method];
        if (typeof fn !== "function") {
            return Promise.reject(new Error("bridge method unavailable"));
        }
        return fn.apply(window.pywebview.api, Array.prototype.slice.call(argsLike || []));
    }

    function fixedBridgeMethod(method) {
        return function () { return invokeBridge(method, arguments); };
    }

    App.bridge = Object.freeze({
        acceptFirstRunNotice: fixedBridgeMethod("accept_first_run_notice"),
        archiveProjectForRules: fixedBridgeMethod("archive_project_for_rules"),
        automaticRulesStatus: fixedBridgeMethod("automatic_rules_status"),
        backfillProjectRule: fixedBridgeMethod("backfill_project_rule"),
        backfillProjectRulesBatch: fixedBridgeMethod("backfill_project_rules_batch"),
        clearAllLocalData: fixedBridgeMethod("clear_all_local_data"),
        copyTimelineSession: fixedBridgeMethod("copy_timeline_session"),
        createExcludedFolderRule: fixedBridgeMethod("create_excluded_folder_rule"),
        createExcludedKeywordRule: fixedBridgeMethod("create_excluded_keyword_rule"),
        createProjectFolderRule: fixedBridgeMethod("create_project_folder_rule"),
        createProjectForRules: fixedBridgeMethod("create_project_for_rules"),
        createProjectKeywordRule: fixedBridgeMethod("create_project_keyword_rule"),
        deleteProjectFolderRule: fixedBridgeMethod("delete_project_folder_rule"),
        deleteProjectForRules: fixedBridgeMethod("delete_project_for_rules"),
        deleteProjectKeywordRule: fixedBridgeMethod("delete_project_keyword_rule"),
        exportEncryptedBackup: fixedBridgeMethod("export_encrypted_backup"),
        exportStatisticsCsv: fixedBridgeMethod("export_statistics_csv"),
        getFirstRunNotice: fixedBridgeMethod("get_first_run_notice"),
        getOverview: fixedBridgeMethod("get_overview"),
        getProjectRules: fixedBridgeMethod("get_project_rules"),
        getRefreshState: fixedBridgeMethod("get_refresh_state"),
        getSettingsPrivacyStatus: fixedBridgeMethod("get_settings_privacy_status"),
        getStatisticsExportSummary: fixedBridgeMethod("get_statistics_export_summary"),
        getStatus: fixedBridgeMethod("get_status"),
        getTimeline: fixedBridgeMethod("get_timeline"),
        getTimelineSessionActivitySummary: fixedBridgeMethod("get_timeline_session_activity_summary"),
        hideTimelineSession: fixedBridgeMethod("hide_timeline_session"),
        hideTimelineSessionActivity: fixedBridgeMethod("hide_timeline_session_activity"),
        importEncryptedBackup: fixedBridgeMethod("import_encrypted_backup"),
        listProjectsForTimeline: fixedBridgeMethod("list_projects_for_timeline"),
        mergeTimelineSession: fixedBridgeMethod("merge_timeline_session"),
        previewEncryptedBackupManifest: fixedBridgeMethod("preview_encrypted_backup_manifest"),
        previewProjectRuleImpact: fixedBridgeMethod("preview_project_rule_impact"),
        previewProjectRulesBatchImpact: fixedBridgeMethod("preview_project_rules_batch_impact"),
        saveTimelineSessionEdit: fixedBridgeMethod("save_timeline_session_edit"),
        setClipboardCaptureEnabled: fixedBridgeMethod("set_clipboard_capture_enabled"),
        setExcludedRulesEnabled: fixedBridgeMethod("set_excluded_rules_enabled"),
        setProjectEnabledForRules: fixedBridgeMethod("set_project_enabled_for_rules"),
        setProjectRuleEnabled: fixedBridgeMethod("set_project_rule_enabled"),
        setProjectRulesBatchEnabled: fixedBridgeMethod("set_project_rules_batch_enabled"),
        splitTimelineSession: fixedBridgeMethod("split_timeline_session"),
        togglePause: fixedBridgeMethod("toggle_pause"),
        updateProjectFolderRule: fixedBridgeMethod("update_project_folder_rule"),
        updateProjectForRules: fixedBridgeMethod("update_project_for_rules"),
        updateProjectKeywordRule: fixedBridgeMethod("update_project_keyword_rule")
    });

var runtimeState = null;

function frozenRuntime(value) {
    if (!value || typeof value !== "object") return null;
    var copy = Object.assign({}, value);
    if (copy.liveClock && typeof copy.liveClock === "object") {
        copy.liveClock = Object.freeze(Object.assign({}, copy.liveClock));
    }
    if (copy.currentActivity && typeof copy.currentActivity === "object") {
        copy.currentActivity = Object.freeze(Object.assign({}, copy.currentActivity));
    }
    return Object.freeze(copy);
}

function runtimeEnvelope(value) {
    if (!value || typeof value !== "object") return null;
    return value.runtime && typeof value.runtime === "object" ? value.runtime : value;
}

function normalizeRuntimeEnvelope(value, page, reportDate) {
    var envelope = runtimeEnvelope(value);
    if (!envelope || Number(envelope.schema_version || 0) !== 1) return null;
    var scopeDate = String(
        envelope.scope_report_date
        || reportDate
        || App.runtimeReportDateForPage(page || App.currentPage || "overview", reportDate)
        || ""
    );
    var liveDate = String(envelope.live_report_date || scopeDate || "");
    var liveClock = App.normalizeLiveClock
        ? App.normalizeLiveClock(envelope.live_clock || null)
        : (envelope.live_clock || null);
    if (scopeDate && liveDate && scopeDate !== liveDate) liveClock = null;
    return {
        schemaVersion: 1,
        surface: String(envelope.surface || page || App.currentPage || "overview"),
        page: String(page || App.currentPage || envelope.surface || "overview"),
        reportDate: scopeDate,
        liveReportDate: liveDate,
        liveClock: liveClock,
        displaySpanId: String(envelope.display_span_id || (liveClock && liveClock.display_span_id) || ""),
        stableLiveKeyHash: String(envelope.stable_live_key_hash || (liveClock && liveClock.stable_live_key_hash) || ""),
        liveRevision: String(envelope.live_revision || ""),
        structureRevision: String(envelope.structure_revision || ""),
        pageRevision: String(envelope.page_revision || ""),
        sampleId: String(envelope.sample_id || ""),
        currentActivityDisplaySpanId: String(envelope.current_activity_display_span_id || ""),
        currentResourceIdentityHash: String(envelope.current_resource_identity_hash || ""),
        currentActivity: envelope.current_activity || {}
    };
}

var liveRuntimeStore = Object.freeze({
    get: function () { return runtimeState; },
    acceptEnvelope: function (value, page, reportDate) {
        var next = normalizeRuntimeEnvelope(value, page, reportDate);
        if (!next) return null;
        var previous = runtimeState;
        if (previous && previous.liveClock && next.liveClock
            && App.sameLiveContinuity
            && App.sameLiveContinuity(previous.liveClock, next.liveClock)
            && App.rebaseIncomingClockWithoutRollback) {
            next.liveClock = App.rebaseIncomingClockWithoutRollback(
                previous.liveClock,
                next.liveClock,
                Date.now()
            );
        }
        runtimeState = frozenRuntime(next);
        return runtimeState;
    },
    reset: function () {
        runtimeState = null;
        return null;
    },
    setScope: function (page, reportDate) {
        var existing = runtimeState;
        if (!existing) return null;
        runtimeState = frozenRuntime(Object.assign({}, existing, {
            page: String(page || App.currentPage || "overview"),
            reportDate: App.runtimeReportDateForPage(
                page || App.currentPage || "overview",
                reportDate
            )
        }));
        return runtimeState;
    }
});
App.liveRuntimeStore = liveRuntimeStore;
Object.defineProperty(App, "liveRuntime", {
    configurable: false,
    enumerable: true,
    get: function () { return liveRuntimeStore.get(); }
});

function resetClientGeneration(reason) {
    if (App.requestCoordinator) App.requestCoordinator.bumpDataEpoch();
    App.timelineLoaded = false;
    App.statisticsLoaded = false;
    App.rulesLoaded = false;
    App.settingsLoaded = false;
    App.currentSessions = [];
    App.selectedProjectionInstanceKey = null;
    App.selectedProjectionRevision = null;
    App.editingSession = null;
    App.detailsOwner = null;
    App.timelineOwner = null;
    App.mutationOwner = null;
    App.mutationState = "idle";
    App.detailsInFlight = {};
    App.projectsCache = null;
    App.projectsLoading = false;
    App.projectsLoadPromise = null;
    App.lastTimelineData = null;
    App.lastProjectRulesData = null;
    App.lastSessionDetailsViewModel = null;
    App.lastSessionActivitySummaryViewModel = null;
    App.lastRefreshState = null;
    App.statisticsAcceptedPayload = null;
    App.rulesLoadPromise = null;
    App.activePageRefreshInFlight = false;
    App.activePageRefreshPromise = null;
    App.activePageRefreshPending = null;
    App.reconcileInFlight = false;
    App.liveClockContractRefreshRequested = false;
    App.liveClockContractViolation = null;
    App.firstRunNoticeLoaded = false;
    App.firstRunNoticeLoading = false;
    liveRuntimeStore.reset();
    App._monotonicRenderState = {};
    App.overviewRequestToken = (App.overviewRequestToken || 0) + 1;
    App.timelineRequestToken = (App.timelineRequestToken || 0) + 1;
    App.statisticsRequestToken = (App.statisticsRequestToken || 0) + 1;
    App.rulesRequestToken = (App.rulesRequestToken || 0) + 1;
    App.settingsRequestToken = (App.settingsRequestToken || 0) + 1;
    App.lastClientGenerationResetReason = String(reason || "data_generation_changed");
}
App.resetClientGeneration = resetClientGeneration;


    function invalidateProjectCatalog() {
        App.projectsCache = null;
        App.projectsLoading = false;
        App.projectsLoadPromise = null;
        if (typeof App.loadProjects === "function") {
            Promise.resolve().then(function () { return App.loadProjects(); });
        }
    }
    App.invalidateProjectCatalog = invalidateProjectCatalog;

    function refreshStatus() {
        var token = App.requestCoordinator.beginLatest("status", "current");
        return App.bridge.getStatus().then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return;
            var status = App.handleResult(result, function (msg) { throw new Error(msg); });
            App.showStatus(status);
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) App.showError("刷新失败");
        });
    }

    function refreshStatusFromRefreshState(state) {
        if (!state || !state.ok) return refreshStatus();
        App.showStatus({
            ok: true,
            status: state.collector_status,
            paused: !!state.paused,
            display: state.status_display || ""
        });
        return Promise.resolve();
    }
    App.refreshStatusFromRefreshState = refreshStatusFromRefreshState;

    function refreshOverview() {
        var token = App.requestCoordinator.beginLatest("overview", "today");
        return App.bridge.getOverview().then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return;
            var bundle = App.handleResult(result, function (msg) { throw new Error(msg); });
            if (!bundle || !App.acceptPagePayloadRuntime(bundle, "overview", bundle.date)) return;
            var overview = bundle.overview || {};
            overview.date = bundle.date || overview.date;
            overview.current_activity = bundle.current_activity || overview.current_activity;
            overview.live_clock = bundle.live_clock || overview.live_clock;
            overview.activity_display_model = bundle.activity_display_model || overview.activity_display_model;
            overview.display_span_id = bundle.display_span_id || overview.display_span_id;
            overview.sample_id = bundle.sample_id || overview.sample_id;
            overview.kpi_live_base = bundle.kpi_live_base || overview.kpi_live_base;
            overview.kpi_live_targets = bundle.kpi_live_targets || overview.kpi_live_targets;
            if (overview.today_total_seconds === undefined) overview.today_total_seconds = bundle.today_total_seconds || 0;
            if (overview.classified_seconds === undefined) overview.classified_seconds = bundle.classified_seconds || 0;
            if (overview.uncategorized_seconds === undefined) overview.uncategorized_seconds = bundle.uncategorized_seconds || 0;
            if (overview.current_activity_elapsed_seconds === undefined) overview.current_activity_elapsed_seconds = bundle.current_activity_elapsed_seconds || 0;
            App.showOverview(overview);
            App.showRecent({
                activities: bundle.activities || [],
                live_clock: bundle.live_clock || null,
                activity_display_model: bundle.activity_display_model || null,
                display_span_id: bundle.display_span_id || "",
                sample_id: bundle.sample_id || ""
            });
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) App.showError("刷新失败");
        });
    }
    App.refreshOverview = refreshOverview;

    function refreshTimeline() {
        return typeof App.refreshTimeline === "function" ? App.refreshTimeline() : Promise.resolve();
    }

    function _runCurrentPageRefresh(state, options) {
        App.activePageRefreshInFlight = true;
        var statePromise = state && state.ok
            ? Promise.resolve(state)
            : App.bridge.getRefreshState(
                App.currentPage === "timeline" ? App.timelineDate : null
            ).then(function (result) {
                return App.handleResult(result, function () { return null; });
            });
        return statePromise.then(function (acceptedState) {
            if (acceptedState && acceptedState.ok) App.acceptRefreshStateRuntime(acceptedState);
            var promises = [
                acceptedState && acceptedState.ok
                    ? refreshStatusFromRefreshState(acceptedState)
                    : refreshStatus()
            ];
            if (App.currentPage === "overview") {
                promises.push(refreshOverview());
            } else if (App.currentPage === "timeline" && App.timelineLoaded) {
                if (typeof App._timelineEditingActive !== "function" || !App._timelineEditingActive()) {
                    promises.push(refreshTimeline());
                } else {
                    refreshCurrentActivityFromState(acceptedState || App.lastRefreshState);
                }
            }
            return Promise.allSettled(promises);
        }).then(function (results) {
            App.lastFullRefreshAtEpochMs = Date.now();
            var anyError = results.some(function (item) { return item.status === "rejected"; });
            if (!anyError) App.clearError();
            return results;
        });
    }

    function refreshCurrentPageData(state, options) {
        if (App.activePageRefreshInFlight) {
            App.activePageRefreshPending = { state: state, options: options };
            return App.activePageRefreshPromise || Promise.resolve();
        }
        App.activePageRefreshPromise = _runCurrentPageRefresh(state, options).finally(function () {
            App.activePageRefreshInFlight = false;
            var pending = App.activePageRefreshPending;
            App.activePageRefreshPending = null;
            App.activePageRefreshPromise = null;
            if (pending) return refreshCurrentPageData(pending.state, pending.options);
        });
        return App.activePageRefreshPromise;
    }
    App.refreshCurrentPageData = refreshCurrentPageData;
    App.refreshAll = function () { return refreshCurrentPageData(); };

    function fullReconcileCollectionViews(reason) {
        if (App.reconcileInFlight) return App.activePageRefreshPromise || Promise.resolve();
        App.reconcileInFlight = true;
        return refreshCurrentPageData(null, { reason: reason || "reconcile" }).then(function () {
            App.lastReconcileAtEpochMs = Date.now();
        }).finally(function () {
            App.reconcileInFlight = false;
        });
    }
    App.fullReconcileCollectionViews = fullReconcileCollectionViews;

    function togglePause() {
        App.bridge.togglePause().then(function (result) {
            var status = App.handleResult(result, function (msg) { App.showError(msg); });
            App.showStatus(status);
        }).catch(function () {
            App.showError("切换暂停状态失败，请稍后重试。");
        });
    }
    App.togglePause = togglePause;

    function switchPage(pageId) {
        var navItems = document.querySelectorAll(".nav-item");
        var pages = document.querySelectorAll(".page");
        for (var i = 0; i < navItems.length; i++) navItems[i].classList.remove("active");
        for (var j = 0; j < pages.length; j++) pages[j].classList.remove("active");
        var navTarget = document.querySelector('.nav-item[data-page="' + pageId + '"]');
        var pageTarget = document.getElementById("page-" + pageId);
        if (navTarget) navTarget.classList.add("active");
        if (pageTarget) pageTarget.classList.add("active");
        App.currentPage = pageId;
        liveRuntimeStore.setScope(pageId, pageId === "timeline" ? App.timelineDate : null);
        if (pageId === "timeline" && !App.timelineLoaded && !App.timelineLoading) {
            App.loadTimelineReport(App.timelineDate, { showLoading: true });
        }
        if (pageId === "statistics" && !App.statisticsLoaded) {
            App.initStatisticsDefaults();
            App.loadStatisticsExportSummary();
        }
        if (pageId === "rules" && !App.rulesLoaded) App.loadProjectRules();
        if (pageId === "settings" && !App.settingsLoaded && !App.settingsLoading) {
            App.loadSettingsPrivacyStatus();
        }
        if (pageId === "overview" || (pageId === "timeline" && App.timelineLoaded)) {
            refreshCurrentPageData();
        }
    }
    App.switchPage = switchPage;

    function initNav() {
        var navItems = document.querySelectorAll(".nav-item");
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].addEventListener("click", function () {
                switchPage(this.getAttribute("data-page"));
            });
        }
    }
    App.initNav = initNav;

    function bind(id, event, handler) {
        var element = document.getElementById(id);
        if (element) element.addEventListener(event, handler);
    }

    function initButtons() {
        bind("toggle-pause-btn", "click", togglePause);
        bind("refresh-btn", "click", App.refreshAll);
        bind("timeline-prev-btn", "click", App.goPrevDay);
        bind("timeline-next-btn", "click", App.goNextDay);
        bind("timeline-today-btn", "click", App.goToday);
        bind("timeline-date-input", "change", function (event) {
            App.loadTimelineReport(event.target.value || null, { resetSelection: true, showLoading: true });
        });
        bind("edit-save-btn", "click", App.saveEdit);
        bind("edit-cancel-btn", "click", App.cancelEdit);
        [
            ["timeline-hide-session", "hide"],
            ["timeline-merge-previous", "merge", "previous"],
            ["timeline-merge-next", "merge", "next"],
            ["timeline-split-session", "split"],
            ["timeline-copy-session", "copy"]
        ].forEach(function (action) {
            bind(action[0], "click", function () {
                App.runTimelineSessionOperation(action[1], action[2] ? { direction: action[2] } : undefined);
            });
        });
        bind("edit-note-text", "input", App.updateNoteCount);
        bind("statistics-load-btn", "click", App.loadStatisticsExportSummary);
        bind("statistics-today-btn", "click", function () { App.applyStatisticsQuickRange("today"); });
        bind("statistics-7d-btn", "click", function () { App.applyStatisticsQuickRange("7d"); });
        bind("statistics-month-btn", "click", function () { App.applyStatisticsQuickRange("month"); });
        bind("stats-export-action-btn", "click", App.exportStatisticsCsv);
        bind("settings-clipboard-toggle", "change", App.handleCaptureToggleChange);
        bind("settings-backup-export-btn", "click", App.exportEncryptedBackup);
        bind("settings-backup-manifest-btn", "click", App.previewEncryptedBackupManifest);
        bind("settings-backup-import-btn", "click", App.importEncryptedBackup);
        bind("settings-clear-local-data-btn", "click", App.clearAllLocalData);
        bind("settings-clear-all-btn", "click", App.clearAllLocalData);
        if (App.initRulesPanelEvents) App.initRulesPanelEvents();
        bind("first-run-notice-accept-btn", "click", App.acceptFirstRunNotice);
        bind("first-run-notice-close-btn", "click", function () {
            if (App.firstRunNoticeViewingFromSettings) App.hideFirstRunNotice();
        });
        bind("settings-privacy-notice-btn", "click", App.openPrivacyNoticeFromSettings);
    }
    App.initButtons = initButtons;

    function updateCurrentActivityCacheFromRefreshState(state) {
        if (!state) return;
        if (App.currentPage === "overview") {
            if (!App.lastOverviewSnapshot) App.lastOverviewSnapshot = {};
            App.lastOverviewSnapshot.current_activity = state.current_activity || {};
        } else if (App.currentPage === "timeline") {
            if (!App.lastTimelineData) App.lastTimelineData = {};
            App.lastTimelineData.current_activity = state.current_activity || {};
        }
    }

    function currentActivityRenderIdentity(state) {
        var current = (state && state.current_activity) || {};
        return [
            current.active === true ? "active" : "inactive",
            current.current_duration_live === true ? "live" : "static",
            String(current.live_state || ""),
            String(current.display_span_id || ""),
            String(current.current_activity_display_span_id || ""),
            String(current.current_resource_identity_hash || ""),
            String(current.stable_live_key_hash || "")
        ].join("|");
    }

    function refreshCurrentActivityFromState(state, options) {
        if (!state || !state.current_activity) return;
        var runtime = liveRuntimeStore.get();
        if (!runtime || runtime.liveRevision !== String(state.live_revision || "")) return;
        options = options || {};
        updateCurrentActivityCacheFromRefreshState(state);
        if (options.forceRender !== true) return;
        var element = App.currentPage === "overview"
            ? document.getElementById("current-activity")
            : App.currentPage === "timeline"
            ? document.getElementById("timeline-current")
            : null;
        if (element) App.renderCurrentActivityElement(element, state.current_activity || {}, App.currentPage);
    }
    App.refreshCurrentActivityFromState = refreshCurrentActivityFromState;
    App.refreshTimelineCurrentActivityFromState = function (state) {
        if (App.currentPage !== "timeline") return;
        refreshCurrentActivityFromState(state, { forceRender: true });
    };

    function runRevisionCheck() {
        if (App.refreshCheckInFlight) return;
        App.refreshCheckInFlight = true;
        var token = App.requestCoordinator.beginLatest("heartbeat", App.currentPage + "|" + (App.timelineDate || ""));
        App.bridge.getRefreshState(App.currentPage === "timeline" ? App.timelineDate : null).then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return;
            var state = App.handleResult(result, function () { return null; });
            if (!state) return;
            var previousState = App.lastRefreshState;
            var prevPageRevision = previousState && previousState.page_revision;
            var isFirstCheck = prevPageRevision === null || prevPageRevision === undefined;
            var liveStateChanged = isFirstCheck || (previousState && previousState.live_revision) !== state.live_revision;
            var pageStructureChanged = isFirstCheck || prevPageRevision !== state.page_revision;
            var currentActivityIdentityChanged = currentActivityRenderIdentity(previousState) !== currentActivityRenderIdentity(state);
            var renderCurrent = liveStateChanged || pageStructureChanged || currentActivityIdentityChanged || App.liveClockContractRefreshRequested;
            if (!App.acceptRefreshStateRuntime(state)) return;
            refreshCurrentActivityFromState(state, { forceRender: renderCurrent });
            refreshStatusFromRefreshState(state);
            var triggered = false;
            if (pageStructureChanged || App.liveClockContractRefreshRequested) {
                triggered = true;
                App.liveClockContractRefreshRequested = false;
                refreshCurrentPageData(state);
            }
            var now = Date.now();
            if (!triggered && !App.reconcileInFlight
                && now - App.lastReconcileAtEpochMs >= App.RECONCILE_INTERVAL_MS) {
                fullReconcileCollectionViews("heartbeat-lowfreq");
            }
        }).finally(function () {
            if (App.requestCoordinator.isCurrent(token)) App.refreshCheckInFlight = false;
        });
    }
    App.runRevisionCheck = runRevisionCheck;

    function startHeartbeat() {
        if (App.heartbeatTimer !== null) clearInterval(App.heartbeatTimer);
        App.heartbeatTimer = setInterval(function () {
            try { if (App.applyLocalTicker) App.applyLocalTicker(); } catch (error) {}
            try { runRevisionCheck(); } catch (error) {}
        }, App.HEARTBEAT_INTERVAL_MS);
    }
    App.startHeartbeat = startHeartbeat;

    function init() {
        initNav();
        initButtons();
        App.loadFirstRunNotice().then(function (noticeConfirmed) {
            if (!noticeConfirmed) return;
            var preload = typeof App.loadProjects === "function" ? App.loadProjects() : Promise.resolve();
            return preload.then(function () {
                return App.bridge.getRefreshState(
                    App.currentPage === "timeline" ? App.timelineDate : null
                );
            }).then(function (result) {
                var state = App.handleResult(result, function () { return null; });
                if (state) App.acceptRefreshStateRuntime(state);
                return refreshCurrentPageData(state);
            }).then(function () {
                App.lastReconcileAtEpochMs = Date.now();
                startHeartbeat();
            }, startHeartbeat);
        });
    }
    App.init = init;

    var initStarted = false;
    function isBridgeReady() { return !!(window.pywebview && window.pywebview.api); }
    function bootstrap() {
        if (initStarted) return;
        initStarted = true;
        init();
    }
    function onBridgeReady() {
        window.removeEventListener("pywebviewready", onBridgeReady);
        bootstrap();
    }
    function onDomReady() {
        if (isBridgeReady()) bootstrap();
        else window.addEventListener("pywebviewready", onBridgeReady);
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", onDomReady);
    else onDomReady();
})();
