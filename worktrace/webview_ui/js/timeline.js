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

    function showTimeline(data) {
        if (!data) return;
        if (data.date) App.timelineDate = data.date;
        App.lastTimelineData = data;
        var dateInput = document.getElementById("timeline-date-input");
        if (dateInput) dateInput.value = data.date || "";
        renderTimelineTotal(data);
        App.renderCurrentActivityElement(
            document.getElementById("timeline-current"),
            data.current_activity || {},
            "timeline"
        );

        var listEl = document.getElementById("timeline-sessions-list");
        var sessions = Array.isArray(data.entries) ? data.entries : [];
        App.currentSessions = sessions;
        if (sessions.length === 0) {
            listEl.innerHTML = '<div class="timeline-empty">当日暂无活动记录</div>';
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
            html += '<div class="' + classes + '" data-projection-instance-key="'
                + App.escapeHtml(session.projection_instance_key || "") + '" title="'
                + App.escapeHtml(projectLabel) + '｜' + App.escapeHtml(startText) + '｜'
                + App.escapeHtml(durationText) + '">'
                + '<div class="timeline-item-main">'
                + '<div class="timeline-item-project">' + App.escapeHtml(projectLabel) + '</div>'
                + '<div class="timeline-item-time">' + App.escapeHtml(startText) + '</div>'
                + (session.has_duration_override ? '<div class="timeline-item-adjusted">已修正</div>' : '')
                + '</div><div class="timeline-item-side">'
                + '<div class="timeline-item-duration"' + clockAttributes
                + ' data-duration-seconds="' + String(seconds) + '">'
                + App.escapeHtml(durationText) + '</div>'
                + '<div class="timeline-item-count">'
                + App.escapeHtml(String(session.event_count || 0) + " 条")
                + '</div></div></div>';
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
            })(items[j]);
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
            if (items[i].getAttribute("data-projection-instance-key") === projectionInstanceKey) {
                items[i].classList.add("selected");
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
            detailsHeader.textContent = "加载项目活动耗时…";
            detailsList.innerHTML = "";
        } else {
            detailsHeader.textContent = "正在刷新项目活动耗时…";
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
                detailsHeader.textContent = "加载项目活动耗时失败";
                detailsList.innerHTML = '<div class="timeline-empty">'
                    + App.escapeHtml(message) + '</div>';
            });
            if (!data || !App.timelineRequestState.isCurrentDetailsOwner(owner)) return null;
            if (!acceptTimelineDetailsPayload(data, date)) return null;
            renderSessionDetails(data);
            return data;
        }).catch(function () {
            if (!App.timelineRequestState.isCurrentDetailsOwner(owner)) return null;
            detailsHeader.textContent = "加载项目活动耗时失败";
            detailsList.innerHTML = '<div class="timeline-empty">无法加载项目活动耗时，请稍后重试。</div>';
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
            header.textContent = "项目活动耗时";
            list.innerHTML = '<div class="timeline-empty">该时段暂无活动耗时</div>';
            return;
        }
        header.textContent = "项目活动耗时";
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
                + (row.can_hide_activity
                    ? '<button type="button" class="summary-hide-activity" data-summary-id="'
                        + App.escapeHtml(String(row.summary_id || ""))
                        + '">从该时段移除该活动</button>'
                    : '')
                + '</div>';
        }
        list.innerHTML = html;
        var buttons = list.querySelectorAll(".summary-hide-activity");
        for (var index = 0; index < buttons.length; index++) {
            buttons[index].addEventListener("click", function (event) {
                event.stopPropagation();
                App.runTimelineSessionOperation("hideActivity", {
                    summaryId: this.getAttribute("data-summary-id")
                });
            });
        }
    }
    App.renderSessionDetails = renderSessionDetails;
    App.renderSessionActivitySummary = renderSessionDetails;

    function loadProjects() {
        if (App.projectsCache) return Promise.resolve(App.projectsCache);
        if (App.projectsLoading) return App.projectsLoadPromise || Promise.resolve(null);
        App.projectsLoading = true;
        App.projectsLoadPromise = App.bridge.listProjectsForTimeline().then(function (result) {
            if (result && result.ok !== false && Array.isArray(result.projects)) {
                App.projectsCache = result.projects;
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
    App.loadProjects = loadProjects;

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
        App.editingSession = null;
        App.editSaving = false;
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

    function saveEdit() {
        if (!App.editingSession || App.editSaving) return;
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
            showEditStatus("没有需要保存的更改", false);
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
                return;
            }
            App.timelineRequestState.transitionMutation(owner, "confirmed_success", result);
            consumeMutationResult(result);
            setEditSaving(false);
            App.timelineRequestState.releaseMutationOwner(owner, "confirmed_success", result);
            showEditStatus("保存成功", false);
            return refreshAfterConfirmedMutation().catch(function () {
                showEditStatus("操作已保存，但刷新失败", true);
            });
        }).catch(function () {
            if (App.timelineRequestState.isCurrentMutationOwner(owner)) markMutationUnknown(owner);
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

    function findMergeTarget(sourceKey, direction) {
        var sessions = App.currentSessions || [];
        for (var i = 0; i < sessions.length; i++) {
            if ((sessions[i].projection_instance_key || "") !== sourceKey) continue;
            var targetIndex = direction === "previous" ? i - 1 : i + 1;
            return targetIndex >= 0 && targetIndex < sessions.length
                ? sessions[targetIndex]
                : null;
        }
        return null;
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
        App.loadTimelineReport(App.shiftDate(current, -1), {
            showLoading: true,
            resetSelection: true
        });
    };
    App.goNextDay = function () {
        var input = document.getElementById("timeline-date-input");
        var current = App.timelineDate || (input ? input.value : null);
        App.loadTimelineReport(App.shiftDate(current, 1), {
            showLoading: true,
            resetSelection: true
        });
    };
    App.goToday = function () {
        App.loadTimelineReport(null, {
            showLoading: true,
            resetSelection: true
        });
    };
})();
