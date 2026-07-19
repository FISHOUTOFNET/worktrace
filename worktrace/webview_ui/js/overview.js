// WorkTrace WebView frontend — overview module.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function renderKpi(element, durableSeconds, target, continuityKey) {
        var clock = target && App.validateLiveClock(target.live_clock);
        var live = !!(target && target.enabled === true && clock && clock.is_live === true
            && clock.duration_semantic === "aggregate_live");
        var seconds = live
            ? App.computeClockDurationNow(clock, Date.now())
            : Math.max(0, parseInt(durableSeconds, 10) || 0);
        if (live) App.setLiveClockTarget(element, clock, continuityKey, continuityKey);
        else App.clearLiveClockTarget(element);
        App.renderDurationProjected(element, seconds || 0, continuityKey);
    }

    function showOverview(overview) {
        if (!overview) return;
        App.lastOverviewSnapshot = overview;
        document.getElementById("kpi-date").textContent = overview.date || "--";
        document.getElementById("kpi-projects").textContent = String(overview.project_count || 0);
        var current = overview.current_activity || {};
        renderKpi(
            document.getElementById("kpi-total"),
            overview.today_total_seconds,
            kpiLiveTarget(overview, "today_total_seconds"),
            "overview-total"
        );
        renderKpi(
            document.getElementById("kpi-classified"),
            overview.classified_seconds,
            kpiLiveTarget(overview, "classified_seconds"),
            "overview-classified"
        );
        renderKpi(
            document.getElementById("kpi-uncategorized"),
            overview.uncategorized_seconds,
            kpiLiveTarget(overview, "uncategorized_seconds"),
            "overview-uncategorized"
        );
        App.renderCurrentActivityElement(
            document.getElementById("current-activity"),
            current,
            "overview"
        );
    }
    App.showOverview = showOverview;

    function kpiLiveTarget(overview, field) {
        overview = overview || {};
        var targets = overview.kpi_live_targets;
        if (!targets || typeof targets !== "object") return null;
        var target = targets[field];
        return target && typeof target === "object" ? target : null;
    }

    function showRecent(recentResult) {
        App.lastRecentData = recentResult;
        var listEl = document.getElementById("recent-list");
        if (!recentResult || !recentResult.activities || recentResult.activities.length === 0) {
            listEl.innerHTML = '<div class="recent-empty">暂无活动</div>';
            return;
        }
        var html = "";
        for (var i = 0; i < recentResult.activities.length; i++) {
            var item = recentResult.activities[i];
            var isStatusOnly = item.row_kind === "status_only";
            var inProgress = item.is_in_progress === true || (!item.end_time && item.is_in_progress !== false);
            var clock = App.validateLiveClock(item.live_clock);
            var canTick = !!(!isStatusOnly
                && clock
                && clock.is_live === true
                && clock.duration_semantic === "aggregate_live");
            if (item.live_clock && !clock) {
                App.recordLiveClockContractViolation("", "overview", "recent_invalid_live_clock", 2);
            }
            var timeRange = App.formatTimeRange(item.start_time, item.end_time, inProgress);
            var durableSeconds = Math.max(0, parseInt(item.duration_seconds, 10) || 0);
            var initialSeconds = canTick
                ? App.computeClockDurationNow(clock, Date.now())
                : durableSeconds;
            var continuityKey = canTick ? App.liveContinuityKey(item, "recent") : "";
            var cls = "recent-item";
            if (inProgress) cls += " in-progress";
            if (canTick) cls += " live-projected";
            var durationText = App.formatDuration(initialSeconds || 0);
            var statusText = App.displayStatusText(item);
            var titleText = isStatusOnly
                ? (item.display_status || item.status_label || statusText || "")
                : App.formatProjectLabel(item.project_name, item.project_description);
            var clockAttributes = canTick
                ? App.liveClockDataAttributes(clock, continuityKey, "recent")
                : "";
            html += '<div class="' + cls + '" data-recent-index="' + i + '"'
                + ' data-duration-seconds="' + durableSeconds + '">'
                + '<div>'
                + '<div class="recent-item-project">' + App.escapeHtml(titleText) + '</div>'
                + '<div class="recent-item-time">' + App.escapeHtml(timeRange) + '</div>'
                + '<div class="recent-item-status">' + App.escapeHtml(statusText) + '</div>'
                + '</div>'
                + '<div class="recent-item-duration"' + clockAttributes
                + ' data-duration-seconds="' + String(initialSeconds || 0) + '">'
                + App.escapeHtml(durationText) + '</div>'
                + '</div>';
        }
        listEl.innerHTML = html;
    }
    App.showRecent = showRecent;

})();
