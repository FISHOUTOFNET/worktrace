// WorkTrace WebView frontend core module. Only communicates with Python through the pywebview API bridge.
// Does not persist sensitive data in browser storage APIs. Does not access any external network resources.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // 1s heartbeat: local ticker re-renders fetched durations with a wall-clock delta, then a lightweight
    // ``get_refresh_state`` revision check. Heavy interfaces run only on structural revision change.
    App.HEARTBEAT_INTERVAL_MS = 1000;
    App.NOTE_MAX_LENGTH = 2000;
    App.heartbeatTimer = null;

    // Ticker invariant: ONLY updates DOM text; never calls a bridge method, never writes the DB,
    // never starts / stops the collector. Render flows seed static bases and active-elapsed
    // offsets; the heartbeat may only advance the page-scoped active span clock.
    App.lastOverviewSnapshot = null;
    // Structural caches only — used to re-render lists on page switch / edit-guard checks. They
    // MUST NOT participate in live-row seconds computation. ``applyLocalTicker`` reads static
    // bases / active-elapsed offsets from the DOM and the one page-scoped active span clock.
    App.lastRecentData = null;
    App.lastSessionDetailsViewModel = null;
    App.lastTimelineData = null;

    // Canonical active span clocks. There is one dynamic project-duration clock per visible page
    // scope; rows and KPIs never own their own complete clock. ``liveClockBySpanId`` is retained
    // only as a compatibility mirror for diagnostics/tests and is not used by the ticker to
    // compute row durations.
    App.liveClockBySpanId = {};
    App.liveDisplayModel = null;
    App.activeDisplaySpanId = "";
    App.activeSpanClockByPage = {};
    App.activeElapsedAnchorByPage = {};
    // Compatibility alias for older callers; do not use this as a row clock registry.
    App.liveClockByPage = App.activeSpanClockByPage;
    App.activeDisplaySpanIdByPage = {};
    App.currentActivityClockByPage = {};
    App.currentActivityContinuityKeyByPage = {};
    App.liveClockContractViolation = null;
    App.liveClockContractRefreshRequested = false;

    // ``lastRefreshState`` caches the last ``get_refresh_state`` payload for revision comparison;
    // ``refreshCheckInFlight`` / ``activePageRefreshInFlight`` guard overlapping checks / refreshes.
    App.lastRefreshState = null;
    App.refreshCheckInFlight = false;
    App.activePageRefreshInFlight = false;
    // Pending page refresh: records a request made while a refresh is in-flight; after completion a new
    // refresh is triggered if true so a page-switch refresh is never silently skipped by the in-flight guard.
    App.pendingPageRefresh = false;
    App.lastFullRefreshAtEpochMs = 0;
    App.RECONCILE_INTERVAL_MS = 180000;
    App.lastReconcileAtEpochMs = 0;
    App.reconcileInFlight = false;

    // Maps a continuity key to the last rendered seconds. Same live continuity never visually rolls
    // back; closed / historical rows opt into factual backend overwrites.
    App._monotonicRenderState = {};

    App.currentPage = "overview";
    App.timelineDate = null;
    App.timelineLoaded = false;
    App.timelineLoading = false;
    App.selectedSessionId = null;
    // Stable live key for the selected session. Selection continuity: stable_live_key_hash stays the same
    // when session_id changes across the virtual / persisted_open / absorbed_pending transitions.
    App.selectedSessionLiveKey = null;

    // races a manual refresh.
    App.timelineRequestToken = 0;
    App.detailsRequestToken = 0;
    App.overviewRequestToken = 0;
    App.recentRequestToken = 0;

    App.projectsCache = null;
    App.projectsLoading = false;
    App.currentSessions = [];
    App.editingSession = null;
    App.editSaving = false;

    App.timeSaving = false;
    App.editingActivityId = null;
    App.activityTimeSaving = false;

    App.sessionSplitSaving = false;
    App.editingSplitActivityId = null;
    App.activitySplitSaving = false;

    App.mergeSaving = false;
    App.mergingActivityId = null;

    App.hideSaving = false;
    App.hidingActivityId = null;
    App.deleteSaving = false;
    App.deletingActivityId = null;

    App.correctionShellOpen = false;
    App.correctionShellSessionId = null;
    App.correctionShellActivityId = null;
    App.correctionShellMode = null;
    App.correctionShellHighlightTimer = null;
    App.selectedBatchActivityIds = {};
    App.batchProjectSaving = false;
    App.batchProjectTargetId = null;
    App.batchNoteSaving = false;
    App.restoreSaving = false;
    App.restoreSavingActivityId = null;

    App.statisticsLoaded = false;
    App.statisticsLoading = false;
    App.statisticsRequestToken = 0;
    App.statisticsExportSaving = false;

    // A single read-only load is in flight at a time; the request token
    // guards against stale responses on rapid re-entry.
    App.settingsLoaded = false;
    App.settingsLoading = false;
    App.settingsRequestToken = 0;
    // Capture toggle write state. Separate from settingsLoading (read) so a
    // write in flight never pollutes the read-state guard. While true, both
    // the refresh button and the capture toggle are disabled.
    App.settingsWriteInProgress = false;
    // Encrypted backup export + manifest preview state. Separate from the
    // capture toggle so backup operations and toggle writes cannot overlap.
    // While either is true, the backup controls are disabled.
    App.settingsBackupExportInProgress = false;
    App.settingsBackupManifestInProgress = false;
    // Backup import + clear-all state. Separate from backup manifest preview,
    // export, and capture toggle writes so Settings operations stay mutually
    // exclusive. While either is true, every Settings control is disabled.
    App.settingsBackupImportInProgress = false;
    App.settingsClearAllInProgress = false;

    // First-run privacy notice state
    App.firstRunNoticeLoaded = false;
    App.firstRunNoticeLoading = false;
    App.firstRunNoticeRequired = false;
    App.firstRunNoticeAcceptInProgress = false;
    App.firstRunNoticeViewingFromSettings = false;

    App.rulesLoaded = false;
    App.rulesLoading = false;
    App.rulesRequestToken = 0;
    App.rulesSortMode = "last_used";

    // Keyword rule delete in-flight: carries the "keyword:<id>" key of the
    // row being deleted so only that row's button enters deleting state.
    App.rulesDeletingRuleKey = null;

    // Folder rule delete in-flight: carries the "folder:<id>" key of the
    // row being deleted so only that row's button enters deleting state.
    App.rulesDeletingFolderKey = null;

    // Cache of the last-loaded Project Rules data so the unified panel and
    // the advanced excluded-rules panel can re-render without a round-trip
    // through loadProjectRules (which would lose input focus).
    App.lastProjectRulesData = null;

    // Created-rule backfill in-flight: carries the "<kind>:<id>" key while
    // the optional "apply to history" step runs after a rule is created.
    App.rulesBackfillingRuleKey = null;

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


    function callBridge(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        if (typeof window.pywebview === "undefined" || !window.pywebview.api) {
            return Promise.reject(new Error("bridge unavailable"));
        }
        return window.pywebview.api[method].apply(window.pywebview.api, args);
    }
    App.callBridge = callBridge;


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


    function safeText(value, fallback) {
        if (value === null || value === undefined || value === "") {
            return fallback || "";
        }
        return String(value);
    }
    App.safeText = safeText;


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

    // Display-only start time (HH:MM) extracted from a backend
    // "YYYY-MM-DD HH:MM:SS" timestamp.
    function formatStartTimeOnly(start_time) {
        return (start_time || "").slice(11, 16);
    }
    App.formatStartTimeOnly = formatStartTimeOnly;

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

    // Shared render contract for every live duration target.
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

    function renderDurationProjected(el, seconds, continuityKey, options) {
        if (!el) return;
        var opts = options || {};
        var allowDecrease = opts.allowDecrease === true;
        var key = String(continuityKey || "");
        var next = Math.max(0, parseInt(seconds, 10) || 0);
        var state = App._monotonicRenderState;
        var entry = key ? state[key] : null;
        if (!allowDecrease && entry && typeof entry.lastSeconds === "number" && next < entry.lastSeconds) {
            next = entry.lastSeconds;
        }
        el.textContent = App.formatDuration(next);
        el.setAttribute("data-duration-seconds", String(next));
        if (key) {
            state[key] = { lastSeconds: next };
        }
    }
    App.renderDurationProjected = renderDurationProjected;

    function renderDurationMonotonic(el, nextSeconds, continuityKey, allowDecrease) {
        renderDurationProjected(el, nextSeconds, continuityKey, { allowDecrease: allowDecrease === true });
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

    // Unified project label contract: ``name`` if description empty, else ``name（description）``
    // using full-width Chinese parens with no surrounding space, consistent across all rendered rows.
    function formatProjectLabel(name, description) {
        var n = String(name || "").trim();
        if (!n) n = "未归类";
        var d = String(description || "").trim();
        if (!d) return n;
        return n + "（" + d + "）";
    }
    App.formatProjectLabel = formatProjectLabel;

    // ===== Active Span Anchored Projection =====
    //
    // The only dynamic project-duration time source is the page-scoped active
    // span clock. Recent rows, Timeline sessions/details, KPI totals, and
    // Timeline total store a static base plus the active elapsed value observed
    // when that base was rendered.
    //
    // Active elapsed:
    //     carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)
    //
    // Live display:
    //     base_seconds_at_render + max(0, active_elapsed_now - active_elapsed_at_render)

    function tickerNowEpochMs() {
        return Date.now();
    }

    function nonNegativeInt(value, fallback) {
        var n = parseInt(value, 10);
        if (isNaN(n) || n < 0) return fallback || 0;
        return n;
    }

    function normalizeLiveClock(clock) {
        if (!clock || typeof clock !== "object") return null;
        var durationAtSample = nonNegativeInt(
            clock.duration_seconds_at_sample,
            nonNegativeInt(clock.duration_seconds, 0)
        );
        var projectDurationLive = clock.project_duration_live === true
            || clock.is_project_duration_live === true;
        var currentDurationLive = clock.current_duration_live === true;
        return Object.assign({}, clock, {
            display_span_id: String(clock.display_span_id || ""),
            stable_live_key: String(clock.stable_live_key || ""),
            stable_live_key_hash: String(clock.stable_live_key_hash || ""),
            live_state: String(clock.live_state || "none"),
            duration_seconds_at_sample: durationAtSample,
            carry_seconds: nonNegativeInt(clock.carry_seconds, 0),
            live_started_at_epoch_ms: nonNegativeInt(clock.live_started_at_epoch_ms, 0),
            is_live: clock.is_live === true,
            is_project_duration_live: projectDurationLive,
            project_duration_live: projectDurationLive,
            current_duration_live: currentDurationLive,
        });
    }
    App.normalizeLiveClock = normalizeLiveClock;

    function recordLiveClockContractViolation(spanId, page, reason) {
        App.liveClockContractViolation = {
            spanId: String(spanId || ""),
            page: String(page || App.currentPage || ""),
            reason: String(reason || "missing_live_clock"),
            at: Date.now()
        };
        App.liveClockContractRefreshRequested = true;
    }
    App.recordLiveClockContractViolation = recordLiveClockContractViolation;

    function projectClockSeconds(clock, nowMs) {
        var c = normalizeLiveClock(clock);
        if (!c) return 0;
        var startedAt = c.live_started_at_epoch_ms;
        if (!startedAt) return c.duration_seconds_at_sample;
        var now = nonNegativeInt(nowMs, tickerNowEpochMs());
        var elapsed = Math.floor((now - startedAt) / 1000);
        var seconds = c.carry_seconds + elapsed;
        return seconds > 0 ? seconds : 0;
    }
    App.projectClockSeconds = projectClockSeconds;

    function activeElapsedNow(clock, nowMs) {
        var c = normalizeLiveClock(clock);
        if (!c) return 0;
        var activeSample = null;
        if (clock && clock.current_elapsed_at_sample !== undefined
            && clock.current_elapsed_at_sample !== null) {
            activeSample = nonNegativeInt(clock.current_elapsed_at_sample, 0);
        } else if (clock && clock.active_elapsed_at_sample !== undefined
            && clock.active_elapsed_at_sample !== null) {
            activeSample = nonNegativeInt(clock.active_elapsed_at_sample, 0);
        }
        if (activeSample !== null) {
            if (!c.live_started_at_epoch_ms) return activeSample;
            var now = nonNegativeInt(nowMs, tickerNowEpochMs());
            var elapsed = Math.floor((now - c.live_started_at_epoch_ms) / 1000);
            if (elapsed < 0) elapsed = 0;
            return elapsed > activeSample ? elapsed : activeSample;
        }
        return projectClockSeconds(c, nowMs);
    }
    App.activeElapsedNow = activeElapsedNow;

    function activeElapsedAtSample(clock) {
        var c = normalizeLiveClock(clock);
        if (!c) return 0;
        if (clock && clock.current_elapsed_at_sample !== undefined
            && clock.current_elapsed_at_sample !== null) {
            return nonNegativeInt(clock.current_elapsed_at_sample, 0);
        }
        if (clock && clock.active_elapsed_seconds_at_sample !== undefined
            && clock.active_elapsed_seconds_at_sample !== null) {
            return nonNegativeInt(clock.active_elapsed_seconds_at_sample, 0);
        }
        if (clock && clock.active_elapsed_at_sample !== undefined
            && clock.active_elapsed_at_sample !== null) {
            return nonNegativeInt(clock.active_elapsed_at_sample, 0);
        }
        return c.duration_seconds_at_sample;
    }
    App.activeElapsedAtSample = activeElapsedAtSample;

    function projectFromActiveElapsed(baseSecondsAtRender, activeElapsedAtRender, activeClock, nowMs, activeElapsedNowSample) {
        var nowElapsed = (typeof activeElapsedNowSample === "number")
            ? activeElapsedNowSample
            : activeElapsedNow(activeClock, nowMs);
        var delta = nowElapsed - nonNegativeInt(activeElapsedAtRender, 0);
        if (delta < 0) delta = 0;
        return nonNegativeInt(baseSecondsAtRender, 0) + delta;
    }
    App.projectFromActiveElapsed = projectFromActiveElapsed;

    function sameLiveContinuity(previousClock, incomingClock) {
        var prev = normalizeLiveClock(previousClock);
        var incoming = normalizeLiveClock(incomingClock);
        if (!prev || !incoming) return false;
        if (prev.display_span_id && incoming.display_span_id
            && prev.display_span_id === incoming.display_span_id) {
            return true;
        }
        return !!(prev.stable_live_key_hash && incoming.stable_live_key_hash
            && prev.stable_live_key_hash === incoming.stable_live_key_hash);
    }
    App.sameLiveContinuity = sameLiveContinuity;

    function rebaseIncomingClockWithoutRollback(previousClock, incomingClock, nowMs) {
        var incoming = normalizeLiveClock(incomingClock);
        if (!incoming) return null;
        var previous = normalizeLiveClock(previousClock);
        if (!previous || !sameLiveContinuity(previous, incoming)) return incoming;
        var now = nonNegativeInt(nowMs, tickerNowEpochMs());
        var previousSeconds = projectClockSeconds(previous, now);
        var incomingSeconds = projectClockSeconds(incoming, now);
        if (incomingSeconds >= previousSeconds) return incoming;
        var rebased = Object.assign({}, incoming);
        if (rebased.live_started_at_epoch_ms > 0) {
            var elapsed = Math.floor((now - rebased.live_started_at_epoch_ms) / 1000);
            if (elapsed < 0) elapsed = 0;
            rebased.carry_seconds = Math.max(0, previousSeconds - elapsed);
        } else {
            rebased.duration_seconds_at_sample = previousSeconds;
        }
        return normalizeLiveClock(rebased);
    }
    App.rebaseIncomingClockWithoutRollback = rebaseIncomingClockWithoutRollback;

    function findClockInPayload(payload, preferCurrent) {
        if (!payload) return null;
        if (preferCurrent && payload.current_activity_clock) return payload.current_activity_clock;
        if (preferCurrent && payload.activity_display_model && payload.activity_display_model.current_activity_clock) {
            return payload.activity_display_model.current_activity_clock;
        }
        if (preferCurrent && payload.current_activity && payload.current_activity.current_activity_clock) {
            return payload.current_activity.current_activity_clock;
        }
        if (payload.live_clock) return payload.live_clock;
        if (payload.activity_display_model && payload.activity_display_model.live_clock) {
            return payload.activity_display_model.live_clock;
        }
        if (!preferCurrent && payload.current_activity_clock) return payload.current_activity_clock;
        return null;
    }

    function isProjectDurationClock(clock) {
        var c = normalizeLiveClock(clock);
        return !!(c && c.display_span_id && c.project_duration_live === true);
    }

    function isCurrentDurationClock(clock) {
        var c = normalizeLiveClock(clock);
        return !!(c && (
            c.current_duration_live === true
            || clock.current_elapsed_at_sample !== undefined
            || clock.active_elapsed_at_sample !== undefined
        ));
    }

    function mirrorActiveSpanClockForCompatibility(pageScope, clock) {
        var storedClock = normalizeLiveClock(clock);
        if (!storedClock || !storedClock.display_span_id) return;
        var spanId = storedClock.display_span_id;
        var pageActiveSpanId = App.activeDisplaySpanIdByPage[pageScope] || "";
        if (pageActiveSpanId && pageActiveSpanId !== spanId && App.liveClockBySpanId[pageActiveSpanId]) {
            delete App.liveClockBySpanId[pageActiveSpanId];
        }
        App.liveClockBySpanId[spanId] = storedClock;
        App.activeDisplaySpanIdByPage[pageScope] = spanId;
        if (pageScope === App.currentPage) {
            App.activeDisplaySpanId = spanId;
        }
    }

    function commitPageActiveSpanClock(payload, page) {
        var pageScope = String(page || App.currentPage || "overview");
        var incomingClock = normalizeLiveClock(findClockInPayload(payload, false));
        if (!isProjectDurationClock(incomingClock)) {
            clearPageActiveSpanClockFromPageModel(payload, pageScope);
            return null;
        }
        var activeClock = App.activeSpanClockByPage[pageScope] || null;
        var sameContinuity = sameLiveContinuity(activeClock, incomingClock);
        var isCurrentPageScope = (pageScope === App.currentPage);
        if (isCurrentPageScope && activeClock && !sameContinuity) {
            App._monotonicRenderState = {};
        }
        var storedClock = rebaseIncomingClockWithoutRollback(activeClock, incomingClock, tickerNowEpochMs());
        App.activeSpanClockByPage[pageScope] = storedClock;
        App.activeElapsedAnchorByPage[pageScope] = activeElapsedNow(storedClock, tickerNowEpochMs());
        mirrorActiveSpanClockForCompatibility(pageScope, storedClock);
        if (payload.activity_display_model) {
            App.liveDisplayModel = payload.activity_display_model;
        } else {
            App.liveDisplayModel = payload;
        }
        return storedClock;
    }
    App.commitPageActiveSpanClock = commitPageActiveSpanClock;

    function observeRefreshStateActiveSpan(payload, page) {
        var pageScope = String(page || App.currentPage || "overview");
        var incomingClock = normalizeLiveClock(findClockInPayload(payload, false));
        if (!isProjectDurationClock(incomingClock)) {
            return App.activeSpanClockByPage[pageScope] || null;
        }
        var activeClock = App.activeSpanClockByPage[pageScope] || null;
        if (activeClock && !sameLiveContinuity(activeClock, incomingClock)) {
            return activeClock;
        }
        var storedClock = rebaseIncomingClockWithoutRollback(activeClock, incomingClock, tickerNowEpochMs());
        App.activeSpanClockByPage[pageScope] = storedClock;
        App.activeElapsedAnchorByPage[pageScope] = activeElapsedNow(storedClock, tickerNowEpochMs());
        mirrorActiveSpanClockForCompatibility(pageScope, storedClock);
        if (payload && payload.activity_display_model) {
            App.liveDisplayModel = payload.activity_display_model;
        }
        return storedClock;
    }
    App.observeRefreshStateActiveSpan = observeRefreshStateActiveSpan;

    function commitPartialActiveSpanOffset(payload, page) {
        var pageScope = String(page || App.currentPage || "overview");
        var clock = normalizeLiveClock(findClockInPayload(payload, false))
            || App.activeSpanClockByPage[pageScope] || null;
        return activeElapsedNow(clock, tickerNowEpochMs());
    }
    App.commitPartialActiveSpanOffset = commitPartialActiveSpanOffset;

    function clearPageActiveSpanClockFromPageModel(payload, page) {
        var pageScope = String(page || App.currentPage || "overview");
        clearLiveClockRegistry(pageScope);
    }
    App.clearPageActiveSpanClockFromPageModel = clearPageActiveSpanClockFromPageModel;

    // Compatibility wrapper. New code should call the source-specific helpers above.
    function registerLiveClock(payload, options) {
        var opts = options || {};
        var source = String(opts.source || "page_model");
        var pageScope = String(opts.page || App.currentPage || "overview");
        if (source === "refresh_state") {
            return observeRefreshStateActiveSpan(payload, pageScope);
        }
        if (source === "partial_details") {
            return commitPartialActiveSpanOffset(payload, pageScope);
        }
        return commitPageActiveSpanClock(payload, pageScope);
    }
    App.registerLiveClock = registerLiveClock;

    function registerCurrentActivityClock(payload, options) {
        var opts = options || {};
        var pageScope = String(opts.page || App.currentPage || "overview");
        var incomingClock = normalizeLiveClock(findClockInPayload(payload, true));
        if (!isCurrentDurationClock(incomingClock)) {
            delete App.currentActivityClockByPage[pageScope];
            delete App.currentActivityContinuityKeyByPage[pageScope];
            return;
        }
        var prev = App.currentActivityClockByPage[pageScope] || null;
        var prevKey = App.currentActivityContinuityKeyByPage[pageScope] || currentActivityContinuityKey(null, prev, pageScope);
        var incomingKey = currentActivityContinuityKey(null, incomingClock, pageScope);
        var sameCurrentContinuity = !!(prev && prevKey && incomingKey && prevKey === incomingKey);
        if (pageScope === App.currentPage && prev && !sameCurrentContinuity && prevKey) {
            App.resetMonotonicRenderState(prevKey);
        }
        App.currentActivityClockByPage[pageScope] = sameCurrentContinuity
            ? rebaseIncomingClockWithoutRollback(prev, incomingClock, tickerNowEpochMs())
            : incomingClock;
        App.currentActivityContinuityKeyByPage[pageScope] = incomingKey;
        if (payload && payload.activity_display_model) {
            App.liveDisplayModel = payload.activity_display_model;
        }
    }
    App.registerCurrentActivityClock = registerCurrentActivityClock;

    function getActiveCurrentActivityClock() {
        var page = App.currentPage || "overview";
        return App.currentActivityClockByPage[page] || null;
    }
    App.getActiveCurrentActivityClock = getActiveCurrentActivityClock;

    // Return the canonical active span clock for a page scope, or ``null``.
    // Rows never look up their own clocks by span id; they project their
    // static base from this one page active elapsed source.
    function getActiveLiveClock(pageScope) {
        var page = pageScope || App.currentPage || "overview";
        return App.activeSpanClockByPage[page] || null;
    }
    App.getActiveLiveClock = getActiveLiveClock;

    // Clear the live-clock registry. When ``pageScope`` is provided, only
    // that scope's clock is cleared; the current page's active clock is
    // untouched when clearing a non-current scope. When ``pageScope`` is
    // omitted, ALL scopes are cleared (legacy behavior).
    function clearLiveClockRegistry(pageScope) {
        if (pageScope) {
            var spanId = App.activeDisplaySpanIdByPage[pageScope] || "";
            if (spanId && App.liveClockBySpanId[spanId]) {
                delete App.liveClockBySpanId[spanId];
            }
            delete App.activeSpanClockByPage[pageScope];
            delete App.activeElapsedAnchorByPage[pageScope];
            delete App.activeDisplaySpanIdByPage[pageScope];
            // Only clear the global active fields when the cleared scope is
            // the current page; a hidden-page clear MUST NOT touch the
            // current page's active clock.
            if (pageScope === App.currentPage) {
                App.activeDisplaySpanId = "";
                App.liveDisplayModel = null;
            }
            return;
        }
        App.liveClockBySpanId = {};
        App.activeSpanClockByPage = {};
        App.liveClockByPage = App.activeSpanClockByPage;
        App.activeElapsedAnchorByPage = {};
        App.currentActivityClockByPage = {};
        App.currentActivityContinuityKeyByPage = {};
        App.activeDisplaySpanIdByPage = {};
        App.liveDisplayModel = null;
        App.activeDisplaySpanId = "";
    }
    App.clearLiveClockRegistry = clearLiveClockRegistry;

    // SINGLE SOURCE OF TRUTH for live-row continuity keys. Uses ``stable_live_key_hash`` so the key
    // survives the virtual / persisted_open / absorbed_pending transitions (session_id / activity_id
    // change across the transition; stable_live_key_hash does not).
    //
    // The same key MUST be used for both render seeding and ticker updates —
    // a mismatch (e.g. render seeds ``recent:live:<hash>`` while the ticker
    // reads ``span:<spanId>``) breaks the monotonic guard. The ticker reads
    // the seeded key directly from the DOM's ``data-live-continuity-key``
    // attribute so render and ticker stay in lockstep.
    function liveContinuityKey(item, prefix) {
        if (!item) return prefix;
        if (item.stable_live_key_hash) {
            return prefix + ":live:" + item.stable_live_key_hash;
        }
        if (item.display_span_id) {
            return prefix + ":span:" + item.display_span_id;
        }
        if (item.session_id) {
            return prefix + ":" + item.session_id;
        }
        if (item.activity_id) {
            return prefix + ":" + item.activity_id;
        }
        return prefix;
    }
    App.liveContinuityKey = liveContinuityKey;

    function currentActivityContinuityKey(current, clock, prefix) {
        var identity = "";
        if (clock && clock.current_resource_identity_hash) {
            identity = clock.current_resource_identity_hash;
        } else if (clock && clock.current_activity_display_span_id) {
            identity = clock.current_activity_display_span_id;
        } else if (clock && clock.display_span_id) {
            identity = clock.display_span_id;
        } else if (current && current.current_activity_display_span_id) {
            identity = current.current_activity_display_span_id;
        } else if (current && current.start_time) {
            identity = String(current.resource_name || current.app_name || "current")
                + ":" + String(current.start_time || "");
        } else if (current && current.stable_live_key_hash) {
            identity = current.stable_live_key_hash;
        }
        return prefix + ":current:" + (identity || "none");
    }
    App.currentActivityContinuityKey = currentActivityContinuityKey;

    function renderCurrentActivityElement(el, current, currentClock, prefix) {
        if (!el) return;
        current = current || {};
        if (!current.active) {
            el.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a\u65e0";
            return;
        }
        var display = current.display || "";
        var seconds = parseInt(current.elapsed_seconds, 10) || 0;
        if (currentClock && (currentClock.current_duration_live === true || currentClock.is_live === true)) {
            seconds = projectClockSeconds(currentClock, tickerNowEpochMs());
        }
        var continuity = currentActivityContinuityKey(current, currentClock, prefix);
        var previousContinuity = el.getAttribute("data-current-continuity-key") || "";
        if (previousContinuity && previousContinuity !== continuity) {
            App.resetMonotonicRenderState(previousContinuity);
        }
        el.setAttribute("data-current-continuity-key", continuity);
        var entry = App._monotonicRenderState[continuity];
        if (entry && typeof entry.lastSeconds === "number" && seconds < entry.lastSeconds) {
            seconds = entry.lastSeconds;
        }
        var parts = display.split("\uff5c");
        if (parts.length >= 3) {
            parts[2] = App.formatDuration(seconds);
            el.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a" + parts.join("\uff5c");
            App._monotonicRenderState[continuity] = { lastSeconds: seconds };
        } else {
            el.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a" + display;
        }
    }
    App.renderCurrentActivityElement = renderCurrentActivityElement;

    function kpiBaseSeconds(snapshot, field) {
        snapshot = snapshot || {};
        var base = snapshot.kpi_live_base || {};
        if (base[field] !== undefined && base[field] !== null) {
            return nonNegativeInt(base[field], 0);
        }
        return nonNegativeInt(snapshot[field], 0);
    }
    App.kpiBaseSeconds = kpiBaseSeconds;

    function activeElapsedAtRenderFromPayload(payload, pageScope, nowMs) {
        var payloadClock = normalizeLiveClock(findClockInPayload(payload, false));
        if (payloadClock) return activeElapsedAtSample(payloadClock);
        var pageClock = getActiveLiveClock(pageScope);
        return activeElapsedNow(pageClock, nowMs);
    }
    App.activeElapsedAtRenderFromPayload = activeElapsedAtRenderFromPayload;

    function setLiveProjectionAnchor(el, baseSecondsAtRender, activeElapsedAtRender, continuityKey) {
        if (!el) return;
        el.setAttribute("data-live-base-seconds", String(nonNegativeInt(baseSecondsAtRender, 0)));
        el.setAttribute("data-active-elapsed-at-render", String(nonNegativeInt(activeElapsedAtRender, 0)));
        if (continuityKey) {
            el.setAttribute("data-live-continuity-key", String(continuityKey));
        }
    }
    App.setLiveProjectionAnchor = setLiveProjectionAnchor;

    function clearLiveProjectionAnchor(el) {
        if (!el) return;
        el.removeAttribute("data-live-base-seconds");
        el.removeAttribute("data-active-elapsed-at-render");
        el.removeAttribute("data-live-continuity-key");
    }
    App.clearLiveProjectionAnchor = clearLiveProjectionAnchor;

    function anchoredSecondsAtRender(baseSecondsAtSample, activeElapsedAtSampleValue, activeClock, nowMs) {
        var seconds = projectFromActiveElapsed(
            baseSecondsAtSample,
            activeElapsedAtSampleValue,
            activeClock,
            nowMs
        );
        var activeAtRender = activeElapsedNow(activeClock, nowMs);
        return {
            seconds: seconds,
            activeElapsedAtRender: activeAtRender
        };
    }
    App.anchoredSecondsAtRender = anchoredSecondsAtRender;

    function durationElementForLiveNode(node) {
        if (!node) return null;
        var durEl = node.querySelector(
            ".recent-item-duration, .timeline-item-duration, .detail-item-duration"
        );
        if (!durEl && (node.classList.contains("recent-item-duration")
            || node.classList.contains("timeline-item-duration")
            || node.classList.contains("detail-item-duration"))) {
            durEl = node;
        }
        return durEl;
    }

    function renderLiveRowDuration(node, baseSecondsAtRender, activeElapsedAtRender, activeClock, nowMs, activeElapsedNowSample) {
        var clock = normalizeLiveClock(activeClock);
        if (!node || !clock || clock.project_duration_live !== true) return;
        var durEl = durationElementForLiveNode(node);
        if (!durEl) return;
        var continuity = node.getAttribute("data-live-continuity-key")
            || liveContinuityKey(clock, "span");
        var seconds = projectFromActiveElapsed(
            baseSecondsAtRender,
            activeElapsedAtRender,
            clock,
            nowMs,
            activeElapsedNowSample
        );
        renderDurationProjected(durEl, seconds, continuity, { allowDecrease: false });
    }
    App.renderLiveRowDuration = renderLiveRowDuration;

    // ``applyLocalTicker`` re-renders fetched durations with a wall-clock delta each second without a
    // bridge round-trip. Ticker invariant: ONLY updates DOM text; never calls a bridge, never writes
    // the DB, never starts / stops the collector.
    //
    // Per-row contract: each live DOM node carries its OWN
    // ``data-live-base-seconds`` plus ``data-active-elapsed-at-render``.
    // The ticker applies the current page's single active elapsed sample to
    // every row/KPI/total without consulting per-row clocks.
    function applyLocalTicker() {
        var nowMs = tickerNowEpochMs();
        var clock = getActiveLiveClock();
        var activeElapsedNowValue = activeElapsedNow(clock, nowMs);
        var currentActivityClock = getActiveCurrentActivityClock();

        // --- Overview KPIs + current activity ---
        var ov = App.lastOverviewSnapshot;
        if (ov && App.currentPage === "overview") {
            var currentIsUncategorized = true;
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
                var totalBaseAttr = totalEl.getAttribute("data-live-base-seconds");
                var totalActiveAttr = totalEl.getAttribute("data-active-elapsed-at-render");
                var totalSec = totalBaseAttr !== null
                    ? projectFromActiveElapsed(totalBaseAttr, totalActiveAttr, clock, nowMs, activeElapsedNowValue)
                    : kpiBaseSeconds(ov, "today_total_seconds");
                App.renderDurationProjected(
                    totalEl, totalSec, "overview-total", { allowDecrease: false }
                );
            }
            var classifiedEl = document.getElementById("kpi-classified");
            if (classifiedEl) {
                var classifiedSec = kpiBaseSeconds(ov, "classified_seconds");
                if (currentIsUncategorized === false) {
                    var classifiedBaseAttr = classifiedEl.getAttribute("data-live-base-seconds");
                    var classifiedActiveAttr = classifiedEl.getAttribute("data-active-elapsed-at-render");
                    if (classifiedBaseAttr !== null) {
                        classifiedSec = projectFromActiveElapsed(classifiedBaseAttr, classifiedActiveAttr, clock, nowMs, activeElapsedNowValue);
                    }
                }
                App.renderDurationProjected(classifiedEl, classifiedSec, "overview-classified", { allowDecrease: false });
            }
            var uncategorizedEl = document.getElementById("kpi-uncategorized");
            if (uncategorizedEl) {
                var uncategorizedSec = kpiBaseSeconds(ov, "uncategorized_seconds");
                if (currentIsUncategorized === true) {
                    var uncategorizedBaseAttr = uncategorizedEl.getAttribute("data-live-base-seconds");
                    var uncategorizedActiveAttr = uncategorizedEl.getAttribute("data-active-elapsed-at-render");
                    if (uncategorizedBaseAttr !== null) {
                        uncategorizedSec = projectFromActiveElapsed(uncategorizedBaseAttr, uncategorizedActiveAttr, clock, nowMs, activeElapsedNowValue);
                    }
                }
                App.renderDurationProjected(uncategorizedEl, uncategorizedSec, "overview-uncategorized", { allowDecrease: false });
            }
            var currentEl = document.getElementById("current-activity");
            if (currentEl) {
                App.renderCurrentActivityElement(
                    currentEl, current, currentActivityClock, "overview"
                );
            }
        }

        // --- Timeline current-activity area + total ---
        var tl = App.lastTimelineData;
        if (tl && App.currentPage === "timeline") {
            var tlCurrentEl = document.getElementById("timeline-current");
            if (tlCurrentEl) {
                var tlCurrent = tl.current_activity || {};
                App.renderCurrentActivityElement(
                    tlCurrentEl, tlCurrent, currentActivityClock, "timeline"
                );
            }
            var todayStr = App.localTodayStr();
            var isToday = !tl.date || tl.date === todayStr || tl.date === "--";
            var tlTotalEl = document.getElementById("timeline-total");
            if (tlTotalEl && isToday) {
                var tlTotalBaseAttr = tlTotalEl.getAttribute("data-live-base-seconds");
                var tlTotalActiveAttr = tlTotalEl.getAttribute("data-active-elapsed-at-render");
                var tlTotalSec = tlTotalBaseAttr !== null
                    ? projectFromActiveElapsed(tlTotalBaseAttr, tlTotalActiveAttr, clock, nowMs, activeElapsedNowValue)
                    : (parseInt(tl.today_total_seconds, 10) || 0);
                App.renderDurationProjected(
                    tlTotalEl, tlTotalSec, "timeline-total", { allowDecrease: false }
                );
            }
        }

        // --- Unified live-span DOM walk (page-scoped) ---
        // Every live row (recent / session / detail) carries:
        //   - ``data-display-span-id``: display identity only, not a row clock lookup
        //   - ``data-live-base-seconds``: the row's OWN sample display duration
        //   - ``data-active-elapsed-at-render``: active elapsed when that base was rendered
        //   - ``data-live-continuity-key``: the same key the renderer seeded
        // The ticker renders ``base + (active_elapsed_now - active_elapsed_at_render)``.
        //
        // Page-scoped walk: only nodes inside the CURRENT page container
        // (``#page-<currentPage>``) are visited so a hidden page's stale
        // live DOM is never updated with the current page's delta.
        var tickerPage = App.currentPage || "overview";
        var pageRoot = document.getElementById("page-" + tickerPage);
        var liveNodes = pageRoot
            ? pageRoot.querySelectorAll("[data-display-span-id]")
            : [];
        for (var i = 0; i < liveNodes.length; i++) {
            var node = liveNodes[i];
            var spanId = node.getAttribute("data-display-span-id");
            if (!spanId) continue;
            if (!clock) {
                recordLiveClockContractViolation(spanId, tickerPage, "missing_active_span_clock");
                continue;
            }
            if (!(clock.project_duration_live === true || clock.is_project_duration_live === true)) continue;
            var baseAttr = node.getAttribute("data-live-base-seconds");
            if (baseAttr === null || baseAttr === "") continue;
            var nodeBaseSec = parseInt(baseAttr, 10);
            if (isNaN(nodeBaseSec)) continue;
            var activeAttr = node.getAttribute("data-active-elapsed-at-render");
            var nodeActiveAtRender = parseInt(activeAttr, 10);
            if (isNaN(nodeActiveAtRender)) continue;
            renderLiveRowDuration(node, nodeBaseSec, nodeActiveAtRender, clock, nowMs, activeElapsedNowValue);
        }
    }
    App.applyLocalTicker = applyLocalTicker;

    // Timeline editing guard: the ticker, revision-change refresh, low-frequency reconciliation, and
    // page-switch refresh all respect this so user input is never overwritten. Checks saving flags +
    // correctionShellOpen, open-but-unsaved editors, and dirty session edits (editingSession + isEditDirty).
    function timelineEditingActive() {
        if (
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
        ) {
            return true;
        }
        // Inline time / split editors are open (even without unsaved
        // changes) — protect them so a ticker / refresh does not disturb
        // the editor DOM.
        if (App.editingActivityId !== null) return true;
        if (App.editingSplitActivityId !== null) return true;
        // Dirty session edit (project / note / session-level time changed
        // but not yet saved).
        if (App.editingSession && typeof App.isEditDirty === "function" && App.isEditDirty()) {
            return true;
        }
        return false;
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
