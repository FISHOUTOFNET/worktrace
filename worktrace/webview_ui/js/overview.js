// WorkTrace WebView frontend — Overview projection and Timeline handoff.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function aggregateLiveProjection(clock, durableSeconds, enabled) {
        var raw = Number(durableSeconds);
        var durable = Number.isFinite(raw) ? Math.max(0, raw) : 0;
        if (enabled === false
            || !clock
            || clock.is_live !== true
            || clock.duration_semantic !== "aggregate_live") {
            return { seconds: durable, canTick: false };
        }
        if (typeof App.projectLiveClockDurationNow !== "function") {
            // The runtime coordinator is installed later in the shipping script
            // order. Preserve source live metadata without projecting any new
            // seconds until that authority exists.
            return { seconds: durable, canTick: true };
        }
        var projected = App.projectLiveClockDurationNow(clock, Date.now());
        return {
            seconds: projected === null ? durable : projected,
            canTick: projected !== null
        };
    }

    function renderKpi(element, durableSeconds, target, continuityKey) {
        var clock = target && App.validateLiveClock(target.live_clock);
        var projection = aggregateLiveProjection(
            clock,
            durableSeconds,
            !!(target && target.enabled === true)
        );
        if (projection.canTick) App.setLiveClockTarget(element, clock, continuityKey, continuityKey);
        else App.clearLiveClockTarget(element);
        App.renderDurationProjected(element, projection.seconds || 0, continuityKey);
    }

    function kpiLiveTarget(bundle, field) {
        var targets = bundle && bundle.kpi_live_targets;
        var target = targets && targets[field];
        return target && typeof target === "object" ? target : null;
    }

    function durationMarkup(item, role) {
        var clock = App.validateLiveClock(item && item.live_clock);
        var durable = Math.max(0, parseInt(item && item.duration_seconds, 10) || 0);
        var projection = aggregateLiveProjection(clock, durable, true);
        var continuity = projection.canTick ? App.liveContinuityKey(item, role) : "";
        var attributes = projection.canTick
            ? App.liveClockDataAttributes(clock, continuity, role)
            : "";
        return '<strong class="numeric recent-duration"' + attributes
            + ' data-duration-seconds="' + String(projection.seconds || 0) + '">'
            + App.escapeHtml(App.formatDuration(projection.seconds || 0)) + '</strong>';
    }

    function descriptionClass(item, base) {
        return base + (item && item.description_source === "derived" ? " derived" : "");
    }

    function renderProjectDistribution(distribution) {
        var bar = document.getElementById("overview-project-bar");
        var segments = distribution && Array.isArray(distribution.segments)
            ? distribution.segments.slice(0, 4)
            : [];
        bar.setAttribute("aria-label", "今日总时长分解");
        if (!segments.length) {
            bar.innerHTML = "";
            bar.hidden = true;
            return;
        }

        bar.hidden = false;
        bar.innerHTML = segments.map(function (segment, index) {
            var clock = App.validateLiveClock(segment && segment.live_clock);
            var rawSeconds = Number(segment.duration_seconds);
            var durableSeconds = Number.isFinite(rawSeconds) ? Math.max(0, rawSeconds) : 0;
            var projection = aggregateLiveProjection(clock, durableSeconds, true);
            var seconds = projection.seconds;
            var grow = Math.max(1, Math.round(seconds));
            var label = String(segment.label || "");
            var hours = App.formatCompactHours(seconds);
            var exactDuration = App.formatDuration(seconds);
            var className = segment.is_other
                ? "is-other"
                : segment.is_uncategorized
                    ? "is-uncategorized"
                    : "rank-" + String(index + 1);
            var accessibleText = label + "，" + exactDuration;
            var continuity = projection.canTick
                ? App.liveContinuityKey(
                    segment,
                    "overview-project-" + String(segment.key || index)
                )
                : "";
            var durationAttributes = projection.canTick
                ? App.liveClockDataAttributes(
                    clock,
                    continuity,
                    "overview-project-distribution"
                )
                : "";
            return '<div class="overview-project-segment ' + className
                + '" style="flex-grow: ' + String(grow)
                + '" role="listitem" title="' + App.escapeHtml(label + " · " + exactDuration)
                + '" aria-label="' + App.escapeHtml(accessibleText) + '">'
                + '<span class="overview-project-name">' + App.escapeHtml(label) + '</span>'
                + '<span class="overview-project-hours"' + durationAttributes
                + ' data-duration-format="compact-hours" data-duration-seconds="'
                + String(seconds || 0) + '">' + App.escapeHtml(hours) + '</span>'
                + '</div>';
        }).join("");
    }

    function timelineIntent(item, focusTarget) {
        if (!item || !item.projection_instance_key) return;
        if (typeof App.openTimelineSelectionIntent === "function") {
            return App.openTimelineSelectionIntent(item, focusTarget || "");
        }
        var date = String(item.start_time || item.report_date || App.timelineDate || "").slice(0, 10);
        if (!date) return;
        App.pendingTimelineSelectionIntent = {
            date: date,
            projectionInstanceKey: item.projection_instance_key,
            focusTarget: focusTarget || ""
        };
        App.timelineDate = date;
        App.switchPage("timeline");
        return App.loadTimelineReport(date, {
            showLoading: true,
            resetSelection: false
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
            list.innerHTML = '<div class="empty-state"><strong>暂无最近记录</strong>'
                + '<span>形成可报告的时间段后会显示在这里。</span></div>';
            return;
        }
        list.innerHTML = items.map(function (item, index) {
            return '<button type="button" class="recent-row" data-recent-index="' + index + '">'
                + '<span class="recent-start-time numeric">'
                + App.escapeHtml(App.formatStartTimeOnly(item.start_time)) + '</span>'
                + '<span class="recent-main"><span class="recent-title-line">'
                + '<span class="recent-project" title="'
                + App.escapeHtml(App.formatProjectLabel(item.project_name, item.project_description))
                + '">' + App.escapeHtml(item.project_name || "未归类") + '</span></span>'
                + '<span class="' + descriptionClass(item, "recent-description") + '">'
                + App.escapeHtml(item.display_description || "暂无描述") + '</span></span>'
                + durationMarkup(item, "overview-recent") + '</button>';
        }).join("");
        bindIntentButtons(list, items, "data-recent-index");
    }

    function currentRuntimeIdentity() {
        var store = App.liveRuntimeStore;
        var runtime = store && typeof store.get === "function" ? store.get() : null;
        if (typeof App.runtimeRefreshIdentityForPage === "function") {
            return String(App.runtimeRefreshIdentityForPage("overview", runtime) || "");
        }
        return String(runtime && (runtime.pageRevision || runtime.liveRevision) || "");
    }

    function showOverview(bundle) {
        if (!bundle) return;
        App.lastOverviewSnapshot = bundle;
        App.overviewCommittedRuntimeIdentity = currentRuntimeIdentity();
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
        // Navigation requires a normal active state plus a stable current_session;
        // paused/idle/excluded/error must not show a clickable card even with a
        // stale backend current_session.
        var currentButton = document.getElementById("current-activity");
        var currentActivity = bundle.current_activity || {};
        var currentSession = bundle.current_session;
        var statusAllowsNavigation =
            currentActivity.active !== false
            && String(currentActivity.status || "") === "normal";
        var canNavigate = !!(statusAllowsNavigation
            && currentSession
            && currentSession.projection_instance_key
            && currentSession.start_time);
        currentButton.disabled = !canNavigate;
        currentButton.onclick = canNavigate
            ? function () { timelineIntent(currentSession, ""); }
            : null;
        renderProjectDistribution(bundle.project_distribution);
        renderRecent(bundle.recent);
    }
    App.showOverview = showOverview;

    App.showRecent = function (payload) {
        renderRecent((payload && payload.recent) || []);
    };

    function refreshOverview() {
        var token = App.requestCoordinator.beginLatest("overview", "today");
        return App.bridge.getOverview().then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return;
            var bundle = App.handleResult(result, function (msg) { throw new Error(msg); });
            if (!bundle || !App.acceptPagePayloadRuntime(bundle, "overview", bundle.date)) return;
            var runtime = App.liveRuntimeStore.get();
            var overview = Object.assign({}, bundle.overview || {});
            overview.date = bundle.date || overview.date;
            overview.current_activity = runtime ? runtime.currentActivity : {};
            overview.current_session = bundle.current_session || null;
            overview.project_distribution = bundle.project_distribution || {
                total_seconds: 0,
                segments: []
            };
            overview.recent = bundle.recent || [];
            overview.kpi_live_targets = bundle.kpi_live_targets || {};
            if (overview.today_total_seconds === undefined) {
                overview.today_total_seconds = bundle.today_total_seconds || 0;
            }
            if (overview.classified_seconds === undefined) {
                overview.classified_seconds = bundle.classified_seconds || 0;
            }
            if (overview.uncategorized_seconds === undefined) {
                overview.uncategorized_seconds = bundle.uncategorized_seconds || 0;
            }
            showOverview(overview);
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) App.showError("刷新失败");
        });
    }
    App.refreshOverview = refreshOverview;

    function updateCurrentActivity(activity, options) {
        if (!options || options.render !== true || App.currentPage !== "overview") return;
        var target = document.getElementById("current-activity");
        if (!target) return;
        App.renderCurrentActivityElement(target, activity || {}, "overview");
        var runtimeIdentity = currentRuntimeIdentity();
        var committedIdentity = String(App.overviewCommittedRuntimeIdentity || "");
        if (runtimeIdentity && committedIdentity && runtimeIdentity !== committedIdentity) {
            target.disabled = true;
            target.onclick = null;
        }
    }

    function onOverviewRefreshRequested() {
        return refreshOverview();
    }

    App.overview = Object.freeze({
        refreshPolicy: Object.freeze({
            entryGenerations: Object.freeze(["report_structure"]),
            automaticGenerations: Object.freeze(["report_structure"]),
            deferred: true
        }),
        hasLoadedData: function () { return !!App.lastOverviewSnapshot; },
        refreshEvidence: function () { return App.lastOverviewSnapshot || null; },
        onPageEntered: onOverviewRefreshRequested,
        onRefreshRequested: onOverviewRefreshRequested,
        runtimeRefreshIdentity: function (runtime) {
            return String(runtime && runtime.pageRevision || "");
        },
        updateCurrentActivity: updateCurrentActivity,
        resetGeneration: function () {
            App.overviewRequestToken = (App.overviewRequestToken || 0) + 1;
            App.overviewCommittedRuntimeIdentity = "";
        }
    });
})();
