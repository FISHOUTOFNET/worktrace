// WorkTrace WebView frontend — init module.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};


    function refreshStatus() {
        return App.callBridge("get_status").then(function (result) {
            var status = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            App.showStatus(status);
        }).catch(function () {
            App.showError("刷新失败");
        });
    }

    // directly from a ``get_refresh_state`` payload without calling
    function refreshStatusFromRefreshState(state) {
        if (!state || !state.ok) {
            return refreshStatus();
        }
        var status = {
            ok: true,
            status: state.collector_status,
            paused: !!state.paused,
            display: state.status_display || ""
        };
        App.showStatus(status);
        return Promise.resolve();
    }
    App.refreshStatusFromRefreshState = refreshStatusFromRefreshState;

    // refreshOverview pulls the unified Overview ViewModel (KPIs + current
    // activity + recent + live_clock + sample_id) from one backend sample.
    function refreshOverview() {
        var token = ++App.overviewRequestToken;
        App.recentRequestToken = token;  // single token for the bundle
        return App.callBridge("get_overview").then(function (result) {
            if (token !== App.overviewRequestToken) return;  // stale
            var bundle = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            if (!bundle) return;
            if (!App.acceptPagePayloadRuntime(bundle, "overview", bundle.date)) return;
            var overview = bundle.overview || {};
            // Augment the overview sub-payload with the bundle-level
            overview.date = bundle.date || overview.date;
            overview.current_activity = bundle.current_activity || overview.current_activity;
            overview.live_clock = bundle.live_clock || overview.live_clock;
            overview.activity_display_model = bundle.activity_display_model || overview.activity_display_model;
            overview.display_span_id = bundle.display_span_id || overview.display_span_id;
            overview.sample_id = bundle.sample_id || overview.sample_id;
            overview.kpi_live_base = bundle.kpi_live_base || overview.kpi_live_base;
            overview.kpi_live_targets = bundle.kpi_live_targets || overview.kpi_live_targets;
            if (overview.today_total_seconds === undefined) {
                overview.today_total_seconds = bundle.today_total_seconds || 0;
            }
            if (overview.classified_seconds === undefined) {
                overview.classified_seconds = bundle.classified_seconds || 0;
            }
            if (overview.uncategorized_seconds === undefined) {
                overview.uncategorized_seconds = bundle.uncategorized_seconds || 0;
            }
            if (overview.current_activity_elapsed_seconds === undefined) {
                overview.current_activity_elapsed_seconds = bundle.current_activity_elapsed_seconds || 0;
            }
            App.showOverview(overview);
            App.showRecent({
                activities: bundle.activities || [],
                live_clock: bundle.live_clock || null,
                activity_display_model: bundle.activity_display_model || null,
                display_span_id: bundle.display_span_id || "",
                sample_id: bundle.sample_id || ""
            });
        }).catch(function () {
            if (token !== App.overviewRequestToken) return;  // stale
            App.showError("刷新失败");
        });
    }
    App.refreshOverview = refreshOverview;

    function refreshTimeline() {
        if (typeof App.refreshTimeline === "function") {
            return App.refreshTimeline();
        }
        return Promise.resolve();
    }

    function refreshCurrentPageData(state, options) {
        if (App.activePageRefreshInFlight) {
            return Promise.resolve();
        }
        App.activePageRefreshInFlight = true;
        var statePromise = state && state.ok
            ? Promise.resolve(state)
            : App.callBridge("get_refresh_state").then(function (result) {
                return App.handleResult(result, function () { return null; });
            });
        return statePromise.then(function (acceptedState) {
            if (acceptedState && acceptedState.ok) {
                App.acceptRefreshStateRuntime(acceptedState);
            }
            var promises = [
                acceptedState && acceptedState.ok ? refreshStatusFromRefreshState(acceptedState) : refreshStatus()
            ];
            if (App.currentPage === "overview") {
                promises.push(refreshOverview());
            } else if (App.currentPage === "timeline" && App.timelineLoaded) {
                // revision-change refresh and manual refresh do not overwrite
                if (typeof App._timelineEditingActive !== "function" || !App._timelineEditingActive()) {
                    promises.push(refreshTimeline());
                } else {
                    refreshCurrentActivityFromState(acceptedState || App.lastRefreshState);
                }
            }
            return Promise.allSettled(promises);
        }).then(function (results) {
            App.activePageRefreshInFlight = false;
            App.lastFullRefreshAtEpochMs = Date.now();
            var anyError = false;
            for (var i = 0; i < results.length; i++) {
                if (results[i].status === "rejected") {
                    anyError = true;
                    break;
                }
            }
            if (!anyError) {
                App.clearError();
            }
        }).catch(function (err) {
            App.activePageRefreshInFlight = false;
            throw err;
        });
    }

    // ``refreshAll`` is the manual refresh-button entry point. It delegates
    function refreshAll() {
        return refreshCurrentPageData();
    }
    App.refreshAll = refreshAll;
    App.refreshCurrentPageData = refreshCurrentPageData;

    // Low-frequency collection reconciliation: re-pulls collector status +
    // the CURRENT page's data. Section 五 fix: do NOT call
    // ``refreshOverview()`` when the user is on a non-Overview page (would
    // register an Overview-scope clock and overwrite the current page's).
    function fullReconcileCollectionViews(reason) {
        if (App.reconcileInFlight) return Promise.resolve();
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
            var status = App.handleResult(result, function (msg) {
                App.showError(msg);
            });
            App.showStatus(status);
        }).catch(function () {
            App.showError("切换暂停状态失败，请稍后重试。");
        });
    }
    App.togglePause = togglePause;


    function switchPage(pageId) {
        var navItems = document.querySelectorAll(".nav-item");
        var pages = document.querySelectorAll(".page");
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].classList.remove("active");
        }
        for (var j = 0; j < pages.length; j++) {
            pages[j].classList.remove("active");
        }
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
        // No write / file / dialog action is triggered.
        if (pageId === "statistics" && !App.statisticsLoaded && !App.statisticsLoading) {
            App.initStatisticsDefaults();
            App.loadStatisticsExportSummary();
        }
        // page for the first time. No Project Rules write events are bound
        if (pageId === "rules" && !App.rulesLoaded && !App.rulesLoading) {
            App.loadProjectRules();
        }
        // Lazy-load Settings / Privacy read-only status when navigating to
        if (pageId === "settings" && !App.settingsLoaded && !App.settingsLoading) {
            App.loadSettingsPrivacyStatus();
        }

        // the auto-refresh path. Must run AFTER lazy-load so timeline's
        if (pageId === "overview") {
            refreshCurrentPageData();
        } else if (pageId === "timeline" && App.timelineLoaded) {
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

    function initButtons() {
        document.getElementById("toggle-pause-btn").addEventListener("click", togglePause);
        document.getElementById("refresh-btn").addEventListener("click", refreshAll);
        document.getElementById("timeline-prev-btn").addEventListener("click", App.goPrevDay);
        document.getElementById("timeline-next-btn").addEventListener("click", App.goNextDay);
        document.getElementById("timeline-today-btn").addEventListener("click", App.goToday);
        // a stale detail response cannot backfill the new date's panel.
        var dateInput = document.getElementById("timeline-date-input");
        if (dateInput) {
            dateInput.addEventListener("change", function (e) {
                App.loadTimelineReport(e.target.value || null, { resetSelection: true, showLoading: true });
            });
        }
        document.getElementById("edit-save-btn").addEventListener("click", App.saveEdit);
        document.getElementById("edit-cancel-btn").addEventListener("click", App.cancelEdit);
        var sessionActions = [
            ["timeline-hide-session", "hide_timeline_session"],
            ["timeline-merge-previous", "merge_timeline_session", "previous"],
            ["timeline-merge-next", "merge_timeline_session", "next"],
            ["timeline-split-session", "split_timeline_session"],
            ["timeline-copy-session", "copy_timeline_session"]
        ];
        for (var actionIndex = 0; actionIndex < sessionActions.length; actionIndex++) {
            (function (action) {
                var button = document.getElementById(action[0]);
                if (!button) return;
                button.addEventListener("click", function () {
                    if (action[2]) {
                        var date = App.currentTimelineReportDate();
                        var key = App.selectedProjectionInstanceKey;
                        if (!date || !key) return;
                        App.callBridge(action[1], date, key, action[2]).then(function (result) {
                            var data = App.handleResult(result, function () {});
                            if (data) App.refreshTimeline();
                        });
                    } else {
                        App.runTimelineSessionOperation(action[1]);
                    }
                });
            })(sessionActions[actionIndex]);
        }
        var noteEl = document.getElementById("edit-note-text");
        if (noteEl) {
            noteEl.addEventListener("input", App.updateNoteCount);
        }
        // read-only bridge call; the quick-range buttons only update the
        var statsLoadBtn = document.getElementById("statistics-load-btn");
        if (statsLoadBtn) {
            statsLoadBtn.addEventListener("click", App.loadStatisticsExportSummary);
        }
        var statsTodayBtn = document.getElementById("statistics-today-btn");
        if (statsTodayBtn) {
            statsTodayBtn.addEventListener("click", function () {
                App.applyStatisticsQuickRange("today");
            });
        }
        var stats7dBtn = document.getElementById("statistics-7d-btn");
        if (stats7dBtn) {
            stats7dBtn.addEventListener("click", function () {
                App.applyStatisticsQuickRange("7d");
            });
        }
        var statsMonthBtn = document.getElementById("statistics-month-btn");
        if (statsMonthBtn) {
            statsMonthBtn.addEventListener("click", function () {
                App.applyStatisticsQuickRange("month");
            });
        }
        var statsExportBtn = document.getElementById("stats-export-action-btn");
        if (statsExportBtn) {
            statsExportBtn.addEventListener("click", App.exportStatisticsCsv);
        }
        // Capture toggle write handler. The toggle writes the
        var captureToggle = document.getElementById("settings-clipboard-toggle");
        if (captureToggle) {
            captureToggle.addEventListener("change", App.handleCaptureToggleChange);
        }
        // Encrypted backup write and manifest preview handlers.
        var backupExportBtn = document.getElementById("settings-backup-export-btn");
        if (backupExportBtn) {
            backupExportBtn.addEventListener("click", App.exportEncryptedBackup);
        }
        var backupManifestBtn = document.getElementById("settings-backup-manifest-btn");
        if (backupManifestBtn) {
            backupManifestBtn.addEventListener("click", App.previewEncryptedBackupManifest);
        }
        var backupImportBtn = document.getElementById("settings-backup-import-btn");
        if (backupImportBtn) {
            backupImportBtn.addEventListener("click", App.importEncryptedBackup);
        }
        var clearAllBtn = document.getElementById("settings-clear-local-data-btn");
        if (clearAllBtn) {
            clearAllBtn.addEventListener("click", App.clearAllLocalData);
        }
        if (App.initRulesPanelEvents) {
            App.initRulesPanelEvents();
        }
        // First-run privacy notice handlers. The accept button is only
        var firstRunAcceptBtn = document.getElementById("first-run-notice-accept-btn");
        if (firstRunAcceptBtn) {
            firstRunAcceptBtn.addEventListener("click", App.acceptFirstRunNotice);
        }
        var firstRunCloseBtn = document.getElementById("first-run-notice-close-btn");
        if (firstRunCloseBtn) {
            // Wrap hideFirstRunNotice so the close button only fires in
            firstRunCloseBtn.addEventListener("click", function () {
                if (App.firstRunNoticeViewingFromSettings) {
                    App.hideFirstRunNotice();
                }
            });
        }
        var settingsPrivacyNoticeBtn = document.getElementById("settings-privacy-notice-btn");
        if (settingsPrivacyNoticeBtn) {
            settingsPrivacyNoticeBtn.addEventListener("click", App.openPrivacyNoticeFromSettings);
        }
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
        if (!App.liveRuntime || App.liveRuntime.refreshRevision !== String(state.refresh_revision || "")) return;
        options = options || {};
        updateCurrentActivityCacheFromRefreshState(state);
        if (options.forceRender !== true) return;
        if (App.currentPage === "overview") {
            App.renderCurrentActivityElement(
                document.getElementById("current-activity"),
                state.current_activity || {},
                "overview"
            );
        } else if (App.currentPage === "timeline") {
            App.renderCurrentActivityElement(
                document.getElementById("timeline-current"),
                state.current_activity || {},
                "timeline"
            );
        }
    }
    App.refreshCurrentActivityFromState = refreshCurrentActivityFromState;

    function refreshTimelineCurrentActivityFromState(state) {
        if (App.currentPage !== "timeline" || !state || !state.current_activity) return;
        if (!App.liveRuntime || App.liveRuntime.refreshRevision !== String(state.refresh_revision || "")) return;
        updateCurrentActivityCacheFromRefreshState(state);
        App.renderCurrentActivityElement(
            document.getElementById("timeline-current"),
            state.current_activity || {},
            "timeline"
        );
    }
    App.refreshTimelineCurrentActivityFromState = refreshTimelineCurrentActivityFromState;

    // The heartbeat never writes the DB, never starts / stops the
    function runRevisionCheck() {
        if (App.refreshCheckInFlight) return;
        App.refreshCheckInFlight = true;
        App.callBridge("get_refresh_state").then(function (result) {
            var state = App.handleResult(result, function () {
                return null;
            });
            if (!state) return;
            var previousState = App.lastRefreshState;
            var prevRevision = previousState && previousState.refresh_revision;
            var newRevision = state.refresh_revision;
            var isFirstCheck = prevRevision === null || prevRevision === undefined;
            var revisionChanged = isFirstCheck || prevRevision !== newRevision;
            var prevLiveRevision = previousState && (previousState.live_clock_revision || previousState.live_state_revision || previousState.refresh_revision);
            var newLiveRevision = state.live_clock_revision || state.live_state_revision || state.refresh_revision;
            var prevDisplayProjectionRevision = previousState && (previousState.display_projection_revision || previousState.refresh_revision);
            var newDisplayProjectionRevision = state.display_projection_revision || state.refresh_revision;
            var prevPageRevision = previousState && (previousState.page_structure_revision || previousState.refresh_revision);
            var newPageRevision = state.page_structure_revision || state.refresh_revision;
            var liveStateChanged = isFirstCheck || prevLiveRevision !== newLiveRevision;
            var displayProjectionChanged = isFirstCheck || prevDisplayProjectionRevision !== newDisplayProjectionRevision;
            var pageStructureChanged = isFirstCheck || prevPageRevision !== newPageRevision;
            var currentActivityIdentityChanged = currentActivityRenderIdentity(previousState) !== currentActivityRenderIdentity(state);
            var renderCurrentActivity = revisionChanged
                || liveStateChanged
                || displayProjectionChanged
                || pageStructureChanged
                || currentActivityIdentityChanged
                || App.liveClockContractRefreshRequested;
            var accepted = App.acceptRefreshStateRuntime(state);
            if (!accepted) return;
            refreshCurrentActivityFromState(state, { forceRender: renderCurrentActivity });
            refreshStatusFromRefreshState(state);
            var triggeredHeavyRefresh = false;
            // the refresh_state payload (no get_status call). When revision
            if (liveStateChanged || displayProjectionChanged || pageStructureChanged || App.liveClockContractRefreshRequested) {
                triggeredHeavyRefresh = true;
                App.liveClockContractRefreshRequested = false;
                refreshCurrentPageData(state);
            }
            // and could race the in-flight refresh.
            var now = Date.now();
            if (!triggeredHeavyRefresh
                && !App.activePageRefreshInFlight
                && !App.reconcileInFlight
                && now - App.lastReconcileAtEpochMs >= App.RECONCILE_INTERVAL_MS) {
                fullReconcileCollectionViews("heartbeat-lowfreq");
            }
        }).catch(function () {
        }).then(function () {
            App.refreshCheckInFlight = false;
        });
    }
    App.runRevisionCheck = runRevisionCheck;

    function startHeartbeat() {
        if (App.heartbeatTimer !== null) clearInterval(App.heartbeatTimer);
        App.heartbeatTimer = setInterval(function () {
            try {
                if (typeof App.applyLocalTicker === "function") {
                    App.applyLocalTicker();
                }
            } catch (e) {
            }
            // Lightweight revision check (with in-flight guard).
            try {
                runRevisionCheck();
            } catch (e) {
            }
        }, App.HEARTBEAT_INTERVAL_MS);
    }
    App.startHeartbeat = startHeartbeat;

    function init() {
        initNav();
        initButtons();
        // Load the first-run privacy notice BEFORE refreshing the main UI
        App.loadFirstRunNotice().then(function (noticeConfirmed) {
            if (!noticeConfirmed) return;
            App.callBridge("get_refresh_state").then(function (result) {
                var state = App.handleResult(result, function () { return null; });
                if (state) {
                    App.acceptRefreshStateRuntime(state);
                }
                return refreshCurrentPageData(state);
            }).then(function () {
                App.lastReconcileAtEpochMs = Date.now();
                startHeartbeat();
            }, function () {
                startHeartbeat();
            });
        });
    }
    App.init = init;

    // Gate ``init()`` on BOTH DOMContentLoaded AND the pywebview bridge
    var initStarted = false;

    function isBridgeReady() {
        return !!(window.pywebview && window.pywebview.api);
    }

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
        if (isBridgeReady()) {
            bootstrap();
        } else {
            window.addEventListener("pywebviewready", onBridgeReady);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", onDomReady);
    } else {
        onDomReady();
    }

})();
