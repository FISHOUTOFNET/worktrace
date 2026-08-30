// WorkTrace WebView frontend — timeline presentation owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function exactRowClock(row, semantic, reason) {
        var source = row && row.live_clock;
        if (source === null || source === undefined) return null;
        var clock = App.validateLiveClock(source);
        if (!clock || (clock.is_live === true && clock.duration_semantic !== semantic)) {
            App.recordLiveClockContractViolation(
                clock ? clock.display_span_id : "",
                "timeline",
                reason,
                2
            );
            return null;
        }
        return clock;
    }

    function projectedClock(clock, durableSeconds) {
        var durable = Math.max(0, parseInt(durableSeconds, 10) || 0);
        if (!clock || clock.is_live !== true) {
            return { seconds: durable, canTick: false };
        }
        var projected = App.projectLiveClockDurationNow(clock, Date.now());
        return {
            seconds: projected === null ? durable : projected,
            canTick: projected !== null
        };
    }

    function clockedSeconds(clock, durableSeconds) {
        return projectedClock(clock, durableSeconds).seconds;
    }

    function formatTimelineStartTime(startTime) {
        var value = String(startTime || "");
        var exact = value.length >= 19 ? value.slice(11, 19) : value.slice(0, 8);
        return exact.slice(0, 5);
    }
    App.formatTimelineStartTime = formatTimelineStartTime;

    function formatTimelineDuration(seconds) {
        return App.formatDuration(seconds);
    }
    App.formatTimelineDuration = formatTimelineDuration;

    function renderTimelineTotal(data) {
        var element = document.getElementById("timeline-total");
        var label = document.getElementById("timeline-total-label");
        if (label) {
            label.textContent = String(data.date || "") === String(data.today || "")
                ? "今日总时长"
                : "当日总时长";
        }
        var durable = Math.max(0, parseInt(data.today_total_seconds, 10) || 0);
        var clock = exactRowClock(
            { live_clock: data.total_live_clock },
            "aggregate_live",
            "timeline_total_invalid_live_clock"
        );
        var projection = projectedClock(clock, durable);
        if (projection.canTick) {
            App.setLiveClockTarget(element, clock, "timeline-total", "timeline-total");
        } else {
            App.clearLiveClockTarget(element);
        }
        App.renderDurationProjected(
            element,
            projection.seconds,
            "timeline-total"
        );
    }
    App.renderTimelineTotal = renderTimelineTotal;

    function timelineSessionOrder(left, right) {
        var byStart = String(right.start_time || "")
            .localeCompare(String(left.start_time || ""));
        if (byStart !== 0) return byStart;
        return String(right.projection_instance_key || "")
            .localeCompare(String(left.projection_instance_key || ""));
    }

    function timelineProjectScope(session) {
        session = session || {};
        var rowKind = String(session.row_kind || "");
        if (
            session.privacy_redacted === true
            || rowKind === "standalone_status"
            || rowKind === "status_only"
        ) return "status";
        if (session.project_is_deleted === true) return "other";
        if (rowKind && rowKind !== "project_session") return "other";
        var projectId = parseInt(session.project_id, 10);
        if (session.is_report_project === true && projectId > 0) return "project";
        if (session.is_report_uncategorized === true) return "unclassified";
        return "other";
    }
    App.timelineProjectScope = timelineProjectScope;

    function timelineStatusLabel(session) {
        var status = String(
            session.display_status
            || session.status_summary
            || session.status_code
            || session.status
            || ""
        ).trim();
        var labels = {
            excluded: "已排除",
            idle: "空闲",
            error: "异常",
            paused: "已暂停"
        };
        return labels[status] || status || "状态记录";
    }

    function timelineProjectLabel(session) {
        var scope = timelineProjectScope(session);
        if (scope === "status") return timelineStatusLabel(session || {});
        if (scope === "unclassified") return "未归类";
        if (scope === "project") {
            return App.formatProjectLabel(
                session.project_name,
                session.project_description
            );
        }
        var name = String((session && session.project_name) || "").trim();
        return name && name !== "未归类" ? name : "其他记录";
    }
    App.timelineProjectLabel = timelineProjectLabel;

    function filteredTimelineSessions(entries) {
        var filter = document.getElementById("timeline-project-filter");
        var value = filter ? String(filter.value || "") : "";
        var filtered = (Array.isArray(entries) ? entries : []).filter(function (session) {
            if (!value) return true;
            if (value === "unclassified") {
                return timelineProjectScope(session) === "unclassified";
            }
            return timelineProjectScope(session) === "project"
                && String(session.project_id || "") === value;
        });
        return filtered.slice().sort(timelineSessionOrder);
    }
    App.filteredTimelineSessions = filteredTimelineSessions;

    function renderTimelineProjectFilter(projects) {
        var select = document.getElementById("timeline-project-filter");
        if (!select) return;
        var previous = select.value;
        var html = '<option value="">全部项目</option><option value="unclassified">未归类</option>';
        (projects || []).forEach(function (project) {
            html += '<option value="' + App.escapeHtml(String(project.id || "")) + '">'
                + App.escapeHtml(project.name || "未命名项目") + '</option>';
        });
        select.innerHTML = html;
        select.value = previous;
        if (select.value !== previous) select.value = "";
    }
    App.renderTimelineProjectFilter = renderTimelineProjectFilter;

    function renderSessionDetails(data) {
        if (App.timeline && App.timeline.isEditingActive()) return;
        if (App.lastTimelineData) {
            App.lastTimelineData.current_activity = data.current_activity
                || App.lastTimelineData.current_activity
                || {};
        }
        App.lastSessionDetailsViewModel = data;
        App.lastSessionActivitySummaryViewModel = data;
        var header = document.getElementById("timeline-details-header");
        var list = document.getElementById("timeline-details-list");
        var rows = Array.isArray(data.summary_rows) ? data.summary_rows : [];
        if (rows.length === 0) {
            header.textContent = "活动详情";
            list.innerHTML = '<div class="timeline-empty">该时段暂无活动详情</div>';
            return;
        }
        header.textContent = "活动详情";
        var html = "";
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var clock = exactRowClock(
                row,
                "aggregate_live",
                "timeline_detail_invalid_live_clock"
            );
            var durable = Math.max(0, parseInt(row.duration_seconds, 10) || 0);
            var projection = projectedClock(clock, durable);
            var canTick = projection.canTick;
            var seconds = projection.seconds;
            var continuityKey = canTick
                ? App.liveContinuityKey(row, "project-summary")
                : "";
            var classes = "summary-item";
            if (row.is_in_progress) classes += " in-progress";
            if (canTick) classes += " live-projected";
            var attributes = canTick
                ? App.liveClockDataAttributes(clock, continuityKey, "timeline-detail")
                : "";
            var displayName = row.activity_name || "未知";
            var projectLabel = row.display_project_name || "未归类";
            html += '<div class="' + classes + '" data-summary-id="'
                + App.escapeHtml(String(row.summary_id || ""))
                + '" data-summary-index="' + i + '">'
                + '<div class="summary-item-duration"' + attributes
                + ' data-duration-seconds="' + String(seconds) + '">'
                + App.escapeHtml(App.formatDuration(seconds)) + '</div>'
                + '<div class="summary-item-name" title="' + App.escapeHtml(displayName) + '">'
                + App.escapeHtml(displayName) + '</div>'
                + '<div class="summary-item-project" title="' + App.escapeHtml(projectLabel) + '">'
                + App.escapeHtml(projectLabel) + '</div>'
                + (row.can_hide_activity || row.can_delete
                    ? '<button type="button" class="summary-hide-activity compact-icon-button danger-icon-button" data-summary-id="'
                        + App.escapeHtml(String(row.summary_id || ""))
                        + '" aria-label="删除活动" data-tooltip="删除活动">'
                        + App.iconMarkup("trash") + '</button>'
                    : '')
                + '</div>';
        }
        list.innerHTML = html;
        if (!list._detailsDelegationBound) {
            list.addEventListener("click", function (event) {
                var btn = event.target.closest(".summary-hide-activity");
                if (!btn) return;
                event.stopPropagation();
                App.confirmTimelineDeletion("hideActivity", {
                    summaryId: btn.getAttribute("data-summary-id")
                }, btn);
            });
            list._detailsDelegationBound = true;
        }
    }
    App.renderSessionDetails = renderSessionDetails;
    App.renderSessionActivitySummary = renderSessionDetails;

    App.timelinePresentation = Object.freeze({
        exactRowClock: exactRowClock,
        clockedSeconds: clockedSeconds
    });
})();
