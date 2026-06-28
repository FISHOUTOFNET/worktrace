// WorkTrace WebView frontend — init module (Phase R2 split).
// Refresh orchestration, navigation, button binding, and DOMContentLoaded wiring.
// This module must be loaded LAST so all cross-file App.* references resolve.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Refresh orchestration ------------------------------------------

    function refreshAll() {
        var statusPromise = App.callBridge("get_status").then(function (result) {
            var status = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            App.showStatus(status);
        }).catch(function (err) {
            // Phase 3C.1: never surface raw exception text; use the stable
            // fallback so internal details do not leak into the UI.
            App.showError("刷新失败");
            throw err;
        });

        var overviewPromise = App.callBridge("get_overview").then(function (result) {
            var overview = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            App.showOverview(overview);
        }).catch(function (err) {
            // Phase 3C.1: never surface raw exception text; use the stable
            // fallback so internal details do not leak into the UI.
            App.showError("刷新失败");
            throw err;
        });

        var recentPromise = App.callBridge("get_recent_activities").then(function (result) {
            var recent = App.handleResult(result, function (msg) {
                throw new Error(msg);
            });
            App.showRecent(recent);
        }).catch(function (err) {
            // Phase 3C.1: never surface raw exception text; use the stable
            // fallback so internal details do not leak into the UI.
            App.showError("刷新失败");
            throw err;
        });

        var promises = [statusPromise, overviewPromise, recentPromise];

        // If the Timeline page is currently active, also refresh it.
        if (App.currentPage === "timeline" && App.timelineLoaded) {
            var timelinePromise = new Promise(function (resolve, reject) {
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
                }).catch(function (err) {
                    if (token !== App.timelineRequestToken) { resolve(); return; }  // stale
                    // Keep lastTimelineData on screen; just surface the error.
                    // Phase 3C.1: use the stable "刷新失败" fallback.
                    App.showTimelineError("刷新失败");
                    reject(err);
                });
            });
            promises.push(timelinePromise);
        }

        // If the Project Rules page is active and has been loaded once,
        // refresh its read-only data. The rules module owns the loading
        // guard and request token so stale responses cannot overwrite newer
        // page data.
        if (App.currentPage === "rules" && App.rulesLoaded && !App.rulesLoading) {
            promises.push(App.loadProjectRules());
        }

        Promise.allSettled(promises).then(function (results) {
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
    App.refreshAll = refreshAll;

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
    }
    App.initButtons = initButtons;

    function startAutoRefresh() {
        if (App.refreshTimer !== null) clearInterval(App.refreshTimer);
        App.refreshTimer = setInterval(refreshAll, App.REFRESH_INTERVAL_MS);
    }
    App.startAutoRefresh = startAutoRefresh;

    function init() {
        initNav();
        initButtons();
        refreshAll();
        startAutoRefresh();
    }
    App.init = init;

    // --- DOMContentLoaded wiring (must run at module load) -------------
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();
