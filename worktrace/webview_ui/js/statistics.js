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
            element("statistics-update-status").textContent = loading
                ? "更新中…" : (App.statisticsLoaded ? "已自动更新" : "");
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

    function localDate(value) {
        var year = value.getFullYear();
        var month = String(value.getMonth() + 1).padStart(2, "0");
        var day = String(value.getDate()).padStart(2, "0");
        return year + "-" + month + "-" + day;
    }

    function statisticsWeekRange(today) {
        var start = new Date(
            today.getFullYear(),
            today.getMonth(),
            today.getDate()
        );
        start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
        return {
            dateFrom: localDate(start),
            dateTo: localDate(today)
        };
    }
    App.statisticsWeekRange = statisticsWeekRange;

    function shortcutRange(type, today) {
        var todayValue = localDate(today);
        if (type === "today") return { dateFrom: todayValue, dateTo: todayValue };
        if (type === "week") return statisticsWeekRange(today);
        if (type === "month") {
            return {
                dateFrom: localDate(new Date(today.getFullYear(), today.getMonth(), 1)),
                dateTo: todayValue
            };
        }
        if (type === "all") return { dateFrom: "", dateTo: "" };
        return null;
    }

    function currentSelection() {
        if (!App.statisticsSelectionInitialized || !App.statisticsSelection) {
            var range = statisticsWeekRange(new Date());
            App.statisticsSelection = {
                allTime: false,
                dateFrom: range.dateFrom,
                dateTo: range.dateTo
            };
            App.statisticsSelectionInitialized = true;
        }
        return App.statisticsSelection;
    }

    function setStatisticsSelection(allTime, dateFrom, dateTo) {
        App.statisticsSelection = {
            allTime: !!allTime,
            dateFrom: allTime ? "" : String(dateFrom || ""),
            dateTo: allTime ? "" : String(dateTo || "")
        };
        App.statisticsSelectionInitialized = true;
        syncStatisticsSelection();
    }
    App.setStatisticsSelection = setStatisticsSelection;

    function displayDate(value) {
        return String(value || "").replace(/-/g, "/");
    }

    function selectedProjectLabel() {
        var select = element("statistics-project-filter");
        return select && select.selectedIndex >= 0 && select.options
            ? select.options[select.selectedIndex].text
            : "全部项目";
    }

    function updateStatisticsScope(filters) {
        filters = filters || selectedFilters();
        var scope = filters.allTime
            ? "全部时间"
            : displayDate(filters.dateFrom) + " 至 " + displayDate(filters.dateTo);
        if (element("stats-scope")) {
            element("stats-scope").textContent = "当前范围：" + scope + " · " + selectedProjectLabel();
        }
    }

    function syncStatisticsSelection() {
        var selection = currentSelection();
        var from = element("statistics-date-from");
        var to = element("statistics-date-to");
        if (from) from.value = selection.dateFrom;
        if (to) to.value = selection.dateTo;
        if (element("statistics-date-from-display")) {
            element("statistics-date-from-display").textContent = displayDate(selection.dateFrom);
        }
        if (element("statistics-date-to-display")) {
            element("statistics-date-to-display").textContent = displayDate(selection.dateTo);
        }
        if (element("statistics-date-inputs")) {
            element("statistics-date-inputs").hidden = selection.allTime;
        }
        if (element("statistics-all-time-label")) {
            element("statistics-all-time-label").hidden = !selection.allTime;
        }

        var today = new Date();
        ["today", "week", "month", "all"].forEach(function (type) {
            var range = shortcutRange(type, today);
            var pressed = type === "all"
                ? selection.allTime
                : !selection.allTime
                    && selection.dateFrom === range.dateFrom
                    && selection.dateTo === range.dateTo;
            var button = element("statistics-" + type + "-btn");
            if (button) button.setAttribute("aria-pressed", pressed ? "true" : "false");
        });
        updateStatisticsScope({
            allTime: selection.allTime,
            dateFrom: selection.dateFrom,
            dateTo: selection.dateTo,
            projectId: element("statistics-project-filter")
                ? element("statistics-project-filter").value : ""
        });
    }
    App.syncStatisticsSelection = syncStatisticsSelection;

    function selectedFilters() {
        var selection = currentSelection();
        return {
            dateFrom: selection.allTime ? "" : selection.dateFrom,
            dateTo: selection.allTime ? "" : selection.dateTo,
            projectId: element("statistics-project-filter") ? element("statistics-project-filter").value : "",
            allTime: selection.allTime
        };
    }
    App.selectedStatisticsFilters = selectedFilters;

    function clearStatisticsPresentation() {
        var results = element("statistics-results");
        if (results) results.hidden = true;
        ["stats-total", "stats-activity-count", "stats-project-count", "stats-app-count"]
            .forEach(function (id) {
                if (element(id)) element(id).textContent = "";
            });
        ["stats-by-project", "stats-by-app"].forEach(function (id) {
            if (element(id)) element(id).innerHTML = "";
        });
        ["stats-empty-project", "stats-empty-app"].forEach(function (id) {
            if (element(id)) element(id).hidden = true;
        });
    }
    App.clearStatisticsPresentation = clearStatisticsPresentation;

    function invalidateStatisticsSelection() {
        App.statisticsLoaded = false;
        App.statisticsAcceptedPayload = null;
        App.statisticsSnapshotRevision = "";
        setStatisticsExportStatus("", "");
        clearStatisticsPresentation();
        setStatisticsLoading(false);
    }
    App.invalidateStatisticsSelection = invalidateStatisticsSelection;

    function executeStatisticsQuery(owner) {
        var filters = owner.filters;
        var token = owner.token;
        var request = App.bridge.getStatisticsExportSummary(
            filters.dateFrom, filters.dateTo, filters.projectId
        );
        var pending = request.then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            var data = App.handleResult(result, showStatisticsError);
            if (!data || !data.summary || !data.export_ticket) {
                if (!data) return null;
                showStatisticsError("加载统计失败");
                return null;
            }
            App.statisticsAcceptedPayload = {
                summary: data.summary,
                exportTicket: data.export_ticket,
                filters: filters
            };
            App.statisticsSnapshotRevision = String(data.export_ticket.revision || "");
            showStatistics(data.summary, filters);
            App.statisticsLoaded = true;
            return data;
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) showStatisticsError("加载统计失败");
            return null;
        }).finally(function () {
            if (App.requestCoordinator.isCurrent(token)) setStatisticsLoading(false);
        });
        App.statisticsLoadPromise = pending;
        return pending;
    }

    function beginStatisticsQuery(delay) {
        if (App.statisticsQueryTimer) window.clearTimeout(App.statisticsQueryTimer);
        App.statisticsQueryTimer = null;
        var filters = selectedFilters();
        var key = JSON.stringify(filters);
        var token = App.requestCoordinator.beginLatest("statistics", key);
        invalidateStatisticsSelection();
        App.clearStatisticsError();
        updateStatisticsScope(filters);
        setStatisticsLoading(true);
        if (!filters.allTime) {
            var message = validateStatisticsDateRange(filters.dateFrom, filters.dateTo);
            if (message) {
                showStatisticsError(message);
                setStatisticsLoading(false);
                return Promise.resolve(null);
            }
        }
        var owner = { filters: filters, token: token };
        if (delay > 0) {
            App.statisticsQueryTimer = window.setTimeout(function () {
                App.statisticsQueryTimer = null;
                executeStatisticsQuery(owner);
            }, delay);
            return Promise.resolve(null);
        }
        return executeStatisticsQuery(owner);
    }
    App.beginStatisticsQuery = beginStatisticsQuery;

    function loadStatisticsExportSummary() {
        return beginStatisticsQuery(0);
    }
    App.loadStatisticsExportSummary = loadStatisticsExportSummary;

    function showStatistics(summary, filters) {
        element("stats-total").textContent = summary.total_duration || "00:00:00";
        element("stats-activity-count").textContent = String(summary.session_count || 0);
        element("stats-project-count").textContent = String(summary.project_count || 0);
        element("stats-app-count").textContent = String(summary.app_count || 0);
        renderStatsTable("stats-by-project", "stats-empty-project", summary.by_project || []);
        renderStatsTable("stats-by-app", "stats-empty-app", summary.by_app || []);
        updateStatisticsScope(filters);
        if (element("statistics-results")) element("statistics-results").hidden = false;
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

    function applyStatisticsQuickRange(type) {
        var today = new Date();
        var range = shortcutRange(type, today);
        if (!range) return Promise.resolve(null);
        setStatisticsSelection(type === "all", range.dateFrom, range.dateTo);
        return beginStatisticsQuery(0);
    }
    App.applyStatisticsQuickRange = applyStatisticsQuickRange;

    function scheduleStatisticsQuery(delay) {
        return beginStatisticsQuery(delay || 0);
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
    App.populateStatisticsProjectFilter = populateProjectFilter;

    function initStatisticsDefaults() {
        currentSelection();
        syncStatisticsSelection();
        if (!App.statisticsControlsBound) {
            App.statisticsControlsBound = true;
            ["statistics-date-from", "statistics-date-to"].forEach(function (id) {
                element(id).addEventListener("change", function () {
                    setStatisticsSelection(
                        false,
                        element("statistics-date-from").value,
                        element("statistics-date-to").value
                    );
                    scheduleStatisticsQuery(500);
                });
            });
            element("statistics-project-filter").addEventListener("change", function () {
                syncStatisticsSelection();
                scheduleStatisticsQuery(0);
            });
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
