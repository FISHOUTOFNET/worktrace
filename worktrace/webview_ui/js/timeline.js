// WorkTrace WebView frontend — timeline, details, edits, and navigation.
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

    function clockedSeconds(clock, durableSeconds) {
        if (!clock || clock.is_live !== true) return durableSeconds;
        var projected = App.computeClockDurationNow(clock, Date.now());
        return projected === null ? durableSeconds : projected;
    }

    function renderTimelineTotal(data) {
        var element = document.getElementById("timeline-total");
        var durable = Math.max(0, parseInt(data.today_total_seconds, 10) || 0);
        var clock = exactRowClock(
            { live_clock: data.total_live_clock },
            "aggregate_live",
            "timeline_total_invalid_live_clock"
        );
        if (clock && clock.is_live === true) {
            App.setLiveClockTarget(element, clock, "timeline-total", "timeline-total");
        } else {
            App.clearLiveClockTarget(element);
        }
        App.renderDurationProjected(
            element,
            clockedSeconds(clock, durable),
            "timeline-total"
        );
    }

    function resetEmptyTimeline() {
        App.lastSessionDetailsViewModel = null;
        App.lastSessionActivitySummaryViewModel = null;
        document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
        document.getElementById("timeline-details-list").innerHTML = "";
        App.selectedProjectionInstanceKey = null;
        App.selectedProjectionRevision = null;
        App.detailsOwner = null;
        clearEditPanel();
    }

    function timelineSessionOrder(left, right) {
        if (!!left.is_in_progress !== !!right.is_in_progress) return left.is_in_progress ? -1 : 1;
        return String(right.start_time || "").localeCompare(String(left.start_time || ""));
    }

    function filteredTimelineSessions(entries) {
        var filter = document.getElementById("timeline-project-filter");
        var value = filter ? String(filter.value || "") : "";
        return (Array.isArray(entries) ? entries.slice() : []).filter(function (session) {
            if (!value) return true;
            if (value === "unclassified") {
                // Use the backend authoritative field instead of
                // ``!project_id`` so standalone, privacy-redacted, and
                // deleted-project rows are excluded.
                return session.is_report_uncategorized === true;
            }
            return String(session.project_id || "") === value;
        }).sort(timelineSessionOrder);
    }

    function renderTimelineProjectFilter(projects) {
        var select = document.getElementById("timeline-project-filter");
        if (!select) return;
        var previous = select.value;
        var html = '<option value="">项目：全部</option><option value="unclassified">未归类</option>';
        (projects || []).forEach(function (project) {
            html += '<option value="' + App.escapeHtml(String(project.id || "")) + '">'
                + App.escapeHtml(project.name || "未命名项目") + '</option>';
        });
        select.innerHTML = html;
        select.value = previous;
        if (select.value !== previous) select.value = "";
    }
    App.renderTimelineProjectFilter = renderTimelineProjectFilter;

    function openTimelineDrawer(focusTarget) {
        if (!window.matchMedia || !window.matchMedia("(max-width: 959px)").matches) return;
        var pane = document.getElementById("timeline-details-pane");
        var backdrop = document.getElementById("timeline-drawer-backdrop");
        if (!pane) return;
        App.timelineDrawerRestoreFocus = document.activeElement;
        pane.classList.add("drawer-open");
        if (backdrop) { backdrop.hidden = false; backdrop.classList.add("open"); }
        var target = focusTarget || document.getElementById("timeline-details-close");
        if (target && target.focus) target.focus();
    }
    App.openTimelineDrawer = openTimelineDrawer;

    function closeTimelineDrawer() {
        var pane = document.getElementById("timeline-details-pane");
        var backdrop = document.getElementById("timeline-drawer-backdrop");
        if (pane) pane.classList.remove("drawer-open");
        if (backdrop) { backdrop.classList.remove("open"); backdrop.hidden = true; }
        var restore = App.timelineDrawerRestoreFocus;
        App.timelineDrawerRestoreFocus = null;
        if (restore && restore.focus) restore.focus();
    }
    App.closeTimelineDrawer = closeTimelineDrawer;

    App.applyTimelineProjectFilter = function () {
        // Changing the filter can hide the currently-edited session, which
        // would orphan the draft. Gate the re-render through the context
        // change flow so a dirty draft is saved first.
        requestTimelineContextChange(function () {
            if (App.lastTimelineData) showTimeline(App.lastTimelineData);
        }, "应用筛选");
    };

    function showTimeline(data) {
        if (!data) return;
        if (data.date) App.timelineDate = data.date;
        App.lastTimelineData = data;
        var dateInput = document.getElementById("timeline-date-input");
        if (dateInput) dateInput.value = data.date || "";
        renderTimelineTotal(data);
        loadProjects();
        App.renderCurrentActivityElement(
            document.getElementById("timeline-current"),
            data.current_activity || {},
            "timeline"
        );

        var listEl = document.getElementById("timeline-sessions-list");
        var allSessions = Array.isArray(data.entries) ? data.entries.slice().sort(timelineSessionOrder) : [];
        App.currentSessions = allSessions;
        var sessions = filteredTimelineSessions(allSessions);
        if (sessions.length === 0) {
            listEl.innerHTML = '<div class="empty-state timeline-empty"><strong>'
                + (allSessions.length ? "当前筛选下没有时间段" : "当日暂无时间记录")
                + '</strong><span>'
                + (allSessions.length ? "可切换项目筛选查看其他时间段。" : "选择其他日期，或开始记录新的工作活动。")
                + '</span></div>';
            resetEmptyTimeline();
            return;
        }

        var html = "";
        for (var i = 0; i < sessions.length; i++) {
            var session = sessions[i];
            var clock = exactRowClock(
                session,
                "aggregate_live",
                "timeline_session_invalid_live_clock"
            );
            var canTick = !!(clock && clock.is_live === true);
            var durable = Math.max(0, parseInt(session.duration_seconds, 10) || 0);
            var seconds = clockedSeconds(clock, durable);
            var durationText = App.formatDuration(seconds);
            var startText = App.formatStartTimeOnly(session.start_time);
            var projectLabel = App.formatProjectLabel(
                session.project_name,
                session.project_description
            );
            var continuityKey = canTick
                ? App.liveContinuityKey(session, "session")
                : "";
            var classes = "timeline-item";
            if (session.is_uncategorized) classes += " uncategorized";
            if (session.is_in_progress) classes += " in-progress";
            if (canTick) classes += " live-projected";
            if (session.projection_instance_key === App.selectedProjectionInstanceKey) {
                classes += " selected";
            }
            var clockAttributes = canTick
                ? App.liveClockDataAttributes(clock, continuityKey, "timeline-session")
                : "";
            html += '<button type="button" role="option" aria-selected="'
                + (session.projection_instance_key === App.selectedProjectionInstanceKey ? "true" : "false")
                + '" class="' + classes + '" data-projection-instance-key="'
                + App.escapeHtml(session.projection_instance_key || "") + '" title="'
                + App.escapeHtml(projectLabel) + '｜' + App.escapeHtml(startText) + '｜'
                + App.escapeHtml(durationText) + '">'
                + '<div class="timeline-item-main">'
                + '<div class="timeline-item-project">' + App.escapeHtml(projectLabel) + '</div>'
                + '<div class="timeline-item-time">' + App.escapeHtml(startText) + '</div>'
                + '<div class="timeline-item-description'
                + (session.description_source === "derived" ? ' derived' : '') + '">'
                + App.escapeHtml(session.display_description || "暂无描述") + '</div>'
                + '</div><div class="timeline-item-side">'
                + '<div class="timeline-item-duration"' + clockAttributes
                + ' data-duration-seconds="' + String(seconds) + '">'
                + App.escapeHtml(durationText) + '</div>'
                + (session.is_in_progress ? '<span class="badge live">进行中</span>' : '')
                + '</div></button>';
        }
        listEl.innerHTML = html;
        var items = listEl.querySelectorAll(".timeline-item");
        for (var j = 0; j < items.length; j++) {
            (function (itemEl) {
                itemEl.addEventListener("click", function () {
                    selectTimelineSession(
                        itemEl.getAttribute("data-projection-instance-key"),
                        sessions
                    );
                });
                itemEl.addEventListener("keydown", function (event) {
                    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
                    event.preventDefault();
                    var candidates = Array.prototype.slice.call(items);
                    var target = candidates[Math.max(0, Math.min(candidates.length - 1,
                        candidates.indexOf(itemEl) + (event.key === "ArrowDown" ? 1 : -1)))];
                    if (target) target.focus();
                });
            })(items[j]);
        }

        if (App.selectedProjectionInstanceKey && !sessions.some(function (session) {
            return session.projection_instance_key === App.selectedProjectionInstanceKey;
        })) {
            resetEmptyTimeline();
            closeTimelineDrawer();
            return;
        }

        if (!App.selectedProjectionInstanceKey) return;
        var found = findSessionByProjectionKey(App.selectedProjectionInstanceKey);
        if (!found) {
            resetEmptyTimeline();
            return;
        }
        App.selectedProjectionInstanceKey = found.projection_instance_key || null;
        App.selectedProjectionRevision = found.projection_revision || "";
        var owner = App.timelineRequestState.nextSelectionOwner(
            data.date,
            found.projection_instance_key,
            found.projection_revision || ""
        );
        if (typeof App._timelineEditingActive !== "function" || !App._timelineEditingActive()) {
            loadSessionActivitySummary(
                found.projection_instance_key,
                data.date,
                found.projection_revision || "",
                owner
            );
        }
        if (found.edit_disabled) {
            clearEditPanel();
        } else if (
            !App.editingSession
            || App.editingSession.projection_instance_key !== found.projection_instance_key
            || !isEditDirty()
        ) {
            populateEditPanel(found);
        }
        updateSessionActionButtons(found);
    }
    App.showTimeline = showTimeline;

    function acceptTimelinePayload(data, date) {
        if (!data || data.ok !== true) return false;
        if (String(App.currentPage || "overview") !== "timeline") {
            App.noteRejectedPagePayload(data, "timeline", date);
            return false;
        }
        var expectedDate = App.runtimeReportDateForPage("timeline", date);
        var payloadDate = App.payloadReportDate(data, "timeline", date);
        if (expectedDate && payloadDate && expectedDate !== payloadDate) {
            App.noteRejectedPagePayload(data, "timeline", date);
            return false;
        }
        if (!App.isPagePayloadCompatibleWithRuntime(data, "timeline", date)) {
            App.noteRejectedPagePayload(data, "timeline", date);
            return false;
        }
        return App.acceptLiveRuntimePayload(data, "timeline", date, {
            source: "page_model"
        });
    }
    App.acceptTimelinePayload = acceptTimelinePayload;

    function acceptTimelineDetailsPayload(data, date) {
        var expectedDate = App.runtimeReportDateForPage("timeline", date);
        var payloadDate = App.payloadReportDate(data, "timeline", date);
        if (expectedDate && payloadDate && expectedDate !== payloadDate) {
            App.timelineDetailsRuntimeMismatch = "date_mismatch";
            return false;
        }
        if (!App.isPagePayloadCompatibleWithRuntime(data, "timeline", date)) {
            App.timelineDetailsRuntimeMismatch = "runtime_mismatch";
            return false;
        }
        return App.acceptLiveRuntimePayload(data, "timeline", date, {
            source: "details_model"
        });
    }
    App.acceptTimelineDetailsPayload = acceptTimelineDetailsPayload;

    function selectTimelineSession(projectionInstanceKey, sessions) {
        if (projectionInstanceKey !== App.selectedProjectionInstanceKey
                && (App.editSaving || isEditDirty() || App.mutationState === "unknown")) {
            // Gate the session switch through the context change flow so a
            // dirty draft is saved first and the switch is queued if a save
            // is in flight. On failure or unknown mutation the draft is
            // preserved and the switch is blocked.
            requestTimelineContextChange(function () {
                App.selectedProjectionInstanceKey = projectionInstanceKey;
                showTimeline(App.lastTimelineData);
            }, "切换时间段");
            return;
        }
        App.selectedProjectionInstanceKey = projectionInstanceKey;
        var items = document.querySelectorAll("#timeline-sessions-list .timeline-item");
        var found = null;
        for (var index = 0; index < sessions.length; index++) {
            if (sessions[index].projection_instance_key === projectionInstanceKey) {
                found = sessions[index];
                break;
            }
        }
        for (var i = 0; i < items.length; i++) {
            items[i].classList.remove("selected");
            items[i].setAttribute("aria-selected", "false");
            if (items[i].getAttribute("data-projection-instance-key") === projectionInstanceKey) {
                items[i].classList.add("selected");
                items[i].setAttribute("aria-selected", "true");
            }
        }
        if (!found) return;
        App.selectedProjectionRevision = found.projection_revision || "";
        var owner = App.timelineRequestState.nextSelectionOwner(
            App.timelineDate,
            found.projection_instance_key,
            found.projection_revision || ""
        );
        loadSessionActivitySummary(
            found.projection_instance_key,
            App.timelineDate,
            found.projection_revision || "",
            owner
        );
        if (found.edit_disabled === true) clearEditPanel();
        else populateEditPanel(found);
        updateSessionActionButtons(found);
        openTimelineDrawer(document.getElementById("timeline-details-close"));
    }
    App.selectTimelineSession = selectTimelineSession;

    function loadSessionActivitySummary(projectionInstanceKey, date, detailRevision, owner) {
        return loadSessionDetails(
            projectionInstanceKey,
            date,
            detailRevision,
            false,
            owner
        );
    }
    App.loadSessionActivitySummary = loadSessionActivitySummary;

    function loadSessionDetails(
        projectionInstanceKey,
        date,
        detailRevision,
        retriedStale,
        existingOwner
    ) {
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        var revision = String(detailRevision || App.selectedProjectionRevision || "");
        var owner = existingOwner || App.timelineRequestState.nextSelectionOwner(
            date,
            projectionInstanceKey,
            revision
        );
        var requestKey = App.timelineRequestState.detailRequestKey(owner);
        if (App.detailsInFlight[requestKey]) return App.detailsInFlight[requestKey];
        if (!detailsList.innerHTML.trim()) {
            detailsHeader.textContent = "加载活动详情…";
            detailsList.innerHTML = "";
        } else {
            detailsHeader.textContent = "正在刷新活动详情…";
        }
        var request = App.bridge.getTimelineSessionActivitySummary(
            projectionInstanceKey || "",
            date,
            revision
        ).then(function (result) {
            if (!App.timelineRequestState.isCurrentDetailsOwner(owner)) return null;
            if (result && result.ok === false && result.error === "stale_selection" && !retriedStale) {
                return App.loadTimelineReport(date, {
                    showLoading: false,
                    resetSelection: false
                }).then(function () {
                    var selected = findSessionByProjectionKey(
                        App.selectedProjectionInstanceKey
                    );
                    if (!selected) {
                        resetTimelineReportSelection();
                        return null;
                    }
                    var retryOwner = App.timelineRequestState.nextSelectionOwner(
                        date,
                        selected.projection_instance_key,
                        selected.projection_revision || ""
                    );
                    App.selectedProjectionRevision = selected.projection_revision || "";
                    return loadSessionDetails(
                        selected.projection_instance_key,
                        date,
                        selected.projection_revision || "",
                        true,
                        retryOwner
                    );
                });
            }
            var data = App.handleResult(result, function (message) {
                if (!App.timelineRequestState.isCurrentDetailsOwner(owner)) return;
                detailsHeader.textContent = "加载活动详情失败";
                detailsList.innerHTML = '<div class="timeline-empty">'
                    + App.escapeHtml(message) + '</div>';
            });
            if (!data || !App.timelineRequestState.isCurrentDetailsOwner(owner)) return null;
            if (!acceptTimelineDetailsPayload(data, date)) return null;
            renderSessionDetails(data);
            return data;
        }).catch(function () {
            if (!App.timelineRequestState.isCurrentDetailsOwner(owner)) return null;
            detailsHeader.textContent = "加载活动详情失败";
            detailsList.innerHTML = '<div class="timeline-empty">无法加载活动详情，请稍后重试。</div>';
            return null;
        }).finally(function () {
            if (App.detailsInFlight[requestKey] === request) {
                delete App.detailsInFlight[requestKey];
            }
        });
        App.detailsInFlight[requestKey] = request;
        return request;
    }
    App.loadSessionDetails = loadSessionDetails;

    function renderSessionDetails(data) {
        if (typeof App._timelineEditingActive === "function" && App._timelineEditingActive()) return;
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
            var canTick = !!(clock && clock.is_live === true);
            var durable = Math.max(0, parseInt(row.duration_seconds, 10) || 0);
            var seconds = clockedSeconds(clock, durable);
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
                    ? '<button type="button" class="summary-hide-activity" data-summary-id="'
                        + App.escapeHtml(String(row.summary_id || ""))
                        + '" aria-label="删除活动" data-tooltip="删除活动">'
                        + App.iconMarkup("trash") + '</button>'
                    : '')
                + '</div>';
        }
        list.innerHTML = html;
        var buttons = list.querySelectorAll(".summary-hide-activity");
        for (var index = 0; index < buttons.length; index++) {
            buttons[index].addEventListener("click", function (event) {
                event.stopPropagation();
                App.confirmTimelineDeletion("hideActivity", {
                    summaryId: this.getAttribute("data-summary-id")
                }, this);
            });
        }
    }
    App.renderSessionDetails = renderSessionDetails;
    App.renderSessionActivitySummary = renderSessionDetails;

    function loadProjects() {
        // Delegate to the unified catalog coordinator (installed by
        // rules.js). The coordinator stores both editing and filter
        // catalogs and renders every consumer from a single bridge call.
        if (typeof App.loadProjects === "function" && App.loadProjects !== loadProjects) {
            return App.loadProjects();
        }
        // Fallback: direct load (only used if the coordinator has not been
        // installed yet, e.g. during early init).
        if (App.projectsCache) {
            renderTimelineProjectFilter(App.filterProjectsCache || App.projectsCache);
            return Promise.resolve(App.projectsCache);
        }
        App.projectsLoading = true;
        App.projectsLoadPromise = App.bridge.listProjectsForTimeline().then(function (result) {
            if (result && result.ok !== false) {
                App.editingProjectsCache = result.editing_projects || result.projects || [];
                App.filterProjectsCache = result.filter_projects || result.projects || [];
                App.projectsCache = App.editingProjectsCache;
                renderTimelineProjectFilter(App.filterProjectsCache);
            }
            return App.projectsCache;
        }).catch(function () {
            return null;
        }).finally(function () {
            App.projectsLoading = false;
            App.projectsLoadPromise = null;
        });
        return App.projectsLoadPromise;
    }

    function confirmTimelineDeletion(operation, options, trigger) {
        if (!App.openDeleteDialog) return runTimelineSessionOperation(operation, options);
        var activity = operation === "hideActivity";
        return App.openDeleteDialog({
            trigger: trigger,
            title: activity ? "删除活动" : "删除时间段",
            objectLabel: activity ? "当前时间段中的这个活动" : "当前选中的时间段",
            warning: activity
                ? "活动会从当前时间段移除；页面会在后端确认成功后刷新。"
                : "时间段会从报表中移除；原始采集事实不会在前端被改写。",
            confirmLabel: activity ? "再次确认删除活动" : "再次确认删除时间段",
            twoStep: true
        }).then(function (confirmed) {
            return confirmed ? runTimelineSessionOperation(operation, options) : null;
        });
    }
    App.confirmTimelineDeletion = confirmTimelineDeletion;

    App.toggleTimelineAdvancedMenu = function () {
        var menu = document.getElementById("timeline-session-actions");
        var button = document.getElementById("timeline-advanced-toggle");
        if (!menu || !button) return;
        menu.hidden = !menu.hidden;
        button.setAttribute("aria-expanded", menu.hidden ? "false" : "true");
        if (!menu.hidden) {
            var first = menu.querySelector("button:not([hidden]):not([disabled])");
            if (first) first.focus();
        }
    };

    App.initTimelineAccessibility = function () {
        if (document.documentElement.getAttribute("data-timeline-a11y-bound") === "1") return;
        document.documentElement.setAttribute("data-timeline-a11y-bound", "1");
        document.addEventListener("keydown", function (event) {
            var pane = document.getElementById("timeline-details-pane");
            var menu = document.getElementById("timeline-session-actions");
            if (event.key === "Escape" && menu && !menu.hidden) {
                event.preventDefault();
                menu.hidden = true;
                var toggle = document.getElementById("timeline-advanced-toggle");
                if (toggle) { toggle.setAttribute("aria-expanded", "false"); toggle.focus(); }
                return;
            }
            if (!pane || !pane.classList.contains("drawer-open")) return;
            if (event.key === "Escape") {
                event.preventDefault();
                closeTimelineDrawer();
                return;
            }
            if (App.trapFocus) App.trapFocus(event, pane);
        });
    };

    function findCachedProject(projectId) {
        var projects = App.projectsCache || [];
        for (var i = 0; i < projects.length; i++) {
            if (String(projects[i].id) === String(projectId)) return projects[i];
        }
        return null;
    }

    function renderProjectSelect(projects, currentProjectId) {
        var select = document.getElementById("edit-project-select");
        if (!select) return;
        select.innerHTML = "";
        if (!projects || projects.length === 0) {
            var failure = document.createElement("option");
            failure.value = "";
            failure.textContent = "项目列表加载失败";
            select.appendChild(failure);
            select.disabled = true;
            return;
        }
        for (var i = 0; i < projects.length; i++) {
            var project = projects[i];
            var option = document.createElement("option");
            option.value = String(project.id);
            option.textContent = project.description
                ? (project.name || "") + " (" + project.description + ")"
                : (project.name || "");
            if (currentProjectId && String(project.id) === String(currentProjectId)) {
                option.selected = true;
            }
            select.appendChild(option);
        }
        applyEditCapabilities(App.editingSession);
    }
    App.renderProjectSelect = renderProjectSelect;

    function canEditField(session, field) {
        return !!session && session.edit_disabled !== true && session[field] !== false;
    }

    function hasEditableFields(session) {
        return canEditField(session, "can_edit_project")
            || canEditField(session, "can_edit_note")
            || canEditField(session, "can_edit_duration");
    }

    function applyEditCapabilities(session) {
        var projectAllowed = canEditField(session, "can_edit_project");
        var noteAllowed = canEditField(session, "can_edit_note");
        var durationAllowed = canEditField(session, "can_edit_duration");
        var select = document.getElementById("edit-project-select");
        var note = document.getElementById("edit-note-text");
        var duration = document.getElementById("edit-duration-input");
        var save = document.getElementById("edit-save-btn");
        var cancel = document.getElementById("edit-cancel-btn");
        if (select) select.disabled = App.editSaving || !projectAllowed || !App.projectsCache;
        if (note) note.disabled = App.editSaving || !noteAllowed;
        if (duration) duration.disabled = App.editSaving || !durationAllowed;
        if (cancel) cancel.disabled = App.editSaving || !session;
        if (save) {
            save.disabled = App.editSaving
                || !hasEditableFields(session)
                || (noteAllowed && note && note.value.length > App.NOTE_MAX_LENGTH);
        }
    }
    App.applyTimelineEditCapabilities = applyEditCapabilities;

    function populateEditPanel(session) {
        if (!session) {
            clearEditPanel();
            return;
        }
        App.editingSession = session;
        var panel = document.getElementById("timeline-edit-panel");
        if (panel) panel.hidden = false;
        var select = document.getElementById("edit-project-select");
        if (select && !App.projectsCache) {
            select.innerHTML = '<option value="">加载中…</option>';
            select.disabled = true;
            loadProjects().then(function (projects) {
                if (
                    App.editingSession
                    && App.editingSession.projection_instance_key === session.projection_instance_key
                ) {
                    renderProjectSelect(projects, session.project_id);
                }
            });
        } else if (select) {
            renderProjectSelect(App.projectsCache, session.project_id);
        }
        var duration = document.getElementById("edit-duration-input");
        if (duration) {
            var source = session.adjusted_duration_seconds !== null
                && session.adjusted_duration_seconds !== undefined
                ? session.adjusted_duration_seconds
                : session.duration_seconds;
            var minutes = Math.round((parseInt(source, 10) || 0) / 60);
            duration.value = isNaN(minutes) ? "" : String(minutes);
        }
        var durationStatus = document.getElementById("edit-duration-status");
        if (durationStatus) {
            durationStatus.textContent = session.has_duration_override ? "已修正" : "";
        }
        var note = document.getElementById("edit-note-text");
        if (note) note.value = session.session_note || "";
        var cancel = document.getElementById("edit-cancel-btn");
        if (cancel) cancel.disabled = false;
        updateNoteCount();
        applyEditCapabilities(session);
        showEditStatus("", false);
    }
    App.populateEditPanel = populateEditPanel;

    function clearEditPanel() {
        if (App.timelineAutosaveTimer) window.clearTimeout(App.timelineAutosaveTimer);
        App.timelineAutosaveTimer = null;
        App.timelineAutosaveQueued = false;
        App.editingSession = null;
        App.editSaving = false;
        App.submittedDraft = null;
        var panel = document.getElementById("timeline-edit-panel");
        if (panel) panel.hidden = true;
        updateSessionActionButtons(null);
        var note = document.getElementById("edit-note-text");
        if (note) {
            note.value = "";
            note.disabled = true;
        }
        var select = document.getElementById("edit-project-select");
        if (select) {
            select.innerHTML = '<option value="">加载中…</option>';
            select.disabled = true;
        }
        var duration = document.getElementById("edit-duration-input");
        if (duration) {
            duration.value = "";
            duration.disabled = true;
        }
        var durationStatus = document.getElementById("edit-duration-status");
        if (durationStatus) durationStatus.textContent = "";
        var save = document.getElementById("edit-save-btn");
        var cancel = document.getElementById("edit-cancel-btn");
        if (save) save.disabled = true;
        if (cancel) cancel.disabled = true;
        showEditStatus("", false);
    }
    App.clearEditPanel = clearEditPanel;

    function isEditDirty() {
        if (!App.editingSession) return false;
        var session = App.editingSession;
        var note = document.getElementById("edit-note-text");
        var select = document.getElementById("edit-project-select");
        var duration = document.getElementById("edit-duration-input");
        if (canEditField(session, "can_edit_note") && note) {
            if (note.value !== (session.session_note || "")) return true;
        }
        if (canEditField(session, "can_edit_project") && select && select.value) {
            if (select.value !== String(session.project_id || "")) return true;
        }
        if (canEditField(session, "can_edit_duration") && duration) {
            var source = session.adjusted_duration_seconds !== null
                && session.adjusted_duration_seconds !== undefined
                ? session.adjusted_duration_seconds
                : session.duration_seconds;
            var minutes = Math.round((parseInt(source, 10) || 0) / 60);
            if ((duration.value || "").trim() !== (isNaN(minutes) ? "" : String(minutes))) {
                return true;
            }
        }
        return false;
    }
    App.isEditDirty = isEditDirty;

    function updateNoteCount() {
        var textarea = document.getElementById("edit-note-text");
        var counter = document.getElementById("edit-note-count");
        if (!textarea || !counter) return;
        var length = textarea.value.length;
        counter.textContent = length + " / " + App.NOTE_MAX_LENGTH;
        counter.classList.toggle("over-limit", length > App.NOTE_MAX_LENGTH);
        applyEditCapabilities(App.editingSession);
    }
    App.updateNoteCount = updateNoteCount;

    function showEditStatus(message, isError) {
        var status = document.getElementById("edit-status");
        if (!status) return;
        if (!message) {
            status.hidden = true;
            status.textContent = "";
            status.className = "edit-status";
            return;
        }
        status.hidden = false;
        status.textContent = message;
        status.className = "edit-status "
            + (isError ? "edit-status-error" : "edit-status-success");
    }
    App.showEditStatus = showEditStatus;

    function scheduleTimelineAutosave(delay) {
        if (!App.editingSession) return;
        if (App.timelineAutosaveTimer) window.clearTimeout(App.timelineAutosaveTimer);
        App.timelineAutosaveTimer = null;
        if (App.editSaving) {
            App.timelineAutosaveQueued = true;
            showEditStatus("有新更改，等待保存", false);
            return;
        }
        if (!isEditDirty()) {
            showEditStatus("已保存", false);
            return;
        }
        showEditStatus("等待自动保存", false);
        App.timelineAutosaveTimer = window.setTimeout(function () {
            App.timelineAutosaveTimer = null;
            saveEdit();
        }, Math.max(0, parseInt(delay, 10) || 0));
    }
    App.scheduleTimelineAutosave = scheduleTimelineAutosave;

    App.focusTimelineEditorField = function (target) {
        var id = target === "project" ? "edit-project-select"
            : target === "description" ? "edit-note-text" : "timeline-details-close";
        var element = document.getElementById(id);
        openTimelineDrawer(element);
        if (element && element.focus) element.focus();
    };

    function setEditSaving(saving) {
        App.editSaving = saving;
        applyEditCapabilities(App.editingSession);
    }
    App.setEditSaving = setEditSaving;

    function blockDifferentMutationIntent() {
        showEditStatus("已有操作结果尚未确认，请先重试同一操作或刷新核对。", true);
    }

    function markMutationUnknown(owner) {
        App.timelineRequestState.markMutationUnknown(owner);
        App.timelineAutosaveQueued = false;
        setEditSaving(false);
        showEditStatus("操作结果尚未确认，可重试同一操作或刷新核对。", true);
    }

    function consumeMutationResult(result) {
        App.lastMutationSnapshotRevision = String((result && result.snapshot_revision) || "");
        App.lastMutationOutcomeType = String((result && result.outcome_type) || "");
        var hint = result && result.selection_hint;
        if (!hint) {
            resetTimelineReportSelection();
            return;
        }
        App.selectedProjectionInstanceKey = String(
            hint.projection_instance_key || ""
        ) || null;
        App.selectedProjectionRevision = String(hint.projection_revision || "");
    }

    function refreshAfterConfirmedMutation() {
        return App.loadTimelineReport(currentTimelineReportDate(), {
            showLoading: false,
            resetSelection: false,
            rejectOnError: true,
            errorMessage: "操作已保存，但刷新失败"
        });
    }

    // Rebase the editing session to the refreshed authoritative baseline.
    // After a save + refresh the projection revision advances (R1 -> R2).
    // If the user typed during the in-flight request, populateEditPanel is
    // skipped, leaving App.editingSession at the OLD baseline.
    function rebaseEditingSessionAfterRefresh() {
        if (!App.editingSession || !App.selectedProjectionInstanceKey) return;
        var refreshed = findSessionByProjectionKey(App.selectedProjectionInstanceKey);
        if (!refreshed) return;
        if (refreshed.projection_instance_key !== App.editingSession.projection_instance_key) return;
        App.editingSession = refreshed;
        App.selectedProjectionRevision = refreshed.projection_revision || "";
        // Re-apply capability flags (e.g. can_edit_note) in case the
        // mutation changed the session's editability, but never overwrite
        // the user's current DOM input.
        applyEditCapabilities(refreshed);
    }
    App.rebaseEditingSessionAfterRefresh = rebaseEditingSessionAfterRefresh;

    function saveEdit() {
        if (!App.editingSession) return;
        if (App.editSaving) {
            App.timelineAutosaveQueued = true;
            return;
        }
        var session = App.editingSession;
        var canProject = canEditField(session, "can_edit_project");
        var canNote = canEditField(session, "can_edit_note");
        var canDuration = canEditField(session, "can_edit_duration");
        if (!canProject && !canNote && !canDuration) {
            showEditStatus(session.disable_reason || "当前时段不可编辑", true);
            return;
        }
        var select = document.getElementById("edit-project-select");
        var noteElement = document.getElementById("edit-note-text");
        if (!select || !noteElement) return;
        var key = session.projection_instance_key || App.selectedProjectionInstanceKey;
        var revision = session.projection_revision || App.selectedProjectionRevision;
        if (!key || !revision) {
            showEditStatus("无法保存：时段版本无效，请刷新后重试", true);
            return;
        }
        var originalProjectId = String(session.project_id || "");
        var projectIdText = canProject ? select.value : originalProjectId;
        var projectId = projectIdText ? parseInt(projectIdText, 10) : null;
        if (canProject && (!projectId || !findCachedProject(projectId))) {
            showEditStatus("项目列表已过期，请刷新后重试", true);
            return;
        }
        var originalNote = session.session_note || "";
        var note = canNote ? noteElement.value : originalNote;
        if (note.length > App.NOTE_MAX_LENGTH) {
            showEditStatus("备注不能超过 2000 个字符", true);
            return;
        }
        var projectChanged = canProject && projectIdText !== originalProjectId;
        var noteChanged = canNote && note !== originalNote;
        var adjustedDurationSeconds = null;
        var durationChanged = false;
        var durationElement = document.getElementById("edit-duration-input");
        if (canDuration) {
            var durationText = durationElement ? (durationElement.value || "").trim() : "";
            if (durationText !== "") {
                var minutes = parseInt(durationText, 10);
                if (isNaN(minutes) || minutes < 0) {
                    showEditStatus("时长需为非负整数", true);
                    return;
                }
                adjustedDurationSeconds = minutes * 60;
            }
            var baseline = session.adjusted_duration_seconds !== null
                && session.adjusted_duration_seconds !== undefined
                ? session.adjusted_duration_seconds
                : session.duration_seconds;
            var baselineMinutes = Math.round((parseInt(baseline, 10) || 0) / 60);
            durationChanged = durationText !== String(baselineMinutes);
        } else if (session.has_duration_override === true) {
            adjustedDurationSeconds = parseInt(session.adjusted_duration_seconds, 10);
            if (isNaN(adjustedDurationSeconds)) adjustedDurationSeconds = null;
        }
        if (!projectChanged && !noteChanged && !durationChanged) {
            showEditStatus("已保存", false);
            return;
        }
        var reportDate = currentTimelineReportDate();
        if (!reportDate) {
            showEditStatus("无法保存：日期无效", true);
            return;
        }
        setEditSaving(true);
        showEditStatus("", false);
        var overrideProjectId = canProject
            && (projectChanged || session.has_project_override === true)
            ? projectId
            : null;
        var owner = App.timelineRequestState.nextMutationOwner(
            "save_timeline_session_edit",
            reportDate,
            key,
            revision,
            JSON.stringify([overrideProjectId, adjustedDurationSeconds, note])
        );
        if (!owner) {
            setEditSaving(false);
            blockDifferentMutationIntent();
            return;
        }
        // Snapshot the submitted draft + authoritative revision. This
        // decouples the in-flight request from the live DOM so post-submit
        // input is never overwritten by a stale response, and the queued
        // autosave can rebase onto the post-success revision.
        App.submittedDraft = {
            projectionInstanceKey: key,
            projectionRevision: revision,
            requestId: owner.requestId,
            projectId: overrideProjectId,
            note: note,
            adjustedDurationSeconds: adjustedDurationSeconds
        };
        owner.payload = [
            reportDate,
            key,
            revision,
            owner.requestId,
            overrideProjectId,
            adjustedDurationSeconds,
            note
        ];
        App.bridge.saveTimelineSessionEdit.apply(null, owner.payload).then(function (result) {
            if (!App.timelineRequestState.isCurrentMutationOwner(owner)) return;
            if (!result || result.ok === false) {
                setEditSaving(false);
                showEditStatus(result && result.message ? result.message : "保存失败", true);
                App.timelineRequestState.releaseMutationOwner(owner, "confirmed_failure", result);
                drainPendingContextChange(false);
                return;
            }
            App.timelineRequestState.transitionMutation(owner, "confirmed_success", result);
            consumeMutationResult(result);
            App.timelineRequestState.releaseMutationOwner(owner, "confirmed_success", result);
            showEditStatus("已自动保存", false);
            return refreshAfterConfirmedMutation().catch(function () {
                showEditStatus("操作已保存，但刷新失败", true);
            }).then(function () {
                // Rebase to the refreshed baseline (with the new
                // projection_revision) BEFORE evaluating the queued
                // autosave so the next save uses the new revision.
                rebaseEditingSessionAfterRefresh();
            }).finally(function () {
                setEditSaving(false);
                if (App.timelineAutosaveQueued && isEditDirty()) {
                    App.timelineAutosaveQueued = false;
                    scheduleTimelineAutosave(0);
                } else {
                    App.timelineAutosaveQueued = false;
                    if (!isEditDirty()) App.submittedDraft = null;
                }
                // Drain any queued context change now that the save has
                // resolved. The draft is either persisted (success) or
                // preserved (the success path above ran), so switching is
                // safe.
                drainPendingContextChange(true);
            });
        }).catch(function () {
            if (App.timelineRequestState.isCurrentMutationOwner(owner)) markMutationUnknown(owner);
            drainPendingContextChange(false);
        });
    }
    App.saveEdit = saveEdit;

    App.refreshTimelineAfterEdit = function () {
        return App.loadTimelineReport(currentTimelineReportDate(), {
            showLoading: false,
            resetSelection: false,
            errorMessage: "刷新失败"
        });
    };

    function cancelEdit() {
        if (App.editSaving) return;
        if (!App.editingSession) clearEditPanel();
        else populateEditPanel(App.editingSession);
    }
    App.cancelEdit = cancelEdit;

    function updateSessionActionButtons(session) {
        var fields = [
            ["timeline-hide-session", "can_hide"],
            ["timeline-merge-previous", "can_merge_previous"],
            ["timeline-merge-next", "can_merge_next"],
            ["timeline-split-session", "can_split"],
            ["timeline-copy-session", "can_copy"]
        ];
        for (var i = 0; i < fields.length; i++) {
            var button = document.getElementById(fields[i][0]);
            if (!button) continue;
            var allowed = !!(session && session[fields[i][1]]);
            button.hidden = !allowed;
            button.disabled = !allowed;
        }
    }
    App.updateSessionActionButtons = updateSessionActionButtons;

    var TIMELINE_OPERATIONS = Object.freeze({
        hide: Object.freeze({
            intent: "hide_timeline_session",
            invoke: function () { return App.bridge.hideTimelineSession.apply(null, arguments); }
        }),
        hideActivity: Object.freeze({
            intent: "hide_timeline_session_activity",
            invoke: function () { return App.bridge.hideTimelineSessionActivity.apply(null, arguments); }
        }),
        merge: Object.freeze({
            intent: "merge_timeline_session",
            invoke: function () { return App.bridge.mergeTimelineSession.apply(null, arguments); }
        }),
        split: Object.freeze({
            intent: "split_timeline_session",
            invoke: function () { return App.bridge.splitTimelineSession.apply(null, arguments); }
        }),
        copy: Object.freeze({
            intent: "copy_timeline_session",
            invoke: function () { return App.bridge.copyTimelineSession.apply(null, arguments); }
        })
    });

    function runTimelineSessionOperation(operationKey, options) {
        options = options || {};
        var operation = TIMELINE_OPERATIONS[operationKey];
        if (!operation) return Promise.reject(new Error("unsupported_timeline_operation"));
        var key = App.selectedProjectionInstanceKey;
        var date = currentTimelineReportDate();
        var revision = App.selectedProjectionRevision || "";
        if (!key || !date) return Promise.resolve();
        var mergeTarget = operationKey === "merge"
            ? findMergeTarget(key, options.direction)
            : null;
        if (operationKey === "merge" && !mergeTarget) {
            showEditStatus("只能合并相邻时段。", true);
            return Promise.resolve();
        }
        var owner = App.timelineRequestState.nextMutationOwner(
            operation.intent,
            date,
            key,
            revision,
            JSON.stringify([
                options,
                mergeTarget ? mergeTarget.projection_instance_key || "" : "",
                mergeTarget ? mergeTarget.projection_revision || "" : ""
            ])
        );
        if (!owner) {
            blockDifferentMutationIntent();
            return Promise.resolve();
        }
        var args;
        if (operationKey === "hideActivity") {
            args = [date, key, options.summaryId || "", revision, owner.requestId];
        } else if (operationKey === "merge") {
            args = [
                date,
                key,
                options.direction,
                revision,
                owner.requestId,
                mergeTarget.projection_instance_key || "",
                mergeTarget.projection_revision || ""
            ];
        } else {
            args = [date, key, revision, owner.requestId];
        }
        owner.payload = args.slice();
        return operation.invoke.apply(null, args).then(function (result) {
            if (!App.timelineRequestState.isCurrentMutationOwner(owner)) return null;
            var data = App.handleResult(result, function (message) {
                showEditStatus(message || "操作失败，请刷新后重试。", true);
            });
            if (!data) {
                App.timelineRequestState.releaseMutationOwner(owner, "confirmed_failure", result);
                return null;
            }
            App.timelineRequestState.transitionMutation(owner, "confirmed_success", result);
            consumeMutationResult(result);
            App.timelineRequestState.releaseMutationOwner(owner, "confirmed_success", result);
            showEditStatus("操作成功", false);
            return refreshAfterConfirmedMutation().catch(function () {
                showEditStatus("操作已保存，但刷新失败", true);
            });
        }).catch(function () {
            if (App.timelineRequestState.isCurrentMutationOwner(owner)) markMutationUnknown(owner);
            return null;
        });
    }
    App.runTimelineSessionOperation = runTimelineSessionOperation;

    function findSessionByProjectionKey(projectionInstanceKey) {
        var sessions = App.currentSessions || [];
        for (var i = 0; i < sessions.length; i++) {
            if ((sessions[i].projection_instance_key || "") === (projectionInstanceKey || "")) {
                return sessions[i];
            }
        }
        return null;
    }
    App.findSessionByProjectionKey = findSessionByProjectionKey;

    // Find the chronological merge target. The UI renders newest-first but
    // the backend defines previous = time-earlier, next = time-later.
    function findChronologicalMergeTarget(sessions, sourceKey, direction) {
        if (!sessions || !sourceKey) return null;
        var sorted = sessions.slice().sort(function (left, right) {
            var leftTime = String(left.start_time || "");
            var rightTime = String(right.start_time || "");
            if (leftTime < rightTime) return -1;
            if (leftTime > rightTime) return 1;
            return String(left.projection_instance_key || "")
                .localeCompare(String(right.projection_instance_key || ""));
        });
        for (var i = 0; i < sorted.length; i++) {
            if ((sorted[i].projection_instance_key || "") !== sourceKey) continue;
            var targetIndex = direction === "previous" ? i - 1 : i + 1;
            if (targetIndex < 0 || targetIndex >= sorted.length) return null;
            return sorted[targetIndex];
        }
        return null;
    }
    App.findChronologicalMergeTarget = findChronologicalMergeTarget;

    function findMergeTarget(sourceKey, direction) {
        return findChronologicalMergeTarget(App.currentSessions, sourceKey, direction);
    }

    function normalizeTimelineReportDate(date) {
        if (date === "--" || date === "") return null;
        return date || null;
    }
    App.normalizeTimelineReportDate = normalizeTimelineReportDate;

    function currentTimelineReportDate() {
        var input = document.getElementById("timeline-date-input");
        return normalizeTimelineReportDate(
            App.timelineDate || (input ? input.value : null)
        );
    }
    App.currentTimelineReportDate = currentTimelineReportDate;

    function resetTimelineReportSelection() {
        App.selectedProjectionInstanceKey = null;
        App.selectedProjectionRevision = null;
        App.detailsOwner = null;
        App.lastSessionDetailsViewModel = null;
        App.lastSessionActivitySummaryViewModel = null;
        var header = document.getElementById("timeline-details-header");
        var list = document.getElementById("timeline-details-list");
        if (header) header.textContent = "选择左侧时段查看详情";
        if (list) list.innerHTML = "";
        clearEditPanel();
    }
    App.resetTimelineReportSelection = resetTimelineReportSelection;

    function releaseTimelineLoadingOwner(owner) {
        if (owner && App.timelineLoadingOwner === owner) {
            App.timelineLoadingOwner = null;
            App.setTimelineLoading(false);
        }
    }
    App.releaseTimelineLoadingOwner = releaseTimelineLoadingOwner;

    function timelineReportRequest(date, options) {
        options = options || {};
        date = normalizeTimelineReportDate(date);
        var showLoading = options.showLoading !== false;
        var resetSelection = options.resetSelection === true;
        var errorMessage = options.errorMessage
            || (showLoading ? "加载时间线失败" : "刷新失败");
        var rejectOnError = options.rejectOnError === true;
        var timelineOwner = App.timelineRequestState.nextTimelineOwner(date);
        App.timelineDate = date;
        if (resetSelection) resetTimelineReportSelection();
        var loadingOwner = "";
        if (showLoading) {
            loadingOwner = timelineOwner;
            App.timelineLoadingOwner = loadingOwner;
            App.setTimelineLoading(true);
            App.clearTimelineError();
        }
        var token = ++App.timelineRequestToken;
        return App.bridge.getTimeline(date).then(function (result) {
            if (token !== App.timelineRequestToken || App.timelineOwner !== timelineOwner) return;
            var data = App.handleResult(result, function (message) {
                App.showTimelineError(message || errorMessage);
            });
            if (!data) {
                if (rejectOnError) throw new Error("timeline_refresh_failed");
                return;
            }
            if (!acceptTimelinePayload(data, date)) return;
            if (data.date) App.timelineDate = data.date;
            App.timelineLoaded = true;
            showTimeline(data);
            App.clearTimelineError();
        }).catch(function () {
            if (token !== App.timelineRequestToken || App.timelineOwner !== timelineOwner) return;
            App.showTimelineError(errorMessage);
            if (rejectOnError) throw new Error("timeline_refresh_failed");
        }).then(function () {
            releaseTimelineLoadingOwner(loadingOwner);
        }, function (error) {
            releaseTimelineLoadingOwner(loadingOwner);
            throw error;
        });
    }

    App.loadTimeline = function (date) {
        return App.loadTimelineReport(date, {
            showLoading: true,
            resetSelection: false
        });
    };
    App.loadTimelineReport = timelineReportRequest;

    // Single entry point for context changes that could destroy the current
    // edit context (date switch, filter change, session switch).
    function requestTimelineContextChange(actionFn, label) {
        var reason = label || "切换";
        if (App.mutationState === "unknown") {
            showEditStatus("操作结果尚未确认，请先重试或刷新核对后再" + reason + "。", true);
            return Promise.resolve(false);
        }
        if (App.editSaving) {
            App.pendingContextChange = { action: actionFn, reason: reason };
            showEditStatus("正在保存当前更改，保存完成后自动" + reason + "。", false);
            return Promise.resolve(false);
        }
        // Dirty draft with no save in flight: save first, then switch.
        if (isEditDirty()) {
            showEditStatus("正在保存当前更改，保存完成后自动" + reason + "。", false);
            App.pendingContextChange = { action: actionFn, reason: reason };
            saveEdit();
            return Promise.resolve(false);
        }
        // No dirty draft: switch immediately.
        return Promise.resolve().then(actionFn);
    }
    App.requestTimelineContextChange = requestTimelineContextChange;

    // Drains a pending context change after a save completes. Called from
    // the saveEdit finally block. On confirmed failure or unknown result
    // the pending change is cancelled (draft preserved).
    function drainPendingContextChange(saveSucceeded) {
        var pending = App.pendingContextChange;
        if (!pending) return;
        App.pendingContextChange = null;
        if (!saveSucceeded) {
            showEditStatus("保存失败，未" + pending.reason + "，请重试或刷新核对。", true);
            return;
        }
        // Save succeeded — execute the queued context change.
        try {
            pending.action();
        } catch (error) {
            // Swallow; the action is best-effort and the user can retry.
        }
    }
    App.drainPendingContextChange = drainPendingContextChange;
    App.refreshTimeline = function () {
        return App.loadTimelineReport(currentTimelineReportDate(), {
            showLoading: false,
            resetSelection: false,
            errorMessage: "刷新失败"
        });
    };
    App.reloadTimelineAfterRuntimeRefresh = function (date) {
        return App.loadTimelineReport(date, {
            showLoading: true,
            resetSelection: true
        });
    };
    App.goPrevDay = function () {
        var input = document.getElementById("timeline-date-input");
        var current = App.timelineDate || (input ? input.value : null);
        var target = App.shiftDate(current, -1);
        return requestTimelineContextChange(function () {
            App.loadTimelineReport(target, {
                showLoading: true,
                resetSelection: true
            });
        }, "切换到前一天");
    };
    App.goNextDay = function () {
        var input = document.getElementById("timeline-date-input");
        var current = App.timelineDate || (input ? input.value : null);
        var target = App.shiftDate(current, 1);
        return requestTimelineContextChange(function () {
            App.loadTimelineReport(target, {
                showLoading: true,
                resetSelection: true
            });
        }, "切换到后一天");
    };
    App.goToday = function () {
        return requestTimelineContextChange(function () {
            App.loadTimelineReport(null, {
                showLoading: true,
                resetSelection: true
            });
        }, "切换到今天");
    };
    App.goToDate = function (date) {
        var target = date || null;
        return requestTimelineContextChange(function () {
            App.loadTimelineReport(target, {
                showLoading: true,
                resetSelection: true
            });
        }, "切换日期");
    };
})();
