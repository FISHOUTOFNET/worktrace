// WorkTrace WebView frontend — timeline, details, edits, and navigation.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    if (typeof App.timelineStructuralRefreshPending !== "boolean") {
        App.timelineStructuralRefreshPending = false;
    }
    if (typeof App.suppressNextTimelineCollectionRefresh !== "boolean") {
        App.suppressNextTimelineCollectionRefresh = false;
    }

    function resetEmptyTimeline() {
        App.lastSessionDetailsViewModel = null;
        App.lastSessionActivitySummaryViewModel = null;
        document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
        document.getElementById("timeline-details-list").innerHTML = "";
        clearTimelineSelectionState();
        App.detailsOwner = null;
        App.clearEditPanel();
    }

    App.applyTimelineProjectFilter = function () {
        requestTimelineContextChange(function () {
            if (App.lastTimelineData) showTimeline(App.lastTimelineData);
        }, "应用筛选");
    };

    function rememberTimelineSelection(session) {
        if (!session) return null;
        App.selectedProjectionInstanceKey = String(
            session.projection_instance_key || ""
        ) || null;
        App.selectedProjectionRevision = String(
            session.projection_revision || ""
        );
        var firstActivityId = parseInt(session.first_activity_id, 10);
        App.selectedTimelineAnchorActivityId = firstActivityId > 0
            ? firstActivityId
            : null;
        App.selectedTimelineWasInProgress = session.is_in_progress === true;
        var pane = document.getElementById("timeline-details-pane");
        if (pane) pane.classList.add("has-selection");
        return session;
    }

    function clearTimelineSelectionState() {
        App.selectedProjectionInstanceKey = null;
        App.selectedProjectionRevision = null;
        App.selectedTimelineAnchorActivityId = null;
        App.selectedTimelineWasInProgress = false;
        var pane = document.getElementById("timeline-details-pane");
        if (pane) pane.classList.remove("has-selection");
    }

    function resolveTimelineSelection(sessions) {
        var selectedKey = String(App.selectedProjectionInstanceKey || "");
        if (!selectedKey) return null;
        var candidates = Array.isArray(sessions) ? sessions : [];
        var exact = candidates.filter(function (session) {
            return String(session.projection_instance_key || "") === selectedKey;
        });
        if (exact.length === 1) return rememberTimelineSelection(exact[0]);
        var anchor = parseInt(App.selectedTimelineAnchorActivityId, 10);
        if (App.selectedTimelineWasInProgress === true && anchor > 0) {
            var anchored = candidates.filter(function (session) {
                return parseInt(session.first_activity_id, 10) === anchor;
            });
            if (anchored.length === 1) return rememberTimelineSelection(anchored[0]);
        }
        clearTimelineSelectionState();
        App.detailsOwner = null;
        return null;
    }
    App.resolveTimelineSelection = resolveTimelineSelection;

    function showTimeline(data) {
        if (!data) return;
        if (data.date) App.timelineDate = data.date;
        App.lastTimelineData = data;
        var dateInput = document.getElementById("timeline-date-input");
        if (dateInput) dateInput.value = data.date || "";
        App.renderTimelineTotal(data);
        loadProjects();
        App.renderCurrentActivityElement(
            document.getElementById("timeline-current"),
            data.current_activity || {},
            "timeline"
        );

        var listEl = document.getElementById("timeline-sessions-list");
        var allSessions = Array.isArray(data.entries) ? data.entries : [];
        App.currentSessions = allSessions;
        var sessions = App.filteredTimelineSessions(allSessions);
        if (sessions.length === 0) {
            listEl.innerHTML = '<div class="empty-state timeline-empty"><strong>'
                + (allSessions.length ? "当前筛选下没有时间段" : "当日暂无时间记录")
                + '</strong><span>'
                + (allSessions.length ? "可切换项目筛选查看其他时间段。" : "选择其他日期，或开始记录新的工作活动。")
                + '</span></div>';
            resetEmptyTimeline();
            return;
        }
        var hadSelection = !!App.selectedProjectionInstanceKey;
        if (hadSelection && !resolveTimelineSelection(sessions)) {
            resetEmptyTimeline();
            App.closeTimelineDrawer();
        }

        var _renderStart = (typeof performance !== "undefined" && performance.now)
            ? performance.now() : 0;
        var html = "";
        for (var i = 0; i < sessions.length; i++) {
            var session = sessions[i];
            var clock = App.timelinePresentation.exactRowClock(
                session,
                "aggregate_live",
                "timeline_session_invalid_live_clock"
            );
            var canTick = !!(clock && clock.is_live === true);
            var durable = Math.max(0, parseInt(session.duration_seconds, 10) || 0);
            var seconds = App.timelinePresentation.clockedSeconds(clock, durable);
            var durationText = App.formatTimelineDuration(seconds);
            var exactDurationText = durationText;
            var startText = App.formatTimelineStartTime(session.start_time);
            var scope = App.timelineProjectScope(session);
            var projectLabel = App.timelineProjectLabel(session);
            var continuityKey = canTick
                ? App.liveContinuityKey(session, "session")
                : "";
            var classes = "timeline-item";
            if (scope === "unclassified") classes += " uncategorized";
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
                + App.escapeHtml(exactDurationText) + '">'
                + '<div class="timeline-item-main">'
                + '<div class="timeline-item-project">' + App.escapeHtml(projectLabel) + '</div>'
                + '<div class="timeline-item-time">' + App.escapeHtml(startText) + '</div>'
                + '<div class="timeline-item-description'
                + (session.description_source === "derived" ? ' derived' : '') + '">'
                + App.escapeHtml(session.display_description || "暂无描述") + '</div>'
                + '</div><div class="timeline-item-side">'
                + '<div class="timeline-item-duration"' + clockAttributes
                + ' data-duration-seconds="' + String(seconds) + '" title="'
                + App.escapeHtml(exactDurationText) + '" aria-label="时长 '
                + App.escapeHtml(exactDurationText) + '">'
                + App.escapeHtml(durationText) + '</div>'
                + '</div></button>';
        }
        var _htmlBuildMs = _renderStart
            ? (performance.now() - _renderStart) : 0;
        var _commitStart = _renderStart ? performance.now() : 0;
        listEl.innerHTML = html;
        var _commitMs = _commitStart
            ? (performance.now() - _commitStart) : 0;
        App.lastTimelineRenderMs = {
            html_build_ms: Math.round(_htmlBuildMs * 100) / 100,
            dom_commit_ms: Math.round(_commitMs * 100) / 100,
            total_ms: Math.round((_htmlBuildMs + _commitMs) * 100) / 100,
            session_count: sessions.length
        };
        if (App.lastTimelineRenderMs.total_ms >= 50 && window.console && console.debug) {
            console.debug("timeline_render_ms", App.lastTimelineRenderMs);
        }
        if (!listEl._timelineDelegationBound) {
            listEl.addEventListener("click", function (event) {
                var itemEl = event.target.closest(".timeline-item");
                if (!itemEl) return;
                selectTimelineSession(
                    itemEl.getAttribute("data-projection-instance-key"),
                    App.currentSessions || []
                );
            });
            listEl.addEventListener("keydown", function (event) {
                if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
                var itemEl = event.target.closest(".timeline-item");
                if (!itemEl) return;
                event.preventDefault();
                var candidates = Array.prototype.slice.call(
                    listEl.querySelectorAll(".timeline-item")
                );
                var target = candidates[Math.max(0, Math.min(candidates.length - 1,
                    candidates.indexOf(itemEl) + (event.key === "ArrowDown" ? 1 : -1)))];
                if (target) target.focus();
            });
            listEl._timelineDelegationBound = true;
        }

        if (!App.selectedProjectionInstanceKey) return;
        var found = findSessionByProjectionKey(App.selectedProjectionInstanceKey);
        if (!found) {
            resetEmptyTimeline();
            return;
        }
        rememberTimelineSelection(found);
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
            App.clearEditPanel();
        } else if (
            !App.editingSession
            || App.editingSession.projection_instance_key !== found.projection_instance_key
            || !App.isEditDirty()
        ) {
            App.populateEditPanel(found);
        }
        App.timelineEditorState.setReadOnlyNotice(found);
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
        var selectionChanged = projectionInstanceKey !== App.selectedProjectionInstanceKey;
        if (selectionChanged) App.dismissTimelineContextTransientUi();
        if (selectionChanged
                && (App.editSaving || App.isEditDirty() || App.mutationState === "unknown")) {
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
        if (!found) {
            clearTimelineSelectionState();
            return;
        }
        rememberTimelineSelection(found);
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
        if (found.edit_disabled === true) App.clearEditPanel();
        else App.populateEditPanel(found);
        App.timelineEditorState.setReadOnlyNotice(found);
        updateSessionActionButtons(found);
        App.openTimelineDrawer(document.getElementById("timeline-details-close"));
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
        var sourceVersion = (
            App.lastTimelineData
                ? String(App.lastTimelineData.structure_revision || "")
                : ""
        );
        var request = App.bridge.getTimelineSessionActivitySummary(
            projectionInstanceKey || "",
            date,
            revision,
            sourceVersion
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
            App.renderSessionDetails(data);
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

    function loadProjects() {
        if (!App.projectCatalog) return Promise.resolve([]);
        return App.projectCatalog.load().then(function (catalog) {
            var editing = catalog ? catalog.editingProjects : App.projectCatalog.getEditing();
            var filter = catalog ? catalog.filterProjects : App.projectCatalog.getFilter();
            App.renderTimelineProjectFilter(filter || []);
            return editing || [];
        });
    }
    App.loadTimelineProjects = loadProjects;

    function confirmTimelineDeletion(operation, options, trigger) {
        App.dismissTimelineContextTransientUi();
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

    function blockDifferentMutationIntent() {
        App.showEditStatus("已有操作结果尚未确认，请先重试同一操作或刷新核对。", true);
    }

    function markMutationUnknown(owner) {
        App.timelineRequestState.markMutationUnknown(owner);
        App.timelineAutosaveQueued = false;
        App.setEditSaving(false);
        App.showEditStatus("操作结果尚未确认，可重试同一操作或刷新核对。", true);
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

    function rebaseEditingSessionAfterRefresh() {
        if (!App.editingSession || !App.selectedProjectionInstanceKey) return;
        var refreshed = findSessionByProjectionKey(App.selectedProjectionInstanceKey);
        if (!refreshed) return;
        if (refreshed.projection_instance_key !== App.editingSession.projection_instance_key) return;
        App.editingSession = refreshed;
        App.selectedProjectionRevision = refreshed.projection_revision || "";
        App.applyTimelineEditCapabilities(refreshed);
    }
    App.rebaseEditingSessionAfterRefresh = rebaseEditingSessionAfterRefresh;

    function settleSubmittedDurationIntent(submittedDraft) {
        if (
            !submittedDraft
            || submittedDraft.durationTouched !== true
            || App.timelineDurationDraftTouched !== true
        ) return;
        var durationElement = document.getElementById("edit-duration-input");
        var normalized = App.normalizeTimelineDurationInput(
            durationElement ? durationElement.value : ""
        );
        if (
            normalized.valid
            && normalized.seconds === submittedDraft.adjustedDurationSeconds
        ) {
            App.timelineDurationDraftTouched = false;
            App.timelineDurationDraftInvalid = false;
        }
    }

    function saveEdit() {
        if (!App.editingSession) return Promise.resolve(false);
        if (App.timelineDurationDraftInvalid === true) {
            var invalidDuration = App.normalizeTimelineDurationInput(
                (document.getElementById("edit-duration-input") || {}).value || ""
            );
            App.showEditStatus(invalidDuration.reason || "时长无效", true);
            return Promise.resolve(false);
        }
        if (App.timelineCompositionActive === true) {
            App.timelineAutosaveQueued = true;
            return Promise.resolve(false);
        }
        if (App.editSaving) {
            App.timelineAutosaveQueued = true;
            return App.timelineSavePromise || Promise.resolve(false);
        }
        var session = App.editingSession;
        var canProject = App.timelineEditorState.canEditField(session, "can_edit_project");
        var canNote = App.timelineEditorState.canEditField(session, "can_edit_note");
        var canDuration = App.timelineEditorState.canEditField(session, "can_edit_duration");
        if (!canProject && !canNote && !canDuration) {
            App.showEditStatus(session.disable_reason || "当前时段不可编辑", true);
            return Promise.resolve(false);
        }
        var select = document.getElementById("edit-project-select");
        var noteElement = document.getElementById("edit-note-text");
        if (!select || !noteElement) return Promise.resolve(false);
        var key = session.projection_instance_key || App.selectedProjectionInstanceKey;
        var revision = session.projection_revision || App.selectedProjectionRevision;
        if (!key || !revision) {
            App.showEditStatus("无法保存：时段版本无效，请刷新后重试", true);
            return Promise.resolve(false);
        }
        var originalProjectId = String(session.project_id || "");
        var projectIdText = canProject ? select.value : originalProjectId;
        var projectId = projectIdText ? parseInt(projectIdText, 10) : null;
        var projectChanged = canProject && projectIdText !== originalProjectId;
        if (projectChanged && (!projectId || !App.timelineEditorState.findCachedProject(projectId))) {
            App.showEditStatus("项目列表已过期，请刷新后重试", true);
            return Promise.resolve(false);
        }
        var originalNote = session.session_note || "";
        var note = canNote ? noteElement.value : originalNote;
        var noteChanged = canNote && note !== originalNote;
        if (
            noteChanged
            && note.length > App.TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH
        ) {
            App.showEditStatus("描述不能超过 200 个字符", true);
            return Promise.resolve(false);
        }
        var adjustedDurationSeconds = null;
        var durationTouched = canDuration
            && App.timelineDurationDraftTouched === true;
        var durationChanged = false;
        var durationElement = document.getElementById("edit-duration-input");
        var existingDurationOverride = session.has_duration_override === true
            ? parseInt(session.adjusted_duration_seconds, 10) : null;
        if (isNaN(existingDurationOverride)) existingDurationOverride = null;
        if (durationTouched) {
            var durationText = durationElement ? (durationElement.value || "").trim() : "";
            if (durationText === "") {
                adjustedDurationSeconds = null;
                durationChanged = existingDurationOverride !== null;
            } else {
                var normalizedDuration = App.normalizeTimelineDurationInput(durationText);
                if (!normalizedDuration.valid) {
                    App.showEditStatus(normalizedDuration.reason, true);
                    return Promise.resolve(false);
                }
                durationElement.value = normalizedDuration.text;
                adjustedDurationSeconds = normalizedDuration.seconds;
                durationChanged = existingDurationOverride === null
                    || adjustedDurationSeconds !== existingDurationOverride;
            }
        }
        if (!projectChanged && !noteChanged && !durationChanged) {
            App.showEditStatus("已保存", false);
            App.timelineLastSaveFailed = false;
            return Promise.resolve(true);
        }
        var reportDate = currentTimelineReportDate();
        if (!reportDate) {
            App.showEditStatus("无法保存：日期无效", true);
            return Promise.resolve(false);
        }
        App.setEditSaving(true);
        App.timelineLastSaveFailed = false;
        App.showEditStatus("", false);
        var overrideProjectId = canProject
            && (projectChanged || session.has_project_override === true)
            ? projectId
            : null;
        var owner = App.timelineRequestState.nextMutationOwner(
            "save_timeline_session_edit",
            reportDate,
            key,
            revision,
            JSON.stringify([
                overrideProjectId,
                durationTouched,
                adjustedDurationSeconds,
                note
            ])
        );
        if (!owner) {
            App.setEditSaving(false);
            blockDifferentMutationIntent();
            return Promise.resolve(false);
        }
        App.submittedDraft = {
            projectionInstanceKey: key,
            projectionRevision: revision,
            requestId: owner.requestId,
            projectId: overrideProjectId,
            note: note,
            durationTouched: durationTouched,
            adjustedDurationSeconds: adjustedDurationSeconds
        };
        var submittedDraft = App.submittedDraft;
        owner.payload = [
            reportDate,
            key,
            revision,
            owner.requestId,
            overrideProjectId,
            durationTouched,
            adjustedDurationSeconds,
            note
        ];
        var completion = App.bridge.saveTimelineSessionEdit.apply(null, owner.payload).then(function (result) {
            if (!App.timelineRequestState.isCurrentMutationOwner(owner)) return;
            if (!result || result.ok === false) {
                App.setEditSaving(false);
                App.timelineLastSaveFailed = true;
                App.showEditStatus(result && result.message ? result.message : "保存失败", true);
                App.timelineRequestState.releaseMutationOwner(owner, "confirmed_failure", result);
                drainPendingContextChange(false);
                return false;
            }
            App.timelineRequestState.transitionMutation(owner, "confirmed_success", result);
            consumeMutationResult(result);
            App.timelineRequestState.releaseMutationOwner(owner, "confirmed_success", result);
            App.showEditStatus("已自动保存", false);
            return refreshAfterConfirmedMutation().catch(function () {
                App.showEditStatus("操作已保存，但刷新失败", true);
                App.timelineLastSaveFailed = true;
                throw new Error("timeline_refresh_failed");
            }).then(function () {
                rebaseEditingSessionAfterRefresh();
                settleSubmittedDurationIntent(submittedDraft);
                return true;
            }).finally(function () {
                App.setEditSaving(false);
                if (App.timelineAutosaveQueued && App.isEditDirty()) {
                    App.timelineAutosaveQueued = false;
                    App.scheduleTimelineAutosave(0);
                } else {
                    App.timelineAutosaveQueued = false;
                    if (!App.isEditDirty()) App.submittedDraft = null;
                }
                drainPendingContextChange(true);
            });
        }).catch(function () {
            App.timelineLastSaveFailed = true;
            if (App.timelineRequestState.isCurrentMutationOwner(owner)) markMutationUnknown(owner);
            drainPendingContextChange(false);
            return false;
        });
        App.timelineSavePromise = completion.finally(function () {
            if (App.timelineSavePromise) App.timelineSavePromise = null;
            App.updateFDWorkEntryButton();
        });
        return App.timelineSavePromise;
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
        if (!App.editingSession) App.clearEditPanel();
        else App.populateEditPanel(App.editingSession);
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
        var anyAdvancedAllowed = false;
        for (var i = 0; i < fields.length; i++) {
            var button = document.getElementById(fields[i][0]);
            if (!button) continue;
            var allowed = !!(
                session
                && session[fields[i][1]]
                && !App.editSaving
            );
            button.hidden = !allowed;
            button.disabled = !allowed;
            if (i > 0 && allowed) anyAdvancedAllowed = true;
        }
        var toggle = document.getElementById("timeline-advanced-toggle");
        if (toggle) {
            toggle.hidden = !anyAdvancedAllowed;
            toggle.disabled = !anyAdvancedAllowed;
        }
        var menu = document.getElementById("timeline-session-actions");
        if (menu && !anyAdvancedAllowed) {
            App.closeTimelineAdvancedMenu({ restoreFocus: false });
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
        App.dismissTimelineContextTransientUi();
        var key = App.selectedProjectionInstanceKey;
        var date = currentTimelineReportDate();
        var revision = App.selectedProjectionRevision || "";
        if (!key || !date) return Promise.resolve();
        var mergeTarget = operationKey === "merge"
            ? findMergeTarget(key, options.direction)
            : null;
        if (operationKey === "merge" && !mergeTarget) {
            App.showEditStatus("只能合并相邻时段。", true);
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
                App.showEditStatus(message || "操作失败，请刷新后重试。", true);
            });
            if (!data) {
                App.timelineRequestState.releaseMutationOwner(owner, "confirmed_failure", result);
                return null;
            }
            App.timelineRequestState.transitionMutation(owner, "confirmed_success", result);
            consumeMutationResult(result);
            App.timelineRequestState.releaseMutationOwner(owner, "confirmed_success", result);
            App.showEditStatus("操作成功", false);
            return refreshAfterConfirmedMutation().catch(function () {
                App.showEditStatus("操作已保存，但刷新失败", true);
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
        clearTimelineSelectionState();
        App.timelineCompositionActive = false;
        App.detailsOwner = null;
        App.lastSessionDetailsViewModel = null;
        App.lastSessionActivitySummaryViewModel = null;
        var header = document.getElementById("timeline-details-header");
        var list = document.getElementById("timeline-details-list");
        if (header) header.textContent = "选择左侧时段查看详情";
        if (list) list.innerHTML = "";
        App.clearEditPanel();
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
        var bridgeRequest = (
            showLoading
            && resetSelection === false
            && rejectOnError === false
        ) ? App.requestCoordinator.share(
            "timeline-navigation",
            String(date || ""),
            function () { return App.bridge.getTimeline(date); }
        ) : App.bridge.getTimeline(date);
        return bridgeRequest.then(function (result) {
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

    function requestTimelineContextChange(actionFn, label) {
        var reason = label || "切换";
        App.dismissTimelineContextTransientUi();
        if (App.mutationState === "unknown") {
            App.showEditStatus("操作结果尚未确认，请先重试或刷新核对后再" + reason + "。", true);
            return Promise.resolve(false);
        }
        if (App.editSaving) {
            App.pendingContextChange = { action: actionFn, reason: reason };
            App.showEditStatus("正在保存当前更改，保存完成后自动" + reason + "。", false);
            return Promise.resolve(false);
        }
        if (App.isEditDirty()) {
            App.showEditStatus("正在保存当前更改，保存完成后自动" + reason + "。", false);
            App.pendingContextChange = { action: actionFn, reason: reason };
            saveEdit();
            return Promise.resolve(false);
        }
        return Promise.resolve().then(actionFn);
    }
    App.requestTimelineContextChange = requestTimelineContextChange;

    function drainPendingContextChange(saveSucceeded) {
        var pending = App.pendingContextChange;
        if (!pending) return;
        App.pendingContextChange = null;
        if (!saveSucceeded) {
            App.showEditStatus("保存失败，未" + pending.reason + "，请重试或刷新核对。", true);
            return;
        }
        try {
            pending.action();
        } catch (error) {
        }
    }
    App.drainPendingContextChange = drainPendingContextChange;
    function performTimelineRefresh(options) {
        options = options || {};
        return App.loadTimelineReport(currentTimelineReportDate(), {
            showLoading: false,
            resetSelection: false,
            errorMessage: "刷新失败",
            rejectOnError: options.rejectOnError === true
        });
    }

    function timelineEditingActive() {
        return typeof App._timelineEditingActive === "function"
            && App._timelineEditingActive();
    }

    function drainTimelineStructuralRefresh() {
        if (App.timelineStructuralRefreshPending !== true
            || App.currentPage !== "timeline"
            || timelineEditingActive()) {
            return Promise.resolve(false);
        }
        App.timelineStructuralRefreshPending = false;
        App.suppressNextTimelineCollectionRefresh = false;
        return Promise.resolve(performTimelineRefresh({ rejectOnError: true })).then(function () {
            return true;
        }).catch(function (error) {
            App.timelineStructuralRefreshPending = true;
            throw error;
        });
    }

    function refreshTimeline(options) {
        options = options || {};
        if (App.timelineStructuralRefreshPending === true && options.structuralDrain !== true) {
            return drainTimelineStructuralRefresh();
        }
        if (options.forceCollectionRefresh !== true
            && App.currentPage === "timeline"
            && App.suppressNextTimelineCollectionRefresh === true) {
            App.suppressNextTimelineCollectionRefresh = false;
            return Promise.resolve(null);
        }
        App.suppressNextTimelineCollectionRefresh = false;
        return performTimelineRefresh(options);
    }
    App.refreshTimeline = refreshTimeline;

    function onTimelineRuntimeTransition(change) {
        change = change || {};
        if (change.source !== "refresh-state" || App.currentPage !== "timeline") {
            return;
        }
        if (change.structureChanged === true) {
            App.suppressNextTimelineCollectionRefresh = false;
            if (timelineEditingActive()) App.timelineStructuralRefreshPending = true;
            return;
        }
        if (change.liveChanged === true) App.suppressNextTimelineCollectionRefresh = true;
    }

    function onTimelineRefreshRequested(options) {
        options = options || {};
        if (options.automatic === true) return refreshTimeline();
        App.suppressNextTimelineCollectionRefresh = false;
        return refreshTimeline({ forceCollectionRefresh: true });
    }

    function applyTimelineLocalTick() {
        if (App.currentPage !== "timeline" || App.timelineStructuralRefreshPending !== true) {
            return Promise.resolve(false);
        }
        return drainTimelineStructuralRefresh();
    }
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

    function resetTimelineGeneration() {
        if (App.timelineAutosaveTimer) window.clearTimeout(App.timelineAutosaveTimer);
        App.timelineAutosaveTimer = null;
        App.timelineAutosaveQueued = false;
        App.timelineLoaded = false;
        App.currentSessions = [];
        App.selectedProjectionInstanceKey = null;
        App.selectedProjectionRevision = null;
        App.selectedTimelineAnchorActivityId = null;
        App.selectedTimelineWasInProgress = false;
        App.editingSession = null;
        App.submittedDraft = null;
        App.pendingContextChange = null;
        App.editSaving = false;
        App.timelineCompositionActive = false;
        App.timelineDurationDraftTouched = false;
        App.detailsOwner = null;
        App.timelineOwner = null;
        App.mutationOwner = null;
        App.mutationState = "idle";
        App.detailsInFlight = {};
        App.lastTimelineData = null;
        App.lastSessionDetailsViewModel = null;
        App.lastSessionActivitySummaryViewModel = null;
        App.timelineRequestToken = (App.timelineRequestToken || 0) + 1;
        App.timelineStructuralRefreshPending = false;
        App.suppressNextTimelineCollectionRefresh = false;
        if (App.resetTimelineFDWorkState) App.resetTimelineFDWorkState();
        App.resetTimelineTransientUi();
    }
    App.timeline = Object.freeze({
        applyLocalTick: applyTimelineLocalTick,
        onRefreshRequested: onTimelineRefreshRequested,
        onRuntimeTransition: onTimelineRuntimeTransition,
        resetGeneration: resetTimelineGeneration
    });
})();
