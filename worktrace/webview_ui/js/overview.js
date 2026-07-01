// WorkTrace WebView frontend — overview module (Phase R2 split).
// Overview page rendering: KPIs, current activity, recent activities list.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Overview rendering ---------------------------------------------

    function showOverview(overview) {
        if (!overview) return;
        // Phase 6G / 6H-followup: store the overview snapshot so the
        // 1-second heartbeat ticker can increment the displayed durations
        // without a bridge round-trip. The ticker only updates DOM text.
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
        // Phase 6H-followup: seed the monotonic render state for the KPI
        // elements so the ticker's first delta after a backend refresh does
        // not appear to roll back against a stale prior ticker projection.
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
        // Phase 6H-followup: cache the recent snapshot so the 1-second
        // heartbeat ticker can increment the live-projected item's duration
        // without a bridge round-trip. The ticker only updates DOM text.
        App.lastRecentSnapshot = recentResult;
        var listEl = document.getElementById("recent-list");
        if (!recentResult || !recentResult.activities || recentResult.activities.length === 0) {
            listEl.innerHTML = '<div class="recent-empty">暂无活动</div>';
            return;
        }
        var html = "";
        for (var i = 0; i < recentResult.activities.length; i++) {
            var item = recentResult.activities[i];
            // Phase 6H-followup: prefer ``is_in_progress`` over the
            // ``!end_time`` heuristic so the bridge's explicit contract
            // drives the in-progress rendering.
            var inProgress = item.is_in_progress === true || (!item.end_time && item.is_in_progress !== false);
            var timeRange = App.formatTimeRange(item.start_time, item.end_time, inProgress);
            // Phase 6H-followup: prefer ``duration_seconds`` (raw int from
            // the backend) over the pre-formatted ``duration`` string so
            // the ticker / monotonic helper can recompute from a stable
            // baseline. The ``duration`` string is kept as a fallback.
            var durSec = parseInt(item.duration_seconds, 10);
            var durText = (!isNaN(durSec) && durSec >= 0)
                ? App.formatDuration(durSec)
                : (item.duration || "00:00:00");
            var cls = "recent-item";
            if (inProgress) cls += " in-progress";
            if (item.is_live_projected === true) cls += " live-projected";
            if (item.is_virtual === true) cls += " virtual-live";
            html += '<div class="' + cls + '" data-recent-index="' + i + '"'
                + ' data-duration-seconds="' + (isNaN(durSec) ? 0 : durSec) + '"'
                + '>'
                + '<div>'
                + '<div class="recent-item-project">' + App.escapeHtml(item.project_name) + '</div>'
                + '<div class="recent-item-time">' + App.escapeHtml(timeRange) + '</div>'
                + '<div class="recent-item-status">' + App.escapeHtml(item.status || "") + '</div>'
                + '</div>'
                + '<div class="recent-item-duration">' + App.escapeHtml(durText) + '</div>'
                + '</div>';
            // Phase 6H-followup: reset the monotonic render state for this
            // recent row so the backend baseline can replace any prior
            // ticker-projected value without a false "rollback" guard.
            // The continuity key MUST use App.liveContinuityKey() so the
            // ticker (which also uses liveContinuityKey) can locate the
            // seeded state. Using the array index ("recent-" + i) would
            // break the virtual → persisted_open transition because the
            // ticker key is based on stable_live_key_hash, not the index.
            var recentKey = App.liveContinuityKey(item, "recent");
            App.resetMonotonicRenderState(recentKey);
            // Seed the monotonic state with the backend baseline so the
            // ticker's first projection does not appear to roll back.
            App._monotonicRenderState[recentKey] = { lastSeconds: isNaN(durSec) ? 0 : durSec };
        }
        listEl.innerHTML = html;
    }
    App.showRecent = showRecent;

})();
