// WorkTrace WebView frontend — initialization and refresh coordination.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function resetClientGeneration() {
        if (App.requestCoordinator) App.requestCoordinator.bumpDataEpoch();
        App.timelineLoaded = false;
        App.statisticsLoaded = false;
        App.rulesLoaded = false;
        App.settingsLoaded = false;
        App.currentSessions = [];
        App.selectedProjectionInstanceKey = null;
        App.selectedProjectionRevision = null;
        App.editingSession = null;
        App.lastTimelineData = null;
        App.lastProjectRulesData = null;
        App.lastSessionDetailsViewModel = null;
        App.lastSessionActivitySummaryViewModel = null;
        App.lastRefreshState = null;
        App.liveRuntime = null;
        App._monotonicRenderState = {};
        App.overviewRequestToken = (App.overviewRequestToken || 0) + 1;
        App.timelineRequestToken = (App.timelineRequestToken || 0) + 1;
        App.statisticsRequestToken = (App.statisticsRequestToken || 0) + 1;
        App.rulesRequestToken = (App.rulesRequestToken || 0) + 1;
        App.settingsRequestToken = (App.settingsRequestToken || 0) + 1;
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

    // One bridge wrapper owns cross-cutting frontend generation and project
    // catalog invalidation. Individual page modules remain focused on rendering.
    var rawCallBridge = App.callBridge;
    if (typeof rawCallBridge === "function" && !App._hardeningBridgeInstalled) {
        App._hardeningBridgeInstalled = true;
        App.callBridge = function (method) {
            var args = Array.prototype.slice.call(arguments, 1);
            if (method === "save_timeline_session_edit"
                && App.editingSession
                && App.editingSession.can_edit_duration === false) {
                args[5] = null;
            }
            var epoch = App.dataEpoch || 0;
            return rawCallBridge.apply(App, [method].concat(args)).then(function (result) {
                if ((method === "import_encrypted_backup" || method === "clear_all_local_data")
                    && result && result.ok) {
                    resetClientGeneration();
                }
                if (result && result.ok && (
                    method.indexOf("project") >= 0
                    || method.indexOf("rule") >= 0
                ) && method !== "get_project_rules"
                    && method !== "list_projects_for_timeline") {
                    invalidateProjectCatalog();
                }
                // A response from a replaced database generation must never
                // update a page, except for the replacement operation itself.
                if (epoch !== (App.dataEpoch || 0)
                    && method !== "import_encrypted_backup"
                    && method !== "clear_all_local_data") {
                    return { ok: false, stale_generation: true, error: "数据已更新" };
                }
                return result;
            });
        };
    }

    function enforceEditCapabilities() {
        var session = App.editingSession;
        if (!session) return;
        var duration = document.getElementById("edit-duration-input");
        var durationStatus = document.getElementById("edit-duration-status");
        if (duration && session.can_edit_duration === false) {
            duration.disabled = true;
            if (durationStatus) durationStatus.textContent = "进行中活动暂不支持修改时长";
        }
    }

    function installEditCapabilityObserver() {
        var panel = document.getElementById("timeline-edit-panel");
        if (!panel || typeof MutationObserver !== "function") return;
        new MutationObserver(enforceEditCapabilities).observe(panel, {
            attributes: true,
            childList: true,
            subtree: true
        });
    }

    function refreshStatus() {
        var token = App.requestCoordinator.beginLatest("status", "current");
        return App.callBridge("get_status").then(function (result) {
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
        return App.callBridge("get_overview").then(function (result) {
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
        return typeof App.refreshTimeline === "function"
            ? App.refreshTimeline()
            : Promise.resolve();
    }

    function _runCurrentPageRefresh(state, options) {
        App.activePageRefreshInFlight = true;
        var statePromise = state && state.ok
            ? Promise.resolve(state)
            : App.callBridge(
                "get_refresh_state",
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
    function refreshAll() { return refreshCurrentPageData(); }
    App.refreshAll = refreshAll;

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
        App.callBridge("toggle_pause").then(function (result) {
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
        if (typeof App.setLiveRuntimeScope === "function") {
            App.setLiveRuntimeScope(pageId, pageId === "timeline" ? App.timelineDate : null);
        }
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
            ["timeline-hide-session", "hide_timeline_session"],
            ["timeline-merge-previous", "merge_timeline_session", "previous"],
            ["timeline-merge-next", "merge_timeline_session", "next"],
            ["timeline-split-session", "split_timeline_session"],
            ["timeline-copy-session", "copy_timeline_session"]
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
        if (App.initRulesPanelEvents) App.initRulesPanelEvents();
        bind("first-run-notice-accept-btn", "click", App.acceptFirstRunNotice);
        bind("first-run-notice-close-btn", "click", function () {
            if (App.firstRunNoticeViewingFromSettings) App.hideFirstRunNotice();
        });
        bind("settings-privacy-notice-btn", "click", App.openPrivacyNoticeFromSettings);
        installEditCapabilityObserver();
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
        if (!App.liveRuntime || App.liveRuntime.liveRevision !== String(state.live_revision || "")) return;
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
        App.callBridge("get_refresh_state", App.currentPage === "timeline" ? App.timelineDate : null).then(function (result) {
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
            var preload = typeof App.loadProjects === "function"
                ? App.loadProjects()
                : Promise.resolve();
            return preload.then(function () {
                return App.callBridge("get_refresh_state", App.currentPage === "timeline" ? App.timelineDate : null);
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
