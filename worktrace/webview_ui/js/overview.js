// WorkTrace WebView frontend — overview module.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};


    function showOverview(overview) {
        if (!overview) return;
        App.commitPageActiveSpanClock(overview, "overview");
        App.registerCurrentActivityClock(overview, { source: "page_model", page: "overview" });
        App.lastOverviewSnapshot = overview;
        var nowMs = Date.now();
        var clock = App.getActiveLiveClock();
        var activeElapsedAtSample = App.activeElapsedAtRenderFromPayload(overview, "overview", nowMs);
        var activeElapsedAtRender = App.activeElapsedNow(clock, nowMs);
        document.getElementById("kpi-date").textContent = overview.date || "--";
        document.getElementById("kpi-projects").textContent = String(overview.project_count || 0);
        var current = overview.current_activity || {};
        var currentClock = overview.current_activity_clock || (
            overview.activity_display_model ? overview.activity_display_model.current_activity_clock : null
        );
        var currentIsUncategorized = true;
        if (current.is_classified === true) {
            currentIsUncategorized = false;
        } else if (current.is_uncategorized === true) {
            currentIsUncategorized = true;
        } else {
            currentIsUncategorized = null;
        }
        var totalEl = document.getElementById("kpi-total");
        var totalProjection = clock
            ? App.anchoredSecondsAtRender(
                App.kpiBaseSeconds(overview, "today_total_seconds"),
                activeElapsedAtSample,
                clock,
                nowMs
            )
            : { seconds: App.kpiBaseSeconds(overview, "today_total_seconds") };
        if (clock) {
            App.setLiveProjectionAnchor(totalEl, totalProjection.seconds, activeElapsedAtRender, "overview-total");
        } else {
            App.clearLiveProjectionAnchor(totalEl);
        }
        App.renderDurationProjected(
            totalEl,
            totalProjection.seconds,
            "overview-total",
            { allowDecrease: false }
        );
        var classifiedSeconds = App.kpiBaseSeconds(overview, "classified_seconds");
        if (currentIsUncategorized === false && clock) {
            var classifiedProjection = App.anchoredSecondsAtRender(
                classifiedSeconds,
                activeElapsedAtSample,
                clock,
                nowMs
            );
            classifiedSeconds = classifiedProjection.seconds;
            App.setLiveProjectionAnchor(
                document.getElementById("kpi-classified"),
                classifiedProjection.seconds,
                activeElapsedAtRender,
                "overview-classified"
            );
        } else {
            App.clearLiveProjectionAnchor(document.getElementById("kpi-classified"));
        }
        App.renderDurationProjected(
            document.getElementById("kpi-classified"),
            classifiedSeconds,
            "overview-classified",
            { allowDecrease: false }
        );
        var uncategorizedSeconds = App.kpiBaseSeconds(overview, "uncategorized_seconds");
        if (currentIsUncategorized === true && clock) {
            var uncategorizedProjection = App.anchoredSecondsAtRender(
                uncategorizedSeconds,
                activeElapsedAtSample,
                clock,
                nowMs
            );
            uncategorizedSeconds = uncategorizedProjection.seconds;
            App.setLiveProjectionAnchor(
                document.getElementById("kpi-uncategorized"),
                uncategorizedProjection.seconds,
                activeElapsedAtRender,
                "overview-uncategorized"
            );
        } else {
            App.clearLiveProjectionAnchor(document.getElementById("kpi-uncategorized"));
        }
        App.renderDurationProjected(
            document.getElementById("kpi-uncategorized"),
            uncategorizedSeconds,
            "overview-uncategorized",
            { allowDecrease: false }
        );
        App.renderCurrentActivityElement(
            document.getElementById("current-activity"),
            current,
            App.getActiveCurrentActivityClock() || currentClock,
            "overview"
        );
    }
    App.showOverview = showOverview;

    function showRecent(recentResult) {
        // Defensive page-model commit of the same sample keeps the Overview
        // active span page-scoped while rows store only projection offsets.
        App.commitPageActiveSpanClock(recentResult, "overview");
        App.registerCurrentActivityClock(recentResult, { source: "page_model", page: "overview" });
        // Structural cache only — never a live-seconds source.
        App.lastRecentData = recentResult;
        var listEl = document.getElementById("recent-list");
        if (!recentResult || !recentResult.activities || recentResult.activities.length === 0) {
            listEl.innerHTML = '<div class="recent-empty">暂无活动</div>';
            return;
        }
        var html = "";
        var nowMs = Date.now();
        var activeClock = App.getActiveLiveClock("overview");
        var activeElapsedAtSample = App.activeElapsedAtRenderFromPayload(recentResult, "overview", nowMs);
        var activeElapsedAtRender = App.activeElapsedNow(activeClock, nowMs);
        for (var i = 0; i < recentResult.activities.length; i++) {
            var item = recentResult.activities[i];
            var inProgress = item.is_in_progress === true || (!item.end_time && item.is_in_progress !== false);
            if ((item.is_in_progress === true || item.is_live_projected === true)
                && !item.display_span_id
                && typeof App.recordLiveClockContractViolation === "function") {
                App.recordLiveClockContractViolation("", "overview", "recent_live_row_missing_span_id");
            }
            var timeRange = App.formatTimeRange(item.start_time, item.end_time, inProgress);
            var durSec = parseInt(item.duration_seconds, 10);
            var cls = "recent-item";
            if (inProgress) cls += " in-progress";
            if (item.is_live_projected === true) cls += " live-projected";
            if (item.is_virtual === true) cls += " virtual-live";
            // Active-span anchored DOM attributes: ticker reads each row's
            // own base + active elapsed offset, not a row-owned clock.
            var spanId = item.display_span_id || "";
            var continuityKey = spanId ? App.liveContinuityKey(item, "recent") : "";
            var initialSec = (!isNaN(durSec) && durSec >= 0) ? durSec : 0;
            if (spanId && activeClock) {
                initialSec = App.projectFromActiveElapsed(
                    initialSec,
                    activeElapsedAtSample,
                    activeClock,
                    nowMs
                );
            }
            var prevEntry = continuityKey ? App._monotonicRenderState[continuityKey] : null;
            if (prevEntry && typeof prevEntry.lastSeconds === "number" && initialSec < prevEntry.lastSeconds) {
                initialSec = prevEntry.lastSeconds;
            }
            var durText = (!isNaN(durSec) && durSec >= 0)
                ? App.formatDuration(initialSec)
                : (item.duration || "00:00:00");
            html += '<div class="' + cls + '" data-recent-index="' + i + '"'
                + (spanId ? ' data-display-span-id="' + App.escapeHtml(spanId) + '"' : '')
                + (spanId ? ' data-live-base-seconds="' + initialSec + '"' : '')
                + (spanId ? ' data-active-elapsed-at-render="' + activeElapsedAtRender + '"' : '')
                + (continuityKey ? ' data-live-continuity-key="' + App.escapeHtml(continuityKey) + '"' : '')
                + ' data-duration-seconds="' + (isNaN(durSec) ? 0 : durSec) + '"'
                + '>'
                + '<div>'
                + '<div class="recent-item-project">' + App.escapeHtml(App.formatProjectLabel(item.project_name, item.project_description)) + '</div>'
                + '<div class="recent-item-time">' + App.escapeHtml(timeRange) + '</div>'
                + '<div class="recent-item-status">' + App.escapeHtml(item.status || "") + '</div>'
                + '</div>'
                + '<div class="recent-item-duration">' + App.escapeHtml(durText) + '</div>'
                + '</div>';
            // Seed monotonic state by the SAME continuity key the ticker reads.
            if (continuityKey) {
                App._monotonicRenderState[continuityKey] = { lastSeconds: initialSec };
            }
        }
        listEl.innerHTML = html;
    }
    App.showRecent = showRecent;

})();
