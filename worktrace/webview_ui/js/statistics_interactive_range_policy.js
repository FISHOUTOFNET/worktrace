// WorkTrace WebView — bounded interactive Statistics range policy.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var page = document.getElementById("page-statistics");
    var configuredMaxDays = parseInt(
        page ? page.getAttribute("data-max-range-days") : "",
        10
    );
    var maxRangeDays = Number.isFinite(configuredMaxDays) && configuredMaxDays > 0
        ? configuredMaxDays
        : 366;
    var baseValidateDateRange = App.validateStatisticsDateRange;
    var baseApplyQuickRange = App.applyStatisticsQuickRange;
    var baseApplyDraftSelection = App.applyStatisticsDraftSelection;

    function statisticsDateOrdinal(value) {
        var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
        if (!match) return null;
        var year = Number(match[1]);
        var month = Number(match[2]);
        var day = Number(match[3]);
        var epochMs = Date.UTC(year, month - 1, day);
        var resolved = new Date(epochMs);
        if (
            resolved.getUTCFullYear() !== year
            || resolved.getUTCMonth() !== month - 1
            || resolved.getUTCDate() !== day
        ) {
            return null;
        }
        return Math.floor(epochMs / 86400000);
    }

    function validateInteractiveStatisticsDateRange(dateFrom, dateTo) {
        var baseMessage = typeof baseValidateDateRange === "function"
            ? baseValidateDateRange(dateFrom, dateTo)
            : null;
        if (baseMessage) return baseMessage;
        var start = statisticsDateOrdinal(dateFrom);
        var end = statisticsDateOrdinal(dateTo);
        if (start === null || end === null) return "请选择有效日期";
        var rangeDays = end - start + 1;
        if (rangeDays > maxRangeDays) {
            return "单次统计最多支持 " + maxRangeDays + " 天，请缩小日期范围";
        }
        return null;
    }

    function setDraftStatus(message, isError) {
        var status = document.getElementById("statistics-date-status");
        if (status) {
            status.hidden = !message;
            status.textContent = message || "";
            status.className = "statistics-date-status" + (isError ? " error" : "");
        }
        ["statistics-date-from", "statistics-date-to"].forEach(function (id) {
            var input = document.getElementById(id);
            if (input) input.setAttribute("aria-invalid", isError ? "true" : "false");
        });
    }

    function disableAllTimeControl() {
        var button = document.getElementById("statistics-all-btn");
        if (!button) return;
        button.hidden = true;
        button.disabled = true;
        button.setAttribute("aria-hidden", "true");
        button.tabIndex = -1;
    }

    App.validateStatisticsDateRange = validateInteractiveStatisticsDateRange;
    App.applyStatisticsQuickRange = function (type, queryDelay) {
        if (type === "all") return Promise.resolve(null);
        return baseApplyQuickRange(type, queryDelay);
    };
    App.applyStatisticsDraftSelection = function () {
        var from = document.getElementById("statistics-date-from");
        var to = document.getElementById("statistics-date-to");
        var message = validateInteractiveStatisticsDateRange(
            from ? String(from.value || "") : "",
            to ? String(to.value || "") : ""
        );
        if (message) {
            setDraftStatus(message, true);
            return Promise.resolve(null);
        }
        return baseApplyDraftSelection();
    };
    App.statisticsInteractiveRangePolicy = Object.freeze({
        maxRangeDays: maxRangeDays,
        validateDateRange: validateInteractiveStatisticsDateRange
    });

    disableAllTimeControl();
})();