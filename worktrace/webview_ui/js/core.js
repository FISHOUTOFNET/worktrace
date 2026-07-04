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
    // never starts / stops the collector. The live clock is seeded by the render flows and by the
    // lightweight ``get_refresh_state`` heartbeat into the unified registry below.
    App.lastOverviewSnapshot = null;
    // Structural caches only — used to re-render lists on page switch / edit-guard checks. They
    // MUST NOT participate in live-seconds computation; the unified ``App.liveClockBySpanId``
    // registry is the single source of truth for every live duration (current / recent / timeline
    // / detail). ``applyLocalTicker`` never reads these caches as a live-seconds source.
    App.lastRecentData = null;
    App.lastSessionDetailsViewModel = null;
    App.lastTimelineData = null;

    // Project live-clock registry. Keyed by ``display_span_id``. Populated from any payload that
    // carries project ``live_clock`` (Overview / Recent / Timeline / Details / Refresh State).
    // Current-activity UI has its own registry below and never reads this as a fallback.
    App.liveClockBySpanId = {};
    App.liveDisplayModel = null;
    // Explicit active span id — the single live span currently eligible to tick
    // project totals / current-activity area. ``getActiveLiveClock`` reads this
    // instead of relying on object insertion order so a stale clock cannot win
    // by being the last-inserted key.
    App.activeDisplaySpanId = "";
    // Page-scoped live-clock registry (Section 五 fix). Keyed by page scope
    // (``"overview"`` / ``"timeline"`` / ``"refresh_state"``). A hidden page's
    // payload MUST NOT overwrite the current page's active live clock;
    // ``getActiveLiveClock`` reads ``App.liveClockByPage[App.currentPage]``.
    App.liveClockByPage = {};
    App.activeDisplaySpanIdByPage = {};
    App.currentActivityClockByPage = {};

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

    // Maps a continuity key to the last rendered seconds; used by ``renderDurationMonotonic`` to avoid
    // 1-2s visual rollback when the new projected seconds are less than the DOM value.
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

    // Shared monotonic-render contract for every live target. ``renderDurationMonotonic`` avoids 1-2s visual
    // rollback when the same live target is still running: with ``allowDecrease === false`` and a 1-2s decrease,
    // the DOM is kept unchanged; larger decreases (real state change) or ``allowDecrease === true`` overwrite.
    // Backend refresh paths must reset the monotonic state so the real snapshot replaces the projected value.
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

    // ===== Unified Live Clock =====
    //
    // The SINGLE source of truth for the live delta. The current-activity area,
    // KPI totals, recent items, timeline sessions, and detail rows all share
    // ONE live delta derived from the single registered live clock. Each DOM
    // row carries its OWN sample base (``data-live-base-seconds``); the ticker
    // renders ``nodeBaseSeconds + liveDelta`` so a session row whose sample
    // duration is larger than the live activity's own duration is NOT
    // overwritten by the live span value.
    //
    // Live-span formula (the live clock's own current seconds):
    //     liveSeconds(clock) = carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)
    //
    // Unified live delta (shared by every DOM row):
    //     liveDelta = max(0, liveSeconds(clock) - clock.duration_seconds_at_sample)
    //
    // Per-row render:
    //     rowSeconds = rowBaseSecondsAtSample + liveDelta
    //
    // The clock is registered from any payload that carries ``live_clock``
    // (Overview, Recent, Timeline, Details, or the lightweight Refresh State).

    function tickerNowEpochMs() {
        return Date.now();
    }

    // The unified live-seconds formula. Returns the ``duration_seconds_at_sample`` fallback when
    // the clock has no valid ``live_started_at_epoch_ms`` (e.g. paused / idle / historical).
    function liveSeconds(clock) {
        if (!clock) return 0;
        var startedAt = parseInt(clock.live_started_at_epoch_ms, 10);
        var carry = parseInt(clock.carry_seconds, 10) || 0;
        var atSample = parseInt(clock.duration_seconds_at_sample, 10);
        if (isNaN(atSample)) atSample = parseInt(clock.duration_seconds, 10) || 0;
        if (!startedAt || isNaN(startedAt)) return atSample;
        return carry + Math.floor((tickerNowEpochMs() - startedAt) / 1000);
    }
    App.liveSeconds = liveSeconds;

    // Unified live delta: how many seconds have elapsed since the backend
    // sample. Shared by every DOM row. Clamped to 0 so a stale clock or a
    // wall-clock drift never makes the UI count backwards.
    function liveDeltaSeconds(clock) {
        if (!clock) return 0;
        var atSample = parseInt(clock.duration_seconds_at_sample, 10);
        if (isNaN(atSample)) atSample = 0;
        var display = liveSeconds(clock);
        var delta = display - atSample;
        return delta > 0 ? delta : 0;
    }
    App.liveDeltaSeconds = liveDeltaSeconds;

    // Register a live clock from ANY payload (Overview / Recent / Timeline /
    // Details / Refresh State). The payload may carry ``live_clock`` directly
    // or nested inside ``activity_display_model``.
    //
    // The optional second argument is ``{ source: "page_model" | "refresh_state",
    // preserveSameSpanSample: bool, page: <scope> }``. It distinguishes the
    // registration paths so the lightweight refresh_state cannot overwrite a
    // page-model sample clock's ``live_started_at_epoch_ms`` / ``carry_seconds``
    // / ``duration_seconds_at_sample`` while the user is still on the same live
    // span.
    //
    // Page-scoped registry (Section 五 fix): ``options.page`` MUST be one of
    // ``"overview"`` / ``"timeline"`` / ``"refresh_state"``. The clock is
    // stored under ``App.liveClockByPage[page]`` so a hidden page's payload
    // (e.g. Overview refresh during Timeline view) cannot overwrite the
    // current page's active live clock. When ``options.page`` is omitted the
    // clock is registered under the CURRENT page scope (``App.currentPage``)
    // so historical callers keep working but still respect page isolation.
    //
    // Contract:
    //
    // - When the payload has NO live clock, NO display_span_id, or the
    //   clock's project-duration live flag is not true, the registry AND the active span id
    //   for the TARGET page scope MUST be cleared. This prevents a stale
    //   clock from continuing to tick after the activity ends, the collector
    //   pauses, or the user switches pages. Clearing a non-current page's
    //   scope does NOT touch the current page's active clock.
    // - When ``source == "refresh_state"`` AND ``preserveSameSpanSample`` is
    //   true AND the new clock shares the active span id AND the active
    //   clock's ``stable_live_key_hash`` equals the new clock's, the
    //   ``live_started_at_epoch_ms`` / ``carry_seconds`` /
    //   ``duration_seconds_at_sample`` fields of the ACTIVE clock are
    //   PRESERVED. Only non-sample fields (project_duration_live / live_state
    //   / live_state / stable_live_key) refresh from the new payload. This is
    //   the same-span preservation rule: refresh_state is structural-only and
    //   must NOT reset the liveDelta base that the page-model sample seeded.
    // - In all other cases (span id changed, stable key changed, project live
    //   flipped false, live_state structural switch, or source ==
    //   "page_model"), the new clock fully replaces the active clock for the
    //   TARGET page scope.
    function registerLiveClock(payload, options) {
        var opts = options || {};
        var pageScope = String(opts.page || App.currentPage || "overview");
        if (!payload) {
            clearLiveClockRegistry(pageScope);
            return;
        }
        var clock = payload.live_clock;
        if (!clock && payload.activity_display_model) {
            clock = payload.activity_display_model.live_clock;
        }
        if (!clock) {
            clearLiveClockRegistry(pageScope);
            return;
        }
        var spanId = String(clock.display_span_id || "");
        var projectDurationLive = clock.project_duration_live === true
            || clock.is_project_duration_live === true;
        if (!spanId || !projectDurationLive) {
            clearLiveClockRegistry(pageScope);
            return;
        }
        var source = String(opts.source || "page_model");
        var preserveSameSpanSample = !!opts.preserveSameSpanSample;
        // Read the active clock for THIS page scope only so a hidden page's
        // payload cannot overwrite the current page's clock.
        var pageActiveSpanId = App.activeDisplaySpanIdByPage[pageScope] || "";
        var activeClock = pageActiveSpanId
            ? (App.liveClockBySpanId[pageActiveSpanId] || null)
            : null;
        var sameSpan = activeClock
            && pageActiveSpanId === spanId
            && (activeClock.project_duration_live === true
                || activeClock.is_project_duration_live === true);
        var sameStableKey = sameSpan
            && String(activeClock.stable_live_key_hash || "")
                === String(clock.stable_live_key_hash || "");
        var sameLiveState = sameSpan
            && String(activeClock.live_state || "")
                === String(clock.live_state || "");
        var canPreserveSample = source === "refresh_state"
            && preserveSameSpanSample
            && sameSpan
            && sameStableKey
            && sameLiveState;
        // Sample identity changed (different span id, different stable key,
        // different live_state, or a page_model refresh) → wipe any prior
        // monotonic state so the new activity is not poisoned by the previous
        // activity's rollback-guard. ONLY for the current page scope so a
        // hidden page refresh does not reset the current page's monotonic
        // state.
        var isCurrentPageScope = (pageScope === App.currentPage);
        if (isCurrentPageScope) {
            if (pageActiveSpanId && pageActiveSpanId !== spanId) {
                App._monotonicRenderState = {};
            } else if (!canPreserveSample) {
                App._monotonicRenderState = {};
            }
        }
        var storedClock = clock;
        if (canPreserveSample && activeClock) {
            // Preserve the page-model sample fields; refresh only the
            // non-sample identity / status fields from the lightweight
            // refresh_state payload.
            storedClock = {
                display_span_id: clock.display_span_id,
                stable_live_key: clock.stable_live_key,
                stable_live_key_hash: clock.stable_live_key_hash,
                live_state: clock.live_state,
                is_live: clock.is_live,
                is_project_duration_live: clock.is_project_duration_live,
                project_duration_live: clock.project_duration_live,
                current_duration_live: clock.current_duration_live,
                // Sample fields preserved from the active page-model clock.
                live_started_at_epoch_ms: activeClock.live_started_at_epoch_ms,
                carry_seconds: activeClock.carry_seconds,
                duration_seconds_at_sample: activeClock.duration_seconds_at_sample,
            };
        }
        // span-id registry is global so DOM rows on any page can look up
        // their clock; the page scope decides which one is ACTIVE.
        App.liveClockBySpanId[spanId] = storedClock;
        App.liveClockByPage[pageScope] = storedClock;
        App.activeDisplaySpanIdByPage[pageScope] = spanId;
        // Maintain ``activeDisplaySpanId`` for the current page only so
        // legacy readers (and tests) keep working. Hidden-page registrations
        // MUST NOT overwrite this field.
        if (isCurrentPageScope) {
            App.activeDisplaySpanId = spanId;
        }
        if (payload.activity_display_model) {
            App.liveDisplayModel = payload.activity_display_model;
        } else {
            App.liveDisplayModel = payload;
        }
    }
    App.registerLiveClock = registerLiveClock;

    function registerCurrentActivityClock(payload, options) {
        var opts = options || {};
        var pageScope = String(opts.page || App.currentPage || "overview");
        var clock = null;
        if (payload) {
            clock = payload.current_activity_clock || null;
            if (!clock && payload.activity_display_model) {
                clock = payload.activity_display_model.current_activity_clock || null;
            }
            if (!clock && payload.current_activity) {
                clock = payload.current_activity.current_activity_clock || null;
            }
        }
        if (!clock) {
            delete App.currentActivityClockByPage[pageScope];
            return;
        }
        var currentSpanId = String(clock.display_span_id || "");
        var prev = App.currentActivityClockByPage[pageScope] || null;
        if (pageScope === App.currentPage
            && prev
            && String(prev.display_span_id || "") !== currentSpanId) {
            App.resetMonotonicRenderState();
        }
        App.currentActivityClockByPage[pageScope] = clock;
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

    // Return the single active live clock for the CURRENT page scope, or
    // ``null``. Reads ONLY ``App.liveClockByPage[App.currentPage]`` so a
    // hidden page's payload cannot become the active clock. There is NO
    // legacy ``activeDisplaySpanId`` fallback: page-scoped is the single
    // source of truth. When no page-scoped clock is registered yet (e.g.
    // before the first page-model refresh), the ticker renders no live
    // delta, which is the correct behavior.
    function getActiveLiveClock() {
        var page = App.currentPage || "overview";
        return App.liveClockByPage[page] || null;
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
            delete App.liveClockByPage[pageScope];
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
        App.liveClockByPage = {};
        App.currentActivityClockByPage = {};
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
        var hash = "";
        if (clock && clock.stable_live_key_hash) {
            hash = clock.stable_live_key_hash;
        } else if (current && current.stable_live_key_hash) {
            hash = current.stable_live_key_hash;
        }
        return prefix + ":current:" + (hash || "none");
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
            seconds = liveSeconds(currentClock);
        }
        var parts = display.split("\uff5c");
        if (parts.length >= 3) {
            parts[2] = App.formatDuration(seconds);
            el.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a" + parts.join("\uff5c");
            App._monotonicRenderState[currentActivityContinuityKey(current, currentClock, prefix)] = {
                lastSeconds: seconds
            };
        } else {
            el.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a" + display;
        }
    }
    App.renderCurrentActivityElement = renderCurrentActivityElement;

    // ``applyLocalTicker`` re-renders fetched durations with a wall-clock delta each second without a
    // bridge round-trip. Ticker invariant: ONLY updates DOM text; never calls a bridge, never writes
    // the DB, never starts / stops the collector.
    //
    // Per-row contract: each live DOM node carries its OWN
    // ``data-live-base-seconds`` (the row's sample display duration from the
    // backend). The ticker renders ``nodeBaseSeconds + liveDelta``. The live
    // clock's own ``liveSeconds(clock)`` is only used for the current-activity
    // area (whose base IS the live span duration). KPI totals carry their own
    // base in the snapshot payload.
    function applyLocalTicker() {
        var clock = getActiveLiveClock();
        var currentActivityClock = getActiveCurrentActivityClock();
        var liveDelta = 0;
        var projectDurationLive = false;
        if (clock) {
            projectDurationLive = clock.project_duration_live === true
                || clock.is_project_duration_live === true;
            if (projectDurationLive) {
                liveDelta = liveDeltaSeconds(clock);
            }
        }

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
                var totalSec = parseInt(ov.today_total_seconds, 10) || 0;
                App.renderDurationMonotonic(totalEl, totalSec + liveDelta, "overview-total", false);
            }
            var classifiedEl = document.getElementById("kpi-classified");
            if (classifiedEl) {
                var classifiedSec = parseInt(ov.classified_seconds, 10) || 0;
                if (currentIsUncategorized === false) {
                    classifiedSec += liveDelta;
                }
                App.renderDurationMonotonic(classifiedEl, classifiedSec, "overview-classified", false);
            }
            var uncategorizedEl = document.getElementById("kpi-uncategorized");
            if (uncategorizedEl) {
                var uncategorizedSec = parseInt(ov.uncategorized_seconds, 10) || 0;
                if (currentIsUncategorized === true) {
                    uncategorizedSec += liveDelta;
                }
                App.renderDurationMonotonic(uncategorizedEl, uncategorizedSec, "overview-uncategorized", false);
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
                var tlTotalSec = parseInt(tl.today_total_seconds, 10) || 0;
                App.renderDurationMonotonic(tlTotalEl, tlTotalSec + liveDelta, "timeline-total", false);
            }
        }

        // --- Unified live-span DOM walk (page-scoped) ---
        // Every live row (recent / session / detail) carries:
        //   - ``data-display-span-id``: matches the active live clock's span id
        //   - ``data-live-base-seconds``: the row's OWN sample display duration
        //   - ``data-live-continuity-key``: the same key the renderer seeded
        // The ticker renders ``nodeBaseSeconds + liveDelta`` so a session row
        // whose sample duration is larger than the live activity's own
        // duration is NOT overwritten by the live span value. Rows without
        // ``data-live-base-seconds`` keep their seeded text.
        //
        // Page-scoped walk: only nodes inside the CURRENT page container
        // (``#page-<currentPage>``) are visited so a hidden page's stale
        // live DOM is never updated with the current page's delta.
        if (!clock || !(clock.project_duration_live === true || clock.is_project_duration_live === true)) {
            return;
        }
        var tickerPage = App.currentPage || "overview";
        var pageRoot = document.getElementById("page-" + tickerPage);
        var liveNodes = pageRoot
            ? pageRoot.querySelectorAll("[data-display-span-id]")
            : [];
        for (var i = 0; i < liveNodes.length; i++) {
            var node = liveNodes[i];
            var spanId = node.getAttribute("data-display-span-id");
            if (!spanId) continue;
            var nodeClock = App.liveClockBySpanId[spanId] || clock;
            if (!nodeClock) continue;
            if (!(nodeClock.project_duration_live === true || nodeClock.is_project_duration_live === true)) continue;
            var baseAttr = node.getAttribute("data-live-base-seconds");
            if (baseAttr === null || baseAttr === "") continue;
            var nodeBaseSec = parseInt(baseAttr, 10);
            if (isNaN(nodeBaseSec)) continue;
            var nextSec = nodeBaseSec + liveDelta;
            var durEl = node.querySelector(
                ".recent-item-duration, .timeline-item-duration, .detail-item-duration"
            );
            if (!durEl) {
                if (node.classList.contains("recent-item-duration")
                    || node.classList.contains("timeline-item-duration")
                    || node.classList.contains("detail-item-duration")) {
                    durEl = node;
                }
            }
            if (!durEl) continue;
            // Prefer the DOM-seeded continuity key so render and ticker share
            // the same monotonic guard. Fall back to ``span:<spanId>`` only
            // when the renderer did not seed one (defensive).
            var continuity = node.getAttribute("data-live-continuity-key");
            if (!continuity) {
                continuity = "span:" + spanId;
            }
            App.renderDurationMonotonic(durEl, nextSec, continuity, false);
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
