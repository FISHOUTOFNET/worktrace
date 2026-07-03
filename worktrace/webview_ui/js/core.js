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
    // Structural caches only — used to re-render lists on page switch. They MUST NOT participate
    // in live-seconds computation anymore; the unified ``App.liveClockBySpanId`` registry is the
    // single source of truth for every live duration (current / recent / timeline / detail).
    App.lastRecentSnapshot = null;
    App.lastSessionDetailsData = null;
    App.lastTimelineData = null;

    // Unified live-clock registry. Keyed by ``display_span_id``. Populated from any payload that
    // carries ``live_clock`` (Overview / Recent / Timeline / Details / Refresh State). The single
    // live-seconds formula: ``carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)``.
    App.liveClockBySpanId = {};
    App.liveDisplayModel = null;

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
    // The SINGLE source of truth for every live duration in the UI. There are no longer separate
    // ``recentDelta`` / ``tlDelta`` / ``detailDelta`` computations — current activity, recent items,
    // timeline sessions and detail rows all read from the same registered live clock.
    //
    // Formula:  display = carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)
    //
    // The clock is registered from any payload that carries ``live_clock`` (Overview, Recent,
    // Timeline, Details, or the lightweight Refresh State). The 1s heartbeat ``applyLocalTicker``
    // walks every DOM node that carries ``data-display-span-id`` and renders it with the unified
    // clock, so all four display regions stay in lockstep.

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

    function projectLiveSeconds(clock) {
        // Alias kept for callers that semantically "project" a live span.
        return liveSeconds(clock);
    }
    App.projectLiveSeconds = projectLiveSeconds;

    // Register a live clock from ANY payload (Overview / Recent / Timeline / Details / Refresh State).
    // The payload may carry ``live_clock`` directly or nested inside ``activity_display_model``.
    function registerLiveClock(payload) {
        if (!payload) return;
        var clock = payload.live_clock;
        if (!clock && payload.activity_display_model) {
            clock = payload.activity_display_model.live_clock;
        }
        if (!clock) return;
        var spanId = String(clock.display_span_id || "");
        if (!spanId) return;
        App.liveClockBySpanId[spanId] = clock;
        if (payload.activity_display_model) {
            App.liveDisplayModel = payload.activity_display_model;
        } else if (!App.liveDisplayModel) {
            App.liveDisplayModel = payload;
        }
    }
    App.registerLiveClock = registerLiveClock;

    // Return the single active live clock, or ``null``. When multiple spans are registered (rare),
    // the most recently registered one wins. Used by KPI totals and the current-activity area.
    function getActiveLiveClock() {
        var keys = Object.keys(App.liveClockBySpanId);
        if (keys.length === 0) return null;
        return App.liveClockBySpanId[keys[keys.length - 1]];
    }
    App.getActiveLiveClock = getActiveLiveClock;

    function clearLiveClockRegistry() {
        App.liveClockBySpanId = {};
        App.liveDisplayModel = null;
    }
    App.clearLiveClockRegistry = clearLiveClockRegistry;

    // Compatibility wrapper: returns the wall-clock delta since the backend sample for KPI totals.
    // Reads ONLY from the unified registry — never from a page-level snapshot's live_projection.
    function tickerDeltaSeconds(payload) {
        // ``payload`` is accepted for backwards compatibility but ignored; the registry is global.
        var clock = getActiveLiveClock();
        if (!clock) return 0;
        var atSample = parseInt(clock.duration_seconds_at_sample, 10);
        if (isNaN(atSample)) atSample = 0;
        var display = liveSeconds(clock);
        var delta = display - atSample;
        return delta > 0 ? delta : 0;
    }
    App.tickerDeltaSeconds = tickerDeltaSeconds;

    // Compatibility wrapper: returns ``true`` when the unified live clock should tick project totals.
    // Mirrors ``live_clock.is_project_duration_live`` so paused / idle / excluded / error /
    // virtual_pending never inflate KPI totals.
    function tickerLiveEligible(payload) {
        var clock = getActiveLiveClock();
        if (!clock) return false;
        return clock.is_project_duration_live === true;
    }
    App.tickerLiveEligible = tickerLiveEligible;

    function tickerCurrentActivityRunning() {
        return tickerLiveEligible();
    }

    // SINGLE SOURCE OF TRUTH for live-row continuity keys. Uses ``stable_live_key_hash`` so the key
    // survives the virtual / persisted_open / absorbed_pending transitions (session_id / activity_id
    // change across the transition; stable_live_key_hash does not).
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

    // ``applyLocalTicker`` re-renders fetched durations with a wall-clock delta each second without a
    // bridge round-trip. Ticker invariant: ONLY updates DOM text; never calls a bridge, never writes
    // the DB, never starts / stops the collector.
    //
    // Unified path: walks every DOM node carrying ``data-display-span-id`` and renders it with the
    // single registered live clock. KPI totals and the current-activity area use the same clock.
    function applyLocalTicker() {
        var clock = getActiveLiveClock();
        var liveDelta = 0;
        var projectDurationLive = false;
        if (clock) {
            projectDurationLive = clock.is_project_duration_live === true;
            if (projectDurationLive) {
                liveDelta = tickerDeltaSeconds();
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
                if (current.active && clock) {
                    var displaySec = liveSeconds(clock);
                    var display = current.display || "";
                    var parts = display.split("\uff5c");
                    if (parts.length >= 3) {
                        parts[2] = App.formatDuration(displaySec);
                        currentEl.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a" + parts.join("\uff5c");
                    }
                } else if (!current.active) {
                    currentEl.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a\u65e0";
                }
            }
        }

        // --- Timeline current-activity area + total ---
        var tl = App.lastTimelineData;
        if (tl && App.currentPage === "timeline") {
            var tlCurrentEl = document.getElementById("timeline-current");
            if (tlCurrentEl) {
                var tlCurrent = tl.current_activity || {};
                if (tlCurrent.active && clock) {
                    var tlDisplaySec = liveSeconds(clock);
                    var tlDisplay = tlCurrent.display || "";
                    var tlParts = tlDisplay.split("\uff5c");
                    if (tlParts.length >= 3) {
                        tlParts[2] = App.formatDuration(tlDisplaySec);
                        tlCurrentEl.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a" + tlParts.join("\uff5c");
                    }
                } else if (!tlCurrent.active) {
                    tlCurrentEl.textContent = "\u5f53\u524d\u6d3b\u52a8\uff1a\u65e0";
                }
            }
            var todayStr = App.localTodayStr();
            var isToday = !tl.date || tl.date === todayStr || tl.date === "--";
            var tlTotalEl = document.getElementById("timeline-total");
            if (tlTotalEl && isToday) {
                var tlTotalSec = parseInt(tl.today_total_seconds, 10) || 0;
                App.renderDurationMonotonic(tlTotalEl, tlTotalSec + liveDelta, "timeline-total", false);
            }
        }

        // --- Unified live-span DOM walk ---
        // Every live row (recent / session / detail) carries ``data-display-span-id``. The ticker
        // looks up the registered clock by span id and renders ``liveSeconds(clock)`` so all rows
        // share one clock. Rows without the attribute keep their seeded text.
        var liveNodes = document.querySelectorAll("[data-display-span-id]");
        for (var i = 0; i < liveNodes.length; i++) {
            var node = liveNodes[i];
            var spanId = node.getAttribute("data-display-span-id");
            if (!spanId) continue;
            var nodeClock = App.liveClockBySpanId[spanId] || clock;
            if (!nodeClock) continue;
            if (nodeClock.is_live !== true) continue;
            var nextSec = liveSeconds(nodeClock);
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
            var continuity = "span:" + spanId;
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
