// WorkTrace WebView frontend — authoritative Statistics / Export snapshot UI.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function element(id) { return document.getElementById(id); }
    function showStatisticsError(message) {
        var banner = element("statistics-error");
        if (!banner) return;
        banner.hidden = !message;
        banner.textContent = message || "加载统计失败";
    }
    App.showStatisticsError = showStatisticsError;
    App.clearStatisticsError = function () { showStatisticsError(""); };

    function setStatisticsLoading(loading) {
        App.statisticsLoading = !!loading;
        if (element("statistics-loading")) element("statistics-loading").hidden = !loading;
        if (element("statistics-update-status")) {
            element("statistics-update-status").textContent = loading ? "更新中…" : "已自动更新";
        }
        var button = element("stats-export-action-btn");
        if (button) button.disabled = !!loading || !!App.statisticsExportSaving
            || !App.statisticsAcceptedPayload;
    }
    App.setStatisticsLoading = setStatisticsLoading;

    function validateStatisticsDateRange(dateFrom, dateTo) {
        if (!dateFrom || !dateTo) return "请选择完整日期范围";
        if (!/^\d{4}-\d{2}-\d{2}$/.test(dateFrom) || !/^\d{4}-\d{2}-\d{2}$/.test(dateTo)) {
            return "请选择有效日期";
        }
        if (dateFrom > dateTo) return "请选择有效日期范围";
        return null;
    }
    App.validateStatisticsDateRange = validateStatisticsDateRange;

    function selectedFilters() {
        var mode = element("statistics-range-mode") ? element("statistics-range-mode").value : "month";
        var all = mode === "all";
        var dateFrom = "";
        var dateTo = "";
        if (all) {
            dateFrom = "";
            dateTo = "";
        } else if (mode === "month") {
            var today = new Date();
            var start = new Date(today.getFullYear(), today.getMonth(), 1);
            dateFrom = localDate(start);
            dateTo = localDate(today);
        } else {
            dateFrom = element("statistics-date-from").value;
            dateTo = element("statistics-date-to").value;
        }
        return {
            dateFrom: dateFrom,
            dateTo: dateTo,
            projectId: element("statistics-project-filter") ? element("statistics-project-filter").value : "",
            allTime: all
        };
    }

    function selectedProjectLabel() {
        var select = element("statistics-project-filter");
        return select && select.selectedIndex >= 0 ? select.options[select.selectedIndex].text : "全部项目";
    }

    function invalidateStatisticsSelection() {
        App.statisticsLoaded = false;
        App.statisticsAcceptedPayload = null;
        App.statisticsSnapshotRevision = "";
        setStatisticsExportStatus("", "");
        setStatisticsLoading(false);
    }
    App.invalidateStatisticsSelection = invalidateStatisticsSelection;

    function loadStatisticsExportSummary() {
        var filters = selectedFilters();
        if (!filters.allTime) {
            var message = validateStatisticsDateRange(filters.dateFrom, filters.dateTo);
            if (message) { showStatisticsError(message); return Promise.resolve(null); }
        }
        var key = JSON.stringify(filters);
        var token = App.requestCoordinator.beginLatest("statistics", key);
        setStatisticsLoading(true);
        App.clearStatisticsError();
        var request = App.bridge.getStatisticsExportSummary(
            filters.dateFrom, filters.dateTo, filters.projectId
        );
        App.statisticsLoadPromise = request;
        return request.then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            var data = App.handleResult(result, showStatisticsError);
            if (!data || !data.summary || !data.export_ticket) return null;
            App.statisticsAcceptedPayload = {
                summary: data.summary,
                exportTicket: data.export_ticket,
                filters: filters
            };
            App.statisticsSnapshotRevision = String(data.export_ticket.revision || "");
            App.statisticsLoaded = true;
            showStatistics(data.summary, filters);
            return data;
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) showStatisticsError("加载统计失败");
            return null;
        }).finally(function () {
            if (App.requestCoordinator.isCurrent(token)) setStatisticsLoading(false);
        });
    }
    App.loadStatisticsExportSummary = loadStatisticsExportSummary;

    function showStatistics(summary, filters) {
        element("stats-total").textContent = summary.total_duration || "00:00:00";
        element("stats-activity-count").textContent = String(summary.session_count || 0);
        element("stats-project-count").textContent = String(summary.project_count || 0);
        element("stats-app-count").textContent = String(summary.app_count || 0);
        renderStatsTable("stats-by-project", "stats-empty-project", summary.by_project || []);
        renderStatsTable("stats-by-app", "stats-empty-app", summary.by_app || []);
        var scope = (filters && filters.allTime)
            ? "全部时间" : String(summary.date_from || "") + " 至 " + String(summary.date_to || "");
        element("stats-scope").textContent = "当前范围：" + scope + " · " + selectedProjectLabel();
        renderExportPreview(summary.export_preview || {}, scope);
    }
    App.showStatistics = showStatistics;

    function renderStatsTable(tbodyId, emptyId, groups) {
        var body = element(tbodyId);
        var empty = element(emptyId);
        groups = Array.isArray(groups) ? groups : [];
        if (!groups.length) { body.innerHTML = ""; empty.hidden = false; return; }
        empty.hidden = true;
        body.innerHTML = groups.map(function (group) {
            var percentage = Math.max(0, Math.min(100, parseFloat(group.percentage) || 0));
            return '<tr><td title="' + App.escapeHtml(group.display_name || "未知") + '"><div class="stats-name">'
                + '<span>' + App.escapeHtml(group.display_name || "未知") + '</span>'
                + '<span class="stats-share-bar" aria-hidden="true"><i style="width:' + percentage + '%"></i></span>'
                + '</div></td><td class="number">'
                + App.escapeHtml(group.duration || App.formatDuration(group.duration_seconds || 0))
                + '</td><td class="number">' + App.escapeHtml(String(group.activity_count || 0))
                + '</td><td class="number">' + App.escapeHtml(String(group.percentage || 0)) + '%</td></tr>';
        }).join("");
    }
    App.renderStatsTable = renderStatsTable;

    function renderExportPreview(preview, scope) {
        element("stats-export-range").textContent = scope || "--";
        element("stats-export-count").textContent = String(preview.session_count || 0);
        element("stats-export-duration").textContent = preview.included_duration || "00:00:00";
        element("stats-export-formats").textContent = "CSV";
    }
    App.renderExportPreview = renderExportPreview;

    function localDate(value) {
        var year = value.getFullYear();
        var month = String(value.getMonth() + 1).padStart(2, "0");
        var day = String(value.getDate()).padStart(2, "0");
        return year + "-" + month + "-" + day;
    }

    function applyStatisticsQuickRange(type) {
        var today = new Date();
        var start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        if (type === "week") start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
        if (type === "month") start = new Date(today.getFullYear(), today.getMonth(), 1);
        element("statistics-range-mode").value = "custom";
        element("statistics-custom-range").hidden = false;
        element("statistics-date-from").value = localDate(start);
        element("statistics-date-to").value = localDate(today);
        invalidateStatisticsSelection();
        return loadStatisticsExportSummary();
    }
    App.applyStatisticsQuickRange = applyStatisticsQuickRange;

    function scheduleStatisticsQuery(delay) {
        invalidateStatisticsSelection();
        if (App.statisticsQueryTimer) window.clearTimeout(App.statisticsQueryTimer);
        App.statisticsQueryTimer = window.setTimeout(loadStatisticsExportSummary, delay || 0);
    }
    App.scheduleStatisticsQuery = scheduleStatisticsQuery;

    function populateProjectFilter(projects) {
        var select = element("statistics-project-filter");
        if (!select) return;
        var current = select.value;
        select.innerHTML = '<option value="">全部项目</option><option value="unclassified">未归类</option>'
            + (projects || []).map(function (project) {
                return '<option value="' + App.escapeHtml(String(project.id || "")) + '">'
                    + App.escapeHtml(project.name || "未命名项目") + '</option>';
            }).join("");
        select.value = current;
    }

    function initStatisticsDefaults() {
        if (App.statisticsControlsBound) return;
        App.statisticsControlsBound = true;
        var today = new Date();
        var monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
        if (element("statistics-date-from")) element("statistics-date-from").value = localDate(monthStart);
        if (element("statistics-date-to")) element("statistics-date-to").value = localDate(today);
        element("statistics-range-mode").addEventListener("change", function () {
            var custom = this.value === "custom";
            element("statistics-custom-range").hidden = !custom;
            scheduleStatisticsQuery(0);
        });
        ["statistics-date-from", "statistics-date-to"].forEach(function (id) {
            element(id).addEventListener("change", function () { scheduleStatisticsQuery(500); });
        });
        element("statistics-project-filter").addEventListener("change", function () { scheduleStatisticsQuery(0); });
        [["stats-project-tab", "stats-project-panel", "stats-app-tab", "stats-app-panel"],
         ["stats-app-tab", "stats-app-panel", "stats-project-tab", "stats-project-panel"]]
            .forEach(function (ids) {
                element(ids[0]).addEventListener("click", function () {
                    element(ids[0]).setAttribute("aria-selected", "true"); element(ids[1]).hidden = false;
                    element(ids[2]).setAttribute("aria-selected", "false"); element(ids[3]).hidden = true;
                });
            });
        if (App.loadProjects) App.loadProjects().then(populateProjectFilter);
    }
    App.initStatisticsDefaults = initStatisticsDefaults;

    function setStatisticsExportStatus(message, kind) {
        var status = element("stats-export-status");
        if (!status) return;
        status.hidden = !message;
        status.textContent = message || "";
        status.className = "inline-status" + (kind ? " " + kind : "");
    }
    App.setStatisticsExportStatus = setStatisticsExportStatus;

    function setStatisticsExportSaving(saving) {
        App.statisticsExportSaving = !!saving;
        setStatisticsLoading(App.statisticsLoading);
    }
    App.setStatisticsExportSaving = setStatisticsExportSaving;

    function exportStatisticsCsv() {
        if (App.statisticsLoading || App.statisticsExportSaving) return;
        var accepted = App.statisticsAcceptedPayload;
        if (!accepted || !accepted.exportTicket) return;
        setStatisticsExportSaving(true);
        setStatisticsExportStatus("正在导出…", "");
        var ticket = accepted.exportTicket;
        return App.bridge.exportStatisticsCsv(
            ticket.date_from, ticket.date_to, ticket.revision, ticket.project_id || ""
        ).then(function (result) {
            if (result && result.cancelled) setStatisticsExportStatus("已取消导出", "");
            else if (!result || result.ok === false) setStatisticsExportStatus((result && result.error) || "导出失败", "error");
            else setStatisticsExportStatus("已导出 " + (result.filename || "CSV 文件"), "success");
        }).catch(function () {
            setStatisticsExportStatus("导出失败", "error");
        }).finally(function () { setStatisticsExportSaving(false); });
    }
    App.exportStatisticsCsv = exportStatisticsCsv;
})();
