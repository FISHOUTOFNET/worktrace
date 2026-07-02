// WorkTrace WebView frontend — init module.
// Refresh orchestration, navigation, button binding, and DOMContentLoaded wiring.
// This module must be loaded LAST so all cross-file App.* references resolve.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Refresh orchestration ------------------------------------------
    // A single 1-second heartbeat (``startHeartbeat``) drives refresh. Each
    // tick first applies the local ticker (re-renders already-fetched
    // durations with a wall-clock delta), then runs a lightweight
    // ``get_refresh_state`` revision check. Heavy interfaces are only called
    // when the structural revision changes, and only for the data needed by
    // the current page. Rules / Settings / Statistics are NOT included in
    // background auto-refresh; they keep their own page-level load / refresh
    // buttons.
    //
    // ``refreshCurrentPageData`` is the unified heavy-refresh entry point
    // used by the manual refresh button, the heartbeat revision-change
    // branch, and page-switch immediate refresh. It refreshes status (the
    // sidebar is always visible) plus the current page's live data, and is
    // guarded by ``activePageRefreshInFlight`` so overlapping heavy
    // refreshes are skipped.

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

    // ``refreshStatusFromRefreshState`` updates the sidebar status display
    // directly from a ``get_refresh_state`` payload without calling
    // ``get_status`` again. This is the preferred path inside the heartbeat
    // because ``get_refresh_state`` already returns ``collector_status`` /
    // ``paused`` / ``status_display``. Falls back to refreshStatus when
    // state is null or missing required fields so the sidebar always
    // reflects the latest backend state.
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

    function refreshOverview() {
        // Request token prevents stale Overview responses from overwriting
        // newer data when the user switches pages or a revision-change
        // refresh races a manual refresh. Only the response whose token
        // equals the current value is applied to the DOM.
        var token = ++App.overviewRequestToken;
        return App.callBridge("get_overview").then(function (result) {
            if (token !== App.overviewRequestToken) return;  // stale
            var overview = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            App.showOverview(overview);
        }).catch(function () {
            if (token !== App.overviewRequestToken) return;  // stale
            App.showError("刷新失败");
        });
    }

    function refreshRecent() {
        // Request token prevents stale Recent responses from overwriting
        // newer data. Same rationale as ``refreshOverview``.
        var token = ++App.recentRequestToken;
        return App.callBridge("get_recent_activities").then(function (result) {
            if (token !== App.recentRequestToken) return;  // stale
            var recent = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            App.showRecent(recent);
        }).catch(function () {
            if (token !== App.recentRequestToken) return;  // stale
            App.showError("刷新失败");
        });
    }

    // Single-sample Overview bundle. One backend call reads the snapshot
    // once and returns ``live_projection`` + ``overview`` KPI +
    // ``current_activity`` + ``activities`` + ``sample_id`` from the same
    // sample, so overview, current activity, and recent rows do not drift.
    //
    // The bundle response is split into the shapes ``showOverview`` and
    // ``showRecent`` expect: the overview sub-payload is augmented with
    // ``live_projection`` / ``live_display`` / ``current_activity`` so the
    // ticker (which prefers ``live_projection``) reads from the single
    // source of truth; the recent payload is wrapped as
    // ``{activities, live_projection, live_display}`` so ``showRecent``
    // and the recent-branch ticker see the same sample.
    function refreshOverviewBundle() {
        var token = ++App.overviewRequestToken;
        App.recentRequestToken = token;  // single token for the bundle
        return App.callBridge("get_overview_live_bundle").then(function (result) {
            if (token !== App.overviewRequestToken) return;  // stale
            var bundle = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            if (!bundle) return;
            var overview = bundle.overview || {};
            // Augment the overview sub-payload with the bundle-level
            // fields the ticker / showOverview read so a single sample
            // drives KPIs, current activity, and the recent live row.
            overview.date = bundle.date || overview.date;
            overview.current_activity = bundle.current_activity || overview.current_activity;
            overview.live_projection = bundle.live_projection || overview.live_projection;
            overview.live_display = bundle.live_display || bundle.live_projection || overview.live_display;
            overview.sample_id = bundle.sample_id || overview.sample_id;
            // KPI fields may live at the bundle root (get_overview
            // shape) — copy them in when the overview sub-payload does
            // not already carry them.
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
            // Build the recent payload shape from the bundle's activities +
            // live_projection so showRecent and the recent ticker branch
            // use the same single sample.
            App.showRecent({
                activities: bundle.activities || [],
                live_projection: bundle.live_projection || null,
                live_display: bundle.live_display || bundle.current_activity || null,
                sample_id: bundle.sample_id || ""
            });
        }).catch(function () {
            if (token !== App.overviewRequestToken) return;  // stale
            App.showError("刷新失败");
        });
    }
    App.refreshOverviewBundle = refreshOverviewBundle;

    function refreshTimeline() {
        return new Promise(function (resolve, reject) {
            var dateEl = document.getElementById("timeline-date-input");
            var date = App.timelineDate || (dateEl ? dateEl.value : null);
            if (date === "--" || date === "") date = null;
            var token = ++App.timelineRequestToken;
            App.callBridge("get_timeline", date).then(function (result) {
                if (token !== App.timelineRequestToken) { resolve(); return; }  // stale
                var data = App.handleResult(result, function (msg) {
                    App.showTimelineError(msg || "刷新失败");
                    throw new Error(msg);
                });
                if (data) {
                    App.showTimeline(data);
                    App.clearTimelineError();
                }
                resolve();
            }).catch(function () {
                if (token !== App.timelineRequestToken) { resolve(); return; }  // stale
                App.showTimelineError("刷新失败");
                reject(new Error("timeline refresh failed"));
            });
        });
    }

    function refreshCurrentPageData() {
        // When a refresh is already in-flight, record a pending request
        // instead of silently skipping. After the in-flight refresh
        // completes, if ``pendingPageRefresh`` is true a new refresh is
        // triggered for the CURRENT page so page-switch immediate refresh
        // is never lost. Stale-response protection is already handled by
        // per-page request tokens (timelineRequestToken etc.), so a pending
        // refresh always targets the latest page.
        if (App.activePageRefreshInFlight) {
            App.pendingPageRefresh = true;
            return Promise.resolve();
        }
        App.activePageRefreshInFlight = true;
        App.pendingPageRefresh = false;
        var promises = [refreshStatus()];
        if (App.currentPage === "overview") {
            // Single-sample Overview bundle: one backend call returns KPI
            // + current activity + recent + live_projection from the same
            // snapshot sample, eliminating multi-sample drift between
            // current activity and the recent live row.
            promises.push(refreshOverviewBundle());
        } else if (App.currentPage === "timeline" && App.timelineLoaded) {
            // Skip Timeline refresh when an editor / split editor / dirty
            // session edit / correction shell is active so the heartbeat
            // revision-change refresh and manual refresh do not overwrite
            // user input. The next heartbeat tick after the editor closes
            // will catch up.
            if (typeof App._timelineEditingActive !== "function" || !App._timelineEditingActive()) {
                promises.push(refreshTimeline());
            }
        }
        // Rules / Settings / Statistics are intentionally NOT auto-refreshed
        // by the heartbeat; they keep their own page-level refresh buttons.
        return Promise.allSettled(promises).then(function (results) {
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
            // If a page switch (or other caller) requested a refresh
            // while this one was in-flight, trigger a new refresh now for
            // whatever the current page is. This ensures the page-switch
            // immediate refresh is never silently skipped.
            if (App.pendingPageRefresh) {
                App.pendingPageRefresh = false;
                refreshCurrentPageData();
            }
        });
    }

    // ``refreshAll`` is the manual refresh-button entry point. It delegates
    // to ``refreshCurrentPageData`` so the manual button obeys the same
    // page-scoped contract (status + current page live data) and does not
    // pull in Rules / Settings / Statistics auto-refresh.
    function refreshAll() {
        return refreshCurrentPageData();
    }
    App.refreshAll = refreshAll;
    App.refreshCurrentPageData = refreshCurrentPageData;

    // Low-frequency collection reconciliation. Re-pulls collector status +
    // Overview + current Timeline so a stalled ``refresh_revision`` signal
    // (e.g. a missed update between heartbeat ticks) cannot freeze the UI
    // forever. Rules / Settings / Statistics are NEVER touched here. When a
    // Timeline editor / split editor / correction shell write is in
    // progress, the Timeline re-render is skipped (only sidebar + overview
    // refresh) so the user's input focus and button state are preserved.
    // This is the background safety net only; the manual refresh button
    // can still trigger a heavier refresh.
    function fullReconcileCollectionViews(reason) {
        if (App.reconcileInFlight) return Promise.resolve();
        App.reconcileInFlight = true;
        var promises = [refreshStatus()];
        // Overview is always refreshed: the sidebar / current activity
        // display depend on it on every page. Use the single-sample
        // bundle so current activity / KPI / recent live row do not drift
        // apart during reconciliation.
        promises.push(refreshOverviewBundle());
        // Timeline is only re-rendered when no editing / split / correction
        // shell write is in progress so input focus is never lost. When the
        // user is editing, the next heartbeat revision check (which also
        // respects the editing guard) will catch up after the editor closes.
        if (App.currentPage === "timeline" && App.timelineLoaded
            && !App._timelineEditingActive()) {
            promises.push(refreshTimeline());
        }
        return Promise.allSettled(promises).then(function () {
            App.reconcileInFlight = false;
            App.lastReconcileAtEpochMs = Date.now();
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

    // --- Navigation -----------------------------------------------------

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

        // Lazy-load Timeline data when navigating to it for the first time.
        if (pageId === "timeline" && !App.timelineLoaded && !App.timelineLoading) {
            App.loadTimeline(App.timelineDate);
        }
        // Lazy-load Statistics / Export read-only summary when navigating
        // to the page for the first time. Defaults to today's date range.
        // No write / file / dialog action is triggered.
        if (pageId === "statistics" && !App.statisticsLoaded && !App.statisticsLoading) {
            App.initStatisticsDefaults();
            App.loadStatisticsExportSummary();
        }
        // Lazy-load Project Rules read-only data when navigating to the
        // page for the first time. No Project Rules write events are bound
        // here.
        if (pageId === "rules" && !App.rulesLoaded && !App.rulesLoading) {
            App.loadProjectRules();
        }
        // Lazy-load Settings / Privacy read-only status when navigating to
        // the page for the first time. Only a single read is in flight at a
        // time; subsequent visits reuse the cached status until the user
        // clicks the refresh button.
        if (pageId === "settings" && !App.settingsLoaded && !App.settingsLoading) {
            App.loadSettingsPrivacyStatus();
        }

        // Immediately refresh the current page's live data on page switch
        // so the user sees fresh data without waiting for the next
        // heartbeat revision check. Only live pages (overview / timeline)
        // are refreshed here; Rules / Settings / Statistics keep their
        // lazy-load-once + manual-refresh behavior and are NOT included in
        // the auto-refresh path. Must run AFTER lazy-load so timeline's
        // first load is not bypassed.
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
        // Timeline date navigation
        document.getElementById("timeline-prev-btn").addEventListener("click", App.goPrevDay);
        document.getElementById("timeline-next-btn").addEventListener("click", App.goNextDay);
        document.getElementById("timeline-today-btn").addEventListener("click", App.goToday);
        // Date input: typing/picking a date reloads the timeline for that
        // day. Mirrors the prev/next/today token + cache reset behavior so
        // a stale detail response cannot backfill the new date's panel.
        var dateInput = document.getElementById("timeline-date-input");
        if (dateInput) {
            dateInput.addEventListener("change", function (e) {
                App.timelineDate = e.target.value || null;
                App.selectedSessionId = null;
                App.detailsRequestToken++;
                App.lastSessionDetailsData = null;
                App.resetCorrectionShellState();
                App.loadTimeline(App.timelineDate);
            });
        }
        // Timeline editing handlers
        document.getElementById("edit-save-btn").addEventListener("click", App.saveEdit);
        document.getElementById("edit-cancel-btn").addEventListener("click", App.cancelEdit);
        var noteEl = document.getElementById("edit-note-text");
        if (noteEl) {
            noteEl.addEventListener("input", App.updateNoteCount);
        }
        // Session-level time correction handler. Per-activity inline
        // editor buttons are bound inside renderSessionDetails because
        // they are recreated on each render.
        var sessionTimeSaveBtn = document.getElementById("edit-time-save-btn");
        if (sessionTimeSaveBtn) {
            sessionTimeSaveBtn.addEventListener("click", App.saveSessionTime);
        }
        // Session-level split handler. Per-activity inline split buttons
        // are bound inside renderSessionDetails.
        var sessionSplitSaveBtn = document.getElementById("edit-split-save-btn");
        if (sessionSplitSaveBtn) {
            sessionSplitSaveBtn.addEventListener("click", App.saveSessionSplit);
        }
        // Session-level hide / soft-delete handlers. Per-activity
        // hide/delete buttons are bound inside renderSessionDetails.
        var sessionHideBtn = document.getElementById("edit-visibility-hide-btn");
        if (sessionHideBtn) {
            sessionHideBtn.addEventListener("click", App.saveSessionHide);
        }
        var sessionDeleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (sessionDeleteBtn) {
            sessionDeleteBtn.addEventListener("click", App.saveSessionDelete);
        }
        // Correction shell open / close handlers. The shell only reads
        // display-safe data and guides the user back to the existing
        // action buttons; no new write path is wired here.
        var shellOpenBtn = document.getElementById("open-correction-shell-btn");
        if (shellOpenBtn) {
            shellOpenBtn.addEventListener("click", function () {
                App.openCorrectionShell("session", null);
            });
        }
        var shellCloseBtn = document.getElementById("correction-shell-close-btn");
        if (shellCloseBtn) {
            shellCloseBtn.addEventListener("click", App.closeCorrectionShell);
        }
        // Batch project reassignment controls inside the correction shell.
        // The save button calls the bridge's
        // batch_update_timeline_activities_project method; the select-all /
        // clear buttons only manipulate in-memory selection state.
        App.bindBatchProjectControls();
        // Batch note overwrite controls inside the correction shell. The
        // save button calls the bridge's
        // batch_update_timeline_activities_note method; the textarea input
        // updates the count / save button state in-memory only.
        App.bindBatchNoteControls();
        // Single activity restore controls inside the correction shell.
        // The restore buttons are rendered dynamically, so event
        // delegation on the list container handles clicks without
        // re-binding on every render.
        App.bindRestoreControls();
        // Statistics / Export page controls. The load button triggers a
        // read-only bridge call; the quick-range buttons only update the
        // in-memory date inputs and re-trigger the read. The export button
        // opens the native save dialog through the bridge and writes the
        // chosen CSV file; the frontend never writes files directly.
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
        // clipboard_capture_enabled flag through the bridge; no other
        // write action is wired here.
        var captureToggle = document.getElementById("settings-clipboard-toggle");
        if (captureToggle) {
            captureToggle.addEventListener("change", App.handleCaptureToggleChange);
        }
        // Encrypted backup export + manifest preview handlers. The export
        // button opens a native save dialog and writes an encrypted
        // .wtbackup file; the manifest preview button opens a native open
        // file dialog and reads the non-sensitive manifest. The import
        // button opens a native open file dialog (reusing the existing
        // .wtbackup open dialog helper) and imports the chosen file in
        // replace mode; the clear-all button does not open a dialog and
        // only triggers the destructive reset when the user has typed the
        // explicit Chinese confirmation literal. No save-settings,
        // set-path, or arbitrary file/folder dialog action is registered here.
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
        // Project Rules keyword create submit handler. This is the only
        // Project Rules create event bound in init; the existing rule
        // toggle uses event delegation set up inside rules.js.
        var keywordCreateBtn = document.getElementById("rules-keyword-create-submit");
        if (keywordCreateBtn) {
            keywordCreateBtn.addEventListener("click", App.handleKeywordCreateSubmit);
        }
        // Project Rules folder create submit handler. Same pattern as the
        // keyword create submit handler; the folder edit / delete /
        // edit-save / edit-cancel use event delegation set up inside
        // rules.js on the #rules-list container.
        var folderCreateBtn = document.getElementById("rules-folder-create-submit");
        if (folderCreateBtn) {
            folderCreateBtn.addEventListener("click", App.handleFolderCreateSubmit);
        }
        // Project Rules project create submit handler. Same pattern as the
        // keyword / folder create submit handlers; the project edit /
        // toggle / archive use event delegation set up inside rules.js on
        // the #rules-list container.
        var projectCreateBtn = document.getElementById("rules-project-create-submit");
        if (projectCreateBtn) {
            projectCreateBtn.addEventListener("click", App.handleProjectCreateSubmit);
        }
        // First-run privacy notice handlers. The accept button is only
        // ever visible in "gate" mode (blocking first-run gate). The close
        // button is only ever visible in "view" mode (read-only view from
        // Settings); the JS mode guard inside hideFirstRunNotice ensures
        // the close button can never dismiss the gate. The Settings
        // "查看隐私说明" button opens the overlay in view mode without
        // writing any setting or starting the collector.
        var firstRunAcceptBtn = document.getElementById("first-run-notice-accept-btn");
        if (firstRunAcceptBtn) {
            firstRunAcceptBtn.addEventListener("click", App.acceptFirstRunNotice);
        }
        var firstRunCloseBtn = document.getElementById("first-run-notice-close-btn");
        if (firstRunCloseBtn) {
            // Wrap hideFirstRunNotice so the close button only fires in
            // view mode. The button is hidden in gate mode by
            // renderFirstRunNotice, but this guard also defends against
            // any future code path that might re-enable it.
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

    // Unified 1-second heartbeat. Each tick:
    //   1. Apply the local ticker (re-render already-fetched durations
    //      with a wall-clock delta). The ticker only updates DOM text.
    //   2. Run a lightweight ``get_refresh_state`` revision check. When the
    //      structural ``refresh_revision`` changes, refresh only the data
    //      needed by the current page (``refreshCurrentPageData``). When
    //      the revision is unchanged, no heavy interface is called.
    // The heartbeat never writes the DB, never starts / stops the
    // collector, and never calls Rules / Settings / Statistics bridges.
    function runRevisionCheck() {
        if (App.refreshCheckInFlight) return;
        App.refreshCheckInFlight = true;
        // Pass the current Timeline date so the structural revision is
        // scoped to the viewed date. When not on the Timeline page or no
        // date is set, pass null to use the default (today). This ensures
        // a structural change on a past date (edit / split / merge / hide
        // / restore) triggers a heavy refresh even when today's revision
        // is unchanged.
        var reportDate = (App.currentPage === "timeline" && App.timelineLoaded && App.timelineDate)
            ? App.timelineDate
            : null;
        App.callBridge("get_refresh_state", reportDate).then(function (result) {
            var state = App.handleResult(result, function () {
                return null;
            });
            if (!state) return;
            var prevRevision = App.lastRefreshState && App.lastRefreshState.refresh_revision;
            var newRevision = state.refresh_revision;
            var isFirstCheck = prevRevision === null || prevRevision === undefined;
            App.lastRefreshState = state;
            var triggeredHeavyRefresh = false;
            // When revision unchanged, only update the sidebar status from
            // the refresh_state payload (no get_status call). When revision
            // changed (or first check), refresh the current page's heavy
            // data.
            if (isFirstCheck || prevRevision !== newRevision) {
                triggeredHeavyRefresh = true;
                refreshCurrentPageData();
            } else {
                refreshStatusFromRefreshState(state);
            }
            // Low-frequency reconciliation. Even when revision is
            // unchanged, periodically re-pull status + Overview + current
            // Timeline so a missed revision signal cannot freeze the UI.
            // Guarded by ``reconcileInFlight`` and the editing-active guard
            // inside ``fullReconcileCollectionViews``.
            //
            // Skip when a revision-change heavy refresh was just triggered
            // on this same tick — the heavy refresh already re-pulled all
            // page data, so a concurrent reconciliation would be redundant
            // and could race the in-flight refresh.
            // in-flight refresh.
            //
            // Skip when a page refresh is already in-flight
            // (``activePageRefreshInFlight``) so the reconciliation does
            // not concurrently re-pull the same data.
            var now = Date.now();
            if (!triggeredHeavyRefresh
                && !App.activePageRefreshInFlight
                && !App.reconcileInFlight
                && now - App.lastReconcileAtEpochMs >= App.RECONCILE_INTERVAL_MS) {
                fullReconcileCollectionViews("heartbeat-lowfreq");
            }
        }).catch(function () {
            // Swallow revision-check errors; the ticker phase still runs.
        }).then(function () {
            App.refreshCheckInFlight = false;
        });
    }
    App.runRevisionCheck = runRevisionCheck;

    function startHeartbeat() {
        if (App.heartbeatTimer !== null) clearInterval(App.heartbeatTimer);
        App.heartbeatTimer = setInterval(function () {
            // Local ticker (update DOM text with wall-clock delta).
            try {
                if (typeof App.applyLocalTicker === "function") {
                    App.applyLocalTicker();
                }
            } catch (e) {
                // Swallow ticker errors: the ticker is cosmetic and must
                // never break the revision check or the rest of the UI.
            }
            // Lightweight revision check (with in-flight guard).
            try {
                runRevisionCheck();
            } catch (e) {
                // Swallow revision-check errors; the next tick retries.
            }
        }, App.HEARTBEAT_INTERVAL_MS);
    }
    App.startHeartbeat = startHeartbeat;

    function init() {
        initNav();
        initButtons();
        // Load the first-run privacy notice BEFORE refreshing the main UI
        // so the privacy gate is shown before any data refresh begins. The
        // notice load is awaited: refreshAll and startHeartbeat only run
        // after the notice state is known. If the notice has not been
        // accepted the blocking gate overlay is shown and the collector
        // must NOT start; the gate's accept handler starts the collector
        // after the user accepts. The backend startup gate
        // (webview_main.py) is the final safety boundary; awaiting here
        // eliminates the frontend race where refreshAll could fire before
        // the gate overlay was up.
        //
        // ``loadFirstRunNotice`` resolves to ``true`` only when the notice
        // state was successfully confirmed. On failure (backend ok:false
        // or bridge rejection) it resolves ``false`` after showing the
        // blocking error overlay. The main UI refresh / heartbeat must NOT
        // start on failure (fail-closed): the collector is not running and
        // auto-refreshing the sidebar would imply data collection is
        // active.
        App.loadFirstRunNotice().then(function (noticeConfirmed) {
            if (!noticeConfirmed) return;
            // Await the first ``refreshCurrentPageData()`` BEFORE reading
            // ``get_refresh_state`` and starting the heartbeat. This ensures
            // the initial heavy refresh completes first, so:
            //   - the first heartbeat tick sees a real revision (not null,
            //     which would trigger a redundant ``isFirstCheck`` heavy
            //     refresh on top of the one that just completed);
            //   - ``activePageRefreshInFlight`` is false when the first
            //     heartbeat tick runs, so the revision check does not skip.
            //
            // Initialize ``lastReconcileAtEpochMs`` AFTER the first refresh
            // completes (not at 0). Without this, the first heartbeat tick
            // sees ``now - 0 >= RECONCILE_INTERVAL_MS`` and immediately
            // triggers low-frequency reconciliation on top of the heavy
            // refresh that just completed.
            refreshCurrentPageData().then(function () {
                App.lastReconcileAtEpochMs = Date.now();
                // Initialize ``lastRefreshState`` BEFORE starting the
                // heartbeat. Without this, the first heartbeat tick sees
                // ``prevRevision === null`` (isFirstCheck === true) and
                // triggers a redundant heavy refresh on top of the one
                // that just completed above.
                return App.callBridge("get_refresh_state");
            }).then(function (result) {
                var state = App.handleResult(result, function () { return null; });
                if (state) {
                    App.lastRefreshState = state;
                }
                startHeartbeat();
            }, function () {
                // get_refresh_state failed: start the heartbeat anyway.
                // The first tick's revision check will initialize
                // lastRefreshState as a fallback. ``lastReconcileAtEpochMs``
                // was already initialized above so the first tick does not
                // immediately trigger reconciliation.
                startHeartbeat();
            });
        });
    }
    App.init = init;

    // --- Bootstrap wiring (must run at module load) -------------------
    // Gate ``init()`` on BOTH DOMContentLoaded AND the pywebview bridge
    // being ready. The bridge is ready when either:
    //   - ``window.pywebview && window.pywebview.api`` already exists
    //     (pywebview finished injecting before this script ran), OR
    //   - the ``pywebviewready`` event fires on ``window`` (pywebview
    //     finishes injecting after this script ran).
    // Without this gate, ``init()`` runs on DOMContentLoaded and
    // immediately calls ``App.loadFirstRunNotice()`` -> ``App.callBridge()``.
    // If the bridge is not yet injected, ``callBridge`` rejects with
    // "bridge unavailable" and ``loadFirstRunNotice``'s catch branch
    // renders the blocking "隐私说明加载失败" overlay — a false positive
    // that blocks the user even though the backend notice is fine.
    // ``initStarted`` ensures ``init()`` only runs once regardless of
    // event ordering (DOMContentLoaded before/after pywebviewready, or
    // both already satisfied at script load). If ``pywebviewready`` has
    // already fired by the time ``onDomReady`` runs, the
    // ``isBridgeReady()`` check catches the already-injected state, so
    // the event being missed is harmless.
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
