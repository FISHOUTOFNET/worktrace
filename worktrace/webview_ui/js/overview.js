// WorkTrace WebView frontend — overview module.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};


    function showOverview(overview) {
        if (!overview) return;
        App.registerLiveClock(overview);
        App.lastOverviewSnapshot = overview;
        document.getElementById("kpi-date").textContent = overview.date || "--";
        document.getElementById("kpi-total").textContent = overview.total_duration || "00:00:00";
        document.getElementById("kpi-classified").textContent = overview.classified_duration || "00:00:00";
        document.getElementById("kpi-uncategorized").textContent = overview.uncategorized_duration || "00:00:00";
        document.getElementById("kpi-projects").textContent = String(overview.project_count || 0);
        var current = overview.current_activity || {};
        var currentEl = document.getElementById("current-activity");
        if (current.active) {
            currentEl.textContent = "当前活动：" + current.display;
        } else {
            currentEl.textContent = "当前活动：无";
        }
        App._monotonicRenderState["overview-total"] = {
            lastSeconds: parseInt(overview.today_total_seconds, 10) || 0
        };
        App._monotonicRenderState["overview-classified"] = {
            lastSeconds: parseInt(overview.classified_seconds, 10) || 0
        };
        App._monotonicRenderState["overview-uncategorized"] = {
            lastSeconds: parseInt(overview.uncategorized_seconds, 10) || 0
        };
    }
    App.showOverview = showOverview;

    function showRecent(recentResult) {
        // Register the unified live clock (shares the same sample as the Overview bundle).
        App.registerLiveClock(recentResult);
        // Structural cache only — used for re-render on page switch, never a live-seconds source.
        App.lastRecentData = recentResult;
        var listEl = document.getElementById("recent-list");
        if (!recentResult || !recentResult.activities || recentResult.activities.length === 0) {
            listEl.innerHTML = '<div class="recent-empty">暂无活动</div>';
            return;
        }
        var html = "";
        for (var i = 0; i < recentResult.activities.length; i++) {
            var item = recentResult.activities[i];
            var inProgress = item.is_in_progress === true || (!item.end_time && item.is_in_progress !== false);
            var timeRange = App.formatTimeRange(item.start_time, item.end_time, inProgress);
            var durSec = parseInt(item.duration_seconds, 10);
            var durText = (!isNaN(durSec) && durSec >= 0)
                ? App.formatDuration(durSec)
                : (item.duration || "00:00:00");
            var cls = "recent-item";
            if (inProgress) cls += " in-progress";
            if (item.is_live_projected === true) cls += " live-projected";
            if (item.is_virtual === true) cls += " virtual-live";
            // Unified live-span DOM attributes: ticker walks [data-display-span-id]
            // and reads each row's OWN sample base from [data-live-base-seconds]
            // so a session/recent row whose sample duration is larger than the
            // live activity's own duration is NOT overwritten by the live span.
            var spanId = item.display_span_id || "";
            var liveBaseSec = (spanId && !isNaN(durSec)) ? durSec : 0;
            var continuityKey = spanId ? App.liveContinuityKey(item, "recent") : "";
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
            // Seed monotonic state by the SAME continuity key the ticker will
            // read from data-live-continuity-key so render and ticker share
            // one monotonic guard.
            if (continuityKey) {
                App.resetMonotonicRenderState(continuityKey);
                App._monotonicRenderState[continuityKey] = { lastSeconds: isNaN(durSec) ? 0 : durSec };
            }
        }
        listEl.innerHTML = html;
    }
    App.showRecent = showRecent;

})();
