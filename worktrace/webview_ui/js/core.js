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
        var preserved = [];
        if (typeof element.className === "string" && element.className) {
            preserved = element.className.split(/\s+/).filter(function (className) {
                return className && App.STATUS_TYPE_CLASS_VALUES.indexOf(className) === -1;
            });
        }
        if (preserved.indexOf("edit-status") === -1) preserved.unshift("edit-status");
        preserved.push(statusClassFor(type));
        element.className = preserved.join(" ");
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

    function setDetailStatus(message) {
        var header = document.getElementById("timeline-details-header");
        if (!header) return;
        header.textContent = message || "请选择一条时间记录";
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

    function handleResult(result, onError) {
        if (result && result.ok === false) {
            onError(result.message || "操作失败", result.error || "operation_failed");
            return null;
        }
        return result;
    }
    App.handleResult = handleResult;

    function showStatus(statusResult) {
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
    }
    App.showStatus = showStatus;

    function safeText(value, fallback) {
        if (value === null || value === undefined || value === "") return fallback || "";
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
        var startText = (start || "").slice(11, 16);
        var endText = (end || "").slice(11, 16);
        return inProgress || !endText ? startText + "-进行中" : startText + "-" + endText;
    }
    App.formatTimeRange = formatTimeRange;

    function formatStartTimeOnly(startTime) {
        return (startTime || "").slice(11, 16);
    }
    App.formatStartTimeOnly = formatStartTimeOnly;

    function shiftDate(dateString, days) {
        var base;
        if (!dateString || dateString === "--") {
            base = new Date();
        } else {
            var parts = dateString.split("-");
            base = new Date(
                parseInt(parts[0], 10),
                parseInt(parts[1], 10) - 1,
                parseInt(parts[2], 10)
            );
        }
        base.setDate(base.getDate() + days);
        var year = base.getFullYear();
        var month = String(base.getMonth() + 1).padStart(2, "0");
        var day = String(base.getDate()).padStart(2, "0");
        return year + "-" + month + "-" + day;
    }
    App.shiftDate = shiftDate;

    function localTodayStr() {
        var date = new Date();
        var year = date.getFullYear();
        var month = String(date.getMonth() + 1).padStart(2, "0");
        var day = String(date.getDate()).padStart(2, "0");
        return year + "-" + month + "-" + day;
    }
    App.localTodayStr = localTodayStr;

    function formatDuration(seconds) {
        var value = Math.max(0, parseInt(seconds, 10) || 0);
        var hours = Math.floor(value / 3600);
        var remainder = value % 3600;
        var minutes = Math.floor(remainder / 60);
        var remainingSeconds = remainder % 60;
        function pad(number) { return number < 10 ? "0" + number : String(number); }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(remainingSeconds);
    }
    App.formatDuration = formatDuration;

    function readDurationSecondsFromText(element) {
        if (!element) return 0;
        var attribute = element.getAttribute("data-duration-seconds");
        if (attribute !== null && attribute !== "") {
            var parsed = parseInt(attribute, 10);
            if (!isNaN(parsed) && parsed >= 0) return parsed;
        }
        var match = /^(\d+):(\d{2}):(\d{2})$/.exec((element.textContent || "").trim());
        if (!match) return 0;
        return parseInt(match[1], 10) * 3600
            + parseInt(match[2], 10) * 60
            + parseInt(match[3], 10);
    }
    App.readDurationSecondsFromText = readDurationSecondsFromText;

    function renderDurationProjected(element, seconds, continuityKey, options) {
        if (!element) return;
        var allowDecrease = options && options.allowDecrease === true;
        var key = String(continuityKey || "");
        var next = Math.max(0, parseInt(seconds, 10) || 0);
        var entry = key ? App._monotonicRenderState[key] : null;
        if (!allowDecrease && entry && typeof entry.lastSeconds === "number" && next < entry.lastSeconds) {
            next = entry.lastSeconds;
        }
        element.textContent = formatDuration(next);
        element.setAttribute("data-duration-seconds", String(next));
        if (key) App._monotonicRenderState[key] = { lastSeconds: next };
    }
    App.renderDurationProjected = renderDurationProjected;

    function renderDurationMonotonic(element, seconds, continuityKey, allowDecrease) {
        renderDurationProjected(element, seconds, continuityKey, {
            allowDecrease: allowDecrease === true
        });
    }
    App.renderDurationMonotonic = renderDurationMonotonic;

    function resetMonotonicRenderState(continuityKey) {
        if (continuityKey) delete App._monotonicRenderState[continuityKey];
        else App._monotonicRenderState = {};
    }
    App.resetMonotonicRenderState = resetMonotonicRenderState;

    function formatProjectLabel(name, description) {
        var projectName = String(name || "").trim() || "未归类";
        var projectDescription = String(description || "").trim();
        return projectDescription
            ? projectName + "（" + projectDescription + "）"
            : projectName;
    }
    App.formatProjectLabel = formatProjectLabel;

    function displayStatusText(item) {
        item = item || {};
        return item.display_status || item.status_label || item.status_summary || "";
    }
    App.displayStatusText = displayStatusText;

    function nonNegativeInt(value, fallback) {
        var parsed = parseInt(value, 10);
        return isNaN(parsed) || parsed < 0 ? (fallback || 0) : parsed;
    }

    function normalizeLiveClock(clock) {
        if (!clock || typeof clock !== "object") return null;
        var durationAtSample = nonNegativeInt(
            clock.duration_seconds_at_sample,
            nonNegativeInt(clock.duration_seconds, 0)
        );
        var projectDurationLive = clock.project_duration_live === true
            || clock.is_project_duration_live === true;
        return Object.assign({}, clock, {
            display_span_id: String(clock.display_span_id || ""),
            stable_live_key_hash: String(clock.stable_live_key_hash || ""),
            live_state: String(clock.live_state || "none"),
            duration_seconds_at_sample: durationAtSample,
            carry_seconds: nonNegativeInt(clock.carry_seconds, durationAtSample),
            live_started_at_epoch_ms: nonNegativeInt(clock.live_started_at_epoch_ms, 0),
            is_live: clock.is_live === true,
            is_project_duration_live: projectDurationLive,
            project_duration_live: projectDurationLive,
            current_duration_live: clock.current_duration_live === true
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

    function projectFromDisplayBase(displayBaseSeconds, activeElapsedNowValue) {
        return nonNegativeInt(displayBaseSeconds, 0)
            + nonNegativeInt(activeElapsedNowValue, 0);
    }
    App.projectFromDisplayBase = projectFromDisplayBase;

    function runtimeReportDateForPage(page, fallbackDate) {
        if (page === "timeline") {
            return fallbackDate || App.timelineDate || localTodayStr();
        }
        return fallbackDate || localTodayStr();
    }
    App.runtimeReportDateForPage = runtimeReportDateForPage;

    function liveContinuityKey(item, prefix) {
        if (!item) return prefix;
        if (item.stable_live_key_hash) return prefix + ":live:" + item.stable_live_key_hash;
        if (item.display_span_id) return prefix + ":span:" + item.display_span_id;
        if (item.projection_instance_key) return prefix + ":" + item.projection_instance_key;
        if (item.activity_id) return prefix + ":" + item.activity_id;
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
        } else if (clock && clock.display_span_id) {
            identity = clock.display_span_id;
        } else if (current && current.start_time) {
            identity = String(current.resource_name || current.app_name || "current")
                + ":" + String(current.start_time || "");
        }
        return prefix + ":current:" + (identity || "none");
    }
    App.currentActivityContinuityKey = currentActivityContinuityKey;

    function renderCurrentActivityElement(element, current, prefix) {
        if (!element) return;
        current = current || {};
        if (!current.active) {
            element.textContent = "当前活动：无";
            return;
        }
        var clock = App.getActiveLiveClock ? App.getActiveLiveClock() : null;
        var displaySpanId = String((clock && clock.display_span_id) || "");
        var currentActivityDisplaySpanId = String(current.current_activity_display_span_id || "");
        var currentResourceIdentityHash = String(current.current_resource_identity_hash || "");
        var stableLiveKeyHash = String(
            current.stable_live_key_hash || (clock && clock.stable_live_key_hash) || ""
        );
        var canTickCurrent = !!(
            clock
            && clock.current_duration_live === true
            && displaySpanId
            && currentActivityDisplaySpanId
            && currentResourceIdentityHash
        );
        var seconds = canTickCurrent && App.computeActiveElapsedNow
            ? App.computeActiveElapsedNow(clock, Date.now())
            : (parseInt(current.elapsed_seconds, 10) || 0);
        var continuity = currentActivityContinuityKey(current, clock, prefix);
        var previousContinuity = element.getAttribute("data-current-continuity-key") || "";
        if (previousContinuity && previousContinuity !== continuity) {
            resetMonotonicRenderState(previousContinuity);
        }
        element.setAttribute("data-current-continuity-key", continuity);
        var entry = App._monotonicRenderState[continuity];
        if (entry && typeof entry.lastSeconds === "number" && seconds < entry.lastSeconds) {
            seconds = entry.lastSeconds;
        }
        var parts = String(current.display || "").split("｜");
        if (parts.length >= 3) {
            var html = "当前活动："
                + escapeHtml(parts[0] || "")
                + "｜"
                + escapeHtml(parts[1] || "")
                + "｜"
                + '<span class="current-activity-duration"'
                + (canTickCurrent ? ' data-live-duration-target="1"' : '')
                + (canTickCurrent ? ' data-duration-semantic="current-live"' : '')
                + (canTickCurrent ? ' data-display-base-seconds="0"' : '')
                + (canTickCurrent ? ' data-live-base-seconds="0"' : '')
                + (canTickCurrent ? ' data-live-role="' + escapeHtml(prefix || "current") + '-current"' : '')
                + (canTickCurrent ? ' data-live-continuity-key="' + escapeHtml(continuity) + '"' : '')
                + (canTickCurrent ? ' data-current-activity-display-span-id="' + escapeHtml(currentActivityDisplaySpanId) + '"' : '')
                + (canTickCurrent ? ' data-current-resource-identity-hash="' + escapeHtml(currentResourceIdentityHash) + '"' : '')
                + (canTickCurrent ? ' data-display-span-id="' + escapeHtml(displaySpanId) + '"' : '')
                + (canTickCurrent && stableLiveKeyHash ? ' data-stable-live-key-hash="' + escapeHtml(stableLiveKeyHash) + '"' : '')
                + ' data-duration-seconds="' + String(seconds) + '"'
                + '>' + escapeHtml(formatDuration(seconds)) + '</span>';
            for (var index = 3; index < parts.length; index++) {
                html += "｜" + escapeHtml(parts[index] || "");
            }
            element.innerHTML = html;
            App._monotonicRenderState[continuity] = { lastSeconds: seconds };
        } else {
            element.textContent = "当前活动：" + (current.display || displayStatusText(current));
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

    function setLiveProjectionAnchor(element, displayBaseSeconds, continuityKey, role) {
        if (!element) return;
        var base = String(nonNegativeInt(displayBaseSeconds, 0));
        element.setAttribute("data-live-duration-target", "1");
        element.setAttribute("data-duration-semantic", "aggregate-live");
        element.setAttribute("data-display-base-seconds", base);
        element.setAttribute("data-live-base-seconds", base);
        if (role) element.setAttribute("data-live-role", String(role));
        if (continuityKey) element.setAttribute("data-live-continuity-key", String(continuityKey));
        var runtime = App.liveRuntime || {};
        if (runtime.displaySpanId) {
            element.setAttribute("data-display-span-id", String(runtime.displaySpanId));
        }
        if (runtime.stableLiveKeyHash) {
            element.setAttribute("data-stable-live-key-hash", String(runtime.stableLiveKeyHash));
        }
    }
    App.setLiveProjectionAnchor = setLiveProjectionAnchor;

    function clearLiveProjectionAnchor(element) {
        if (!element) return;
        [
            "data-live-duration-target",
            "data-duration-semantic",
            "data-display-base-seconds",
            "data-live-base-seconds",
            "data-live-role",
            "data-live-continuity-key",
            "data-display-span-id",
            "data-stable-live-key-hash"
        ].forEach(function (name) { element.removeAttribute(name); });
    }
    App.clearLiveProjectionAnchor = clearLiveProjectionAnchor;

    function renderLiveDurationTarget(target, displayBaseSeconds, activeElapsedNowValue) {
        if (!target) return;
        var continuity = target.getAttribute("data-live-continuity-key") || "";
        renderDurationProjected(
            target,
            projectFromDisplayBase(displayBaseSeconds, activeElapsedNowValue),
            continuity,
            { allowDecrease: false }
        );
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
        var currentSpan = target.getAttribute("data-current-activity-display-span-id") || "";
        if (currentSpan) {
            return !!runtime.currentActivityDisplaySpanId
                && currentSpan === runtime.currentActivityDisplaySpanId;
        }
        var resourceHash = target.getAttribute("data-current-resource-identity-hash") || "";
        if (resourceHash) {
            return !!runtime.currentResourceIdentityHash
                && resourceHash === runtime.currentResourceIdentityHash;
        }
        var span = target.getAttribute("data-display-span-id") || "";
        if (span) return !!runtime.displaySpanId && span === runtime.displaySpanId;
        var stableHash = nearestStableHash(target);
        if (stableHash) {
            return !!runtime.stableLiveKeyHash && stableHash === runtime.stableLiveKeyHash;
        }
        return false;
    }
    App.liveTargetCompatibleWithRuntime = liveTargetCompatibleWithRuntime;

    function timelineEditingActive() {
        if (App.editSaving) return true;
        return !!(
            App.editingSession
            && typeof App.isEditDirty === "function"
            && App.isEditDirty()
        );
    }
    App._timelineEditingActive = timelineEditingActive;
})();
