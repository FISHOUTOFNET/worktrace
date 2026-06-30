// WorkTrace WebView frontend — init module (Phase R2 split).
// Refresh orchestration, navigation, button binding, and DOMContentLoaded wiring.
// This module must be loaded LAST so all cross-file App.* references resolve.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Refresh orchestration ------------------------------------------
    // Phase 6H-followup: the fixed 8-second full refresh and the independent
    // 1-second ticker are replaced by a single 1-second heartbeat
    // (``startHeartbeat``). The heartbeat first applies the local ticker
    // (re-renders already-fetched durations with a wall-clock delta) and
    // then runs a lightweight ``get_refresh_state`` revision check. Heavy
    // interfaces are only called when the structural revision changes, and
    // only for the data needed by the current page. Rules / Settings /
    // Statistics are NOT included in background auto-refresh; they keep
    // their own page-level load / refresh buttons.
    //
    // ``refreshCurrentPageData`` is the unified heavy-refresh entry point
    // used by the manual refresh button, the heartbeat revision-change
    // branch, and page-switch immediate refresh. It refreshes status (the
    // sidebar is always visible) plus the current page's live data. It is
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

    // Phase 6H-followup section 8: ``refreshStatusFromRefreshState`` updates
    // the sidebar status display directly from a ``get_refresh_state``
    // payload without calling ``get_status`` again. This is the preferred
    // path inside the heartbeat because ``get_refresh_state`` already
    // returns ``collector_status`` / ``paused`` / ``status_display``.
    // Falls back to the legacy ``refreshStatus`` path when ``state`` is
    // null or missing required fields so the sidebar always reflects the
    // backend truth.
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
        return App.callBridge("get_overview").then(function (result) {
            var overview = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            App.showOverview(overview);
        }).catch(function () {
            App.showError("刷新失败");
        });
    }

    function refreshRecent() {
        return App.callBridge("get_recent_activities").then(function (result) {
            var recent = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            App.showRecent(recent);
        }).catch(function () {
            App.showError("刷新失败");
        });
    }

    function refreshTimeline() {
        return new Promise(function (resolve, reject) {
            var dateEl = document.getElementById("timeline-date-display");
            var date = App.timelineDate || (dateEl ? dateEl.textContent : null);
            if (date === "--") date = null;
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
        if (App.activePageRefreshInFlight) return Promise.resolve();
        App.activePageRefreshInFlight = true;
        var promises = [refreshStatus()];
        if (App.currentPage === "overview") {
            promises.push(refreshOverview());
            promises.push(refreshRecent());
        } else if (App.currentPage === "timeline" && App.timelineLoaded) {
            promises.push(refreshTimeline());
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
        });
    }

    // ``refreshAll`` is kept as the manual refresh-button entry point. It
    // now delegates to ``refreshCurrentPageData`` so the manual button also
    // obeys the page-scoped contract (status + current page live data) and
    // does not pull in Rules / Settings / Statistics auto-refresh.
    function refreshAll() {
        return refreshCurrentPageData();
    }
    App.refreshAll = refreshAll;
    App.refreshCurrentPageData = refreshCurrentPageData;

    // Phase 6H-followup section 8/10: low-frequency collection
    // reconciliation. Re-pulls collector status + Overview + current
    // Timeline so a stalled ``refresh_revision`` signal (e.g. a missed
    // update between heartbeat ticks) cannot freeze the UI forever. Rules
    // / Settings / Statistics are NEVER touched here. When a Timeline
    // editor / split editor / correction shell write is in progress, the
    // Timeline re-render is skipped (only sidebar + overview refresh) so
    // the user's input focus and button state are preserved. The manual
    // refresh button can still trigger a heavier refresh; this is the
    // background safety net only.
    function fullReconcileCollectionViews(reason) {
        if (App.reconcileInFlight) return Promise.resolve();
        App.reconcileInFlight = true;
        var promises = [refreshStatus()];
        // Overview is always refreshed: the sidebar / current activity
        // display depend on it on every page.
        promises.push(refreshOverview());
        promises.push(refreshRecent());
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
        // Phase 4A: lazy-load Statistics / Export read-only summary when
        // navigating to the page for the first time. Defaults to today's
        // date range. No write / file / dialog action is triggered.
        if (pageId === "statistics" && !App.statisticsLoaded && !App.statisticsLoading) {
            App.initStatisticsDefaults();
            App.loadStatisticsExportSummary();
        }
        // Phase 5A: lazy-load Project Rules read-only data when navigating
        // to the page for the first time. No Project Rules write events are
        // bound in this phase.
        if (pageId === "rules" && !App.rulesLoaded && !App.rulesLoading) {
            App.loadProjectRules();
        }
        // Phase 6A: lazy-load Settings / Privacy read-only status when
        // navigating to the page for the first time. Only a single read is
        // in flight at a time; subsequent visits reuse the cached status
        // until the user clicks the refresh button.
        if (pageId === "settings" && !App.settingsLoaded && !App.settingsLoading) {
            App.loadSettingsPrivacyStatus();
        }

        // Phase 6H-followup: immediately refresh the current page's live
        // data on page switch so the user sees fresh data without waiting
        // for the next heartbeat revision check. Only live pages
        // (overview / timeline) are refreshed here; Rules / Settings /
        // Statistics keep their lazy-load-once + manual-refresh behavior
        // and are NOT included in the auto-refresh path. Must run AFTER
        // lazy-load so timeline's first load is not bypassed.
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
        // Phase 3A: Timeline editing handlers
        document.getElementById("edit-save-btn").addEventListener("click", App.saveEdit);
        document.getElementById("edit-cancel-btn").addEventListener("click", App.cancelEdit);
        var noteEl = document.getElementById("edit-note-text");
        if (noteEl) {
            noteEl.addEventListener("input", App.updateNoteCount);
        }
        // Phase 3B.1: session-level time correction handler. Per-activity
        // inline editor buttons are bound inside renderSessionDetails because
        // they are recreated on each render.
        var sessionTimeSaveBtn = document.getElementById("edit-time-save-btn");
        if (sessionTimeSaveBtn) {
            sessionTimeSaveBtn.addEventListener("click", App.saveSessionTime);
        }
        // Phase 3B.2: session-level split handler. Per-activity inline split
        // buttons are bound inside renderSessionDetails.
        var sessionSplitSaveBtn = document.getElementById("edit-split-save-btn");
        if (sessionSplitSaveBtn) {
            sessionSplitSaveBtn.addEventListener("click", App.saveSessionSplit);
        }
        // Phase 3B.4: session-level hide / soft-delete handlers. Per-activity
        // hide/delete buttons are bound inside renderSessionDetails.
        var sessionHideBtn = document.getElementById("edit-visibility-hide-btn");
        if (sessionHideBtn) {
            sessionHideBtn.addEventListener("click", App.saveSessionHide);
        }
        var sessionDeleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (sessionDeleteBtn) {
            sessionDeleteBtn.addEventListener("click", App.saveSessionDelete);
        }
        // Phase 3B.5B: correction shell open / close handlers. The shell
        // only reads display-safe data and guides the user back to the
        // existing action buttons; no new write path is wired here.
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
        // Phase 3B.6: batch project reassignment controls inside the
        // correction shell. The save button calls the bridge's
        // batch_update_timeline_activities_project method; the select-all /
        // clear buttons only manipulate in-memory selection state.
        App.bindBatchProjectControls();
        // Phase 3B.7: batch note overwrite controls inside the correction
        // shell. The save button calls the bridge's
        // batch_update_timeline_activities_note method; the textarea input
        // updates the count / save button state in-memory only.
        App.bindBatchNoteControls();
        // Phase 3B.8: single activity restore controls inside the correction
        // shell. The restore buttons are rendered dynamically, so event
        // delegation on the list container handles clicks without
        // re-binding on every render.
        App.bindRestoreControls();
        // Phase 4A / 4B: Statistics / Export page controls. The load button
        // triggers a read-only bridge call; the quick-range buttons only
        // update the in-memory date inputs and re-trigger the read. The
        // export button (Phase 4B) opens the native save dialog through the
        // bridge and writes the chosen CSV file; the frontend never writes a
        // file itself.
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
        // Phase 6B: capture toggle write handler. The toggle
        // writes the clipboard_capture_enabled flag through the bridge;
        // no other write action is wired here.
        var captureToggle = document.getElementById("settings-clipboard-toggle");
        if (captureToggle) {
            captureToggle.addEventListener("change", App.handleCaptureToggleChange);
        }
        // Phase 6C: encrypted backup export + manifest preview handlers.
        // The export button opens a native save dialog and writes an
        // encrypted .wtbackup file; the manifest preview button opens a
        // native open file dialog and reads the non-sensitive manifest.
        // Phase 6D: the import button opens a native open file dialog
        // (reusing the existing .wtbackup open dialog helper) and imports
        // the chosen file in replace mode; the clear-all button does not
        // open a dialog and only triggers the destructive reset when the
        // user has typed the explicit Chinese confirmation literal.
        // No save-settings, set-path, or arbitrary file/folder dialog
        // action is wired here.
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
        // Phase 5C: Project Rules keyword create submit handler. This is
        // the only Project Rules create event bound in init; the existing
        // rule toggle uses event delegation set up inside rules.js.
        var keywordCreateBtn = document.getElementById("rules-keyword-create-submit");
        if (keywordCreateBtn) {
            keywordCreateBtn.addEventListener("click", App.handleKeywordCreateSubmit);
        }
        // Phase 5E: Project Rules folder create submit handler. Same pattern
        // as the keyword create submit handler; the folder edit / delete
        // / edit-save / edit-cancel use event delegation set up inside
        // rules.js on the #rules-list container.
        var folderCreateBtn = document.getElementById("rules-folder-create-submit");
        if (folderCreateBtn) {
            folderCreateBtn.addEventListener("click", App.handleFolderCreateSubmit);
        }
        // Phase 5G: Project Rules project create submit handler. Same pattern
        // as the keyword / folder create submit handlers; the project
        // edit / toggle / archive use event delegation set up inside
        // rules.js on the #rules-list container.
        var projectCreateBtn = document.getElementById("rules-project-create-submit");
        if (projectCreateBtn) {
            projectCreateBtn.addEventListener("click", App.handleProjectCreateSubmit);
        }
        // Phase 6E: First-run privacy notice handlers. The accept button
        // is only ever visible in "gate" mode (blocking first-run gate).
        // The close button is only ever visible in "view" mode (read-only
        // view from Settings); the JS mode guard inside hideFirstRunNotice
        // ensures the close button can never dismiss the gate. The
        // Settings "查看隐私说明" button opens the overlay in view mode
        // without writing any setting or starting the collector.
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

    // Phase 6H-followup: unified 1-second heartbeat. Replaces the fixed
    // 8-second full refresh (``startAutoRefresh``) and the independent
    // 1-second ticker (``startLocalTicker``). Each tick:
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
        App.callBridge("get_refresh_state").then(function (result) {
            var state = App.handleResult(result, function () {
                return null;
            });
            if (!state) return;
            var prevRevision = App.lastRefreshState && App.lastRefreshState.refresh_revision;
            var newRevision = state.refresh_revision;
            var isFirstCheck = prevRevision === null || prevRevision === undefined;
            App.lastRefreshState = state;
            // Phase 6H-followup section 10: when revision unchanged, only
            // update the sidebar status from the refresh_state payload
            // (no get_status call). When revision changed (or first
            // check), refresh the current page's heavy data.
            if (isFirstCheck || prevRevision !== newRevision) {
                refreshCurrentPageData();
            } else {
                refreshStatusFromRefreshState(state);
            }
            // Phase 6H-followup section 8/10: low-frequency reconciliation.
            // Even when revision is unchanged, periodically re-pull status +
            // Overview + current Timeline so a missed revision signal cannot
            // freeze the UI. Guarded by ``reconcileInFlight`` and the
            // editing-active guard inside ``fullReconcileCollectionViews``.
            var now = Date.now();
            if (!App.reconcileInFlight
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
        // Clear the legacy timers so a re-init does not stack old intervals.
        if (App.refreshTimer !== null) { clearInterval(App.refreshTimer); App.refreshTimer = null; }
        if (App.localTickerTimer !== null) { clearInterval(App.localTickerTimer); App.localTickerTimer = null; }
        App.heartbeatTimer = setInterval(function () {
            // Phase 1: local ticker (update DOM text with wall-clock delta).
            try {
                if (typeof App.applyLocalTicker === "function") {
                    App.applyLocalTicker();
                }
            } catch (e) {
                // Swallow ticker errors: the ticker is cosmetic and must
                // never break the revision check or the rest of the UI.
            }
            // Phase 2: lightweight revision check (with in-flight guard).
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
        // Phase 6G: load the first-run privacy notice BEFORE refreshing
        // the main UI so the privacy gate is shown before any data
        // refresh begins. The notice load is awaited: refreshAll and
        // startAutoRefresh only run after the notice state is known. If
        // the notice has not been accepted the blocking gate overlay is
        // shown and the collector must NOT start; the gate's accept
        // handler starts the collector after the user accepts. The
        // backend startup gate (webview_main.py) is the final safety
        // boundary; awaiting here eliminates the frontend race where
        // refreshAll could fire before the gate overlay was up.
        //
        // Phase 6I: loadFirstRunNotice resolves to ``true`` only when the
        // notice state was successfully confirmed. On failure (backend
        // ok:false or bridge rejection) it resolves ``false`` after
        // showing the blocking error overlay. The main UI refresh /
        // auto-refresh / local ticker must NOT start on failure
        // (fail-closed): the collector is not running and auto-refreshing
        // the sidebar would imply data collection is active. The old
        // catch branch that unconditionally started refresh is removed.
        App.loadFirstRunNotice().then(function (noticeConfirmed) {
            if (!noticeConfirmed) return;
            // Phase 6H-followup: the initial load uses the unified
            // ``refreshCurrentPageData`` so the first heavy refresh is
            // page-scoped. The unified heartbeat then takes over: every 1
            // second it first applies the local ticker (DOM-only duration
            // updates) and then runs the lightweight ``get_refresh_state``
            // revision check, calling heavy interfaces only when the
            // structural revision changes.
            refreshCurrentPageData();
            startHeartbeat();
        });
    }
    App.init = init;

    // --- Bootstrap wiring (must run at module load) -------------------
    // Phase 6H: gate ``init()`` on BOTH DOMContentLoaded AND the pywebview
    // bridge being ready. The bridge is ready when either:
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
