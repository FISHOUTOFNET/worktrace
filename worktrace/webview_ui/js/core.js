// WorkTrace WebView frontend — core module (Phase R2 split).
// Namespace + shared state + bridge helper + generic helpers + date/time/format utils.
// Only communicates with Python through pywebview API bridge.
// Does not persist sensitive data in browser storage APIs.
// Does not access any external network resources.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Module-level state (single source of truth across all js modules) ---
    // Phase 6H-followup: the fixed 8-second full refresh and the independent
    // 1-second ticker are replaced by a single 1-second heartbeat. The
    // heartbeat first applies the local ticker (re-renders already-fetched
    // durations with a wall-clock delta) and then runs a lightweight
    // ``get_refresh_state`` revision check. Heavy interfaces (get_overview /
    // get_recent_activities / get_timeline) are only called when the
    // structural revision changes. ``REFRESH_INTERVAL_MS`` is kept for the
    // manual refresh button fallback but is no longer used by any timer.
    App.REFRESH_INTERVAL_MS = 8000;
    App.HEARTBEAT_INTERVAL_MS = 1000;
    App.LOCAL_TICKER_INTERVAL_MS = 1000;
    App.NOTE_MAX_LENGTH = 2000;
    App.refreshTimer = null;
    App.localTickerTimer = null;
    App.heartbeatTimer = null;

    // --- Phase 6G / 6H-followup: live display state -------------------
    // The heartbeat's local-ticker phase re-renders already-fetched
    // durations with a locally-computed elapsed increment. The ticker ONLY
    // updates DOM text; it never calls a bridge method, never writes the DB,
    // and never starts / stops the collector. The following snapshots are
    // set by showOverview / showRecent / showTimeline / renderSessionDetails
    // respectively and read by the ticker to compute the live increment.
    App.lastOverviewSnapshot = null;
    // Phase 6H-followup: recent-activities snapshot so the ticker can
    // increment the live-projected recent item's duration without a bridge
    // round-trip. Set by showRecent.
    App.lastRecentSnapshot = null;
    // Phase 6H-followup: session-details snapshot so the ticker can
    // increment the live-projected detail row's duration without a bridge
    // round-trip. Set by renderSessionDetails.
    App.lastSessionDetailsData = null;

    // --- Phase 6H-followup: heartbeat refresh-state ---------------------
    // ``lastRefreshState`` caches the last ``get_refresh_state`` payload so
    // the heartbeat can compare ``refresh_revision`` between ticks.
    // ``refreshCheckInFlight`` guards against overlapping get_refresh_state
    // round-trips. ``activePageRefreshInFlight`` guards against overlapping
    // heavy page-data refreshes triggered by a revision change.
    // ``lastFullRefreshAtEpochMs`` records the last time a heavy refresh
    // completed so a future safety net can detect a stalled heartbeat.
    App.lastRefreshState = null;
    App.refreshCheckInFlight = false;
    App.activePageRefreshInFlight = false;
    App.lastFullRefreshAtEpochMs = 0;
    // Phase 6H-followup section 8/10: low-frequency collection reconciliation.
    // Every ``RECONCILE_INTERVAL_MS`` the heartbeat triggers a guarded
    // ``fullReconcileCollectionViews`` that re-pulls collector status +
    // Overview + current Timeline so a stalled revision signal cannot
    // freeze the UI forever. Rules / Settings / Statistics are NOT touched.
    // The reconciliation skips Timeline re-render when an editor / split /
    // correction shell is open so the user's input focus is preserved.
    App.RECONCILE_INTERVAL_MS = 180000;  // 3 minutes (within 2-5 min band)
    App.lastReconcileAtEpochMs = 0;
    App.reconcileInFlight = false;

    // --- Phase 6H-followup: monotonic duration render state ------------
    // Maps a continuity key (e.g. ``"current-activity"``,
    // ``"session-<id>"``, ``"recent-<index>"``) to the last rendered
    // seconds. Used by ``renderDurationMonotonic`` to avoid visual rollback
    // when the new projected seconds are 1-2s less than the DOM value.
    App._monotonicRenderState = {};

    // --- Timeline state -------------------------------------------------
    App.currentPage = "overview";
    App.timelineDate = null;       // null = today (backend decides)
    App.timelineLoaded = false;    // whether timeline has been loaded at least once
    App.timelineLoading = false;   // whether a timeline load is in progress
    App.selectedSessionId = null;  // currently selected session for detail view

    // Request tokens prevent stale bridge responses from overwriting newer
    // data when the user rapidly switches dates. Each load increments the
    // token; only the response whose token equals the current value is
    // applied to the DOM.
    App.timelineRequestToken = 0;
    App.detailsRequestToken = 0;

    // --- Phase 3A: Timeline editing state -------------------------------
    App.projectsCache = null;
    App.projectsLoading = false;
    App.currentSessions = [];
    App.editingSession = null;
    App.editSaving = false;

    // --- Phase 3B.1: Timeline time-correction state ---------------------
    App.timeSaving = false;
    App.editingActivityId = null;
    App.activityTimeSaving = false;

    // --- Phase 3B.2: Timeline activity-split state -----------------------
    App.sessionSplitSaving = false;
    App.editingSplitActivityId = null;
    App.activitySplitSaving = false;

    // --- Phase 3B.3: Timeline activity-merge state -----------------------
    App.mergeSaving = false;
    App.mergingActivityId = null;

    // --- Phase 3B.4: Timeline hide / soft delete state -------------------
    App.hideSaving = false;
    App.hidingActivityId = null;
    App.deleteSaving = false;
    App.deletingActivityId = null;

    // --- Phase 3B.5B: Timeline correction shell state -------------------
    App.correctionShellOpen = false;
    App.correctionShellSessionId = null;
    App.correctionShellActivityId = null;
    App.correctionShellMode = null;  // "session" | "activity" | null
    App.correctionShellHighlightTimer = null;
    App.selectedBatchActivityIds = {};
    App.batchProjectSaving = false;
    App.batchProjectTargetId = null;
    App.batchNoteSaving = false;
    App.restoreSaving = false;
    App.restoreSavingActivityId = null;

    // --- Phase 4A / 4B: Statistics / Export state -----------------------
    App.statisticsLoaded = false;
    App.statisticsLoading = false;
    App.statisticsRequestToken = 0;
    App.statisticsExportSaving = false;

    // --- Phase 6A: Settings / Privacy read-only state -----------------
    // Only a single read-only load is in flight at a time. The request
    // token guards against stale responses when the user re-enters the
    // page rapidly; it is monotonically incremented per load attempt.
    App.settingsLoaded = false;
    App.settingsLoading = false;
    App.settingsRequestToken = 0;
    // --- Phase 6B: Settings / Privacy capture toggle write -------------
    // Separate from settingsLoading (read) so a write in flight never
    // pollutes the read-state guard. While true, both the refresh button
    // and the capture toggle are disabled so no concurrent write or
    // read can race the in-flight toggle write.
    App.settingsWriteInProgress = false;
    // --- Phase 6C: Settings / Privacy encrypted backup state -----------
    // Separate from settingsWriteInProgress (capture toggle) so a backup
    // operation in flight never races the capture toggle and vice versa.
    // While either is true, the backup controls are disabled.
    App.settingsBackupExportInProgress = false;
    App.settingsBackupManifestInProgress = false;
    // --- Phase 6D: Settings / Privacy backup import + clear-all state --
    // Separate from settingsBackupExportInProgress (6C export) and
    // settingsBackupManifestInProgress (6C manifest) so an import / clear
    // in flight never races the export / manifest / capture toggle. While
    // either is true, every Settings control is disabled.
    App.settingsBackupImportInProgress = false;
    App.settingsClearAllInProgress = false;

    // --- Phase 6E: First-run privacy notice state -----------------------
    // ``firstRunNoticeLoaded`` is true after the first ``get_first_run_notice``
    // round-trip completes (success or failure). ``firstRunNoticeLoading``
    // is true while the load is in flight so a rapid re-entry cannot
    // re-trigger a second load. ``firstRunNoticeRequired`` is true when
    // the backend reports ``accepted === false``; the blocking overlay
    // stays open and the sidebar pause/resume control must not start
    // the collector. ``firstRunNoticeAcceptInProgress`` is true while
    // the accept round-trip is in flight so the accept button can be
    // disabled. ``firstRunNoticeViewingFromSettings`` is true when the
    // overlay was opened from the Settings / Privacy "查看隐私说明"
    // button; in that mode the close button is shown and no accept
    // action is taken on close. All variables live in JS memory only;
    // no browser storage APIs are used.
    App.firstRunNoticeLoaded = false;
    App.firstRunNoticeLoading = false;
    App.firstRunNoticeRequired = false;
    App.firstRunNoticeAcceptInProgress = false;
    App.firstRunNoticeViewingFromSettings = false;

    // --- Phase 5B: Project Rules state ---------------------------------
    App.rulesLoaded = false;
    App.rulesLoading = false;
    App.rulesRequestToken = 0;
    App.rulesSavingRuleKey = null;

    // --- Phase 5C: Project Rules keyword creation state ---------------
    // Separate from rulesSavingRuleKey so the toggle write state and the
    // keyword create write state can never pollute each other. Only one
    // keyword create may be in flight at a time.
    App.rulesCreatingKeyword = false;

    // --- Phase 5D: Project Rules keyword deletion state ---------------
    // Separate from rulesSavingRuleKey (Phase 5B toggle) and
    // rulesCreatingKeyword (Phase 5C create) so the three write paths can
    // never pollute each other. Only one keyword delete may be in flight
    // at a time; it carries the "<kind>:<id>" key of the row being
    // deleted so the deleting button label can be flipped to ``正在删除…``.
    App.rulesDeletingRuleKey = null;

    // --- Phase 5F: Project Rules keyword rule edit state ----------------
    // Separate from rulesSavingRuleKey (Phase 5B toggle),
    // rulesCreatingKeyword (Phase 5C create), rulesDeletingRuleKey
    // (Phase 5D delete), and the folder CRUD states (Phase 5E) so the
    // five write paths can never pollute each other. Only one keyword
    // edit may be in flight at a time; it carries the "keyword:<id>" key
    // of the row being edited.
    App.rulesEditingKeywordKey = null;   // "keyword:<id>" of the row being edited
    App.rulesUpdatingKeywordKey = null;  // "keyword:<id>" of the row being saved

    // --- Phase 5E: Project Rules folder rule CRUD state ----------------
    // Separate from rulesSavingRuleKey (Phase 5B toggle),
    // rulesCreatingKeyword (Phase 5C keyword create), and
    // rulesDeletingRuleKey (Phase 5D keyword delete) so the four write
    // paths can never pollute each other. Only one folder write may be in
    // flight per kind at a time.
    App.rulesCreatingFolder = false;
    App.rulesEditingFolderKey = null;   // "folder:<id>" of the row being edited
    App.rulesDeletingFolderKey = null;  // "folder:<id>" of the row being deleted
    // Phase 5E: cache of the last-loaded Project Rules data so the inline
    // folder edit form can re-render the list immediately without a
    // round-trip through loadProjectRules (which would lose input focus).
    App.lastProjectRulesData = null;

    // --- Phase 5G: Project lifecycle state -----------------------------
    // Separate from all rule write states (5B toggle, 5C keyword create,
    // 5D keyword delete, 5E folder CRUD, 5F keyword edit) so project
    // lifecycle writes can never pollute rule write button / input
    // disabled state. Only one project lifecycle write may be in flight
    // per kind at a time.
    App.rulesCreatingProject = false;
    App.rulesEditingProjectId = null;   // project id being edited (int or null)
    App.rulesUpdatingProjectId = null;  // project id being saved (int or null)
    App.rulesTogglingProjectId = null;  // project id being toggled (int or null)
    App.rulesArchivingProjectId = null; // project id being archived (int or null)

    // --- Phase 5H: rule impact preview + safe single-rule backfill state ---
    // Separate from all rule write states (5B toggle, 5C keyword create,
    // 5D keyword delete, 5E folder CRUD, 5F keyword edit, 5G project
    // lifecycle) so preview / backfill can never pollute any other write
    // button / input disabled state. ``rulesPreviewingImpactKey`` carries
    // the "<kind>:<id>" key of the rule whose preview is loading;
    // ``rulesBackfillingRuleKey`` carries the key of the rule being applied;
    // ``rulesImpactPreviewKey`` is the key of the rule whose preview is
    // currently rendered (null = no preview shown);
    // ``rulesImpactPreviewData`` caches the last preview payload so the
    // panel can be re-rendered from cache without a round-trip.
    App.rulesPreviewingImpactKey = null;
    App.rulesBackfillingRuleKey = null;
    App.rulesImpactPreviewKey = null;
    App.rulesImpactPreviewData = null;

    // --- Phase 5I: selected-rule batch operations state ----------------
    // Separate from all rule write states (5B toggle, 5C keyword create,
    // 5D keyword delete, 5E folder CRUD, 5F keyword edit, 5G project
    // lifecycle, 5H single-rule preview / backfill) so batch operations
    // can never pollute any other write button / input disabled state.
    // ``rulesBatchSelectedKeys`` is an object map of selected rule keys
    // ("<kind>:<id>" -> true) kept in JS memory only (no browser storage
    // APIs). ``rulesBatchInFlight`` is true while any batch
    // operation (preview / apply / enable / disable) is running; while
    // true, every batch button AND every per-rule write button is disabled.
    // ``rulesBatchPanelData`` caches the last batch panel payload
    // ({mode: "preview"|"apply"|"toggle", payload: {...}} | null) so the
    // panel can be re-rendered from cache without a round-trip.
    App.rulesBatchSelectedKeys = {};
    App.rulesBatchInFlight = false;
    App.rulesBatchPanelData = null;

    // --- Phase 3C: Unified Timeline status semantics -------------------
    App.STATUS_TYPE_CLASS = {
        info: "edit-status-info",
        success: "edit-status-success",
        error: "edit-status-error",
        loading: "edit-status-loading",
        empty: "edit-status-empty"
    };

    App.STATUS_TYPE_CLASS_VALUES = [
        "edit-status-info", "edit-status-success", "edit-status-error",
        "edit-status-loading", "edit-status-empty"
    ];

    // Last successfully rendered Timeline payload.
    App.lastTimelineData = null;

    // --- Bridge helper --------------------------------------------------

    function callBridge(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        if (typeof window.pywebview === "undefined" || !window.pywebview.api) {
            return Promise.reject(new Error("bridge unavailable"));
        }
        return window.pywebview.api[method].apply(window.pywebview.api, args);
    }
    App.callBridge = callBridge;

    // --- Overview error banner ------------------------------------------

    function showError(message) {
        var banner = document.getElementById("overview-error");
        if (!banner) return;
        if (!message) {
            banner.hidden = true;
            banner.textContent = "加载失败，请稍后重试。";
            return;
        }
        banner.hidden = false;
        banner.textContent = message;
    }
    App.showError = showError;

    function clearError() {
        showError("");
    }
    App.clearError = clearError;

    // --- Timeline error / loading ---------------------------------------

    function showTimelineError(message) {
        var banner = document.getElementById("timeline-error");
        if (!banner) return;
        if (!message) {
            banner.hidden = true;
            banner.textContent = "加载失败，请稍后重试。";
            return;
        }
        banner.hidden = false;
        banner.textContent = message;
    }
    App.showTimelineError = showTimelineError;

    function clearTimelineError() {
        showTimelineError("");
    }
    App.clearTimelineError = clearTimelineError;

    function setTimelineLoading(loading) {
        App.timelineLoading = loading;
        var el = document.getElementById("timeline-loading");
        if (el) el.hidden = !loading;
    }
    App.setTimelineLoading = setTimelineLoading;

    // --- Phase 3C: Unified Timeline status semantics -------------------

    function statusClassFor(type) {
        return App.STATUS_TYPE_CLASS[type] || App.STATUS_TYPE_CLASS.info;
    }
    App.statusClassFor = statusClassFor;

    function applyStatusType(el, type) {
        if (!el) return;
        var preserved = [];
        if (typeof el.className === "string" && el.className) {
            preserved = el.className.split(/\s+/).filter(function (cls) {
                return cls && App.STATUS_TYPE_CLASS_VALUES.indexOf(cls) === -1;
            });
        }
        if (preserved.indexOf("edit-status") === -1) {
            preserved.unshift("edit-status");
        }
        preserved.push(statusClassFor(type));
        el.className = preserved.join(" ");
    }
    App.applyStatusType = applyStatusType;

    function setTimelineStatus(message, type) {
        if (!message) {
            clearTimelineError();
            setTimelineLoading(false);
            return;
        }
        if (type === "loading") {
            setTimelineLoading(true);
            clearTimelineError();
            return;
        }
        setTimelineLoading(false);
        if (type === "error") {
            showTimelineError(message);
            return;
        }
        clearTimelineError();
    }
    App.setTimelineStatus = setTimelineStatus;

    function setDetailStatus(message, type) {
        var header = document.getElementById("timeline-details-header");
        if (!header) return;
        if (!message) {
            header.textContent = "请选择一条时间记录";
            return;
        }
        header.textContent = message;
    }
    App.setDetailStatus = setDetailStatus;

    function setEditStatus(message, type) {
        if (!message) {
            App.showEditStatus("", false);
            return;
        }
        App.showEditStatus(message, type === "error");
    }
    App.setEditStatus = setEditStatus;

    function setCorrectionStatus(message, type) {
        App.setCorrectionShellStatus(message, type === "error");
    }
    App.setCorrectionStatus = setCorrectionStatus;

    // --- Generic result handler -----------------------------------------

    function handleResult(result, onError) {
        if (result && result.ok === false) {
            onError(result.error || "操作失败");
            return null;
        }
        return result;
    }
    App.handleResult = handleResult;

    function showStatus(statusResult) {
        if (!statusResult) return;
        var display = document.getElementById("status-display");
        var btn = document.getElementById("toggle-pause-btn");
        display.textContent = statusResult.display || "未知";
        display.className = "status-display";
        if (statusResult.status === "running" && !statusResult.paused) {
            display.classList.add("recording");
            btn.textContent = "暂停记录";
            btn.className = "toggle-btn pause-style";
        } else {
            display.classList.add("paused");
            btn.textContent = "开始记录";
            btn.className = "toggle-btn";
        }
    }
    App.showStatus = showStatus;

    // --- Phase 3B.9: consolidation helpers (display-safe text) ---------

    function safeText(value, fallback) {
        if (value === null || value === undefined || value === "") {
            return fallback || "";
        }
        return String(value);
    }
    App.safeText = safeText;

    // --- Utility --------------------------------------------------------

    function escapeHtml(text) {
        if (text === null || text === undefined) return "";
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }
    App.escapeHtml = escapeHtml;

    function formatTimeRange(start, end, inProgress) {
        var startTxt = (start || "").slice(11, 16);
        var endTxt = (end || "").slice(11, 16);
        if (inProgress || !endTxt) {
            return startTxt + "-进行中";
        }
        return startTxt + "-" + endTxt;
    }
    App.formatTimeRange = formatTimeRange;

    function shiftDate(dateStr, days) {
        // dateStr is "YYYY-MM-DD" or null (meaning today)
        var base;
        if (!dateStr || dateStr === "--") {
            base = new Date();
        } else {
            var parts = dateStr.split("-");
            base = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        }
        base.setDate(base.getDate() + days);
        var y = base.getFullYear();
        var m = String(base.getMonth() + 1).padStart(2, "0");
        var d = String(base.getDate()).padStart(2, "0");
        return y + "-" + m + "-" + d;
    }
    App.shiftDate = shiftDate;

    function localTodayStr() {
        var d = new Date();
        var y = d.getFullYear();
        var m = String(d.getMonth() + 1).padStart(2, "0");
        var day = String(d.getDate()).padStart(2, "0");
        return y + "-" + m + "-" + day;
    }
    App.localTodayStr = localTodayStr;

    function formatDuration(seconds) {
        var s = Math.max(0, parseInt(seconds, 10) || 0);
        var h = Math.floor(s / 3600);
        var rem = s % 3600;
        var m = Math.floor(rem / 60);
        var sec = rem % 60;
        function pad(n) { return n < 10 ? "0" + n : String(n); }
        return pad(h) + ":" + pad(m) + ":" + pad(sec);
    }
    App.formatDuration = formatDuration;

    // --- Phase 6H-followup: unified projection / monotonic helpers -------
    // These helpers are shared by Overview KPI, current activity, recent,
    // Timeline total, Timeline session, and Timeline details so every live
    // target uses the same projection + monotonic-render contract.
    //
    // ``projectLiveSeconds`` computes the live display seconds from a
    // backend baseline plus the wall-clock delta since ``baselineEpochMs``.
    // It never writes the DB and never calls the bridge.
    //
    // ``readDurationSecondsFromText`` reads the ``data-duration-seconds``
    // attribute (preferred) or parses the ``HH:MM:SS`` text as a fallback.
    //
    // ``renderDurationMonotonic`` writes the formatted duration to ``el``
    // while avoiding a 1-2 second visual rollback when the same live target
    // (same ``continuityKey``) is still running. When ``allowDecrease`` is
    // false and the new seconds are 1-2 less than the last rendered value,
    // the DOM is kept unchanged. A larger decrease (real state change) or
    // ``allowDecrease === true`` always overwrites. The backend refresh
    // path must reset the monotonic state (or pass ``allowDecrease = true``)
    // so the real baseline can replace the projected value.
    function projectLiveSeconds(baseSeconds, baselineEpochMs) {
        var base = parseInt(baseSeconds, 10) || 0;
        if (base < 0) base = 0;
        if (!baselineEpochMs) return base;
        var baseline = parseInt(baselineEpochMs, 10);
        if (!baseline || isNaN(baseline)) return base;
        var delta = Math.floor((Date.now() - baseline) / 1000);
        if (delta < 0) delta = 0;
        return base + delta;
    }
    App.projectLiveSeconds = projectLiveSeconds;

    function readDurationSecondsFromText(el) {
        if (!el) return 0;
        var attr = el.getAttribute("data-duration-seconds");
        if (attr !== null && attr !== "") {
            var n = parseInt(attr, 10);
            if (!isNaN(n) && n >= 0) return n;
        }
        var text = (el.textContent || "").trim();
        var m = /^(\d+):(\d{2}):(\d{2})$/.exec(text);
        if (m) {
            return parseInt(m[1], 10) * 3600 + parseInt(m[2], 10) * 60 + parseInt(m[3], 10);
        }
        return 0;
    }
    App.readDurationSecondsFromText = readDurationSecondsFromText;

    function renderDurationMonotonic(el, nextSeconds, continuityKey, allowDecrease) {
        if (!el) return;
        var next = Math.max(0, parseInt(nextSeconds, 10) || 0);
        var state = App._monotonicRenderState;
        var entry = state[continuityKey];
        if (allowDecrease === false && entry && typeof entry.lastSeconds === "number") {
            if (next < entry.lastSeconds && (entry.lastSeconds - next) <= 2) {
                // Same live target still running; avoid 1-2s visual rollback.
                return;
            }
        }
        el.textContent = App.formatDuration(next);
        state[continuityKey] = { lastSeconds: next };
    }
    App.renderDurationMonotonic = renderDurationMonotonic;

    function resetMonotonicRenderState(continuityKey) {
        if (continuityKey) {
            delete App._monotonicRenderState[continuityKey];
        } else {
            App._monotonicRenderState = {};
        }
    }
    App.resetMonotonicRenderState = resetMonotonicRenderState;

    // --- Phase 6H-followup: 1-second heartbeat local ticker ---------------
    // ``applyLocalTicker`` is the first phase of the unified heartbeat. It
    // re-renders already-fetched durations with a wall-clock delta so the
    // UI updates every second without a bridge round-trip. The ticker ONLY
    // updates DOM text; it never calls a bridge method, never writes the DB,
    // and never starts / stops the collector. It is a no-op when the current
    // activity is paused / idle / excluded / error or when no snapshot has
    // been fetched yet. The heartbeat's second phase (revision check) runs
    // in init.js and calls heavy interfaces only when the structural
    // revision changes.
    function tickerNowEpochMs() {
        return Date.now();
    }

    function tickerDeltaSeconds(snapshot) {
        if (!snapshot) return 0;
        var snapshotAt = parseInt(snapshot.snapshot_at_epoch_ms, 10);
        if (!snapshotAt) return 0;
        var now = tickerNowEpochMs();
        var delta = Math.floor((now - snapshotAt) / 1000);
        return delta > 0 ? delta : 0;
    }

    function tickerCurrentActivityRunning(snapshot) {
        var current = snapshot && snapshot.current_activity;
        if (!current || !current.active) return false;
        if (current.is_paused) return false;
        return true;
    }

    function applyLocalTicker() {
        // Overview page: update KPI total + classified + uncategorized +
        // current activity display. total / classified / uncategorized
        // must use the same delta so the KPIs stay consistent. The delta
        // is added to EITHER classified OR uncategorized (never both)
        // depending on the current activity's classification state.
        var ov = App.lastOverviewSnapshot;
        if (ov && App.currentPage === "overview") {
            var delta = 0;
            var currentIsUncategorized = true;
            if (tickerCurrentActivityRunning(ov)) {
                delta = tickerDeltaSeconds(ov);
            }
            var current = ov.current_activity || {};
            if (current.is_classified === true) {
                currentIsUncategorized = false;
            } else if (current.is_uncategorized === true) {
                currentIsUncategorized = true;
            } else {
                currentIsUncategorized = null;
            }
            var totalEl = document.getElementById("kpi-total");
            if (totalEl) {
                var totalSec = parseInt(ov.today_total_seconds, 10) || 0;
                App.renderDurationMonotonic(totalEl, totalSec + delta, "overview-total", false);
            }
            var classifiedEl = document.getElementById("kpi-classified");
            if (classifiedEl) {
                var classifiedSec = parseInt(ov.classified_seconds, 10) || 0;
                if (currentIsUncategorized === false) {
                    classifiedSec += delta;
                }
                App.renderDurationMonotonic(classifiedEl, classifiedSec, "overview-classified", false);
            }
            var uncategorizedEl = document.getElementById("kpi-uncategorized");
            if (uncategorizedEl) {
                var uncategorizedSec = parseInt(ov.uncategorized_seconds, 10) || 0;
                if (currentIsUncategorized === true) {
                    uncategorizedSec += delta;
                }
                App.renderDurationMonotonic(uncategorizedEl, uncategorizedSec, "overview-uncategorized", false);
            }
            var currentEl = document.getElementById("current-activity");
            if (currentEl) {
                if (current.active) {
                    var elapsedSec = parseInt(current.elapsed_seconds, 10) || 0;
                    var display = current.display || "";
                    var parts = display.split("｜");
                    if (parts.length >= 3) {
                        parts[2] = App.formatDuration(elapsedSec + delta);
                        currentEl.textContent = "当前活动：" + parts.join("｜");
                    }
                } else {
                    currentEl.textContent = "当前活动：无";
                }
            }
        }
        // Recent list: update the live-projected recent item's duration.
        // Only when the overview page is active and a recent snapshot with a
        // live projection target is available.
        var recent = App.lastRecentSnapshot;
        if (recent && App.currentPage === "overview") {
            var recentDelta = tickerDeltaSeconds(recent);
            var projectedIndex = parseInt(recent.live_projected_recent_index, 10);
            if (projectedIndex >= 0 && recentDelta >= 0) {
                var recentEl = document.querySelector('.recent-item[data-recent-index="' + projectedIndex + '"] .recent-item-duration');
                if (recentEl) {
                    var baseSec = App.readDurationSecondsFromText(recentEl);
                    // ``live_projected_seconds`` is the backend baseline; add
                    // the wall-clock delta on top. ``baseSec`` already
                    // includes the projection baseline (the backend added it
                    // to the target item's ``duration_seconds``), so we only
                    // add the delta here.
                    var projectedSec = baseSec + recentDelta;
                    App.renderDurationMonotonic(recentEl, projectedSec, "recent-" + projectedIndex, false);
                }
            }
        }
        // Timeline page: update date total + current activity display +
        // in-progress / live-projected session duration + projected detail.
        // Only when viewing today.
        var tl = App.lastTimelineData;
        if (tl && App.currentPage === "timeline") {
            var todayStr = App.localTodayStr();
            var isToday = !tl.date || tl.date === todayStr || tl.date === "--";
            var tlDelta = 0;
            if (isToday && tickerCurrentActivityRunning(tl)) {
                tlDelta = tickerDeltaSeconds(tl);
            }
            var tlTotalEl = document.getElementById("timeline-total");
            if (tlTotalEl) {
                var tlTotalSec = parseInt(tl.today_total_seconds, 10) || 0;
                App.renderDurationMonotonic(tlTotalEl, tlTotalSec + tlDelta, "timeline-total", false);
            }
            var tlCurrentEl = document.getElementById("timeline-current");
            if (tlCurrentEl) {
                var tlCurrent = tl.current_activity || {};
                if (tlCurrent.active) {
                    var tlElapsedSec = parseInt(tlCurrent.elapsed_seconds, 10) || 0;
                    var tlDisplay = tlCurrent.display || "";
                    var tlParts = tlDisplay.split("｜");
                    if (tlParts.length >= 3) {
                        tlParts[2] = App.formatDuration(tlElapsedSec + tlDelta);
                        tlCurrentEl.textContent = "当前活动：" + tlParts.join("｜");
                    }
                } else {
                    tlCurrentEl.textContent = "当前活动：无";
                }
            }
            // Update in-progress / live-projected session durations.
            // Phase 6H-followup section 7.3: locate each session's DOM via
            // ``data-session-id`` instead of array index so a re-rendered
            // list (e.g. after a revision change) cannot mismatch sessions.
            if (isToday && tlDelta >= 0 && tl.sessions) {
                for (var si = 0; si < tl.sessions.length; si++) {
                    var s = tl.sessions[si];
                    if (s.is_in_progress || s.is_live_projected) {
                        var sid = s.session_id;
                        var itemEl = document.querySelector(
                            '#timeline-sessions-list .timeline-item[data-session-id="' + sid + '"]'
                        );
                        if (itemEl) {
                            var durEl = itemEl.querySelector(".timeline-item-duration");
                            if (durEl) {
                                var sSec = parseInt(s.duration_seconds, 10) || 0;
                                var continuity = "session-" + sid;
                                App.renderDurationMonotonic(durEl, sSec + tlDelta, continuity, false);
                            }
                        }
                    }
                }
            }
            // Phase 6H-followup section 7.4: detail-row projection. Two
            // cases are handled:
            //   (a) selected session is a real ``is_in_progress`` session:
            //       update that session's ``a.is_in_progress`` detail row.
            //   (b) selected session equals ``live_projected_session_id`` and
            //       the current activity is not yet persisted: temporarily
            //       update the latest detail row.
            // In both cases, skip when an editor / split editor / correction
            // shell write is in progress so the user's input focus and
            // button state are never disturbed.
            if (isToday && tlDelta >= 0 && App.selectedSessionId
                && App.lastSessionDetailsData && !App._timelineEditingActive()) {
                var detailsList = document.getElementById("timeline-details-list");
                if (detailsList) {
                    // Case (a): real is_in_progress session. Find the
                    // detail row whose activity_id matches the in-progress
                    // activity and update its duration.
                    var selectedSessionObj = null;
                    for (var ssi = 0; ssi < tl.sessions.length; ssi++) {
                        if (tl.sessions[ssi].session_id === App.selectedSessionId) {
                            selectedSessionObj = tl.sessions[ssi];
                            break;
                        }
                    }
                    if (selectedSessionObj && selectedSessionObj.is_in_progress) {
                        var inProgressRows = detailsList.querySelectorAll(
                            '.detail-item.in-progress .detail-item-duration'
                        );
                        if (inProgressRows.length > 0) {
                            var ipDurEl = inProgressRows[inProgressRows.length - 1];
                            var ipBaseSec = App.readDurationSecondsFromText(ipDurEl);
                            var ipAid = ipDurEl.closest(".detail-item").getAttribute("data-activity-id") || "0";
                            App.renderDurationMonotonic(
                                ipDurEl, ipBaseSec + tlDelta, "detail-" + ipAid, false
                            );
                        }
                    }
                    // Case (b): live-projected session. The current activity
                    // is not yet persisted, so the latest detail row gets
                    // projection baseline + delta on top of its real duration.
                    var projectedSessionId = tl.live_projected_session_id || "";
                    if (projectedSessionId && App.selectedSessionId === projectedSessionId) {
                        var detailRows = detailsList.querySelectorAll(".detail-item");
                        if (detailRows.length > 0) {
                            var latestRow = detailRows[detailRows.length - 1];
                            var detailDurEl = latestRow.querySelector(".detail-item-duration");
                            if (detailDurEl) {
                                var detailBaseSec = App.readDurationSecondsFromText(detailDurEl);
                                var projectedBaseSec = parseInt(tl.live_projected_seconds, 10) || 0;
                                var detailProjectedSec = detailBaseSec + projectedBaseSec + tlDelta;
                                var latestAid = latestRow.getAttribute("data-activity-id") || "0";
                                App.renderDurationMonotonic(detailDurEl, detailProjectedSec, "detail-" + latestAid, false);
                            }
                        }
                    }
                }
            }
        }
    }
    App.applyLocalTicker = applyLocalTicker;

    // Phase 6H-followup section 7.4: helper that reports whether any
    // Timeline editing / split / correction-shell write is in progress.
    // The ticker uses this to skip detail-row duration updates that could
    // race with the user's input or with a save / split / restore operation.
    // The ticker only ever modifies ``.detail-item-duration`` text, so when
    // an editor is open the row's text is intentionally left untouched.
    function timelineEditingActive() {
        return !!(
            App.editSaving ||
            App.timeSaving ||
            App.activityTimeSaving ||
            App.sessionSplitSaving ||
            App.activitySplitSaving ||
            App.mergeSaving ||
            App.hideSaving ||
            App.deleteSaving ||
            App.batchProjectSaving ||
            App.batchNoteSaving ||
            App.restoreSaving ||
            App.correctionShellOpen
        );
    }
    App._timelineEditingActive = timelineEditingActive;

    // Backend stores time as "YYYY-MM-DD HH:MM:SS". <input type="datetime-local">
    // uses "YYYY-MM-DDTHH:MM:SS" (T separator). These helpers convert between
    // the two fixed formats without relying on Date parsing.
    function backendToDatetimeLocal(value) {
        if (!value || typeof value !== "string") return "";
        return value.replace(" ", "T");
    }
    App.backendToDatetimeLocal = backendToDatetimeLocal;

    function datetimeLocalToBackend(value) {
        if (!value || typeof value !== "string") return "";
        return value.replace("T", " ");
    }
    App.datetimeLocalToBackend = datetimeLocalToBackend;

    function midpointTime(startVal, endVal) {
        if (!startVal || !endVal) return "";
        var s = parseBackendTimeParts(startVal);
        var e = parseBackendTimeParts(endVal);
        if (!s || !e) return "";
        var midMs = (s.ts + e.ts) / 2;
        var d = new Date(midMs);
        return formatUtcParts(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate(),
            d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds());
    }
    App.midpointTime = midpointTime;

    function parseBackendTimeParts(value) {
        var m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/.exec(value || "");
        if (!m) return null;
        var ts = Date.UTC(
            parseInt(m[1], 10),
            parseInt(m[2], 10) - 1,
            parseInt(m[3], 10),
            parseInt(m[4], 10),
            parseInt(m[5], 10),
            parseInt(m[6], 10)
        );
        return { ts: ts };
    }
    App.parseBackendTimeParts = parseBackendTimeParts;

    function formatUtcParts(y, mo, d, h, mi, s) {
        function pad(n) { return n < 10 ? "0" + n : String(n); }
        return y + "-" + pad(mo) + "-" + pad(d) + " " + pad(h) + ":" + pad(mi) + ":" + pad(s);
    }
    App.formatUtcParts = formatUtcParts;

})();
