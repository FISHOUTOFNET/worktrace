// WorkTrace WebView frontend — core module (Phase R2 split).
// Namespace + shared state + bridge helper + generic helpers + date/time/format utils.
// Only communicates with Python through pywebview API bridge.
// Does not persist sensitive data in browser storage APIs.
// Does not access any external network resources.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Module-level state (single source of truth across all js modules) ---
    App.REFRESH_INTERVAL_MS = 8000;
    App.NOTE_MAX_LENGTH = 2000;
    App.refreshTimer = null;

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
