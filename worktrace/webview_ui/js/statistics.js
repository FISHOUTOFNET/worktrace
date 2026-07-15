// WorkTrace WebView frontend — statistics module.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function showStatisticsError(message) {
        var banner = document.getElementById("statistics-error");
        if (!banner) return;
        banner.hidden = !message;
        banner.textContent = message || "加载统计失败";
    }
    App.showStatisticsError = showStatisticsError;
    App.clearStatisticsError = function () { showStatisticsError(""); };

    function setStatisticsLoading(loading) {
        App.statisticsLoading = loading;
        var el = document.getElementById("statistics-loading");
        if (el) el.hidden = !loading;
        var btn = document.getElementById("statistics-load-btn");
        if (btn) btn.disabled = !!loading || !!App.statisticsExportSaving;
        var exportBtn = document.getElementById("stats-export-action-btn");
        if (exportBtn) exportBtn.disabled = !!loading || !!App.statisticsExportSaving || !App.statisticsAcceptedPayload;
    }
    App.setStatisticsLoading = setStatisticsLoading;

    function validateStatisticsDateRange(dateFrom, dateTo) {
        if (!dateFrom || !dateTo) return "请选择有效日期";
        var fromParts = dateFrom.split("-");
        var toParts = dateTo.split("-");
        if (fromParts.length !== 3 || toParts.length !== 3) return "请选择有效日期";
        var from = new Date(+fromParts[0], +fromParts[1] - 1, +fromParts[2]);
        var to = new Date(+toParts[0], +toParts[1] - 1, +toParts[2]);
        if (isNaN(from.getTime()) || isNaN(to.getTime())) return "请选择有效日期";
        if (from > to) return "请选择有效日期范围";
        if (Math.round((to - from) / 86400000) > 30) return "日期范围过大";
        return null;
    }
    App.validateStatisticsDateRange = validateStatisticsDateRange;

    function selectedRange() {
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        return {
            dateFrom: fromEl ? fromEl.value : "",
            dateTo: toEl ? toEl.value : ""
        };
    }

    function loadStatisticsExportSummary() {
        var range = selectedRange();
        var rangeMsg = validateStatisticsDateRange(range.dateFrom, range.dateTo);
        if (rangeMsg) {
            showStatisticsError(rangeMsg);
            return Promise.resolve(null);
        }
        var key = range.dateFrom + "|" + range.dateTo;
        var token = App.requestCoordinator.beginLatest("statistics", key);
        setStatisticsLoading(true);
        App.clearStatisticsError();
        return App.callBridge("get_statistics_export_summary", range.dateFrom, range.dateTo).then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            var data = App.handleResult(result, function (msg) {
                showStatisticsError(msg || "加载统计失败");
            });
            if (!data || !data.summary) return null;
            var summary = data.summary;
            var exportRevision = summary.export_revision
                || (summary.export_preview && summary.export_preview.export_revision)
                || "";
            App.statisticsAcceptedPayload = {
                dateFrom: String(summary.date_from || range.dateFrom),
                dateTo: String(summary.date_to || range.dateTo),
                exportRevision: String(exportRevision)
            };
            App.statisticsSnapshotRevision = String(exportRevision);
            App.statisticsLoaded = true;
            showStatistics(summary);
            App.clearStatisticsError();
            return summary;
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) showStatisticsError("加载统计失败");
            return null;
        }).finally(function () {
            if (App.requestCoordinator.isCurrent(token)) setStatisticsLoading(false);
        });
    }
    App.loadStatisticsExportSummary = loadStatisticsExportSummary;

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
            html += '<tr class="stats-table-row">'
                + '<td class="stats-table-name" title="' + App.escapeHtml(name) + '">' + App.escapeHtml(name) + '</td>'
                + '<td class="stats-table-duration">' + App.escapeHtml(App.safeText(g.duration, "00:00:00")) + '</td>'
                + '<td class="stats-table-count">' + App.escapeHtml(String(g.activity_count || 0)) + '</td>'
                + '<td class="stats-table-pct">' + App.escapeHtml(String(g.percentage || 0) + "%") + '</td>'
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
        if (rangeEl) rangeEl.textContent = App.safeText(dateFrom, "") + " 至 " + App.safeText(dateTo, "");
        if (countEl) countEl.textContent = String(preview.included_activity_count || 0);
        if (durationEl) durationEl.textContent = preview.included_duration || "00:00:00";
        if (formatsEl) {
            var formats = preview.available_formats || [];
            formatsEl.textContent = formats.length ? formats.join("、") : "--";
        }
        setStatisticsLoading(false);
    }
    App.renderExportPreview = renderExportPreview;

    function applyStatisticsQuickRange(type) {
        var today = App.localTodayStr();
        var from;
        if (type === "today") from = today;
        else if (type === "7d") from = App.shiftDate(today, -6);
        else if (type === "month") {
            var parts = today.split("-");
            from = parts[0] + "-" + parts[1] + "-01";
        } else return;
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        if (fromEl) fromEl.value = from;
        if (toEl) toEl.value = today;
        return loadStatisticsExportSummary();
    }
    App.applyStatisticsQuickRange = applyStatisticsQuickRange;

    App.initStatisticsDefaults = function () {
        var today = App.localTodayStr();
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        if (fromEl && !fromEl.value) fromEl.value = today;
        if (toEl && !toEl.value) toEl.value = today;
    };

    function setStatisticsExportStatus(message, kind) {
        var el = document.getElementById("stats-export-status");
        if (!el) return;
        el.hidden = !message;
        el.textContent = message || "";
        el.className = "stats-export-status" + (kind ? " " + kind : "");
    }
    App.setStatisticsExportStatus = setStatisticsExportStatus;

    function setStatisticsExportSaving(saving) {
        App.statisticsExportSaving = saving;
        var btn = document.getElementById("stats-export-action-btn");
        if (btn) btn.disabled = saving || App.statisticsLoading || !App.statisticsAcceptedPayload;
        var loadBtn = document.getElementById("statistics-load-btn");
        if (loadBtn) loadBtn.disabled = saving || App.statisticsLoading;
    }
    App.setStatisticsExportSaving = setStatisticsExportSaving;

    function exportStatisticsCsv() {
        if (App.statisticsExportSaving || App.statisticsLoading) return;
        var accepted = App.statisticsAcceptedPayload;
        if (!accepted || !accepted.exportRevision) {
            setStatisticsExportStatus("请先加载统计数据", "error");
            return;
        }
        setStatisticsExportSaving(true);
        setStatisticsExportStatus("正在导出…", "info");
        App.callBridge(
            "export_statistics_csv",
            accepted.dateFrom,
            accepted.dateTo,
            accepted.exportRevision
        ).then(function (result) {
            if (!result) {
                setStatisticsExportStatus("导出失败", "error");
            } else if (result.cancelled) {
                setStatisticsExportStatus("已取消导出", "info");
            } else if (result.ok) {
                setStatisticsExportStatus(
                    "导出成功：" + App.safeText(result.filename, "")
                    + "（" + String(result.activity_count || 0) + " 条，共 "
                    + App.safeText(result.duration, "00:00:00") + "）",
                    "success"
                );
            } else {
                setStatisticsExportStatus(result.error || "导出失败", "error");
            }
        }).catch(function () {
            setStatisticsExportStatus("导出失败", "error");
        }).finally(function () {
            setStatisticsExportSaving(false);
        });
    }
    App.exportStatisticsCsv = exportStatisticsCsv;
})();
