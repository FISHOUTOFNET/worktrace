// WorkTrace WebView frontend — Overview projection and Timeline handoff.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function renderKpi(element, durableSeconds, target, continuityKey) {
        var clock = target && App.validateLiveClock(target.live_clock);
        var live = !!(target && target.enabled === true && clock && clock.is_live === true
            && clock.duration_semantic === "aggregate_live");
        var seconds = live
            ? App.computeClockDurationNow(clock, Date.now())
            : Math.max(0, parseInt(durableSeconds, 10) || 0);
        if (live) App.setLiveClockTarget(element, clock, continuityKey, continuityKey);
        else App.clearLiveClockTarget(element);
        App.renderDurationProjected(element, seconds || 0, continuityKey);
    }

    function kpiLiveTarget(bundle, field) {
        var targets = bundle && bundle.kpi_live_targets;
        var target = targets && targets[field];
        return target && typeof target === "object" ? target : null;
    }

    function durationMarkup(item, role) {
        var clock = App.validateLiveClock(item && item.live_clock);
        var canTick = !!(clock && clock.is_live === true
            && clock.duration_semantic === "aggregate_live");
        var durable = Math.max(0, parseInt(item && item.duration_seconds, 10) || 0);
        var seconds = canTick ? App.computeClockDurationNow(clock, Date.now()) : durable;
        var continuity = canTick ? App.liveContinuityKey(item, role) : "";
        var attributes = canTick
            ? App.liveClockDataAttributes(clock, continuity, role)
            : "";
        return '<strong class="numeric recent-duration"' + attributes
            + ' data-duration-seconds="' + String(seconds || 0) + '">'
            + App.escapeHtml(App.formatDuration(seconds || 0)) + '</strong>';
    }

    function descriptionClass(item, base) {
        return base + (item && item.description_source === "derived" ? " derived" : "");
    }

    function timelineIntent(item, focusTarget) {
        if (!item || !item.projection_instance_key) return;
        var date = String(item.start_time || item.report_date || App.timelineDate || "").slice(0, 10);
        if (!date) return;
        App.pendingTimelineSelectionIntent = {
            date: date,
            projectionInstanceKey: item.projection_instance_key,
            focusTarget: focusTarget || ""
        };
        App.timelineDate = date;
        App.switchPage("timeline");
        App.loadTimelineReport(date, {
            showLoading: true,
            resetSelection: false
        }).then(function () {
            var selected = App.findSessionByProjectionKey(item.projection_instance_key);
            if (!selected) return;
            App.selectTimelineSession(item.projection_instance_key, App.currentSessions || []);
            if (typeof App.focusTimelineEditorField === "function") {
                App.focusTimelineEditorField(focusTarget || "");
            }
        });
    }
    App.openOverviewTimelineIntent = timelineIntent;

    function bindIntentButtons(container, items, attribute, focusResolver) {
        var buttons = container.querySelectorAll("[" + attribute + "]");
        for (var index = 0; index < buttons.length; index++) {
            (function (button) {
                button.addEventListener("click", function () {
                    var item = items[parseInt(button.getAttribute(attribute), 10)];
                    timelineIntent(item, focusResolver ? focusResolver(item) : "");
                });
            })(buttons[index]);
        }
    }

    function renderRecent(items) {
        var list = document.getElementById("recent-list");
        items = Array.isArray(items) ? items : [];
        if (!items.length) {
            list.innerHTML = '<div class="empty-state"><strong>暂无最近活动</strong>'
                + '<span>已结束且无需整理的时间段会显示在这里。</span></div>';
            return;
        }
        list.innerHTML = items.map(function (item, index) {
            return '<button type="button" class="recent-row" data-recent-index="' + index + '">'
                + '<span class="numeric">' + App.escapeHtml(App.formatStartTimeOnly(item.start_time)) + '</span>'
                + '<span class="recent-main"><span class="recent-project" title="'
                + App.escapeHtml(App.formatProjectLabel(item.project_name, item.project_description))
                + '">' + App.escapeHtml(item.project_name || "未归类") + '</span>'
                + '<span class="' + descriptionClass(item, "recent-description") + '">'
                + App.escapeHtml(item.display_description || "暂无描述") + '</span></span>'
                + durationMarkup(item, "overview-recent") + '</button>';
        }).join("");
        bindIntentButtons(list, items, "data-recent-index");
    }

    function attentionReason(item) {
        if (item.missing_fields === "project_and_description") return "缺少项目和用户描述";
        if (item.missing_fields === "project") return "缺少项目";
        return "缺少用户描述";
    }

    function attentionFocus(item) {
        return item && item.needs_project ? "project" : "description";
    }

    function renderAttention(items, remaining) {
        var list = document.getElementById("overview-attention-list");
        var more = document.getElementById("overview-attention-more");
        items = Array.isArray(items) ? items : [];
        if (!items.length) {
            list.innerHTML = '<div class="empty-compact">今日记录已整理</div>';
            more.hidden = true;
            more.innerHTML = "";
            return;
        }
        list.innerHTML = items.map(function (item, index) {
            return '<div class="attention-item"><div><strong>'
                + App.escapeHtml(App.formatStartTimeOnly(item.start_time) + " · "
                    + (item.needs_project ? "未选择项目" : (item.project_name || "未归类")))
                + '</strong><div class="' + descriptionClass(item, "attention-description") + '">'
                + App.escapeHtml(item.display_description || "暂无描述") + '</div>'
                + '<div class="attention-reason">' + App.escapeHtml(attentionReason(item)) + '</div></div>'
                + '<button type="button" data-attention-index="' + index + '">整理</button></div>';
        }).join("");
        bindIntentButtons(list, items, "data-attention-index", attentionFocus);
        remaining = Math.max(0, parseInt(remaining, 10) || 0);
        more.hidden = remaining === 0;
        more.innerHTML = remaining
            ? '<span>还有 ' + remaining + ' 条待整理记录</span>'
                + '<button type="button" data-attention-more>查看</button>'
            : "";
        var view = more.querySelector("[data-attention-more]");
        if (view) view.addEventListener("click", function () {
            timelineIntent(items[0], attentionFocus(items[0]));
        });
    }

    function showOverview(bundle) {
        if (!bundle) return;
        App.lastOverviewSnapshot = bundle;
        document.getElementById("overview-project-count").textContent = String(
            Math.max(0, parseInt(bundle.project_count, 10) || 0)
        );
        document.getElementById("overview-classified-duration").textContent =
            bundle.classified_duration || App.formatDuration(bundle.classified_seconds || 0);
        document.getElementById("overview-uncategorized-duration").textContent =
            bundle.uncategorized_duration || App.formatDuration(bundle.uncategorized_seconds || 0);
        renderKpi(
            document.getElementById("kpi-total"),
            bundle.today_total_seconds,
            kpiLiveTarget(bundle, "today_total_seconds"),
            "overview-total"
        );
        App.renderCurrentActivityElement(
            document.getElementById("current-activity"),
            bundle.current_activity || {},
            "overview"
        );
        var currentButton = document.getElementById("current-activity");
        currentButton.onclick = bundle.current_session
            ? function () { timelineIntent(bundle.current_session, ""); }
            : null;
        renderAttention(bundle.attention, bundle.attention_remaining_count);
        renderRecent(bundle.recent);
    }
    App.showOverview = showOverview;

    App.showRecent = function (payload) {
        renderRecent((payload && (payload.recent || payload.activities)) || []);
    };
})();
