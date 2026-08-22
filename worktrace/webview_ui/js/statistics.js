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
        var button = element("stats-export-action-btn");
        if (button) button.disabled = !!loading || !!App.statisticsExportSaving
            || !App.statisticsAcceptedPayload;
    }
    App.setStatisticsLoading = setStatisticsLoading;

    if (typeof App.statisticsLiveTickerSuspended !== "boolean") {
        App.statisticsLiveTickerSuspended = false;
    }

    function suspendStatisticsLiveTicker() {
        if (App.statisticsLiveTickerSuspended === true) return;
        if (typeof App.applyStatisticsLocalTicker === "function") {
            App.applyStatisticsLocalTicker();
        }
        App.statisticsLiveTickerSuspended = true;
    }
    App.suspendStatisticsLiveTicker = suspendStatisticsLiveTicker;

    function resumeStatisticsLiveTicker() {
        App.statisticsLiveTickerSuspended = false;
        App.statisticsLastLiveRenderKey = "";
    }
    App.resumeStatisticsLiveTicker = resumeStatisticsLiveTicker;

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
        if (!App.statisticsSelection) {
            var range = statisticsWeekRange(new Date());
            App.statisticsSelection = {
                allTime: false,
                dateFrom: range.dateFrom,
                dateTo: range.dateTo
            };
        }
        App.statisticsSelectionInitialized = true;
        if (!App.statisticsDraftSelection) {
            App.statisticsDraftSelection = cloneStatisticsSelection(App.statisticsSelection);
            App.statisticsDraftDirty = false;
        }
        return App.statisticsSelection;
    }

    function cloneStatisticsSelection(selection) {
        selection = selection || {};
        return {
            allTime: !!selection.allTime,
            dateFrom: selection.allTime ? "" : String(selection.dateFrom || ""),
            dateTo: selection.allTime ? "" : String(selection.dateTo || "")
        };
    }

    function statisticsSelectionsEqual(left, right) {
        left = cloneStatisticsSelection(left);
        right = cloneStatisticsSelection(right);
        return left.allTime === right.allTime
            && left.dateFrom === right.dateFrom
            && left.dateTo === right.dateTo;
    }

    function currentDraftSelection() {
        currentSelection();
        if (!App.statisticsDraftSelection) {
            App.statisticsDraftSelection = cloneStatisticsSelection(App.statisticsSelection);
        }
        return App.statisticsDraftSelection;
    }

    function setStatisticsSelection(allTime, dateFrom, dateTo) {
        App.statisticsSelection = {
            allTime: !!allTime,
            dateFrom: allTime ? "" : String(dateFrom || ""),
            dateTo: allTime ? "" : String(dateTo || "")
        };
        App.statisticsSelectionInitialized = true;
        App.statisticsDraftSelection = cloneStatisticsSelection(App.statisticsSelection);
        App.statisticsDraftDirty = false;
        syncStatisticsSelection();
        syncStatisticsDraftSelection();
    }
    App.setStatisticsSelection = setStatisticsSelection;

    function setStatisticsDraftStatus(message, isError) {
        var status = element("statistics-date-status");
        if (!status) return;
        status.hidden = !message;
        status.textContent = message || "";
        status.className = "statistics-date-status" + (isError ? " error" : "");
        ["statistics-date-from", "statistics-date-to"].forEach(function (id) {
            var input = element(id);
            if (input) input.setAttribute("aria-invalid", isError ? "true" : "false");
        });
    }

    function syncStatisticsSelection() {
        var selection = currentSelection();
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
    }
    App.syncStatisticsSelection = syncStatisticsSelection;

    function syncStatisticsDateInputPresentation(input) {
        if (!input) return;
        input.setAttribute("data-empty", String(!String(input.value || "")));
    }
    App.syncStatisticsDateInputPresentation = syncStatisticsDateInputPresentation;

    function syncStatisticsDraftSelection() {
        var selection = currentDraftSelection();
        var from = element("statistics-date-from");
        var to = element("statistics-date-to");
        if (from) from.value = selection.dateFrom;
        if (to) to.value = selection.dateTo;
        syncStatisticsDateInputPresentation(from);
        syncStatisticsDateInputPresentation(to);
        setStatisticsDraftStatus(
            App.statisticsDraftDirty ? "日期范围尚未应用" : "",
            false
        );
    }
    App.syncStatisticsDraftSelection = syncStatisticsDraftSelection;

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
        ["stats-total", "stats-activity-count", "stats-project-count", "stats-file-count", "stats-app-count"]
            .forEach(function (id) {
                if (element(id)) element(id).textContent = "";
            });
        ["stats-by-project", "stats-by-file", "stats-by-app"].forEach(function (id) {
            if (element(id)) element(id).innerHTML = "";
        });
        ["stats-empty-project", "stats-empty-file", "stats-empty-app"].forEach(function (id) {
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
        resumeStatisticsLiveTicker();
    }
    App.invalidateStatisticsSelection = invalidateStatisticsSelection;

    function statisticsGroupKey(group, index) {
        group = group || {};
        var key = String(group.key || "");
        if (key) return key;
        return "display:" + String(group.display_name || "未知") + "|" + String(index || 0);
    }

    function statisticsGroupRecordCount(group) {
        group = group || {};
        var value = group.record_count;
        if (value === undefined || value === null) value = group.session_count;
        if (value === undefined || value === null) value = group.activity_count;
        var parsed = parseInt(value, 10);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
    }
    App.statisticsGroupRecordCount = statisticsGroupRecordCount;

    function statisticsConcreteFileCount(groups) {
        return (Array.isArray(groups) ? groups : []).filter(function (group) {
            return String(group && group.key || "") !== "file:excluded";
        }).length;
    }
    App.statisticsConcreteFileCount = statisticsConcreteFileCount;

    function patchStatsTable(tbodyId, groups) {
        var body = element(tbodyId);
        if (!body || typeof body.querySelectorAll !== "function") return false;
        var rows = body.querySelectorAll("tr");
        groups = Array.isArray(groups) ? groups : [];
        if (rows.length !== groups.length) return false;
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var group = groups[i] || {};
            var expectedKey = statisticsGroupKey(group, i);
            if (typeof row.getAttribute === "function"
                && String(row.getAttribute("data-statistics-key") || "") !== expectedKey) {
                return false;
            }
            var cells = row.children;
            if (!cells || cells.length < 4) return false;
            var displayName = String(group.display_name || "未知");
            var duration = group.duration || App.formatDuration(group.duration_seconds || 0);
            var recordCount = String(statisticsGroupRecordCount(group));
            var percentage = Math.max(0, Math.min(100, parseFloat(group.percentage) || 0));
            var percentageText = String(group.percentage || 0) + "%";
            if (cells[0].title !== displayName) cells[0].title = displayName;
            var name = typeof row.querySelector === "function"
                ? row.querySelector(".stats-name > span")
                : null;
            if (name && name.textContent !== displayName) name.textContent = displayName;
            if (cells[1].textContent !== duration) cells[1].textContent = duration;
            if (cells[2].textContent !== recordCount) cells[2].textContent = recordCount;
            if (cells[3].textContent !== percentageText) cells[3].textContent = percentageText;
            var bar = typeof row.querySelector === "function"
                ? row.querySelector(".stats-share-bar i")
                : null;
            if (bar && bar.style) bar.style.width = percentage + "%";
        }
        return true;
    }
    App.patchStatsTable = patchStatsTable;

    function reconcileStatsTable(tbodyId, emptyId, groups) {
        groups = Array.isArray(groups) ? groups : [];
        if (!patchStatsTable(tbodyId, groups)) {
            renderStatsTable(tbodyId, emptyId, groups);
            return;
        }
        var empty = element(emptyId);
        if (empty) empty.hidden = groups.length > 0;
    }

    function renderStatisticsMetrics(summary) {
        var byFile = Array.isArray(summary && summary.by_file) ? summary.by_file : [];
        if (element("stats-total")) {
            element("stats-total").textContent = summary.total_duration || "00:00:00";
        }
        if (element("stats-activity-count")) {
            element("stats-activity-count").textContent = String(summary.session_count || 0);
        }
        if (element("stats-project-count")) {
            element("stats-project-count").textContent = String(summary.project_count || 0);
        }
        if (element("stats-file-count")) {
            element("stats-file-count").textContent = String(statisticsConcreteFileCount(byFile));
        }
        if (element("stats-app-count")) {
            element("stats-app-count").textContent = String(summary.app_count || 0);
        }
    }
    App.renderStatisticsMetrics = renderStatisticsMetrics;

    function reconcileStatisticsPresentation(summary) {
        renderStatisticsMetrics(summary);
        reconcileStatsTable("stats-by-project", "stats-empty-project", summary.by_project || []);
        reconcileStatsTable("stats-by-file", "stats-empty-file", summary.by_file || []);
        reconcileStatsTable("stats-by-app", "stats-empty-app", summary.by_app || []);
        if (element("statistics-results")) element("statistics-results").hidden = false;
    }
    App.reconcileStatisticsPresentation = reconcileStatisticsPresentation;

    function executeStatisticsQuery(owner) {
        var filters = owner.filters;
        var token = owner.token;
        var accepted = false;
        var request = App.bridge.getStatisticsExportSummary(
            filters.dateFrom, filters.dateTo, filters.projectId
        );
        var pending = request.then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            var data = App.handleResult(
                result,
                owner.preservePresentation === true ? function () {} : showStatisticsError
            );
            if (!data || !data.summary || !data.export_ticket) {
                if (owner.preservePresentation === true) {
                    throw new Error("statistics_background_refresh_failed");
                }
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
            if (owner.preservePresentation === true && App.statisticsLoaded === true) {
                reconcileStatisticsPresentation(data.summary);
            } else {
                showStatistics(data.summary);
            }
            App.statisticsLoaded = true;
            accepted = true;
            resumeStatisticsLiveTicker();
            App.clearStatisticsError();
            if (typeof App.markPageFresh === "function") App.markPageFresh("statistics");
            return data;
        }).catch(function (error) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            if (owner.preservePresentation === true) throw error;
            showStatisticsError("加载统计失败");
            return null;
        }).finally(function () {
            if (!App.requestCoordinator.isCurrent(token)) return;
            if (owner.preservePresentation !== true) setStatisticsLoading(false);
            if (accepted && owner.preservePresentation === true) {
                var button = element("stats-export-action-btn");
                if (button) button.disabled = !!App.statisticsExportSaving
                    || !App.statisticsAcceptedPayload;
            }
        });
        App.statisticsLoadPromise = pending;
        return pending;
    }

    function beginStatisticsQuery(delay, options) {
        options = options || {};
        var preservePresentation = options.preservePresentation === true
            && App.statisticsLoaded === true
            && !!App.statisticsAcceptedPayload;
        if (preservePresentation && App.statisticsLoading === true) {
            return App.statisticsLoadPromise || Promise.resolve(null);
        }
        if (App.statisticsQueryTimer) window.clearTimeout(App.statisticsQueryTimer);
        App.statisticsQueryTimer = null;
        if (!preservePresentation && typeof App.clearScheduledAutomaticPageRefresh === "function") {
            App.clearScheduledAutomaticPageRefresh();
        }
        var filters = selectedFilters();
        var key = JSON.stringify(filters);
        var token = App.requestCoordinator.beginLatest("statistics", key);
        if (!preservePresentation) {
            invalidateStatisticsSelection();
            App.clearStatisticsError();
        }
        if (!preservePresentation) setStatisticsLoading(true);
        if (!filters.allTime) {
            var message = validateStatisticsDateRange(filters.dateFrom, filters.dateTo);
            if (message) {
                if (preservePresentation) return Promise.reject(new Error("statistics_background_scope_invalid"));
                showStatisticsError(message);
                setStatisticsLoading(false);
                return Promise.resolve(null);
            }
        }
        var owner = {
            filters: filters,
            token: token,
            preservePresentation: preservePresentation
        };
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

    function loadStatisticsExportSummary(options) {
        return beginStatisticsQuery(0, options);
    }
    App.loadStatisticsExportSummary = loadStatisticsExportSummary;

    function showStatistics(summary) {
        renderStatisticsMetrics(summary);
        renderStatsTable("stats-by-project", "stats-empty-project", summary.by_project || []);
        renderStatsTable("stats-by-file", "stats-empty-file", summary.by_file || []);
        renderStatsTable("stats-by-app", "stats-empty-app", summary.by_app || []);
        if (element("statistics-results")) element("statistics-results").hidden = false;
    }
    App.showStatistics = showStatistics;

    function renderStatsTable(tbodyId, emptyId, groups) {
        var body = element(tbodyId);
        var empty = element(emptyId);
        groups = Array.isArray(groups) ? groups : [];
        if (!groups.length) { body.innerHTML = ""; empty.hidden = false; return; }
        empty.hidden = true;
        body.innerHTML = groups.map(function (group, index) {
            var percentage = Math.max(0, Math.min(100, parseFloat(group.percentage) || 0));
            return '<tr data-statistics-key="' + App.escapeHtml(statisticsGroupKey(group, index))
                + '"><td title="' + App.escapeHtml(group.display_name || "未知") + '"><div class="stats-name">'
                + '<span>' + App.escapeHtml(group.display_name || "未知") + '</span>'
                + '<span class="stats-share-bar" aria-hidden="true"><i style="width:' + percentage + '%"></i></span>'
                + '</div></td><td class="number">'
                + App.escapeHtml(group.duration || App.formatDuration(group.duration_seconds || 0))
                + '</td><td class="number">' + App.escapeHtml(String(statisticsGroupRecordCount(group)))
                + '</td><td class="number">' + App.escapeHtml(String(group.percentage || 0)) + '%</td></tr>';
        }).join("");
    }
    App.renderStatsTable = renderStatsTable;

    var statisticsTabs = {
        project: { tab: "stats-project-tab", panel: "stats-project-panel" },
        file: { tab: "stats-file-tab", panel: "stats-file-panel" },
        app: { tab: "stats-app-tab", panel: "stats-app-panel" }
    };
    var statisticsTabOrder = ["project", "file", "app"];

    function activateStatisticsTab(view) {
        Object.keys(statisticsTabs).forEach(function (name) {
            var descriptor = statisticsTabs[name];
            var selected = name === view;
            var tab = element(descriptor.tab);
            tab.setAttribute("aria-selected", selected ? "true" : "false");
            tab.tabIndex = selected ? 0 : -1;
            element(descriptor.panel).hidden = !selected;
        });
    }
    App.activateStatisticsTab = activateStatisticsTab;

    function handleStatisticsTabKeydown(event, view) {
        var key = event && event.key;
        if (["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(key) < 0) return;
        if (event.preventDefault) event.preventDefault();
        var index = statisticsTabOrder.indexOf(view);
        if (key === "Home") index = 0;
        else if (key === "End") index = statisticsTabOrder.length - 1;
        else if (key === "ArrowRight") index = (index + 1) % statisticsTabOrder.length;
        else index = (index + statisticsTabOrder.length - 1) % statisticsTabOrder.length;
        var targetView = statisticsTabOrder[index];
        activateStatisticsTab(targetView);
        var target = element(statisticsTabs[targetView].tab);
        if (target && target.focus) target.focus();
    }
    App.handleStatisticsTabKeydown = handleStatisticsTabKeydown;

    function applyStatisticsQuickRange(type) {
        var today = new Date();
        var range = shortcutRange(type, today);
        if (!range) return Promise.resolve(null);
        setStatisticsSelection(type === "all", range.dateFrom, range.dateTo);
        return beginStatisticsQuery(0);
    }
    App.applyStatisticsQuickRange = applyStatisticsQuickRange;

    function handleStatisticsDraftDateChange() {
        var from = element("statistics-date-from");
        var to = element("statistics-date-to");
        App.statisticsDraftSelection = {
            allTime: false,
            dateFrom: from ? String(from.value || "") : "",
            dateTo: to ? String(to.value || "") : ""
        };
        App.statisticsDraftDirty = !statisticsSelectionsEqual(
            App.statisticsDraftSelection,
            currentSelection()
        );
        syncStatisticsDraftSelection();
    }
    App.handleStatisticsDraftDateChange = handleStatisticsDraftDateChange;

    function applyStatisticsDraftSelection() {
        var draft = currentDraftSelection();
        if (draft.allTime) {
            setStatisticsSelection(true, "", "");
            return beginStatisticsQuery(0);
        }
        var message = validateStatisticsDateRange(draft.dateFrom, draft.dateTo);
        if (message) {
            setStatisticsDraftStatus(message, true);
            return Promise.resolve(null);
        }
        setStatisticsSelection(false, draft.dateFrom, draft.dateTo);
        return beginStatisticsQuery(0);
    }
    App.applyStatisticsDraftSelection = applyStatisticsDraftSelection;

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

    function loadStatisticsProjectCatalog() {
        if (!App.projectCatalog) return Promise.resolve(null);
        return App.projectCatalog.load().then(function (catalog) {
            if (!catalog) return null;
            populateProjectFilter(catalog.filterProjects);
            return catalog;
        });
    }
    App.loadStatisticsProjectCatalog = loadStatisticsProjectCatalog;

    function initStatisticsDefaults() {
        currentSelection();
        syncStatisticsSelection();
        syncStatisticsDraftSelection();
        activateStatisticsTab("project");
        if (!App.statisticsControlsBound) {
            App.statisticsControlsBound = true;
            ["statistics-date-from", "statistics-date-to"].forEach(function (id) {
                var input = element(id);
                input.addEventListener("input", handleStatisticsDraftDateChange);
                input.addEventListener("change", handleStatisticsDraftDateChange);
            });
            element("statistics-project-filter").addEventListener("change", function () {
                syncStatisticsSelection();
                scheduleStatisticsQuery(0);
            });
            Object.keys(statisticsTabs).forEach(function (view) {
                var tab = element(statisticsTabs[view].tab);
                tab.addEventListener("click", function () {
                    activateStatisticsTab(view);
                });
                tab.addEventListener("keydown", function (event) {
                    handleStatisticsTabKeydown(event, view);
                });
            });
            loadStatisticsProjectCatalog();
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

    function resetStatisticsTransientUi() {
        if (App.statisticsQueryTimer) window.clearTimeout(App.statisticsQueryTimer);
        App.statisticsQueryTimer = null;
        setStatisticsExportStatus("", "");
        App.statisticsDraftSelection = cloneStatisticsSelection(
            App.statisticsSelection || currentSelection()
        );
        App.statisticsDraftDirty = false;
        syncStatisticsDraftSelection();
    }
    App.resetStatisticsTransientUi = resetStatisticsTransientUi;

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

    function resetStatisticsGeneration() {
        App.statisticsLoaded = false;
        App.statisticsAcceptedPayload = null;
        App.statisticsSnapshotRevision = "";
        App.statisticsSelection = null;
        App.statisticsDraftSelection = null;
        App.statisticsDraftDirty = false;
        App.statisticsSelectionInitialized = false;
        App.statisticsRequestToken = (App.statisticsRequestToken || 0) + 1;
        App.statisticsLiveTickerSuspended = false;
        App.statisticsLastLiveRenderKey = "";
        if (App.statisticsQueryTimer) window.clearTimeout(App.statisticsQueryTimer);
        App.statisticsQueryTimer = null;
        clearStatisticsPresentation();
        setStatisticsLoading(false);
        setStatisticsExportStatus("", "");
    }
    App.statistics = Object.freeze({
        applyLocalTick: function () {
            if (typeof App.applyStatisticsLocalTicker === "function") {
                return App.applyStatisticsLocalTicker();
            }
        },
        resetGeneration: resetStatisticsGeneration
    });
})();
