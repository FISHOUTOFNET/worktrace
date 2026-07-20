// WorkTrace WebView frontend core module.
// Owns UI state and rendering helpers only. Runtime transport acceptance and
// the application clock are owned exclusively by init.js.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    App.HEARTBEAT_INTERVAL_MS = 1000;
    App.NOTE_MAX_LENGTH = 2000;
    App.heartbeatTimer = null;
    App.lastOverviewSnapshot = null;
    App.lastRecentData = null;
    App.lastSessionDetailsViewModel = null;
    App.lastSessionActivitySummaryViewModel = null;
    App.lastTimelineData = null;
    App.liveDisplayModel = null;
    App.liveClockContractViolation = null;
    App.liveClockContractRefreshRequested = false;
    App.liveClockViolationKeys = {};
    App.lastRefreshState = null;
    App.refreshCheckInFlight = false;
    App.activePageRefreshInFlight = false;
    App.lastFullRefreshAtEpochMs = 0;
    App.RECONCILE_INTERVAL_MS = 180000;
    App.lastReconcileAtEpochMs = 0;
    App.reconcileInFlight = false;
    App._monotonicRenderState = {};
    App.currentPage = "overview";
    App.timelineDate = null;
    App.timelineLoaded = false;
    App.timelineLoading = false;
    App.timelineLoadingOwner = null;
    App.timelineEpoch = 0;
    App.selectionEpoch = 0;
    App.detailsOwner = null;
    App.selectedProjectionRevision = null;
    App.timelineRequestToken = 0;
    App.detailsInFlight = {};
    App.overviewRequestToken = 0;
    App.recentRequestToken = 0;
    App.projectsCache = null;
    App.projectsLoading = false;
    App.currentSessions = [];
    App.editingSession = null;
    App.editSaving = false;
    App.statisticsLoaded = false;
    App.statisticsLoading = false;
    App.statisticsRequestToken = 0;
    App.statisticsExportSaving = false;
    App.settingsLoaded = false;
    App.settingsLoading = false;
    App.settingsRequestToken = 0;
    App.settingsWriteInProgress = false;
    App.settingsBackupExportInProgress = false;
    App.settingsBackupManifestInProgress = false;
    App.settingsBackupImportInProgress = false;
    App.settingsClearAllInProgress = false;
    App.firstRunNoticeLoaded = false;
    App.firstRunNoticeLoading = false;
    App.firstRunNoticeRequired = false;
    App.firstRunNoticeAcceptInProgress = false;
    App.firstRunNoticeViewingFromSettings = false;
    App.rulesLoaded = false;
    App.rulesLoading = false;
    App.rulesRequestToken = 0;
    App.rulesSortMode = "last_used";
    App.rulesDeletingRuleKey = null;
    App.rulesDeletingFolderKey = null;
    App.lastProjectRulesData = null;
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

    function showError(message) {
        var banner = document.getElementById("overview-error");
        if (!banner) return;
        banner.hidden = !message;
        banner.textContent = message || "加载失败，请稍后重试。";
    }
    App.showError = showError;
    App.clearError = function () { showError(""); };

    function showTimelineError(message) {
        var banner = document.getElementById("timeline-error");
        if (!banner) return;
        banner.hidden = !message;
        banner.textContent = message || "加载失败，请稍后重试。";
    }
    App.showTimelineError = showTimelineError;
    App.clearTimelineError = function () { showTimelineError(""); };

    function setTimelineLoading(loading) {
        App.timelineLoading = loading;
        var element = document.getElementById("timeline-loading");
        if (element) element.hidden = !loading;
    }
    App.setTimelineLoading = setTimelineLoading;

    function statusClassFor(type) {
        return App.STATUS_TYPE_CLASS[type] || App.STATUS_TYPE_CLASS.info;
    }
    App.statusClassFor = statusClassFor;

    function applyStatusType(element, type) {
        if (!element) return;
        var preserved = typeof element.className === "string"
            ? element.className.split(/\s+/).filter(function (className) {
                return className && App.STATUS_TYPE_CLASS_VALUES.indexOf(className) === -1;
            })
            : [];
        if (preserved.indexOf("edit-status") === -1) preserved.unshift("edit-status");
        preserved.push(statusClassFor(type));
        element.className = preserved.join(" ");
    }
    App.applyStatusType = applyStatusType;

    App.setTimelineStatus = function (message, type) {
        if (!message) {
            App.clearTimelineError();
            setTimelineLoading(false);
        } else if (type === "loading") {
            setTimelineLoading(true);
            App.clearTimelineError();
        } else if (type === "error") {
            setTimelineLoading(false);
            showTimelineError(message);
        } else {
            setTimelineLoading(false);
            App.clearTimelineError();
        }
    };

    App.setDetailStatus = function (message) {
        var header = document.getElementById("timeline-details-header");
        if (header) header.textContent = message || "请选择一条时间记录";
    };

    App.setEditStatus = function (message, type) {
        App.showEditStatus(message || "", type === "error");
    };

    function projectRuntimePresentation(result) {
        if (!result || typeof result !== "object") return result;
        var runtime = result.runtime;
        if (!runtime || Number(runtime.schema_version || 0) !== 2) return result;
        var projected = Object.assign({}, result);
        projected.current_activity = runtime.current_activity || {};
        return projected;
    }

    function handleResult(result, onError) {
        if (result && result.ok === false) {
            onError(result.message || "操作失败", result.error || "operation_failed");
            return null;
        }
        return projectRuntimePresentation(result);
    }
    App.handleResult = handleResult;
    App.projectRuntimePresentation = projectRuntimePresentation;

    App.showStatus = function (statusResult) {
        if (!statusResult) return;
        var display = document.getElementById("status-display");
        var button = document.getElementById("toggle-pause-btn");
        if (!display || !button) return;
        display.textContent = statusResult.display || "未知";
        display.className = "status-display";
        if (statusResult.status === "running" && !statusResult.paused) {
            display.classList.add("recording");
            button.textContent = "暂停记录";
            button.className = "toggle-btn pause-style";
        } else {
            display.classList.add("paused");
            button.textContent = "开始记录";
            button.className = "toggle-btn";
        }
    };

    App.safeText = function (value, fallback) {
        return value === null || value === undefined || value === ""
            ? (fallback || "")
            : String(value);
    };

    function escapeHtml(text) {
        if (text === null || text === undefined) return "";
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }
    App.escapeHtml = escapeHtml;

    App.formatTimeRange = function (start, end, inProgress) {
        var startText = (start || "").slice(11, 16);
        var endText = (end || "").slice(11, 16);
        return inProgress || !endText ? startText + "-进行中" : startText + "-" + endText;
    };
    App.formatStartTimeOnly = function (startTime) { return (startTime || "").slice(11, 16); };

    App.shiftDate = function (dateString, days) {
        var base;
        if (!dateString || dateString === "--") {
            base = new Date();
        } else {
            var parts = dateString.split("-");
            base = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        }
        base.setDate(base.getDate() + days);
        return base.getFullYear()
            + "-" + String(base.getMonth() + 1).padStart(2, "0")
            + "-" + String(base.getDate()).padStart(2, "0");
    };

    function localTodayStr() {
        var date = new Date();
        return date.getFullYear()
            + "-" + String(date.getMonth() + 1).padStart(2, "0")
            + "-" + String(date.getDate()).padStart(2, "0");
    }
    App.localTodayStr = localTodayStr;

    function formatDuration(seconds) {
        var value = Math.max(0, parseInt(seconds, 10) || 0);
        var hours = Math.floor(value / 3600);
        var minutes = Math.floor((value % 3600) / 60);
        var remainder = value % 60;
        function pad(number) { return number < 10 ? "0" + number : String(number); }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(remainder);
    }
    App.formatDuration = formatDuration;

    App.readDurationSecondsFromText = function (element) {
        if (!element) return 0;
        var attribute = element.getAttribute("data-duration-seconds");
        if (attribute !== null && attribute !== "") {
            var parsed = parseInt(attribute, 10);
            if (!isNaN(parsed) && parsed >= 0) return parsed;
        }
        var match = /^(\d+):(\d{2}):(\d{2})$/.exec((element.textContent || "").trim());
        return match
            ? parseInt(match[1], 10) * 3600 + parseInt(match[2], 10) * 60 + parseInt(match[3], 10)
            : 0;
    };

    function renderDurationProjected(element, seconds, continuityKey, options) {
        if (!element) return;
        var next = Math.max(0, parseInt(seconds, 10) || 0);
        element.textContent = formatDuration(next);
        element.setAttribute("data-duration-seconds", String(next));
        if (continuityKey) App._monotonicRenderState[String(continuityKey)] = { lastSeconds: next };
        void options;
    }
    App.renderDurationProjected = renderDurationProjected;
    App.renderDurationMonotonic = function (element, seconds, key) {
        renderDurationProjected(element, seconds, key);
    };
    App.resetMonotonicRenderState = function (key) {
        if (key) delete App._monotonicRenderState[key];
        else App._monotonicRenderState = {};
    };

    App.formatProjectLabel = function (name, description) {
        var projectName = String(name || "").trim() || "未归类";
        var projectDescription = String(description || "").trim();
        return projectDescription ? projectName + "（" + projectDescription + "）" : projectName;
    };
    App.displayStatusText = function (item) {
        item = item || {};
        return item.display_status || item.status_label || item.status_summary || "";
    };

    var LIVE_CLOCK_KEYS = [
        "aggregate_base_seconds",
        "display_span_id",
        "duration_semantic",
        "elapsed_seconds_at_sample",
        "is_live",
        "live_state",
        "sampled_at_epoch_ms",
        "stable_live_key_hash",
        "started_at_epoch_ms"
    ];

    function exactObjectKeys(value, expected) {
        if (!value || typeof value !== "object" || Array.isArray(value)) return false;
        var actual = Object.keys(value).sort();
        if (actual.length !== expected.length) return false;
        for (var index = 0; index < expected.length; index++) {
            if (actual[index] !== expected[index]) return false;
        }
        return true;
    }

    function nonNegativeInteger(value) {
        return typeof value === "number" && Number.isInteger(value) && value >= 0;
    }

    App.validateLiveClock = function (clock) {
        if (!exactObjectKeys(clock, LIVE_CLOCK_KEYS)) return null;
        if (!nonNegativeInteger(clock.sampled_at_epoch_ms)
            || !nonNegativeInteger(clock.started_at_epoch_ms)
            || !nonNegativeInteger(clock.elapsed_seconds_at_sample)
            || !nonNegativeInteger(clock.aggregate_base_seconds)
            || typeof clock.is_live !== "boolean"
            || ["current_live", "aggregate_live", "static_closed"].indexOf(clock.duration_semantic) === -1
            || ["persisted_open", "suppressed", "none"].indexOf(clock.live_state) === -1
            || typeof clock.display_span_id !== "string"
            || typeof clock.stable_live_key_hash !== "string") {
            return null;
        }
        if (clock.is_live === true) {
            if (clock.live_state !== "persisted_open"
                || clock.duration_semantic === "static_closed"
                || clock.sampled_at_epoch_ms <= 0
                || clock.started_at_epoch_ms <= 0
                || !clock.display_span_id
                || !clock.stable_live_key_hash) {
                return null;
            }
        } else if (clock.duration_semantic !== "static_closed") {
            return null;
        }
        return Object.freeze(Object.assign({}, clock));
    };
    App.normalizeLiveClock = App.validateLiveClock;

    App.recordLiveClockContractViolation = function (spanId, page, reason, schemaVersion) {
        var key = [
            String(page || App.currentPage || ""),
            String(reason || "invalid_live_clock"),
            String(schemaVersion || 2),
            String(spanId || "")
        ].join("|");
        if (App.liveClockViolationKeys[key]) return;
        App.liveClockViolationKeys[key] = true;
        App.liveClockContractViolation = {
            spanId: String(spanId || ""),
            page: String(page || App.currentPage || ""),
            reason: String(reason || "invalid_live_clock"),
            schemaVersion: Number(schemaVersion || 2),
            at: Date.now()
        };
        App.liveClockContractRefreshRequested = true;
    };

    App.runtimeReportDateForPage = function (page, fallbackDate) {
        return page === "timeline"
            ? (fallbackDate || App.timelineDate || localTodayStr())
            : (fallbackDate || localTodayStr());
    };

    App.liveContinuityKey = function (item, prefix) {
        var clock = item && App.validateLiveClock(item.live_clock);
        if (clock && clock.stable_live_key_hash) return prefix + ":live:" + clock.stable_live_key_hash;
        if (clock && clock.display_span_id) return prefix + ":span:" + clock.display_span_id;
        if (item && item.projection_instance_key) return prefix + ":" + item.projection_instance_key;
        if (item && item.activity_id) return prefix + ":" + item.activity_id;
        return prefix;
    };

    App.currentActivityContinuityKey = function (current, clock, prefix) {
        var identity = clock && (clock.display_span_id || clock.stable_live_key_hash);
        if (!identity) identity = String(current.persisted_activity_id || current.activity_id || "")
            + ":" + String(current.start_time || "");
        return prefix + ":current:" + (identity || "none");
    };

    App.computeClockDurationNow = function (clock, nowMs) {
        var accepted = App.validateLiveClock(clock);
        if (!accepted || accepted.duration_semantic === "static_closed") return null;
        var delta = accepted.is_live
            ? Math.max(0, Math.floor((nowMs - accepted.sampled_at_epoch_ms) / 1000))
            : 0;
        var elapsed = accepted.elapsed_seconds_at_sample + delta;
        return accepted.duration_semantic === "aggregate_live"
            ? accepted.aggregate_base_seconds + elapsed
            : elapsed;
    };
    App.computeActiveElapsedNow = function (clock, nowMs) {
        var accepted = App.validateLiveClock(clock);
        if (!accepted || accepted.duration_semantic !== "current_live") return 0;
        return App.computeClockDurationNow(accepted, nowMs) || 0;
    };

    function liveClockAttribute(name, value) {
        return ' data-clock-' + name + '="' + escapeHtml(String(value)) + '"';
    }

    App.liveClockDataAttributes = function (clock, continuityKey, role) {
        var accepted = App.validateLiveClock(clock);
        if (!accepted || accepted.is_live !== true) return "";
        var result = ' data-live-clock-target="1"';
        result += liveClockAttribute("sampled-at-epoch-ms", accepted.sampled_at_epoch_ms);
        result += liveClockAttribute("started-at-epoch-ms", accepted.started_at_epoch_ms);
        result += liveClockAttribute("elapsed-seconds-at-sample", accepted.elapsed_seconds_at_sample);
        result += liveClockAttribute("aggregate-base-seconds", accepted.aggregate_base_seconds);
        result += liveClockAttribute("duration-semantic", accepted.duration_semantic);
        result += liveClockAttribute("is-live", "true");
        result += liveClockAttribute("live-state", accepted.live_state);
        result += liveClockAttribute("display-span-id", accepted.display_span_id);
        result += liveClockAttribute("stable-live-key-hash", accepted.stable_live_key_hash);
        if (continuityKey) result += ' data-live-continuity-key="' + escapeHtml(String(continuityKey)) + '"';
        if (role) result += ' data-live-role="' + escapeHtml(String(role)) + '"';
        return result;
    };

    App.readLiveClockTarget = function (element) {
        if (!element || element.getAttribute("data-live-clock-target") !== "1") return null;
        var clock = {
            sampled_at_epoch_ms: Number(element.getAttribute("data-clock-sampled-at-epoch-ms")),
            started_at_epoch_ms: Number(element.getAttribute("data-clock-started-at-epoch-ms")),
            elapsed_seconds_at_sample: Number(element.getAttribute("data-clock-elapsed-seconds-at-sample")),
            aggregate_base_seconds: Number(element.getAttribute("data-clock-aggregate-base-seconds")),
            duration_semantic: String(element.getAttribute("data-clock-duration-semantic") || ""),
            is_live: element.getAttribute("data-clock-is-live") === "true",
            live_state: String(element.getAttribute("data-clock-live-state") || ""),
            display_span_id: String(element.getAttribute("data-clock-display-span-id") || ""),
            stable_live_key_hash: String(element.getAttribute("data-clock-stable-live-key-hash") || "")
        };
        return App.validateLiveClock(clock);
    };

    App.setLiveClockTarget = function (element, clock, continuityKey, role) {
        if (!element) return false;
        App.clearLiveClockTarget(element);
        var accepted = App.validateLiveClock(clock);
        if (!accepted || accepted.is_live !== true) return false;
        element.setAttribute("data-live-clock-target", "1");
        element.setAttribute("data-clock-sampled-at-epoch-ms", String(accepted.sampled_at_epoch_ms));
        element.setAttribute("data-clock-started-at-epoch-ms", String(accepted.started_at_epoch_ms));
        element.setAttribute("data-clock-elapsed-seconds-at-sample", String(accepted.elapsed_seconds_at_sample));
        element.setAttribute("data-clock-aggregate-base-seconds", String(accepted.aggregate_base_seconds));
        element.setAttribute("data-clock-duration-semantic", accepted.duration_semantic);
        element.setAttribute("data-clock-is-live", "true");
        element.setAttribute("data-clock-live-state", accepted.live_state);
        element.setAttribute("data-clock-display-span-id", accepted.display_span_id);
        element.setAttribute("data-clock-stable-live-key-hash", accepted.stable_live_key_hash);
        if (continuityKey) element.setAttribute("data-live-continuity-key", String(continuityKey));
        if (role) element.setAttribute("data-live-role", String(role));
        return true;
    };

    App.clearLiveClockTarget = function (element) {
        if (!element) return;
        [
            "data-live-clock-target",
            "data-clock-sampled-at-epoch-ms",
            "data-clock-started-at-epoch-ms",
            "data-clock-elapsed-seconds-at-sample",
            "data-clock-aggregate-base-seconds",
            "data-clock-duration-semantic",
            "data-clock-is-live",
            "data-clock-live-state",
            "data-clock-display-span-id",
            "data-clock-stable-live-key-hash",
            "data-live-continuity-key",
            "data-live-role"
        ].forEach(function (name) { element.removeAttribute(name); });
    };

    App.renderCurrentActivityElement = function (element, current, prefix) {
        if (!element) return;
        current = current || {};
        if (!current.active) {
            App.clearLiveClockTarget(element);
            element.textContent = "当前活动：无";
            return;
        }
        var clock = App.getActiveLiveClock ? App.getActiveLiveClock() : null;
        var accepted = App.validateLiveClock(clock);
        var canTick = !!(accepted
            && accepted.is_live === true
            && accepted.duration_semantic === "current_live");
        var seconds = canTick
            ? App.computeClockDurationNow(accepted, Date.now())
            : (parseInt(current.elapsed_seconds, 10) || 0);
        var continuity = App.currentActivityContinuityKey(current, accepted, prefix);
        var parts = String(current.display || "").split("｜");
        if (parts.length < 3) {
            element.textContent = "当前活动：" + (current.display || App.displayStatusText(current));
            return;
        }
        var attributes = canTick
            ? App.liveClockDataAttributes(accepted, continuity, (prefix || "current") + "-current")
            : "";
        var html = "当前活动：" + escapeHtml(parts[0]) + "｜" + escapeHtml(parts[1]) + "｜"
            + '<span class="current-activity-duration"' + attributes
            + ' data-duration-seconds="' + String(seconds || 0) + '">'
            + escapeHtml(formatDuration(seconds || 0)) + '</span>';
        for (var index = 3; index < parts.length; index++) html += "｜" + escapeHtml(parts[index]);
        element.innerHTML = html;
    };

    App.renderLiveDurationTarget = function (target, clock, nowMs) {
        if (!target) return false;
        var accepted = App.validateLiveClock(clock);
        if (!accepted || accepted.is_live !== true) return false;
        var seconds = App.computeClockDurationNow(accepted, nowMs);
        if (seconds === null) return false;
        renderDurationProjected(
            target,
            seconds,
            target.getAttribute("data-live-continuity-key") || ""
        );
        return true;
    };

    App.liveTargetCompatibleWithRuntime = function (target, runtime) {
        if (!target || !runtime) return false;
        var targetClock = App.readLiveClockTarget(target);
        var runtimeClock = App.validateLiveClock(runtime.liveClock);
        if (!targetClock || !runtimeClock) return false;
        return targetClock.display_span_id === runtimeClock.display_span_id
            && targetClock.stable_live_key_hash === runtimeClock.stable_live_key_hash;
    };

    App._timelineEditingActive = function () {
        return App.editSaving || !!(
            App.editingSession
            && typeof App.isEditDirty === "function"
            && App.isEditDirty()
        );
    };
})();
