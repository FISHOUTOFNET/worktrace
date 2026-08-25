// Timeline selection continuity across projection refreshes and Overview navigation.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var baseLoadTimelineReport = App.loadTimelineReport;
    var continuityLoadSequence = 0;

    if (typeof baseLoadTimelineReport !== "function") return;

    function projectionKind(value) {
        var explicit = value && typeof value === "object"
            ? String(value.projection_kind || "")
            : "";
        if (explicit) return explicit;
        var key = value && typeof value === "object"
            ? String(value.projection_instance_key || "")
            : String(value || "");
        var separator = key.indexOf(":");
        return separator > 0 ? key.slice(0, separator) : "";
    }

    function selectionAnchorActivityId(session) {
        if (!session) return null;
        var activityIds = Array.isArray(session.activity_ids) ? session.activity_ids : [];
        var candidates = [
            session.anchor_activity_id,
            session.first_activity_id,
            activityIds.length ? activityIds[0] : null
        ];
        for (var index = 0; index < candidates.length; index++) {
            var value = parseInt(candidates[index], 10);
            if (value > 0) return value;
        }
        return null;
    }

    function sessionContainsAnchor(session, anchorActivityId) {
        var anchor = parseInt(anchorActivityId, 10);
        if (!(anchor > 0) || !session) return false;
        var activityIds = Array.isArray(session.activity_ids) ? session.activity_ids : [];
        for (var index = 0; index < activityIds.length; index++) {
            if (parseInt(activityIds[index], 10) === anchor) return true;
        }
        return selectionAnchorActivityId(session) === anchor;
    }

    function resolveCandidate(projectionInstanceKey, anchorActivityId, sessions) {
        var selectedKey = String(projectionInstanceKey || "");
        if (!selectedKey) return null;
        var candidates = Array.isArray(sessions) ? sessions : [];
        var exact = candidates.filter(function (session) {
            return String(session.projection_instance_key || "") === selectedKey;
        });
        if (exact.length === 1) return exact[0];
        if (exact.length > 1 || projectionKind(selectedKey) !== "base") return null;
        var anchor = parseInt(anchorActivityId, 10);
        if (!(anchor > 0)) return null;
        var anchored = candidates.filter(function (session) {
            return projectionKind(session) === "base"
                && sessionContainsAnchor(session, anchor);
        });
        return anchored.length === 1 ? anchored[0] : null;
    }
    App.resolveTimelineSelectionContinuity = resolveCandidate;

    function currentReportDate() {
        return String(
            App.timelineDate
            || (App.lastTimelineData && App.lastTimelineData.date)
            || ""
        ).slice(0, 10);
    }

    function filteredContains(session) {
        if (!session || typeof App.filteredTimelineSessions !== "function") return false;
        var key = String(session.projection_instance_key || "");
        return App.filteredTimelineSessions(App.currentSessions || []).some(function (candidate) {
            return String(candidate.projection_instance_key || "") === key;
        });
    }

    function setSelectionIdentity(session, anchorActivityId) {
        if (!session) return;
        App.selectedProjectionInstanceKey = String(session.projection_instance_key || "") || null;
        App.selectedProjectionRevision = String(session.projection_revision || "");
        App.selectedTimelineAnchorActivityId = parseInt(anchorActivityId, 10) > 0
            ? parseInt(anchorActivityId, 10)
            : selectionAnchorActivityId(session);
        App.selectedTimelineWasInProgress = session.is_in_progress === true;
    }

    function captureSelection() {
        var key = String(App.selectedProjectionInstanceKey || "");
        var anchor = parseInt(App.selectedTimelineAnchorActivityId, 10);
        if (!key || !(anchor > 0)) return null;
        return {
            date: currentReportDate(),
            dataEpoch: App.dataEpoch || 0,
            projectionInstanceKey: key,
            anchorActivityId: anchor
        };
    }

    function restoreSelectionAfterRefresh(captured) {
        if (!captured || App.currentPage !== "timeline") return false;
        if (captured.dataEpoch !== (App.dataEpoch || 0)) return false;
        if (App.selectedProjectionInstanceKey) return false;
        if (captured.date !== currentReportDate()) return false;
        var target = resolveCandidate(
            captured.projectionInstanceKey,
            captured.anchorActivityId,
            App.currentSessions || []
        );
        if (!target || !filteredContains(target)) return false;
        setSelectionIdentity(target, captured.anchorActivityId);
        if (App.lastTimelineData && typeof App.showTimeline === "function") {
            App.showTimeline(App.lastTimelineData);
            if (sessionContainsAnchor(target, captured.anchorActivityId)) {
                App.selectedTimelineAnchorActivityId = captured.anchorActivityId;
            }
        }
        return true;
    }

    function clearPendingIntent() {
        App.pendingTimelineSelectionIntent = null;
    }

    function consumePendingIntent() {
        var intent = App.pendingTimelineSelectionIntent;
        if (!intent || App.currentPage !== "timeline") return false;
        if (intent.dataEpoch !== undefined
                && intent.dataEpoch !== (App.dataEpoch || 0)) {
            clearPendingIntent();
            return false;
        }
        if (String(intent.date || "").slice(0, 10) !== currentReportDate()) {
            clearPendingIntent();
            return false;
        }
        var target = resolveCandidate(
            intent.projectionInstanceKey,
            intent.anchorActivityId,
            App.currentSessions || []
        );
        if (!target) {
            clearPendingIntent();
            if (typeof App.resetTimelineReportSelection === "function") {
                App.resetTimelineReportSelection();
            }
            return false;
        }
        if (!filteredContains(target)) {
            var filter = document.getElementById("timeline-project-filter");
            if (filter) filter.value = "";
            if (App.lastTimelineData && typeof App.showTimeline === "function") {
                App.showTimeline(App.lastTimelineData);
            }
        }
        if (typeof App.selectTimelineSession !== "function") {
            clearPendingIntent();
            return false;
        }
        App.selectTimelineSession(target.projection_instance_key, App.currentSessions || []);
        if (App.selectedProjectionInstanceKey !== target.projection_instance_key) return false;
        if (sessionContainsAnchor(target, intent.anchorActivityId)) {
            App.selectedTimelineAnchorActivityId = parseInt(intent.anchorActivityId, 10);
        }
        clearPendingIntent();
        if (intent.focusTarget && typeof App.focusTimelineEditorField === "function") {
            App.focusTimelineEditorField(intent.focusTarget);
        }
        return true;
    }
    App.consumePendingTimelineSelectionIntent = consumePendingIntent;

    App.loadTimelineReport = function (date, options) {
        var sequence = ++continuityLoadSequence;
        var beforeData = App.lastTimelineData;
        var captured = captureSelection();
        return Promise.resolve(baseLoadTimelineReport.call(App, date, options)).then(function (result) {
            if (sequence !== continuityLoadSequence || App.currentPage !== "timeline") return result;
            if (!App.lastTimelineData || App.lastTimelineData === beforeData) return result;
            if (App.pendingTimelineSelectionIntent) consumePendingIntent();
            else restoreSelectionAfterRefresh(captured);
            return result;
        });
    };

    function navigateToTimelineSelection(item, focusTarget) {
        var date = String(
            item.start_time || item.report_date || App.timelineDate || ""
        ).slice(0, 10);
        if (!date) return Promise.resolve(false);
        App.pendingTimelineSelectionIntent = {
            date: date,
            dataEpoch: App.dataEpoch || 0,
            projectionInstanceKey: String(item.projection_instance_key || ""),
            anchorActivityId: selectionAnchorActivityId(item),
            focusTarget: focusTarget || ""
        };
        App.timelineDate = date;
        App.switchPage("timeline");
        if (App.currentPage !== "timeline") {
            clearPendingIntent();
            return Promise.resolve(false);
        }
        var needsRefresh = typeof App.pageNeedsRefresh === "function"
            ? App.pageNeedsRefresh("timeline")
            : !(App.timelineLoaded && App.lastTimelineData);
        if (!needsRefresh && App.lastTimelineData
                && String(App.lastTimelineData.date || "").slice(0, 10) === date) {
            return Promise.resolve(consumePendingIntent());
        }
        var ownerDate = App.timelineOwner
            ? String(App.timelineOwner.absoluteReportDate || "")
            : "";
        if (App.timelineLoading === true && ownerDate === date) {
            return Promise.resolve(true);
        }
        return App.loadTimelineReport(date, {
            showLoading: true,
            resetSelection: false
        }).then(function () { return true; });
    }

    function openTimelineSelectionIntent(item, focusTarget) {
        if (!item || !item.projection_instance_key) return Promise.resolve(false);
        var action = function () {
            return navigateToTimelineSelection(item, focusTarget || "");
        };
        if (App.timeline && typeof App.timeline.isEditingActive === "function"
                && App.timeline.isEditingActive()
                && typeof App.requestTimelineContextChange === "function") {
            return App.requestTimelineContextChange(action, "切换时间段");
        }
        return action();
    }
    App.openTimelineSelectionIntent = openTimelineSelectionIntent;
})();
