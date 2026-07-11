(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function absoluteDate(value) {
        if (!value || value === "--") return null;
        return String(value);
    }

    function nextTimelineOwner(date) {
        App.timelineEpoch = (App.timelineEpoch || 0) + 1;
        return {
            timelineEpoch: App.timelineEpoch,
            absoluteReportDate: absoluteDate(date)
        };
    }

    function nextSelectionOwner(date, projectionInstanceKey, projectionRevision) {
        App.selectionEpoch = (App.selectionEpoch || 0) + 1;
        App.detailsOwner = {
            timelineEpoch: App.timelineEpoch || 0,
            selectionEpoch: App.selectionEpoch,
            absoluteReportDate: absoluteDate(date),
            projectionInstanceKey: projectionInstanceKey || "",
            projectionRevision: projectionRevision || ""
        };
        return App.detailsOwner;
    }

    function isCurrentDetailsOwner(owner) {
        return !!owner
            && App.detailsOwner === owner
            && owner.timelineEpoch === (App.timelineEpoch || 0)
            && owner.selectionEpoch === (App.selectionEpoch || 0)
            && owner.absoluteReportDate === absoluteDate(App.timelineDate)
            && owner.projectionInstanceKey === App.selectedProjectionInstanceKey
            && owner.projectionRevision === (App.selectedSessionDetailRevision || "");
    }

    function detailRequestKey(owner) {
        return [
            owner.absoluteReportDate || "",
            owner.projectionInstanceKey || "",
            owner.projectionRevision || "",
            String(owner.timelineEpoch || 0),
            String(owner.selectionEpoch || 0)
        ].join("|");
    }

    App.timelineEpoch = App.timelineEpoch || 0;
    App.selectionEpoch = App.selectionEpoch || 0;
    App.detailsOwner = App.detailsOwner || null;
    App.timelineRequestState = {
        absoluteDate: absoluteDate,
        detailRequestKey: detailRequestKey,
        isCurrentDetailsOwner: isCurrentDetailsOwner,
        nextSelectionOwner: nextSelectionOwner,
        nextTimelineOwner: nextTimelineOwner
    };
})();
