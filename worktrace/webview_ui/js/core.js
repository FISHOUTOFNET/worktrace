// WorkTrace WebView frontend — core module.
// Namespace + shared state + bridge helper + generic helpers + date/time/format utils.
// Only communicates with Python through pywebview API bridge.
// Does not persist sensitive data in browser storage APIs.
// Does not access any external network resources.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // Single 1-second heartbeat: applies the local ticker (re-renders
    // already-fetched durations with a wall-clock delta) and then runs a
    // lightweight ``get_refresh_state`` revision check. Heavy interfaces
    // (get_overview / get_recent_activities / get_timeline) are only called
    // when the structural revision changes.
    App.HEARTBEAT_INTERVAL_MS = 1000;
    App.NOTE_MAX_LENGTH = 2000;
    App.heartbeatTimer = null;

    // The local ticker ONLY updates DOM text; it never calls a bridge
    // method, never writes the DB, and never starts / stops the collector.
    // The snapshots are set by showOverview / showRecent / showTimeline /
    // renderSessionDetails and read by the ticker to compute the live
    // increment.
    App.lastOverviewSnapshot = null;
    // Recent-activities snapshot so the ticker can increment the live-
    // projected recent item's duration without a bridge round-trip.
    App.lastRecentSnapshot = null;
    // Session-details snapshot so the ticker can increment the live-
    // projected detail row's duration without a bridge round-trip.
    App.lastSessionDetailsData = null;

    // ``lastRefreshState`` caches the last ``get_refresh_state`` payload so
    // the heartbeat can compare ``refresh_revision`` between ticks.
    // ``refreshCheckInFlight`` / ``activePageRefreshInFlight`` guard
    // overlapping revision checks and heavy page-data refreshes.
    // ``lastFullRefreshAtEpochMs`` records the last heavy-refresh completion.
    App.lastRefreshState = null;
    App.refreshCheckInFlight = false;
    App.activePageRefreshInFlight = false;
    // Pending page refresh: when ``refreshCurrentPageData`` is called while
    // a refresh is already in-flight, the request is recorded here. After
    // the in-flight refresh completes, a new refresh is triggered if this
    // flag is true so a page-switch immediate refresh is never silently
    // skipped by the global in-flight guard.
    App.pendingPageRefresh = false;
    App.lastFullRefreshAtEpochMs = 0;
    App.RECONCILE_INTERVAL_MS = 180000;
    App.lastReconcileAtEpochMs = 0;
    App.reconcileInFlight = false;

    // Maps a continuity key (e.g. ``"recent:live:<stable_hash>"``,
    // ``"session:live:<stable_hash>"``, ``"detail:live:<stable_hash>"``,
    // ``"overview-total"``) to the last rendered seconds. Used by
    // ``renderDurationMonotonic`` to avoid visual rollback when the new
    // projected seconds are 1-2s less than the DOM value.
    App._monotonicRenderState = {};

    App.currentPage = "overview";
    App.timelineDate = null;
    App.timelineLoaded = false;
    App.timelineLoading = false;
    App.selectedSessionId = null;
    // Stable live key (stable_live_key_hash) for the currently selected
    // session. Selection continuity: when session_id changes from
    // "virtual-live:<hash>" to the real DB session id, stable_live_key_hash
    // stays the same so the selection survives the virtual → persisted_open
    // transition.
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
    App.rulesSavingRuleKey = null;

    // Keyword creation writes are isolated from rule toggle writes.
    // Only one keyword create may be in flight at a time.
    App.rulesCreatingKeyword = false;

    // Keyword deletion writes carry the "<kind>:<id>" key of the row being
    // deleted so only that row's button enters deleting state.
    App.rulesDeletingRuleKey = null;

    // Keyword edit writes carry the "keyword:<id>" key of the row being
    // edited or saved.
    App.rulesEditingKeywordKey = null;
    App.rulesUpdatingKeywordKey = null;

    // Folder rule CRUD state. Only one folder write may be in flight per
    // kind at a time.
    App.rulesCreatingFolder = false;
    App.rulesEditingFolderKey = null;
    App.rulesDeletingFolderKey = null;
    // Cache of the last-loaded Project Rules data so the inline folder
    // edit form can re-render the list immediately without a round-trip
    // through loadProjectRules (which would lose input focus).
    App.lastProjectRulesData = null;

    // Project lifecycle writes are isolated from rule CRUD button and input
    // disabled state. Only one project lifecycle write may be in flight per
    // kind at a time.
    App.rulesCreatingProject = false;
    App.rulesEditingProjectId = null;
    App.rulesUpdatingProjectId = null;
    App.rulesTogglingProjectId = null;
    App.rulesArchivingProjectId = null;

    // Rule impact preview + safe single-rule backfill state.
    // ``rulesPreviewingImpactKey``: preview key currently loading.
    // ``rulesBackfillingRuleKey``: backfill key currently being applied.
    // ``rulesImpactPreviewKey``: rendered preview key (null = no preview).
    // ``rulesImpactPreviewData``: cached preview payload for re-render.
    App.rulesPreviewingImpactKey = null;
    App.rulesBackfillingRuleKey = null;
    App.rulesImpactPreviewKey = null;
    App.rulesImpactPreviewData = null;

    // Selected-rule batch operations state.
    // ``rulesBatchSelectedKeys``: selected rule keys kept in JS memory only.
    // ``rulesBatchInFlight``: true while preview / apply / enable / disable
    // batch work is running; while true, batch and per-rule write controls
    // are disabled.
    // ``rulesBatchPanelData``: cached batch panel payload for re-render.
    App.rulesBatchSelectedKeys = {};
    App.rulesBatchInFlight = false;
    App.rulesBatchPanelData = null;

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
    // session list and read-only detail rows where the end time is no
    // longer shown.
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

    // Shared by Overview KPI, current activity, recent, Timeline total,
    // Timeline session, and Timeline details so every live target uses the
    // same monotonic-render contract.
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
    // so the real snapshot duration can replace the projected value.
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

    // Unified project label contract:
    //   project_label = name if description empty else f"{name}（{description}）"
    // Uses full-width Chinese parentheses with no surrounding space so the
    // label stays compact and consistent across all rendered rows.
    // session / Timeline detail / virtual / pending / persisted-open rows.
    function formatProjectLabel(name, description) {
        var n = String(name || "").trim();
        if (!n) n = "未归类";
        var d = String(description || "").trim();
        if (!d) return n;
        return n + "（" + d + "）";
    }
    App.formatProjectLabel = formatProjectLabel;

    // ``applyLocalTicker`` re-renders already-fetched durations with a
    // wall-clock delta so the UI updates every second without a bridge
    // round-trip. The ticker ONLY updates DOM text; it never calls a
    // bridge method, never writes the DB, and never starts / stops the
    // collector. It is a no-op when the current activity is paused / idle /
    // excluded / error or when no snapshot has been fetched yet.
    // been fetched yet. The heartbeat's second phase (revision check) runs
    // in init.js and calls heavy interfaces only when the structural
    // revision changes.
    //
    // The ticker computes the live delta from the activity's start_time
    // (``live_started_at_epoch_ms``) instead of the backend response time,
    // so the same current activity does not jump fast/slow across
    // refreshes because the start_time anchor is stable. The formula is:
    // across refreshes. The formula is:
    //   display_seconds = carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)
    // and the KPI delta is:
    //   delta = display_seconds - elapsed_seconds_at_response
    function tickerNowEpochMs() {
        return Date.now();
    }

    // Returns the wall-clock increment to add to KPI totals and per-item
    // durations. Uses the stable start-time anchor so the delta does not
    // drift between refreshes. Returns 0 when the payload has no live
    // clock fields or the current activity is not live-eligible.
    // when the current activity is not live-eligible.
    //
    // The ticker reads from the SINGLE page-level live projection. When
    // the payload carries a ``live_projection`` field (Overview bundle /
    // Timeline / Detail), that field is the single source of truth.
    // Payloads without ``live_projection`` fall back to ``live_display``
    // / ``current_activity`` so the Timeline main payload keeps working.
    // main payload (which still carries ``live_display``) keeps working.
    function tickerDeltaSeconds(payload) {
        if (!payload) return 0;
        var ld = payload.live_projection || payload.live_display || payload.current_activity;
        if (!ld) return 0;
        var startedAt = parseInt(ld.live_started_at_epoch_ms, 10);
        if (!startedAt || isNaN(startedAt)) {
            return 0;
        }
        var carry = parseInt(ld.carry_seconds, 10) || 0;
        // ``live_projection`` carries ``duration_seconds``; ``live_display``
        // / ``current_activity`` carry ``elapsed_seconds``. Accept either
        // field from the backend payload.
        var elapsedAtResponse = parseInt(ld.duration_seconds, 10);
        if (isNaN(elapsedAtResponse)) {
            elapsedAtResponse = parseInt(ld.elapsed_seconds, 10) || 0;
        }
        var displaySeconds = carry + Math.floor((tickerNowEpochMs() - startedAt) / 1000);
        var delta = displaySeconds - elapsedAtResponse;
        return delta > 0 ? delta : 0;
    }
    App.tickerDeltaSeconds = tickerDeltaSeconds;

    // Live-display eligibility: only virtual (unpersisted normal) and
    // persisted_open (real open normal row) increment normal project
    // duration. paused / idle / excluded / error / none never do.
    // Prefer ``live_projection.live_state`` (single source of truth) when
    // present; fall back to ``live_display`` / ``current_activity`` for
    // payloads without live_projection.
    function tickerLiveEligible(payload) {
        if (!payload) return false;
        var lp = payload.live_projection;
        if (lp) {
            return lp.live_state === "virtual" || lp.live_state === "persisted_open";
        }
        var ld = payload.live_display;
        if (ld) {
            return ld.live_state === "virtual" || ld.live_state === "persisted_open";
        }
        var current = payload.current_activity;
        if (!current || !current.active) return false;
        if (current.is_paused) return false;
        if (current.status !== "normal") return false;
        return true;
    }
    App.tickerLiveEligible = tickerLiveEligible;

    function tickerCurrentActivityRunning(snapshot) {
        return tickerLiveEligible(snapshot);
    }

    // Stable continuity key for a live item. Uses ``stable_live_key_hash``
    // when available so the continuity survives the virtual → persisted_open
    // transition. Falls back to the session / activity id for non-live
    // items.
    //
    // SINGLE SOURCE OF TRUTH: this is the ONLY place that should construct
    // a live-row continuity key. The ticker, the render seed, and any live
    // duration DOM update MUST all call App.liveContinuityKey(item,
    // prefix) so the key stays stable across the virtual → persisted_open
    // transition.
    // array index, the session id, or the activity id directly would break
    // the virtual → persisted_open transition because those values change
    // across the transition while stable_live_key_hash stays the same.
    function liveContinuityKey(item, prefix) {
        if (!item) return prefix;
        if (item.stable_live_key_hash) {
            return prefix + ":live:" + item.stable_live_key_hash;
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

    function applyLocalTicker() {
        // Overview page: KPI total + classified + uncategorized + current
        // activity display. total / classified / uncategorized must use
        // the same delta. The delta is added to EITHER classified OR
        // uncategorized (never both) depending on the current activity's
        // classification state.
        var ov = App.lastOverviewSnapshot;
        if (ov && App.currentPage === "overview") {
            var delta = 0;
            var currentIsUncategorized = true;
            if (tickerLiveEligible(ov)) {
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
                    // Compute the display seconds from the stable start-time
                    // anchor so the current activity display does not drift
                    // between refreshes. Prefer ``live_projection`` (single
                    // source of truth) when the Overview bundle is in use.
                    // prefer ``live_projection`` (single source of truth)
                    // when the Overview bundle is in use.
                    var ld = ov.live_projection || ov.live_display || current;
                    var startedAt = parseInt(ld.live_started_at_epoch_ms, 10);
                    var carry = parseInt(ld.carry_seconds, 10) || 0;
                    var elapsedSec = parseInt(current.elapsed_seconds, 10) || 0;
                    var displaySec;
                    if (startedAt && !isNaN(startedAt)) {
                        displaySec = carry + Math.floor((Date.now() - startedAt) / 1000);
                    } else {
                        displaySec = elapsedSec + delta;
                    }
                    var display = current.display || "";
                    var parts = display.split("｜");
                    if (parts.length >= 3) {
                        parts[2] = App.formatDuration(displaySec);
                        currentEl.textContent = "当前活动：" + parts.join("｜");
                    }
                } else {
                    currentEl.textContent = "当前活动：无";
                }
            }
        }
        // Recent list: update live (virtual or persisted-open) recent items.
        // The baseline comes from the cached payload's ``duration_seconds``,
        // NOT from DOM text. Both virtual live items and real is_in_progress
        // items are handled by flag. The continuity key uses
        // stable_live_key_hash so the duration display does not reset when
        // virtual → persisted.
        var recent = App.lastRecentSnapshot;
        if (recent && App.currentPage === "overview" && recent.activities) {
            var recentDelta = tickerLiveEligible(recent) ? tickerDeltaSeconds(recent) : 0;
            for (var ri = 0; ri < recent.activities.length; ri++) {
                var rItem = recent.activities[ri];
                if (rItem.is_virtual_live || rItem.is_in_progress) {
                    var rEl = document.querySelector(
                        '.recent-item[data-recent-index="' + ri + '"] .recent-item-duration'
                    );
                    if (rEl) {
                        var rBaseSec = parseInt(rItem.duration_seconds, 10) || 0;
                        var rContinuity = liveContinuityKey(rItem, "recent");
                        App.renderDurationMonotonic(
                            rEl, rBaseSec + recentDelta, rContinuity, false
                        );
                    }
                }
            }
        }
        // Timeline page: date total + current activity display + in-progress
        // / live-projected session duration + projected detail. Only when
        // viewing today.
        var tl = App.lastTimelineData;
        if (tl && App.currentPage === "timeline") {
            var todayStr = App.localTodayStr();
            var isToday = !tl.date || tl.date === todayStr || tl.date === "--";
            var tlDelta = 0;
            if (isToday && tickerLiveEligible(tl)) {
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
                    var tlLd = tl.live_display || tlCurrent;
                    var tlStartedAt = parseInt(tlLd.live_started_at_epoch_ms, 10);
                    var tlCarry = parseInt(tlLd.carry_seconds, 10) || 0;
                    var tlElapsedSec = parseInt(tlCurrent.elapsed_seconds, 10) || 0;
                    var tlDisplaySec;
                    if (tlStartedAt && !isNaN(tlStartedAt)) {
                        tlDisplaySec = tlCarry + Math.floor((Date.now() - tlStartedAt) / 1000);
                    } else {
                        tlDisplaySec = tlElapsedSec + tlDelta;
                    }
                    var tlDisplay = tlCurrent.display || "";
                    var tlParts = tlDisplay.split("｜");
                    if (tlParts.length >= 3) {
                        tlParts[2] = App.formatDuration(tlDisplaySec);
                        tlCurrentEl.textContent = "当前活动：" + tlParts.join("｜");
                    }
                } else {
                    tlCurrentEl.textContent = "当前活动：无";
                }
            }
            // Update in-progress / live-projected session durations.
            // Locate each session's DOM via ``data-session-id`` instead of
            // array index so a re-rendered list cannot mismatch sessions.
            // The continuity key uses stable_live_key_hash for live
            // sessions so the duration does not reset on transition. Look
            // up the DOM by stable_live_key_hash FIRST so the ticker
            // survives the virtual → persisted_open transition; fall back to
            // session_id for closed sessions that don't carry a stable key.
            // virtual → persisted_open transition (when session_id
            // changes from "virtual-live:<hash>" to the real DB session
            // id, the stable_live_key_hash stays the same). Fall back to
            // session_id for closed sessions that don't carry a stable
            // key (verification item 三.5).
            if (isToday && tlDelta >= 0 && tl.sessions) {
                for (var si = 0; si < tl.sessions.length; si++) {
                    var s = tl.sessions[si];
                    if (s.is_in_progress || s.is_live_projected || s.is_virtual_live) {
                        var sid = s.session_id;
                        var sStableKey = s.stable_live_key_hash || "";
                        var itemEl = null;
                        if (sStableKey) {
                            itemEl = document.querySelector(
                                '#timeline-sessions-list .timeline-item[data-stable-live-key-hash="' + sStableKey + '"]'
                            );
                        }
                        if (!itemEl) {
                            itemEl = document.querySelector(
                                '#timeline-sessions-list .timeline-item[data-session-id="' + sid + '"]'
                            );
                        }
                        if (itemEl) {
                            var durEl = itemEl.querySelector(".timeline-item-duration");
                            if (durEl) {
                                var sSec = parseInt(s.duration_seconds, 10) || 0;
                                var sContinuity = liveContinuityKey(s, "session");
                                App.renderDurationMonotonic(durEl, sSec + tlDelta, sContinuity, false);
                            }
                        }
                    }
                }
            }
            // Detail-row projection. The detail ticker must NOT use the
            // Timeline main payload delta: the detail payload carries its
            // own ``live_display`` field so the detail ticker computes its
            // delta from the same unified live clock, independent of when
            // the Timeline main payload arrived. This prevents drift
            // between the detail duration and its own timing anchor.
            if (isToday && (App.selectedSessionId || App.selectedSessionLiveKey)
                && App.lastSessionDetailsData && !App._timelineEditingActive()) {
                var detailsList = document.getElementById("timeline-details-list");
                if (detailsList) {
                    var detailDelta = 0;
                    if (tickerLiveEligible(App.lastSessionDetailsData)) {
                        detailDelta = tickerDeltaSeconds(App.lastSessionDetailsData);
                    }
                    var detailActs = App.lastSessionDetailsData.activities || [];
                    for (var dai = 0; dai < detailActs.length; dai++) {
                        var dAct = detailActs[dai];
                        if (dAct.is_virtual_live || dAct.is_in_progress) {
                            // Look up the DOM by stable_live_key_hash FIRST
                            // so the ticker survives the virtual →
                            // persisted_open transition; fall back to
                            // activity_id for closed rows.
                            // to the real DB id, the stable_live_key_hash
                            // stays the same). Fall back to activity_id
                            // for closed rows that don't carry a stable
                            // key (verification item 三.5).
                            var dStableKey = dAct.stable_live_key_hash || "";
                            var dEl = null;
                            if (dStableKey) {
                                dEl = detailsList.querySelector(
                                    '.detail-item[data-stable-live-key-hash="' + dStableKey + '"] .detail-item-duration'
                                );
                            }
                            if (!dEl) {
                                var dAid = dAct.activity_id || 0;
                                dEl = detailsList.querySelector(
                                    '.detail-item[data-activity-id="' + dAid + '"] .detail-item-duration'
                                );
                            }
                            if (dEl) {
                                var dBaseSec = parseInt(dAct.duration_seconds, 10) || 0;
                                var dContinuity = liveContinuityKey(dAct, "detail");
                                App.renderDurationMonotonic(
                                    dEl, dBaseSec + detailDelta, dContinuity, false
                                );
                            }
                            break;
                        }
                    }
                }
            }
        }
    }
    App.applyLocalTicker = applyLocalTicker;

    // Timeline editing guard. The ticker, revision-change refresh,
    // low-frequency reconciliation, and page-switch refresh all respect
    // this guard so user input is never overwritten. It checks saving
    // flags + correctionShellOpen, OPEN BUT NOT YET SAVED editors
    // (editingActivityId / editingSplitActivityId), and dirty session
    // edits (editingSession + isEditDirty).
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
