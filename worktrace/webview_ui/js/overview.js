// WorkTrace WebView frontend — overview module.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};


    function showOverview(overview) {
        if (!overview) return;
        App.registerLiveClock(overview, { source: "page_model", page: "overview" });
        App.registerCurrentActivityClock(overview, { source: "page_model", page: "overview" });
        App.lastOverviewSnapshot = overview;
        var nowMs = Date.now();
        var clock = App.getActiveLiveClock();
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
        App.renderDurationProjected(
            document.getElementById("kpi-total"),
            App.projectLiveBaseSeconds(App.kpiBaseSeconds(overview, "today_total_seconds"), clock, nowMs),
            "overview-total",
            { allowDecrease: false }
        );
        var classifiedSeconds = App.kpiBaseSeconds(overview, "classified_seconds");
        if (currentIsUncategorized === false) {
            classifiedSeconds = App.projectLiveBaseSeconds(classifiedSeconds, clock, nowMs);
        }
        App.renderDurationProjected(
            document.getElementById("kpi-classified"),
            classifiedSeconds,
            "overview-classified",
            { allowDecrease: false }
        );
        var uncategorizedSeconds = App.kpiBaseSeconds(overview, "uncategorized_seconds");
        if (currentIsUncategorized === true) {
            uncategorizedSeconds = App.projectLiveBaseSeconds(uncategorizedSeconds, clock, nowMs);
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
        // ``source: "page_model"``: defensive re-registration of the same sample.
        // ``page: "overview"`` keeps the clock page-scoped (Section 五 fix).
        App.registerLiveClock(recentResult, { source: "page_model", page: "overview" });
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
        for (var i = 0; i < recentResult.activities.length; i++) {
            var item = recentResult.activities[i];
            var inProgress = item.is_in_progress === true || (!item.end_time && item.is_in_progress !== false);
            var timeRange = App.formatTimeRange(item.start_time, item.end_time, inProgress);
            var durSec = parseInt(item.duration_seconds, 10);
            var cls = "recent-item";
            if (inProgress) cls += " in-progress";
            if (item.is_live_projected === true) cls += " live-projected";
            if (item.is_virtual === true) cls += " virtual-live";
            // Unified live-span DOM attributes: ticker reads each row's
            // OWN sample base from [data-live-base-seconds].
            var spanId = item.display_span_id || "";
            var liveBaseSec = (spanId && !isNaN(durSec)) ? durSec : 0;
            var continuityKey = spanId ? App.liveContinuityKey(item, "recent") : "";
            var rowClock = spanId ? App.liveClockBySpanId[spanId] : null;
            var initialSec = (!isNaN(durSec) && durSec >= 0) ? durSec : 0;
            if (spanId && rowClock) {
                initialSec = App.projectLiveBaseSeconds(initialSec, rowClock, nowMs);
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
                + (spanId ? ' data-live-base-seconds="' + liveBaseSec + '"' : '')
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
