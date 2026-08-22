// WorkTrace frontend — stateless page lifecycle capability boundary.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function extendPage(name, capabilities) {
        var existing = App[name] && typeof App[name] === "object" ? App[name] : {};
        App[name] = Object.freeze(Object.assign({}, existing, capabilities));
    }

    extendPage("overview", {
        hasLoadedData: function () {
            return !!App.lastOverviewSnapshot;
        },
        refreshEvidence: function () {
            return App.lastOverviewSnapshot || null;
        },
        updateCurrentActivity: function (activity) {
            if (!App.lastOverviewSnapshot) App.lastOverviewSnapshot = {};
            App.lastOverviewSnapshot.current_activity = activity || {};
        }
    });

    extendPage("timeline", {
        hasLoadedData: function () {
            if (App.timelineLoaded !== true || !App.lastTimelineData) return false;
            var requestedDate = String(App.timelineDate || "");
            var loadedDate = String(App.lastTimelineData.date || "");
            return !requestedDate || requestedDate === loadedDate;
        },
        isLoading: function () {
            return App.timelineLoading === true;
        },
        refreshEvidence: function () {
            return App.lastTimelineData || null;
        },
        reportDate: function () {
            return App.timelineDate || null;
        },
        isEditing: function () {
            return typeof App._timelineEditingActive === "function"
                && App._timelineEditingActive();
        },
        automaticRefreshAllowed: function (today) {
            return String(App.timelineDate || "") === String(today || "");
        },
        refreshScopeKey: function () {
            return "timeline|" + String(App.timelineDate || "");
        },
        updateCurrentActivity: function (activity) {
            if (!App.lastTimelineData) App.lastTimelineData = {};
            App.lastTimelineData.current_activity = activity || {};
        }
    });

    extendPage("statistics", {
        hasLoadedData: function () {
            return App.statisticsLoaded === true;
        },
        refreshEvidence: function () {
            return App.statisticsAcceptedPayload || null;
        },
        automaticRefreshAllowed: function (today) {
            var selection = App.statisticsSelection;
            if (!selection || selection.allTime === true) return true;
            var from = String(selection.dateFrom || "");
            var to = String(selection.dateTo || "");
            return !!from && !!to && from <= today && to >= today;
        },
        refreshScopeKey: function () {
            var selection = App.statisticsSelection || {};
            var filter = document.getElementById("statistics-project-filter");
            return [
                "statistics",
                selection.allTime === true ? "all" : "range",
                String(selection.dateFrom || ""),
                String(selection.dateTo || ""),
                filter ? String(filter.value || "") : ""
            ].join("|");
        }
    });

    extendPage("rules", {
        hasLoadedData: function () {
            return App.rulesLoaded === true;
        },
        refreshEvidence: function () {
            return App.lastProjectRulesData || null;
        }
    });

    extendPage("settings", {
        hasLoadedData: function () {
            return App.settingsLoaded === true;
        },
        refreshEvidence: function () {
            return App.lastSettingsStatus || null;
        }
    });
})();
