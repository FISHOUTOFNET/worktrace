// WorkTrace WebView frontend — statistics module.
// Statistics page: read-only summary loading + controlled CSV download.
// The single controlled write action; the frontend never writes a file itself.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};


    function showStatisticsError(message) {
        var banner = document.getElementById("statistics-error");
        if (!banner) return;
        if (!message) {
            banner.hidden = true;
            banner.textContent = "加载统计失败";
            return;
        }
        banner.hidden = false;
        banner.textContent = message;
    }
    App.showStatisticsError = showStatisticsError;

    function clearStatisticsError() {
        showStatisticsError("");
    }
    App.clearStatisticsError = clearStatisticsError;

    function setStatisticsLoading(loading) {
        App.statisticsLoading = loading;
        var el = document.getElementById("statistics-loading");
        if (el) el.hidden = !loading;
        var btn = document.getElementById("statistics-load-btn");
        if (btn) btn.disabled = loading;
        // Also disable the CSV download button while statistics are loading
        // so a write cannot be triggered mid-load.
        var exportBtn = document.getElementById("stats-export-action-btn");
        if (exportBtn) exportBtn.disabled = loading || App.statisticsExportSaving;
    }
    App.setStatisticsLoading = setStatisticsLoading;

    function loadStatisticsExportSummary() {
        // Refuse concurrent loads. The load button is already disabled
        // while loading, but this guard also covers any programmatic
        // trigger path (quick range buttons, lazy load).
        if (App.statisticsLoading) return;
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        var dateFrom = fromEl ? fromEl.value : "";
        var dateTo = toEl ? toEl.value : "";
        if (!dateFrom || !dateTo) {
            showStatisticsError("请选择有效日期");
            return;
        }
        // Client-side range pre-check so the user gets an immediate clear
        // message without a bridge round-trip. The bridge and service still
        // perform the canonical validation.
        var rangeMsg = validateStatisticsDateRange(dateFrom, dateTo);
        if (rangeMsg) {
            showStatisticsError(rangeMsg);
            return;
        }
        setStatisticsLoading(true);
        clearStatisticsError();
        var token = ++App.statisticsRequestToken;
        App.callBridge("get_statistics_export_summary", dateFrom, dateTo).then(function (result) {
            if (token !== App.statisticsRequestToken) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                // Never surface raw exception text; the bridge already
                // collapsed to a stable Chinese message.
                showStatisticsError(msg || "加载统计失败");
            });
            setStatisticsLoading(false);
            if (!data) return;  // keep prior rendered data on error
            App.statisticsLoaded = true;
            App.statisticsSnapshotRevision = (data.summary && data.summary.snapshot_revision) || "";
            showStatistics(data.summary);
            clearStatisticsError();
        }).catch(function () {
            if (token !== App.statisticsRequestToken) return;  // stale response
            setStatisticsLoading(false);
            // Keep prior data on screen; just surface the error.
            showStatisticsError("加载统计失败");
        });
    }
    App.loadStatisticsExportSummary = loadStatisticsExportSummary;

    function validateStatisticsDateRange(dateFrom, dateTo) {
        // Returns a Chinese error message string if the range is invalid,
        // or null if it passes the client-side pre-check.
        if (!dateFrom || !dateTo) return "请选择有效日期";
        var fromParts = dateFrom.split("-");
        var toParts = dateTo.split("-");
        if (fromParts.length !== 3 || toParts.length !== 3) return "请选择有效日期";
        var from = new Date(
            parseInt(fromParts[0], 10),
            parseInt(fromParts[1], 10) - 1,
            parseInt(fromParts[2], 10)
        );
        var to = new Date(
            parseInt(toParts[0], 10),
            parseInt(toParts[1], 10) - 1,
            parseInt(toParts[2], 10)
        );
        if (isNaN(from.getTime()) || isNaN(to.getTime())) return "请选择有效日期";
        if (from > to) return "请选择有效日期范围";
        // 31-day inclusive max (same as service STATISTICS_SUMMARY_MAX_RANGE_DAYS).
        var diffDays = Math.round((to - from) / (1000 * 60 * 60 * 24));
        if (diffDays > 30) return "日期范围过大";
        return null;
    }
    App.validateStatisticsDateRange = validateStatisticsDateRange;

    function showStatistics(summary) {
        if (!summary) return;
        document.getElementById("stats-total").textContent = summary.total_duration || "00:00:00";
        document.getElementById("stats-activity-count").textContent = String(summary.activity_count || 0);
        document.getElementById("stats-project-count").textContent = String(summary.project_count || 0);
        document.getElementById("stats-app-count").textContent = String(summary.app_count || 0);
        renderStatsTable("stats-by-project", "stats-empty-project", summary.by_project || []);
        renderStatsTable("stats-by-app", "stats-empty-app", summary.by_app || []);
        renderStatsTable("stats-by-status", "stats-empty-status", summary.by_status || []);
        renderExportPreview(summary.export_preview || {}, summary.date_from, summary.date_to);
    }
    App.showStatistics = showStatistics;

    function renderStatsTable(tbodyId, emptyId, groups) {
        var tbody = document.getElementById(tbodyId);
        var empty = document.getElementById(emptyId);
        if (!tbody) return;
        if (!groups || !groups.length) {
            tbody.innerHTML = "";
            if (empty) empty.hidden = false;
            return;
        }
        if (empty) empty.hidden = true;
        var html = "";
        for (var i = 0; i < groups.length; i++) {
            var g = groups[i];
            var name = App.safeText(g.display_name, "");
            var duration = App.safeText(g.duration, "00:00:00");
            var count = String(g.activity_count || 0);
            var pct = String(g.percentage || 0) + "%";
            html += '<tr class="stats-table-row">'
                + '<td class="stats-table-name" title="' + App.escapeHtml(name) + '">' + App.escapeHtml(name) + '</td>'
                + '<td class="stats-table-duration">' + App.escapeHtml(duration) + '</td>'
                + '<td class="stats-table-count">' + App.escapeHtml(count) + '</td>'
                + '<td class="stats-table-pct">' + App.escapeHtml(pct) + '</td>'
                + '</tr>';
        }
        tbody.innerHTML = html;
    }
    App.renderStatsTable = renderStatsTable;

    function renderExportPreview(preview, dateFrom, dateTo) {
        var rangeEl = document.getElementById("stats-export-range");
        var countEl = document.getElementById("stats-export-count");
        var durationEl = document.getElementById("stats-export-duration");
        var formatsEl = document.getElementById("stats-export-formats");
        if (rangeEl) rangeEl.textContent = App.escapeHtml(App.safeText(dateFrom, "") + " 至 " + App.safeText(dateTo, ""));
        if (countEl) countEl.textContent = String(preview.included_activity_count || 0);
        if (durationEl) durationEl.textContent = preview.included_duration || "00:00:00";
        App.statisticsSnapshotRevision = preview.snapshot_revision || App.statisticsSnapshotRevision || "";
        if (formatsEl) {
            var formats = preview.available_formats || [];
            formatsEl.textContent = formats.length ? App.escapeHtml(formats.join("、")) : "--";
        }
    }
    App.renderExportPreview = renderExportPreview;

    function applyStatisticsQuickRange(type) {
        var today = App.localTodayStr();
        var from, to;
        if (type === "today") {
            from = today;
            to = today;
        } else if (type === "7d") {
            from = App.shiftDate(today, -6);
            to = today;
        } else if (type === "month") {
            var parts = today.split("-");
            from = parts[0] + "-" + parts[1] + "-01";
            to = today;
        } else {
            return;
        }
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        if (fromEl) fromEl.value = from;
        if (toEl) toEl.value = to;
        loadStatisticsExportSummary();
    }
    App.applyStatisticsQuickRange = applyStatisticsQuickRange;

    function initStatisticsDefaults() {
        var today = App.localTodayStr();
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        if (fromEl && !fromEl.value) fromEl.value = today;
        if (toEl && !toEl.value) toEl.value = today;
    }
    App.initStatisticsDefaults = initStatisticsDefaults;

    // Statistics CSV download

    function setStatisticsExportStatus(message, kind) {
        var el = document.getElementById("stats-export-status");
        if (!el) return;
        if (!message) {
            el.hidden = true;
            el.textContent = "";
            el.className = "stats-export-status";
            return;
        }
        el.hidden = false;
        el.textContent = message;
        el.className = "stats-export-status" + (kind ? " " + kind : "");
    }
    App.setStatisticsExportStatus = setStatisticsExportStatus;

    function setStatisticsExportSaving(saving) {
        App.statisticsExportSaving = saving;
        var btn = document.getElementById("stats-export-action-btn");
        if (btn) {
            btn.disabled = saving || App.statisticsLoading;
        }
        // Block the statistics load button too while a write is in flight.
        var loadBtn = document.getElementById("statistics-load-btn");
        if (loadBtn) loadBtn.disabled = saving || App.statisticsLoading;
    }
    App.setStatisticsExportSaving = setStatisticsExportSaving;

    function exportStatisticsCsv() {
        // Duplicate-click guard: a write is already in flight.
        if (App.statisticsExportSaving) return;
        // Block the export while statistics are loading.
        if (App.statisticsLoading) return;
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        var dateFrom = fromEl ? fromEl.value : "";
        var dateTo = toEl ? toEl.value : "";
        if (!dateFrom || !dateTo) {
            setStatisticsExportStatus("请选择有效日期", "error");
            return;
        }
        var snapshotRevision = App.statisticsSnapshotRevision || "";
        if (!snapshotRevision) {
            setStatisticsExportStatus("请先加载统计数据", "error");
            return;
        }
        // Reuse the same client-side pre-check as the statistics load so
        // the user gets an immediate clear message without a bridge
        // round-trip. The bridge / service still perform canonical validation.
        var rangeMsg = validateStatisticsDateRange(dateFrom, dateTo);
        if (rangeMsg) {
            setStatisticsExportStatus(rangeMsg, "error");
            return;
        }
        setStatisticsExportSaving(true);
        setStatisticsExportStatus("正在导出…", "info");
        App.callBridge("export_statistics_csv", dateFrom, dateTo, snapshotRevision).then(function (result) {
            setStatisticsExportSaving(false);
            if (!result) {
                setStatisticsExportStatus("导出失败", "error");
                return;
            }
            // Cancelled is a clean result, not a failure.
            if (result.cancelled) {
                setStatisticsExportStatus("已取消导出", "info");
                return;
            }
            if (result.ok) {
                var filename = App.safeText(result.filename, "");
                var count = String(result.activity_count || 0);
                var duration = App.safeText(result.duration, "00:00:00");
                setStatisticsExportStatus(
                    "导出成功：" + filename + "（" + count + " 条，共 " + duration + "）",
                    "success"
                );
                return;
            }
            // Known failure: the bridge already collapsed to a Chinese msg.
            setStatisticsExportStatus(result.error || "导出失败", "error");
        }).catch(function () {
            setStatisticsExportSaving(false);
            // Never surface raw exception text; collapse to generic message.
            setStatisticsExportStatus("导出失败", "error");
        });
    }
    App.exportStatisticsCsv = exportStatisticsCsv;

})();
