// WorkTrace WebView frontend.
// Phase 1: Overview page is the production default UI. Other pages remain
// migration placeholders.
// Only communicates with Python through pywebview API bridge.
// Does not persist sensitive data in browser storage APIs.
// Does not access any external network resources.

(function () {
    "use strict";

    var REFRESH_INTERVAL_MS = 8000;
    var refreshTimer = null;

    function callBridge(method) {
        if (typeof window.pywebview === "undefined" || !window.pywebview.api) {
            return Promise.reject(new Error("bridge unavailable"));
        }
        return window.pywebview.api[method]();
    }

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

    function handleResult(result, onError) {
        if (result && result.ok === false) {
            onError(result.error || "操作失败");
            return null;
        }
        return result;
    }

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
            var timeRange = (item.start_time || "").slice(11, 16) + "-" + (item.end_time || "").slice(11, 16);
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

    function escapeHtml(text) {
        if (text === null || text === undefined) return "";
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

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

        Promise.allSettled([statusPromise, overviewPromise, recentPromise]).then(function (results) {
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
