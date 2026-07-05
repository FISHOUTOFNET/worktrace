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
    // never starts / stops the collector. Render flows seed static display bases; the heartbeat
    // may only advance the accepted live runtime.
    App.lastOverviewSnapshot = null;
    // Structural caches only — used to re-render lists on page switch / edit-guard checks. They
    // MUST NOT participate in live-row seconds computation. ``applyLocalTicker`` reads static
    // display bases from the DOM and the one accepted live runtime.
    App.lastRecentData = null;
    App.lastSessionDetailsViewModel = null;
    App.lastTimelineData = null;

    // Canonical accepted live runtime. ``get_refresh_state`` is the only writer;
    // page payloads may render only after proving compatibility with this runtime.
    App.liveDisplayModel = null;
    App.liveRuntime = null;
    App.liveClockContractViolation = null;
    App.liveClockContractRefreshRequested = false;

    // ``lastRefreshState`` caches the last ``get_refresh_state`` payload for revision comparison;
    // ``refreshCheckInFlight`` / ``activePageRefreshInFlight`` guard overlapping checks / refreshes.
    App.lastRefreshState = null;
    App.refreshCheckInFlight = false;
    App.activePageRefreshInFlight = false;
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
    // when session_id changes across the virtual / persisted_open transitions.
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
    //     display_base_seconds + active_elapsed_now

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

    function computeActiveElapsedNow(clock, nowMs) {
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
    App.computeActiveElapsedNow = computeActiveElapsedNow;

    function activeElapsedNow(clock, nowMs) {
        return computeActiveElapsedNow(clock, nowMs);
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

    function projectFromDisplayBase(displayBaseSeconds, activeElapsedNowValue) {
        return nonNegativeInt(displayBaseSeconds, 0)
            + nonNegativeInt(activeElapsedNowValue, 0);
    }
    App.projectFromDisplayBase = projectFromDisplayBase;

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
        if (payload.live_clock) return payload.live_clock;
        if (payload.activity_display_model && payload.activity_display_model.live_clock) {
            return payload.activity_display_model.live_clock;
        }
        return null;
    }

    function isActiveLiveTime(clock) {
        var c = normalizeLiveClock(clock);
        return !!(c && c.display_span_id && c.is_live === true);
    }

    function runtimeReportDateForPage(page, fallbackDate) {
        if (page === "timeline") {
            return fallbackDate || App.timelineDate || App.localTodayStr();
        }
        return fallbackDate || App.localTodayStr();
    }
    App.runtimeReportDateForPage = runtimeReportDateForPage;

    function payloadReportDate(payload, page, fallbackDate) {
        if (payload && (payload.report_date || payload.date)) {
            return String(payload.report_date || payload.date);
        }
        return runtimeReportDateForPage(page, fallbackDate);
    }
    App.payloadReportDate = payloadReportDate;

    function runtimeIdentityFromPayload(payload) {
        payload = payload || {};
        var clock = normalizeLiveClock(findClockInPayload(payload, false));
        var current = payload.current_activity || {};
        return {
            liveClock: isActiveLiveTime(clock) ? clock : null,
            displaySpanId: String(
                payload.display_span_id
                || (clock && clock.display_span_id)
                || ""
            ),
            stableLiveKeyHash: String(
                payload.stable_live_key_hash
                || (clock && clock.stable_live_key_hash)
                || ""
            ),
            refreshRevision: String(payload.refresh_revision || ""),
            liveStateRevision: String(payload.live_state_revision || ""),
            pageStructureRevision: String(payload.page_structure_revision || ""),
            sampleId: String(payload.sample_id || ""),
            currentActivityDisplaySpanId: String(current.current_activity_display_span_id || ""),
            currentResourceIdentityHash: String(current.current_resource_identity_hash || "")
        };
    }
    App.runtimeIdentityFromPayload = runtimeIdentityFromPayload;

    function runtimeVisualContinuityKey(runtime) {
        if (!runtime) return "";
        return [
            runtime.page || "",
            runtime.reportDate || "",
            runtime.displaySpanId || "",
            runtime.stableLiveKeyHash || "",
            runtime.currentActivityDisplaySpanId || "",
            runtime.currentResourceIdentityHash || ""
        ].join("|");
    }
    App.runtimeVisualContinuityKey = runtimeVisualContinuityKey;
    App.runtimeContinuityKey = runtimeVisualContinuityKey;

    function acceptLiveRuntimePayload(payload, page, reportDate, options) {
        if (!payload || !payload.ok) return false;
        options = options || {};
        var runtimePage = String(page || App.currentPage || "overview");
        var runtimeDate = payloadReportDate(payload, runtimePage, reportDate);
        var identity = runtimeIdentityFromPayload(payload);
        var previous = App.liveRuntime || null;
        var previousKey = runtimeVisualContinuityKey(previous);
        var incomingClock = identity.liveClock;
        var previousClock = previous && previous.liveClock;
        if (incomingClock && previousClock && sameLiveContinuity(previousClock, incomingClock)) {
            incomingClock = rebaseIncomingClockWithoutRollback(
                previousClock,
                incomingClock,
                tickerNowEpochMs()
            );
        }
        App.liveRuntime = {
            page: runtimePage,
            reportDate: runtimeDate,
            liveClock: incomingClock,
            displaySpanId: identity.displaySpanId,
            stableLiveKeyHash: identity.stableLiveKeyHash,
            refreshRevision: identity.refreshRevision,
            liveStateRevision: identity.liveStateRevision,
            pageStructureRevision: identity.pageStructureRevision,
            sampleId: identity.sampleId,
            currentActivityDisplaySpanId: identity.currentActivityDisplaySpanId,
            currentResourceIdentityHash: identity.currentResourceIdentityHash
        };
        App.liveDisplayModel = payload.activity_display_model || null;
        if (previousKey && previousKey !== runtimeVisualContinuityKey(App.liveRuntime)) {
            App._monotonicRenderState = {};
        }
        if (options.source === "refresh_state") {
            App.lastRefreshState = payload;
        }
        return true;
    }
    App.acceptLiveRuntimePayload = acceptLiveRuntimePayload;

    function acceptRefreshStateRuntime(state) {
        if (!state || !state.ok) return false;
        var page = App.currentPage || "overview";
        var reportDate = payloadReportDate(state, page);
        return acceptLiveRuntimePayload(state, page, reportDate, {
            source: "refresh_state"
        });
    }
    App.acceptRefreshStateRuntime = acceptRefreshStateRuntime;

    function acceptPagePayloadRuntime(payload, page, reportDate) {
        if (!isPagePayloadCompatibleWithRuntime(payload, page, reportDate)) {
            noteRejectedPagePayload(payload, page, reportDate);
            return false;
        }
        return acceptLiveRuntimePayload(payload, page, reportDate, {
            source: "page_model"
        });
    }
    App.acceptPagePayloadRuntime = acceptPagePayloadRuntime;

    function setLiveRuntimeScope(page, reportDate) {
        App.liveRuntime = {
            page: String(page || App.currentPage || "overview"),
            reportDate: runtimeReportDateForPage(page || App.currentPage || "overview", reportDate),
            liveClock: null,
            displaySpanId: "",
            stableLiveKeyHash: "",
            refreshRevision: "",
            liveStateRevision: "",
            pageStructureRevision: "",
            sampleId: "",
            currentActivityDisplaySpanId: "",
            currentResourceIdentityHash: ""
        };
        App.liveDisplayModel = null;
        App._monotonicRenderState = {};
    }
    App.setLiveRuntimeScope = setLiveRuntimeScope;

    function getActiveLiveClock() {
        var runtime = App.liveRuntime || null;
        if (!runtime || runtime.page !== (App.currentPage || "overview")) return null;
        if (runtime.page === "timeline") {
            var currentDate = runtimeReportDateForPage("timeline");
            if (runtime.reportDate && currentDate && runtime.reportDate !== currentDate) return null;
        }
        return runtime.liveClock || null;
    }
    App.getActiveLiveClock = getActiveLiveClock;

    function isPagePayloadCompatibleWithRuntime(payload, page, reportDate) {
        if (!payload || !payload.ok) return false;
        var expectedPage = String(page || App.currentPage || "overview");
        var expectedDate = payloadReportDate(payload, expectedPage, reportDate);
        if (expectedPage !== String(App.currentPage || "overview")) return false;
        if (expectedPage === "timeline") {
            var currentDate = runtimeReportDateForPage("timeline", reportDate);
            if (expectedDate && currentDate && expectedDate !== currentDate) return false;
        } else if (expectedDate && expectedDate !== App.localTodayStr()) {
            return false;
        }
        var currentRuntime = App.liveRuntime || null;
        var currentClock = currentRuntime && currentRuntime.liveClock;
        var incomingIdentity = runtimeIdentityFromPayload(payload);
        var incomingClock = incomingIdentity.liveClock;
        var currentActivity = payload.current_activity || {};
        if (isActiveLiveTime(currentClock) && incomingClock && !sameLiveContinuity(currentClock, incomingClock)) {
            return false;
        }
        if (
            isActiveLiveTime(currentClock)
            && !incomingClock
            && (currentActivity.active === true || currentActivity.is_active === true)
        ) {
            return false;
        }
        if (
            currentRuntime
            && currentRuntime.currentActivityDisplaySpanId
            && incomingIdentity.currentActivityDisplaySpanId
            && currentRuntime.currentActivityDisplaySpanId !== incomingIdentity.currentActivityDisplaySpanId
        ) {
            return false;
        }
        if (
            currentRuntime
            && currentRuntime.currentResourceIdentityHash
            && incomingIdentity.currentResourceIdentityHash
            && currentRuntime.currentResourceIdentityHash !== incomingIdentity.currentResourceIdentityHash
        ) {
            return false;
        }
        return true;
    }
    App.isPagePayloadCompatibleWithRuntime = isPagePayloadCompatibleWithRuntime;

    function noteRejectedPagePayload(payload, page, reportDate) {
        App.liveClockContractRefreshRequested = true;
        App.liveClockContractViolation = {
            spanId: payload && payload.display_span_id ? String(payload.display_span_id) : "",
            page: String(page || App.currentPage || "overview"),
            reason: "page_payload_runtime_mismatch",
            reportDate: reportDate || (payload && (payload.report_date || payload.date)) || ""
        };
    }
    App.noteRejectedPagePayload = noteRejectedPagePayload;

    // SINGLE SOURCE OF TRUTH for live-row continuity keys. Uses ``stable_live_key_hash`` so the key
    // survives the virtual / persisted_open transitions (session_id / activity_id
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
        if (current && current.current_activity_display_span_id) {
            identity = current.current_activity_display_span_id;
        } else if (current && current.current_resource_identity_hash) {
            identity = current.current_resource_identity_hash;
        } else if (current && current.stable_live_key_hash) {
            identity = current.stable_live_key_hash;
        } else if (clock && clock.current_resource_identity_hash) {
            identity = clock.current_resource_identity_hash;
        } else if (clock && clock.current_activity_display_span_id) {
            identity = clock.current_activity_display_span_id;
        } else if (clock && clock.display_span_id) {
            identity = clock.display_span_id;
        } else if (current && current.start_time) {
            identity = String(current.resource_name || current.app_name || "current")
                + ":" + String(current.start_time || "");
        }
        return prefix + ":current:" + (identity || "none");
    }
    App.currentActivityContinuityKey = currentActivityContinuityKey;

    function renderCurrentActivityElement(el, current, prefix) {
        if (!el) return;
        current = current || {};
        if (!current.active) {
            el.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a\u65e0";
            return;
        }
        var display = current.display || "";
        var seconds = parseInt(current.elapsed_seconds, 10) || 0;
        var continuity = currentActivityContinuityKey(current, null, prefix);
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
            var html = "\u5f53\u524d\u6d3b\u52a8\uff1a"
                + App.escapeHtml(parts[0] || "")
                + "\uff5c"
                + App.escapeHtml(parts[1] || "")
                + "\uff5c"
                + '<span class="current-activity-duration"'
                + ' data-live-duration-target="1"'
                + ' data-duration-semantic="current-live"'
                + ' data-display-base-seconds="0"'
                + ' data-live-base-seconds="0"'
                + ' data-live-role="' + App.escapeHtml(prefix || "current") + '-current"'
                + ' data-live-continuity-key="' + App.escapeHtml(continuity) + '"'
                + (current.current_activity_display_span_id ? ' data-current-activity-display-span-id="' + App.escapeHtml(current.current_activity_display_span_id) + '"' : '')
                + (current.current_resource_identity_hash ? ' data-current-resource-identity-hash="' + App.escapeHtml(current.current_resource_identity_hash) + '"' : '')
                + (current.display_span_id ? ' data-display-span-id="' + App.escapeHtml(current.display_span_id) + '"' : '')
                + (current.stable_live_key_hash ? ' data-stable-live-key-hash="' + App.escapeHtml(current.stable_live_key_hash) + '"' : '')
                + ' data-duration-seconds="' + String(seconds) + '"'
                + '>' + App.escapeHtml(App.formatDuration(seconds)) + '</span>';
            for (var i = 3; i < parts.length; i++) {
                html += "\uff5c" + App.escapeHtml(parts[i] || "");
            }
            el.innerHTML = html;
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

    function setLiveProjectionAnchor(el, displayBaseSeconds, continuityKey, role) {
        if (!el) return;
        var base = String(nonNegativeInt(displayBaseSeconds, 0));
        el.setAttribute("data-live-duration-target", "1");
        el.setAttribute("data-duration-semantic", "aggregate-live");
        el.setAttribute("data-display-base-seconds", base);
        el.setAttribute("data-live-base-seconds", base);
        if (role) {
            el.setAttribute("data-live-role", String(role));
        }
        if (continuityKey) {
            el.setAttribute("data-live-continuity-key", String(continuityKey));
        }
        var runtime = App.liveRuntime || {};
        if (runtime.displaySpanId) {
            el.setAttribute("data-display-span-id", String(runtime.displaySpanId));
        }
        if (runtime.stableLiveKeyHash) {
            el.setAttribute("data-stable-live-key-hash", String(runtime.stableLiveKeyHash));
        }
    }
    App.setLiveProjectionAnchor = setLiveProjectionAnchor;

    function clearLiveProjectionAnchor(el) {
        if (!el) return;
        el.removeAttribute("data-live-duration-target");
        el.removeAttribute("data-duration-semantic");
        el.removeAttribute("data-display-base-seconds");
        el.removeAttribute("data-live-base-seconds");
        el.removeAttribute("data-live-role");
        el.removeAttribute("data-live-continuity-key");
        el.removeAttribute("data-display-span-id");
        el.removeAttribute("data-stable-live-key-hash");
    }
    App.clearLiveProjectionAnchor = clearLiveProjectionAnchor;

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

    function renderLiveDurationTarget(target, displayBaseSeconds, activeElapsedNowValue) {
        if (!target) return;
        var continuity = target.getAttribute("data-live-continuity-key") || "";
        var seconds = projectFromDisplayBase(displayBaseSeconds, activeElapsedNowValue);
        renderDurationProjected(target, seconds, continuity, { allowDecrease: false });
    }
    App.renderLiveDurationTarget = renderLiveDurationTarget;

    function nearestStableHash(target) {
        if (!target) return "";
        var value = target.getAttribute("data-stable-live-key-hash") || "";
        if (value) return value;
        var node = target.parentElement;
        while (node) {
            value = node.getAttribute && node.getAttribute("data-stable-live-key-hash");
            if (value) return value;
            node = node.parentElement;
        }
        return "";
    }

    function liveTargetCompatibleWithRuntime(target, runtime) {
        if (!target || !runtime) return false;
        var targetCurrentSpan = target.getAttribute("data-current-activity-display-span-id") || "";
        if (targetCurrentSpan) {
            return !!runtime.currentActivityDisplaySpanId
                && targetCurrentSpan === runtime.currentActivityDisplaySpanId;
        }
        var targetResourceHash = target.getAttribute("data-current-resource-identity-hash") || "";
        if (targetResourceHash) {
            return !!runtime.currentResourceIdentityHash
                && targetResourceHash === runtime.currentResourceIdentityHash;
        }
        var targetSpan = target.getAttribute("data-display-span-id") || "";
        if (targetSpan) {
            return !!runtime.displaySpanId && targetSpan === runtime.displaySpanId;
        }
        var targetStable = nearestStableHash(target);
        if (targetStable) {
            return !!runtime.stableLiveKeyHash && targetStable === runtime.stableLiveKeyHash;
        }
        return false;
    }
    App.liveTargetCompatibleWithRuntime = liveTargetCompatibleWithRuntime;

    // ``applyLocalTicker`` re-renders fetched durations with a wall-clock delta each second without a
    // bridge round-trip. Ticker invariant: ONLY updates DOM text; never calls a bridge, never writes
    // the DB, never starts / stops the collector.
    //
    // Live target contract: each duration target carries its OWN static
    // ``data-display-base-seconds``. The ticker applies the current page's
    // single active elapsed sample to every current/recent/timeline/detail/KPI
    // target without consulting per-region clocks.
    function applyLocalTicker() {
        var nowMs = tickerNowEpochMs();
        var runtime = App.liveRuntime || null;
        var clock = getActiveLiveClock();
        var activeElapsedNowValue = computeActiveElapsedNow(clock, nowMs);
        var tickerPage = App.currentPage || "overview";
        var pageRoot = document.getElementById("page-" + tickerPage);
        var liveTargets = pageRoot
            ? pageRoot.querySelectorAll('[data-live-duration-target="1"]')
            : [];
        for (var i = 0; i < liveTargets.length; i++) {
            var target = liveTargets[i];
            if (!clock) {
                recordLiveClockContractViolation(
                    target.getAttribute("data-display-span-id") || "",
                    tickerPage,
                    "missing_active_span_clock"
                );
                continue;
            }
            if (!(clock.is_live === true || clock.current_duration_live === true || clock.project_duration_live === true || clock.is_project_duration_live === true)) continue;
            if (!liveTargetCompatibleWithRuntime(target, runtime)) {
                recordLiveClockContractViolation(
                    target.getAttribute("data-display-span-id") || "",
                    tickerPage,
                    "live_target_runtime_mismatch"
                );
                continue;
            }
            var baseAttr = target.getAttribute("data-display-base-seconds");
            if (baseAttr === null || baseAttr === "") {
                baseAttr = target.getAttribute("data-live-base-seconds");
            }
            if (baseAttr === null || baseAttr === "") continue;
            var displayBaseSeconds = parseInt(baseAttr, 10);
            if (isNaN(displayBaseSeconds)) continue;
            var semantic = target.getAttribute("data-duration-semantic") || "";
            if (semantic === "current-live" && displayBaseSeconds !== 0) {
                recordLiveClockContractViolation(
                    target.getAttribute("data-display-span-id") || "",
                    tickerPage,
                    "current_live_target_nonzero_base"
                );
                continue;
            }
            renderLiveDurationTarget(target, displayBaseSeconds, activeElapsedNowValue);
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
