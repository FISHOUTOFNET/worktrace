// WorkTrace WebView frontend.
// Phase 2.1: Overview and Timeline (read-only) pages are production pages.
// Only communicates with Python through pywebview API bridge.
// Does not persist sensitive data in browser storage APIs.
// Does not access any external network resources.
// Phase 2.1 hardening: request token guards against stale responses,
// selected session is preserved across auto-refresh, in-progress sessions
// are clearly marked, long text is truncated with safe tooltips, and
// bridge errors keep the prior data visible instead of clearing it.

(function () {
    "use strict";

    var REFRESH_INTERVAL_MS = 8000;
    var refreshTimer = null;

    // --- Timeline state -------------------------------------------------
    var currentPage = "overview";
    var timelineDate = null;       // null = today (backend decides)
    var timelineLoaded = false;    // whether timeline has been loaded at least once
    var timelineLoading = false;   // whether a timeline load is in progress
    var selectedSessionId = null;  // currently selected session for detail view

    // Request tokens prevent stale bridge responses from overwriting newer
    // data when the user rapidly switches dates. Each load increments the
    // token; only the response whose token equals the current value is
    // applied to the DOM.
    var timelineRequestToken = 0;
    var detailsRequestToken = 0;

    // --- Bridge helper --------------------------------------------------

    function callBridge(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        if (typeof window.pywebview === "undefined" || !window.pywebview.api) {
            return Promise.reject(new Error("bridge unavailable"));
        }
        return window.pywebview.api[method].apply(window.pywebview.api, args);
    }

    // --- Overview error banner ------------------------------------------

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

    function clearError() {
        showError("");
    }

    // --- Timeline error / loading ---------------------------------------

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

    function clearTimelineError() {
        showTimelineError("");
    }

    function setTimelineLoading(loading) {
        timelineLoading = loading;
        var el = document.getElementById("timeline-loading");
        if (el) el.hidden = !loading;
    }

    // --- Generic result handler -----------------------------------------

    function handleResult(result, onError) {
        if (result && result.ok === false) {
            onError(result.error || "操作失败");
            return null;
        }
        return result;
    }

    // --- Overview rendering ---------------------------------------------

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

    function showOverview(overview) {
        if (!overview) return;
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
    }

    function showRecent(recentResult) {
        var listEl = document.getElementById("recent-list");
        if (!recentResult || !recentResult.activities || recentResult.activities.length === 0) {
            listEl.innerHTML = '<div class="recent-empty">暂无活动</div>';
            return;
        }
        var html = "";
        for (var i = 0; i < recentResult.activities.length; i++) {
            var item = recentResult.activities[i];
            var inProgress = !item.end_time;
            var timeRange = formatTimeRange(item.start_time, item.end_time, inProgress);
            html += '<div class="recent-item">'
                + '<div>'
                + '<div class="recent-item-project">' + escapeHtml(item.project_name) + '</div>'
                + '<div class="recent-item-time">' + escapeHtml(timeRange) + '</div>'
                + '<div class="recent-item-status">' + escapeHtml(item.status || "") + '</div>'
                + '</div>'
                + '<div class="recent-item-duration">' + escapeHtml(item.duration) + '</div>'
                + '</div>';
        }
        listEl.innerHTML = html;
    }

    // --- Timeline rendering ---------------------------------------------

    // Last successfully rendered Timeline payload. When a refresh fails, the
    // page keeps showing this data instead of clearing, so the user is never
    // left looking at an empty list with only an error banner.
    var lastTimelineData = null;

    function formatTimeRange(start, end, inProgress) {
        var startTxt = (start || "").slice(11, 16);
        var endTxt = (end || "").slice(11, 16);
        if (inProgress || !endTxt) {
            return startTxt + "-进行中";
        }
        return startTxt + "-" + endTxt;
    }

    function showTimeline(data) {
        if (!data) return;
        lastTimelineData = data;
        document.getElementById("timeline-date-display").textContent = data.date || "--";
        document.getElementById("timeline-total").textContent = data.total_duration || "00:00:00";
        var current = data.current_activity || {};
        var currentEl = document.getElementById("timeline-current");
        if (current.active) {
            currentEl.textContent = "当前活动：" + current.display;
        } else {
            currentEl.textContent = "当前活动：无";
        }

        var listEl = document.getElementById("timeline-sessions-list");
        var sessions = data.sessions || [];
        if (sessions.length === 0) {
            listEl.innerHTML = '<div class="timeline-empty">当日暂无活动记录</div>';
            // Clear details when there are no sessions
            document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
            document.getElementById("timeline-details-list").innerHTML = "";
            selectedSessionId = null;
            return;
        }

        // Build the full HTML string before replacing to avoid flicker.
        var html = "";
        for (var i = 0; i < sessions.length; i++) {
            var s = sessions[i];
            var timeRange = formatTimeRange(s.start_time, s.end_time, s.is_in_progress);
            var projectLabel = s.project_name || "未归类";
            if (s.project_description) {
                projectLabel += " (" + s.project_description + ")";
            }
            var cls = "timeline-item";
            if (s.is_uncategorized) cls += " uncategorized";
            if (s.is_in_progress) cls += " in-progress";
            if (s.session_id === selectedSessionId) cls += " selected";
            html += '<div class="' + cls + '" data-session-id="' + escapeHtml(s.session_id) + '"'
                + ' title="' + escapeHtml(projectLabel) + '｜' + escapeHtml(timeRange) + '｜' + escapeHtml(s.duration) + '"'
                + '>'
                + '<div class="timeline-item-main">'
                + '<div class="timeline-item-project">' + escapeHtml(projectLabel) + '</div>'
                + '<div class="timeline-item-time">' + escapeHtml(timeRange) + '</div>'
                + '<div class="timeline-item-status">' + escapeHtml(s.status || "") + '</div>'
                + '</div>'
                + '<div class="timeline-item-side">'
                + '<div class="timeline-item-duration">' + escapeHtml(s.duration) + '</div>'
                + '<div class="timeline-item-count">' + escapeHtml(String(s.event_count || 0) + " 条") + '</div>'
                + '</div>'
                + '</div>';
        }
        listEl.innerHTML = html;

        // Bind click handlers to session items
        var items = listEl.querySelectorAll(".timeline-item");
        for (var j = 0; j < items.length; j++) {
            (function (itemEl) {
                itemEl.addEventListener("click", function () {
                    var sid = itemEl.getAttribute("data-session-id");
                    selectTimelineSession(sid, sessions);
                });
            })(items[j]);
        }

        // If the previously selected session still exists, reload its details.
        if (selectedSessionId !== null) {
            var found = null;
            for (var k = 0; k < sessions.length; k++) {
                if (sessions[k].session_id === selectedSessionId) {
                    found = sessions[k];
                    break;
                }
            }
            if (found) {
                loadSessionDetails(found.activity_ids, data.date);
            } else {
                // Selected session disappeared (e.g. session ended and was
                // re-grouped). Clear selection gracefully without throwing.
                selectedSessionId = null;
                document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
                document.getElementById("timeline-details-list").innerHTML = "";
            }
        }
    }

    function selectTimelineSession(sessionId, sessions) {
        selectedSessionId = sessionId;
        // Update selected class without full re-render
        var items = document.querySelectorAll("#timeline-sessions-list .timeline-item");
        for (var i = 0; i < items.length; i++) {
            items[i].classList.remove("selected");
            if (items[i].getAttribute("data-session-id") === sessionId) {
                items[i].classList.add("selected");
            }
        }
        // Find the session to get activity_ids
        var found = null;
        for (var j = 0; j < sessions.length; j++) {
            if (sessions[j].session_id === sessionId) {
                found = sessions[j];
                break;
            }
        }
        if (found) {
            var dateEl = document.getElementById("timeline-date-display");
            loadSessionDetails(found.activity_ids, dateEl ? dateEl.textContent : null);
        }
    }

    function loadSessionDetails(activityIds, date) {
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        // Only show the "loading" placeholder when the panel is empty. If
        // we already have details on screen, keep them visible while the
        // new data loads so a refresh does not flash an empty panel.
        if (!detailsList.innerHTML.trim()) {
            detailsHeader.textContent = "加载详情…";
            detailsList.innerHTML = "";
        }

        var token = ++detailsRequestToken;
        callBridge("get_timeline_session_details", activityIds, date).then(function (result) {
            if (token !== detailsRequestToken) return;  // stale response
            var data = handleResult(result, function (msg) {
                detailsHeader.textContent = "加载详情失败";
                detailsList.innerHTML = '<div class="timeline-empty">' + escapeHtml(msg) + '</div>';
            });
            if (!data) return;
            renderSessionDetails(data);
        }).catch(function () {
            if (token !== detailsRequestToken) return;  // stale response
            detailsHeader.textContent = "加载详情失败";
            detailsList.innerHTML = '<div class="timeline-empty">无法加载详情，请稍后重试。</div>';
        });
    }

    function renderSessionDetails(data) {
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        var activities = data.activities || [];
        if (activities.length === 0) {
            detailsHeader.textContent = "该时段暂无活动详情";
            detailsList.innerHTML = '<div class="timeline-empty">暂无详情</div>';
            return;
        }
        detailsHeader.textContent = "活动详情（" + activities.length + " 条）";
        var html = "";
        for (var i = 0; i < activities.length; i++) {
            var a = activities[i];
            var timeRange = formatTimeRange(a.start_time, a.end_time, a.is_in_progress);
            var displayName = a.resource_name || a.app_name || "未知";
            var cls = "detail-item";
            if (a.is_in_progress) cls += " in-progress";
            html += '<div class="' + cls + '">'
                + '<div class="detail-item-time">' + escapeHtml(timeRange) + '</div>'
                + '<div class="detail-item-name" title="' + escapeHtml(displayName) + '">' + escapeHtml(displayName) + '</div>'
                + '<div class="detail-item-meta">'
                + '<span class="detail-item-type">' + escapeHtml(a.resource_type || "") + '</span>'
                + '<span class="detail-item-app">' + escapeHtml(a.app_name || "") + '</span>'
                + '</div>'
                + '<div class="detail-item-project" title="' + escapeHtml(a.project_name || "未归类") + '">' + escapeHtml(a.project_name || "未归类") + '</div>'
                + '<div class="detail-item-duration">' + escapeHtml(a.duration) + '</div>'
                + '</div>';
        }
        detailsList.innerHTML = html;
    }

    // --- Timeline loading -----------------------------------------------

    function loadTimeline(date) {
        setTimelineLoading(true);
        clearTimelineError();
        var token = ++timelineRequestToken;
        callBridge("get_timeline", date).then(function (result) {
            if (token !== timelineRequestToken) return;  // stale response
            var data = handleResult(result, function (msg) {
                showTimelineError(msg || "加载时间详情失败，请稍后重试。");
            });
            setTimelineLoading(false);
            if (!data) return;
            timelineLoaded = true;
            showTimeline(data);
        }).catch(function (err) {
            if (token !== timelineRequestToken) return;  // stale response
            setTimelineLoading(false);
            showTimelineError(err && err.message ? err.message : "加载时间详情失败，请稍后重试。");
        });
    }

    function refreshTimeline() {
        // Silent refresh: do not show loading spinner, just reload data.
        // On error, keep showing the previous data so the user is not left
        // looking at an empty list; only the error banner is shown.
        var dateEl = document.getElementById("timeline-date-display");
        var date = timelineDate || (dateEl ? dateEl.textContent : null);
        if (date === "--") date = null;
        var token = ++timelineRequestToken;
        callBridge("get_timeline", date).then(function (result) {
            if (token !== timelineRequestToken) return;  // stale response
            var data = handleResult(result, function (msg) {
                showTimelineError(msg || "刷新时间详情失败，请稍后重试。");
            });
            if (!data) return;
            showTimeline(data);
            clearTimelineError();
        }).catch(function () {
            if (token !== timelineRequestToken) return;  // stale response
            // Only show error banner; keep lastTimelineData on screen.
            showTimelineError("刷新时间详情失败，请稍后重试。");
        });
    }

    // --- Timeline date navigation ---------------------------------------

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

    function goPrevDay() {
        var dateEl = document.getElementById("timeline-date-display");
        var current = timelineDate || (dateEl ? dateEl.textContent : null);
        timelineDate = shiftDate(current, -1);
        selectedSessionId = null;
        loadTimeline(timelineDate);
    }

    function goNextDay() {
        var dateEl = document.getElementById("timeline-date-display");
        var current = timelineDate || (dateEl ? dateEl.textContent : null);
        timelineDate = shiftDate(current, 1);
        selectedSessionId = null;
        loadTimeline(timelineDate);
    }

    function goToday() {
        timelineDate = null;
        selectedSessionId = null;
        loadTimeline(null);
    }

    // --- Utility --------------------------------------------------------

    function escapeHtml(text) {
        if (text === null || text === undefined) return "";
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    // --- Refresh orchestration ------------------------------------------

    function refreshAll() {
        var statusPromise = callBridge("get_status").then(function (result) {
            var status = handleResult(result, function (msg) {
                throw new Error(msg);
            });
            showStatus(status);
        }).catch(function (err) {
            showError(err && err.message ? err.message : "无法连接采集器状态，请稍后重试。");
            throw err;
        });

        var overviewPromise = callBridge("get_overview").then(function (result) {
            var overview = handleResult(result, function (msg) {
                throw new Error(msg);
            });
            showOverview(overview);
        }).catch(function (err) {
            showError(err && err.message ? err.message : "加载今日概览失败，请稍后重试。");
            throw err;
        });

        var recentPromise = callBridge("get_recent_activities").then(function (result) {
            var recent = handleResult(result, function (msg) {
                throw new Error(msg);
            });
            showRecent(recent);
        }).catch(function (err) {
            showError(err && err.message ? err.message : "加载最近活动失败，请稍后重试。");
            throw err;
        });

        var promises = [statusPromise, overviewPromise, recentPromise];

        // If the Timeline page is currently active, also refresh it.
        if (currentPage === "timeline" && timelineLoaded) {
            var timelinePromise = new Promise(function (resolve, reject) {
                var dateEl = document.getElementById("timeline-date-display");
                var date = timelineDate || (dateEl ? dateEl.textContent : null);
                if (date === "--") date = null;
                var token = ++timelineRequestToken;
                callBridge("get_timeline", date).then(function (result) {
                    if (token !== timelineRequestToken) { resolve(); return; }  // stale
                    var data = handleResult(result, function (msg) {
                        showTimelineError(msg || "刷新时间详情失败，请稍后重试。");
                        throw new Error(msg);
                    });
                    if (data) {
                        showTimeline(data);
                        clearTimelineError();
                    }
                    resolve();
                }).catch(function (err) {
                    if (token !== timelineRequestToken) { resolve(); return; }  // stale
                    // Keep lastTimelineData on screen; just surface the error.
                    showTimelineError("刷新时间详情失败，请稍后重试。");
                    reject(err);
                });
            });
            promises.push(timelinePromise);
        }

        Promise.allSettled(promises).then(function (results) {
            var anyError = false;
            for (var i = 0; i < results.length; i++) {
                if (results[i].status === "rejected") {
                    anyError = true;
                    break;
                }
            }
            if (!anyError) {
                clearError();
            }
        });
    }

    function togglePause() {
        callBridge("toggle_pause").then(function (result) {
            var status = handleResult(result, function (msg) {
                showError(msg);
            });
            showStatus(status);
        }).catch(function () {
            showError("切换暂停状态失败，请稍后重试。");
        });
    }

    // --- Navigation -----------------------------------------------------

    function switchPage(pageId) {
        var navItems = document.querySelectorAll(".nav-item");
        var pages = document.querySelectorAll(".page");
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].classList.remove("active");
        }
        for (var j = 0; j < pages.length; j++) {
            pages[j].classList.remove("active");
        }
        var navTarget = document.querySelector('.nav-item[data-page="' + pageId + '"]');
        var pageTarget = document.getElementById("page-" + pageId);
        if (navTarget) navTarget.classList.add("active");
        if (pageTarget) pageTarget.classList.add("active");

        currentPage = pageId;

        // Lazy-load Timeline data when navigating to it for the first time.
        if (pageId === "timeline" && !timelineLoaded && !timelineLoading) {
            loadTimeline(timelineDate);
        }
    }

    function initNav() {
        var navItems = document.querySelectorAll(".nav-item");
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].addEventListener("click", function () {
                switchPage(this.getAttribute("data-page"));
            });
        }
    }

    function initButtons() {
        document.getElementById("toggle-pause-btn").addEventListener("click", togglePause);
        document.getElementById("refresh-btn").addEventListener("click", refreshAll);
        // Timeline date navigation
        document.getElementById("timeline-prev-btn").addEventListener("click", goPrevDay);
        document.getElementById("timeline-next-btn").addEventListener("click", goNextDay);
        document.getElementById("timeline-today-btn").addEventListener("click", goToday);
    }

    function startAutoRefresh() {
        if (refreshTimer !== null) clearInterval(refreshTimer);
        refreshTimer = setInterval(refreshAll, REFRESH_INTERVAL_MS);
    }

    function init() {
        initNav();
        initButtons();
        refreshAll();
        startAutoRefresh();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
