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
        var allowDecrease = options && options.allowDecrease === true;
        var key = String(continuityKey || "");
        var next = Math.max(0, parseInt(seconds, 10) || 0);
        var previous = key ? App._monotonicRenderState[key] : null;
        if (!allowDecrease && previous && next < previous.lastSeconds) next = previous.lastSeconds;
        element.textContent = formatDuration(next);
        element.setAttribute("data-duration-seconds", String(next));
        if (key) App._monotonicRenderState[key] = { lastSeconds: next };
    }
    App.renderDurationProjected = renderDurationProjected;
    App.renderDurationMonotonic = function (element, seconds, key, allowDecrease) {
        renderDurationProjected(element, seconds, key, { allowDecrease: allowDecrease === true });
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

    function nonNegativeInt(value, fallback) {
        var parsed = parseInt(value, 10);
        return isNaN(parsed) || parsed < 0 ? (fallback || 0) : parsed;
    }

    App.normalizeLiveClock = function (clock) {
        if (!clock || typeof clock !== "object") return null;
        var durationAtSample = nonNegativeInt(clock.duration_seconds_at_sample, 0);
        var projectLive = clock.project_duration_live === true || clock.is_project_duration_live === true;
        return Object.assign({}, clock, {
            display_span_id: String(clock.display_span_id || ""),
            stable_live_key_hash: String(clock.stable_live_key_hash || ""),
            live_state: String(clock.live_state || "none"),
            duration_seconds_at_sample: durationAtSample,
            carry_seconds: nonNegativeInt(clock.carry_seconds, durationAtSample),
            live_started_at_epoch_ms: nonNegativeInt(clock.live_started_at_epoch_ms, 0),
            is_live: clock.is_live === true,
            current_duration_live: clock.current_duration_live === true,
            project_duration_live: projectLive,
            is_project_duration_live: projectLive
        });
    };

    App.recordLiveClockContractViolation = function (spanId, page, reason) {
        App.liveClockContractViolation = {
            spanId: String(spanId || ""),
            page: String(page || App.currentPage || ""),
            reason: String(reason || "missing_live_clock"),
            at: Date.now()
        };
        App.liveClockContractRefreshRequested = true;
    };

    App.projectFromDisplayBase = function (base, active) {
        return nonNegativeInt(base, 0) + nonNegativeInt(active, 0);
    };
    App.runtimeReportDateForPage = function (page, fallbackDate) {
        return page === "timeline"
            ? (fallbackDate || App.timelineDate || localTodayStr())
            : (fallbackDate || localTodayStr());
    };

    App.liveContinuityKey = function (item, prefix) {
        if (!item) return prefix;
        if (item.stable_live_key_hash) return prefix + ":live:" + item.stable_live_key_hash;
        if (item.display_span_id) return prefix + ":span:" + item.display_span_id;
        if (item.projection_instance_key) return prefix + ":" + item.projection_instance_key;
        if (item.activity_id) return prefix + ":" + item.activity_id;
        return prefix;
    };

    App.currentActivityContinuityKey = function (current, clock, prefix) {
        var identity = current.current_activity_display_span_id
            || current.current_resource_identity_hash
            || current.stable_live_key_hash
            || (clock && clock.display_span_id)
            || ((current.resource_name || current.app_name || "current") + ":" + (current.start_time || ""));
        return prefix + ":current:" + (identity || "none");
    };

    App.renderCurrentActivityElement = function (element, current, prefix) {
        if (!element) return;
        current = current || {};
        if (!current.active) {
            element.textContent = "当前活动：无";
            return;
        }
        var clock = App.getActiveLiveClock ? App.getActiveLiveClock() : null;
        var displaySpanId = String((clock && clock.display_span_id) || "");
        var currentSpanId = String(current.current_activity_display_span_id || "");
        var resourceHash = String(current.current_resource_identity_hash || "");
        var stableHash = String(current.stable_live_key_hash || (clock && clock.stable_live_key_hash) || "");
        var canTick = !!(clock && clock.current_duration_live === true && displaySpanId && currentSpanId && resourceHash);
        var seconds = canTick && App.computeActiveElapsedNow
            ? App.computeActiveElapsedNow(clock, Date.now())
            : (parseInt(current.elapsed_seconds, 10) || 0);
        var continuity = App.currentActivityContinuityKey(current, clock, prefix);
        var priorKey = element.getAttribute("data-current-continuity-key") || "";
        if (priorKey && priorKey !== continuity) App.resetMonotonicRenderState(priorKey);
        element.setAttribute("data-current-continuity-key", continuity);
        var prior = App._monotonicRenderState[continuity];
        if (prior && seconds < prior.lastSeconds) seconds = prior.lastSeconds;
        var parts = String(current.display || "").split("｜");
        if (parts.length < 3) {
            element.textContent = "当前活动：" + (current.display || App.displayStatusText(current));
            return;
        }
        var html = "当前活动：" + escapeHtml(parts[0]) + "｜" + escapeHtml(parts[1]) + "｜"
            + '<span class="current-activity-duration"'
            + (canTick ? ' data-live-duration-target="1" data-duration-semantic="current-live" data-display-base-seconds="0" data-live-base-seconds="0"' : '')
            + (canTick ? ' data-live-role="' + escapeHtml(prefix || "current") + '-current"' : '')
            + (canTick ? ' data-live-continuity-key="' + escapeHtml(continuity) + '"' : '')
            + (canTick ? ' data-current-activity-display-span-id="' + escapeHtml(currentSpanId) + '"' : '')
            + (canTick ? ' data-current-resource-identity-hash="' + escapeHtml(resourceHash) + '"' : '')
            + (canTick ? ' data-display-span-id="' + escapeHtml(displaySpanId) + '"' : '')
            + (canTick && stableHash ? ' data-stable-live-key-hash="' + escapeHtml(stableHash) + '"' : '')
            + ' data-duration-seconds="' + String(seconds) + '">' + escapeHtml(formatDuration(seconds)) + '</span>';
        for (var index = 3; index < parts.length; index++) html += "｜" + escapeHtml(parts[index]);
        element.innerHTML = html;
        App._monotonicRenderState[continuity] = { lastSeconds: seconds };
    };

    App.kpiBaseSeconds = function (snapshot, field) {
        snapshot = snapshot || {};
        var base = snapshot.kpi_live_base || {};
        return base[field] !== undefined && base[field] !== null
            ? nonNegativeInt(base[field], 0)
            : nonNegativeInt(snapshot[field], 0);
    };

    App.setLiveProjectionAnchor = function (element, baseSeconds, continuityKey, role) {
        if (!element) return;
        var base = String(nonNegativeInt(baseSeconds, 0));
        element.setAttribute("data-live-duration-target", "1");
        element.setAttribute("data-duration-semantic", "aggregate-live");
        element.setAttribute("data-display-base-seconds", base);
        element.setAttribute("data-live-base-seconds", base);
        if (role) element.setAttribute("data-live-role", String(role));
        if (continuityKey) element.setAttribute("data-live-continuity-key", String(continuityKey));
        var runtime = App.liveRuntime || {};
        if (runtime.displaySpanId) element.setAttribute("data-display-span-id", String(runtime.displaySpanId));
        if (runtime.stableLiveKeyHash) element.setAttribute("data-stable-live-key-hash", String(runtime.stableLiveKeyHash));
    };

    App.clearLiveProjectionAnchor = function (element) {
        if (!element) return;
        [
            "data-live-duration-target", "data-duration-semantic",
            "data-display-base-seconds", "data-live-base-seconds",
            "data-live-role", "data-live-continuity-key",
            "data-display-span-id", "data-stable-live-key-hash"
        ].forEach(function (name) { element.removeAttribute(name); });
    };

    App.renderLiveDurationTarget = function (target, baseSeconds, activeSeconds) {
        if (!target) return;
        renderDurationProjected(
            target,
            App.projectFromDisplayBase(baseSeconds, activeSeconds),
            target.getAttribute("data-live-continuity-key") || "",
            { allowDecrease: false }
        );
    };

    App.liveTargetCompatibleWithRuntime = function (target, runtime) {
        if (!target || !runtime) return false;
        var currentSpan = target.getAttribute("data-current-activity-display-span-id") || "";
        if (currentSpan) return currentSpan === runtime.currentActivityDisplaySpanId;
        var resourceHash = target.getAttribute("data-current-resource-identity-hash") || "";
        if (resourceHash) return resourceHash === runtime.currentResourceIdentityHash;
        var span = target.getAttribute("data-display-span-id") || "";
        if (span) return span === runtime.displaySpanId;
        var stable = target.getAttribute("data-stable-live-key-hash") || "";
        var node = target.parentElement;
        while (!stable && node) {
            stable = node.getAttribute && node.getAttribute("data-stable-live-key-hash");
            node = node.parentElement;
        }
        return !!stable && stable === runtime.stableLiveKeyHash;
    };

    App._timelineEditingActive = function () {
        return App.editSaving || !!(
            App.editingSession
            && typeof App.isEditDirty === "function"
            && App.isEditDirty()
        );
    };
})();
