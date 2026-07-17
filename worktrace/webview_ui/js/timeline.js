// WorkTrace WebView frontend — timeline module: session list, summary panel, P0 edit panel, and date navigation.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};


    function showTimeline(data) {
        if (!data) return;
        if (data.date) App.timelineDate = data.date;
        App.lastTimelineData = data;
        var nowMs = Date.now();
        var clock = App.getActiveLiveClock();
        var projectClock = clock && (clock.project_duration_live === true || clock.is_project_duration_live === true);
        var activeElapsedNowValue = App.computeActiveElapsedNow(clock, nowMs);
        var dateInput = document.getElementById("timeline-date-input");
        if (dateInput) dateInput.value = data.date || "";
        var todayStrForTotal = App.localTodayStr();
        var isTodayForTotal = !data.date || data.date === todayStrForTotal || data.date === "--";
        if (isTodayForTotal) {
            var totalBase = parseInt(data.today_total_base_seconds, 10);
            if (isNaN(totalBase)) totalBase = parseInt(data.today_total_seconds, 10) || 0;
            var totalSeconds = projectClock
                ? App.projectFromDisplayBase(totalBase, activeElapsedNowValue)
                : (parseInt(data.today_total_seconds, 10) || totalBase);
            if (projectClock) {
                App.setLiveProjectionAnchor(
                    document.getElementById("timeline-total"),
                    totalBase,
                    "timeline-total",
                    "timeline-total"
                );
            } else {
                App.clearLiveProjectionAnchor(document.getElementById("timeline-total"));
            }
            App.renderDurationProjected(
                document.getElementById("timeline-total"),
                totalSeconds,
                "timeline-total",
                { allowDecrease: false }
            );
        } else {
            App.clearLiveProjectionAnchor(document.getElementById("timeline-total"));
            App.renderDurationProjected(
                document.getElementById("timeline-total"),
                parseInt(data.today_total_seconds, 10) || 0,
                "timeline-total",
                { allowDecrease: true }
            );
        }
        App.renderCurrentActivityElement(
            document.getElementById("timeline-current"),
            data.current_activity || {},
            "timeline"
        );

        var listEl = document.getElementById("timeline-sessions-list");
        var sessions = data.entries || [];
        App.currentSessions = sessions;
        if (sessions.length === 0) {
            listEl.innerHTML = '<div class="timeline-empty">当日暂无活动记录</div>';
            // Invalidate any pending detail request and clear the detail cache so a stale response does not
            // backfill the cleared panel and the ticker does not project against a stale payload.
            App.lastSessionDetailsViewModel = null;
            App.lastSessionActivitySummaryViewModel = null;
            document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
            document.getElementById("timeline-details-list").innerHTML = "";
            App.selectedProjectionInstanceKey = null;
            App.selectedProjectionRevision = null;
            App.detailsOwner = null;
            clearEditPanel();
            return;
        }

        // Build the full HTML string before replacing to avoid flicker.
        var html = "";
        // Collect continuity keys after projecting to now so the first render
        // and the ticker share one no-rollback state.
        var sessionContinuityKeys = [];
        for (var i = 0; i < sessions.length; i++) {
            var s = sessions[i];
            var sessionCanTick = s.live_delta_eligible === true && !!s.display_span_id;
            // Live projection rows are non-editable while their activity is open; backend marks
            // ``edit_disabled=True`` so the edit panel stays disabled.
            if (s.is_live_projected === true
                && !s.display_span_id
                && typeof App.recordLiveClockContractViolation === "function") {
                App.recordLiveClockContractViolation("", "timeline", "session_live_row_missing_span_id");
            }
            var startTimeOnly = App.formatStartTimeOnly(s.start_time);
            var projectLabel = App.formatProjectLabel(s.project_name, s.project_description);
            var sDurSec = parseInt(s.duration_seconds, 10);
            var cls = "timeline-item";
            if (s.is_uncategorized) cls += " uncategorized";
            if (s.is_in_progress) cls += " in-progress";
            if (sessionCanTick) cls += " live-projected";
            if (s.projection_instance_key === App.selectedProjectionInstanceKey) cls += " selected";
            // Stable live key data attribute so the ticker / selection continuity locates the session DOM across
            // backend-owned persisted-open refreshes without relying on a
            // display-only activity identity.
            var stableKeyHash = s.stable_live_key_hash || "";
            // Active-span anchored DOM attributes: the row stores a static
            // base plus active elapsed offset; the ticker supplies the one
            // Timeline page active elapsed sample.
            var sessSpanId = sessionCanTick ? (s.display_span_id || "") : "";
            var rawSessionDurationSemantic = s.duration_semantic;
            var sessionDurationSemantic = String(rawSessionDurationSemantic || "").replace(/_/g, "-");
            if (sessionCanTick && sessSpanId && sessionDurationSemantic !== "aggregate-live") {
                if (typeof App.recordLiveClockContractViolation === "function") {
                    App.recordLiveClockContractViolation(
                        sessSpanId,
                        "timeline",
                        sessionDurationSemantic ? "timeline_session_non_aggregate_live" : "timeline_session_missing_duration_semantic"
                    );
                }
                sessSpanId = "";
                sessionDurationSemantic = "aggregate-live";
            }
            var sessContinuityKey = sessSpanId ? App.liveContinuityKey(s, "session") : "";
            var sessionDisplayBase = parseInt(s.display_base_seconds, 10);
            if (isNaN(sessionDisplayBase)) sessionDisplayBase = (!isNaN(sDurSec) && sDurSec >= 0) ? sDurSec : 0;
            var initialSec = (!isNaN(sDurSec) && sDurSec >= 0) ? sDurSec : 0;
            if (sessSpanId && projectClock) {
                initialSec = App.projectFromDisplayBase(sessionDisplayBase, activeElapsedNowValue);
            }
            var sessPrev = sessContinuityKey ? App._monotonicRenderState[sessContinuityKey] : null;
            if (sessPrev && typeof sessPrev.lastSeconds === "number" && initialSec < sessPrev.lastSeconds) {
                initialSec = sessPrev.lastSeconds;
            }
            var sDurText = (!isNaN(sDurSec) && sDurSec >= 0)
                ? App.formatDuration(initialSec)
                : (s.duration || "00:00:00");
            html += '<div class="' + cls + '" data-projection-instance-key="' + App.escapeHtml(s.projection_instance_key || "") + '"'
                + (stableKeyHash ? ' data-stable-live-key-hash="' + App.escapeHtml(stableKeyHash) + '"' : '')
                + (sessSpanId ? ' data-display-span-id="' + App.escapeHtml(sessSpanId) + '"' : '')
                + ' title="' + App.escapeHtml(projectLabel) + '｜' + App.escapeHtml(startTimeOnly) + '｜' + App.escapeHtml(sDurText) + '"'
                + '>'
                + '<div class="timeline-item-main">'
                + '<div class="timeline-item-project">' + App.escapeHtml(projectLabel) + '</div>'
                + '<div class="timeline-item-time">' + App.escapeHtml(startTimeOnly) + '</div>'
                + (s.has_duration_override ? '<div class="timeline-item-adjusted">已修正</div>' : '')
                + '</div>'
                + '<div class="timeline-item-side">'
                + '<div class="timeline-item-duration"'
                + (sessSpanId ? ' data-live-duration-target="1"' : '')
                + (sessSpanId ? ' data-duration-semantic="' + App.escapeHtml(sessionDurationSemantic) + '"' : '')
                + (sessSpanId ? ' data-display-span-id="' + App.escapeHtml(sessSpanId) + '"' : '')
                + (stableKeyHash ? ' data-stable-live-key-hash="' + App.escapeHtml(stableKeyHash) + '"' : '')
                + (sessSpanId ? ' data-display-base-seconds="' + sessionDisplayBase + '"' : '')
                + (sessSpanId ? ' data-live-base-seconds="' + sessionDisplayBase + '"' : '')
                + (sessSpanId ? ' data-live-role="timeline-session"' : '')
                + (sessContinuityKey ? ' data-live-continuity-key="' + App.escapeHtml(sessContinuityKey) + '"' : '')
                + ' data-duration-seconds="' + initialSec + '">' + App.escapeHtml(sDurText) + '</div>'
                + '<div class="timeline-item-count">' + App.escapeHtml(String(s.event_count || 0) + " 条") + '</div>'
                + '</div>'
                + '</div>';
            // Continuity key MUST use App.liveContinuityKey() so the ticker can locate the seeded state; a
            // ``stable_live_key_hash`` keeps the backend-owned live row
            // continuous when the surrounding session projection is rebuilt.
            if (sessContinuityKey) {
                sessionContinuityKeys.push({ key: sessContinuityKey, sec: initialSec });
            }
        }
        listEl.innerHTML = html;
        for (var ci = 0; ci < sessionContinuityKeys.length; ci++) {
            var ck = sessionContinuityKeys[ci];
            App._monotonicRenderState[ck.key] = { lastSeconds: ck.sec };
        }
        var items = listEl.querySelectorAll(".timeline-item");
        for (var j = 0; j < items.length; j++) {
            (function (itemEl) {
                itemEl.addEventListener("click", function () {
                    selectTimelineSession(itemEl.getAttribute("data-projection-instance-key"), sessions);
                });
            })(items[j]);
        }

        if (App.selectedProjectionInstanceKey) {
            var found = null;
            if (App.selectedProjectionInstanceKey) {
                for (var pk = 0; pk < sessions.length; pk++) {
                    if (sessions[pk].projection_instance_key === App.selectedProjectionInstanceKey) {
                        found = sessions[pk];
                        break;
                    }
                }
            }
            if (found) {
                // Update the selection anchors so a subsequent refresh can still find the session.
                App.selectedProjectionInstanceKey = found.projection_instance_key || null;
                App.selectedProjectionRevision = found.projection_revision || "";
                var owner = App.timelineRequestState.nextSelectionOwner(data.date, found.projection_instance_key, found.projection_revision || "");
                var skipDetailReload = (typeof App._timelineEditingActive === "function"
                    && App._timelineEditingActive());
                if (!skipDetailReload) {
                    loadSessionActivitySummary(found.projection_instance_key, data.date, found.projection_revision || "", owner);
                }
                // Only re-populate the edit panel if the user is not mid-edit AND the session is not edit-disabled.
                if (!found.edit_disabled
                    && (!App.editingSession || App.editingSession.projection_instance_key !== found.projection_instance_key || !isEditDirty())) {
                    populateEditPanel(found);
                } else if (found.edit_disabled) {
            // Persisted-open live session: clear the edit panel since it cannot be edited.
                    clearEditPanel();
                }
                updateSessionActionButtons(found);
            } else {
                // Selected session disappeared (e.g. re-grouped). Invalidate the pending detail request and clear
                // the detail cache so a stale response does not backfill the cleared panel.
                App.lastSessionDetailsViewModel = null;
                App.lastSessionActivitySummaryViewModel = null;
                App.selectedProjectionInstanceKey = null;
                App.selectedProjectionRevision = null;
                document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
                document.getElementById("timeline-details-list").innerHTML = "";
                clearEditPanel();
            }
        }
    }
    App.showTimeline = showTimeline;

function acceptTimelinePayload(data, date) {
    if (!data || !data.ok) return false;
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
        if (App.isPagePayloadCompatibleWithRuntime(data, "timeline", date)) {
            App.acceptLiveRuntimePayload(data, "timeline", date, {
                source: "details_model"
            });
        } else {
            // Detail payloads may still provide static summaries. Do not
            // turn a live-overlay mismatch into a whole-page refresh loop.
            App.timelineDetailsRuntimeMismatch = "runtime_mismatch";
        }
        return true;
    }
    App.acceptTimelineDetailsPayload = acceptTimelineDetailsPayload;

    function selectTimelineSession(projectionInstanceKey, sessions) {
        App.selectedProjectionInstanceKey = projectionInstanceKey;
        // Update selected class from the canonical projection identity.
        var items = document.querySelectorAll("#timeline-sessions-list .timeline-item");
        var newSelected = null;
        for (var j0 = 0; j0 < sessions.length; j0++) {
            if (sessions[j0].projection_instance_key === projectionInstanceKey) {
                newSelected = sessions[j0];
                break;
            }
        }
        for (var i = 0; i < items.length; i++) {
            items[i].classList.remove("selected");
            if (items[i].getAttribute("data-projection-instance-key") === projectionInstanceKey) {
                items[i].classList.add("selected");
            }
        }
        var found = newSelected;
        if (found) {
            App.selectedProjectionRevision = found.projection_revision || "";
            var owner = App.timelineRequestState.nextSelectionOwner(App.timelineDate, found.projection_instance_key, found.projection_revision || "");
            loadSessionActivitySummary(found.projection_instance_key, App.timelineDate, found.projection_revision || "", owner);
            // Open live sessions are non-editable; a manual click must clear the edit panel.
            if (found.edit_disabled === true) {
                clearEditPanel();
            } else {
                // A manual click always repopulates the edit panel, even if a prior auto-refresh skipped it.
                populateEditPanel(found);
            }
            updateSessionActionButtons(found);
        }
    }
    App.selectTimelineSession = selectTimelineSession;

    function loadSessionActivitySummary(projectionInstanceKey, date, detailRevision, owner) {
        return loadSessionDetails(projectionInstanceKey, date, detailRevision, false, owner);
    }
    App.loadSessionActivitySummary = loadSessionActivitySummary;

    function loadSessionDetails(projectionInstanceKey, date, detailRevision, retriedStale, existingOwner) {
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        var revision = String(detailRevision || App.selectedProjectionRevision || "");
        var owner = existingOwner || App.timelineRequestState.nextSelectionOwner(date, projectionInstanceKey, revision);
        var requestKey = App.timelineRequestState.detailRequestKey(owner);
        if (App.detailsInFlight[requestKey]) return App.detailsInFlight[requestKey];
        // Only show loading when the panel is empty; keep existing summaries visible during refresh.
        if (!detailsList.innerHTML.trim()) {
            detailsHeader.textContent = "加载项目活动耗时…";
            detailsList.innerHTML = "";
        } else {
            detailsHeader.textContent = "正在刷新项目活动耗时…";
        }

        var request = App.bridge.getTimelineSessionActivitySummary(projectionInstanceKey || "", date, revision).then(function (result) {
            if (!App.timelineRequestState.isCurrentDetailsOwner(owner)) return null;
            if (result && result.ok === false && result.error === "stale_selection" && !retriedStale) {
                // The current owner asks for one Timeline refresh and then stops.
                // showTimeline/selectTimelineSession becomes the only owner of any follow-up detail request.
                return App.loadTimelineReport(date, { showLoading: false, resetSelection: false }).then(function () {
                    var selected = findSessionByProjectionKey(App.selectedProjectionInstanceKey);
                    if (!selected) {
                        resetTimelineReportSelection();
                        return null;
                    }
                    var retryOwner = App.timelineRequestState.nextSelectionOwner(date, selected.projection_instance_key, selected.projection_revision || "");
                    App.selectedProjectionRevision = selected.projection_revision || "";
                    return loadSessionDetails(selected.projection_instance_key, date, selected.projection_revision || "", true, retryOwner);
                });
            }
            var data = App.handleResult(result, function (msg) {
                if (!App.timelineRequestState.isCurrentDetailsOwner(owner)) return;
                detailsHeader.textContent = "加载项目活动耗时失败";
                detailsList.innerHTML = '<div class="timeline-empty">' + App.escapeHtml(msg) + '</div>';
            });
            if (!data) return null;
            if (!App.timelineRequestState.isCurrentDetailsOwner(owner)) return null;
            if (!acceptTimelineDetailsPayload(data, date)) return null;
            renderSessionDetails(data);
            return data;
        }).catch(function () {
            if (!App.timelineRequestState.isCurrentDetailsOwner(owner)) return null;
            detailsHeader.textContent = "加载项目活动耗时失败";
            detailsList.innerHTML = '<div class="timeline-empty">无法加载项目活动耗时，请稍后重试。</div>';
            return null;
        }).finally(function () {
            if (App.detailsInFlight[requestKey] === request) delete App.detailsInFlight[requestKey];
        });
        App.detailsInFlight[requestKey] = request;
        return request;
    }
    App.loadSessionDetails = loadSessionDetails;

    function renderSessionDetails(data) {
        if (typeof App._timelineEditingActive === "function" && App._timelineEditingActive()) {
            return;
        }
        var nowMs = Date.now();
        var activeClock = App.getActiveLiveClock();
        var projectClock = activeClock && (activeClock.project_duration_live === true || activeClock.is_project_duration_live === true);
        var activeElapsedNowValue = App.computeActiveElapsedNow(activeClock, nowMs);
        if (App.lastTimelineData) {
            App.lastTimelineData.current_activity = data.current_activity || App.lastTimelineData.current_activity || {};
        }
        // Structural cache only — used for re-render on page switch /
        // edit-guard checks. Live seconds come from DOM anchors plus the
        // accepted live runtime; this cache MUST NOT be read as a live-seconds source.
        App.lastSessionDetailsViewModel = data;
        App.lastSessionActivitySummaryViewModel = data;
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        var rows = data.summary_rows || [];
        if (rows.length === 0) {
            detailsHeader.textContent = "项目活动耗时";
            detailsList.innerHTML = '<div class="timeline-empty">该时段暂无活动耗时</div>';
            return;
        }
        detailsHeader.textContent = "项目活动耗时";
        var html = "";
        var summaryContinuityKeys = [];
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var summaryCanTick = row.live_delta_eligible === true && !!row.display_span_id;
            if (row.is_live_projected === true
                && !row.display_span_id
                && typeof App.recordLiveClockContractViolation === "function") {
                App.recordLiveClockContractViolation("", "timeline", "summary_live_row_missing_span_id");
            }
            var displayName = row.activity_name || "未知";
            var durationSeconds = parseInt(row.duration_seconds, 10);
            var cls = "summary-item";
            if (row.is_in_progress) cls += " in-progress";
            if (summaryCanTick) cls += " live-projected";
            var summaryStableKey = row.stable_live_key_hash || "";
            var summarySpanId = summaryCanTick ? (row.display_span_id || "") : "";
            var summaryContinuityKey = summarySpanId ? App.liveContinuityKey(row, "project-summary") : "";
            var summaryDurationSemantic = String(row.duration_semantic || "aggregate_live").replace(/_/g, "-");
            var summaryDisplayBase = parseInt(row.display_base_seconds, 10);
            if (isNaN(summaryDisplayBase)) summaryDisplayBase = (!isNaN(durationSeconds) && durationSeconds >= 0) ? durationSeconds : 0;
            var initialSec = (!isNaN(durationSeconds) && durationSeconds >= 0) ? durationSeconds : 0;
            if (summarySpanId && projectClock) {
                initialSec = App.projectFromDisplayBase(summaryDisplayBase, activeElapsedNowValue);
            }
            var summaryPrev = summaryContinuityKey ? App._monotonicRenderState[summaryContinuityKey] : null;
            if (summaryPrev && typeof summaryPrev.lastSeconds === "number" && initialSec < summaryPrev.lastSeconds) {
                initialSec = summaryPrev.lastSeconds;
            }
            var durationText = (!isNaN(durationSeconds) && durationSeconds >= 0)
                ? App.formatDuration(initialSec)
                : (row.duration || "00:00:00");
            var projectLabel = row.display_project_name || "未归类";
            html += '<div class="' + cls + '" data-summary-id="' + App.escapeHtml(String(row.summary_id || "")) + '"'
                + (summaryStableKey ? ' data-stable-live-key-hash="' + App.escapeHtml(summaryStableKey) + '"' : '')
                + (summarySpanId ? ' data-display-span-id="' + App.escapeHtml(summarySpanId) + '"' : '')
                + ' data-summary-index="' + i + '"'
                + '>'
                + '<div class="summary-item-duration"'
                + (summarySpanId ? ' data-live-duration-target="1"' : '')
                + (summarySpanId ? ' data-duration-semantic="' + App.escapeHtml(summaryDurationSemantic) + '"' : '')
                + (summarySpanId ? ' data-display-span-id="' + App.escapeHtml(summarySpanId) + '"' : '')
                + (summaryStableKey ? ' data-stable-live-key-hash="' + App.escapeHtml(summaryStableKey) + '"' : '')
                + (summarySpanId ? ' data-display-base-seconds="' + summaryDisplayBase + '"' : '')
                + (summarySpanId ? ' data-live-base-seconds="' + summaryDisplayBase + '"' : '')
                + (summarySpanId ? ' data-live-role="timeline-detail"' : '')
                + (summaryContinuityKey ? ' data-live-continuity-key="' + App.escapeHtml(summaryContinuityKey) + '"' : '')
                + ' data-duration-seconds="' + initialSec + '">' + App.escapeHtml(durationText) + '</div>'
                + '<div class="summary-item-name" title="' + App.escapeHtml(displayName) + '">' + App.escapeHtml(displayName) + '</div>'
                + '<div class="summary-item-project" title="' + App.escapeHtml(projectLabel) + '">' + App.escapeHtml(projectLabel) + '</div>'
                + (row.can_hide_activity ? '<button type="button" class="summary-hide-activity" data-summary-id="' + App.escapeHtml(String(row.summary_id || "")) + '">从该时段移除该活动</button>' : '')
                + '</div>';
            summaryContinuityKeys.push({ index: i, sec: initialSec, key: summaryContinuityKey });
        }
        detailsList.innerHTML = html;
        var removeButtons = detailsList.querySelectorAll(".summary-hide-activity");
        for (var rb = 0; rb < removeButtons.length; rb++) {
            removeButtons[rb].addEventListener("click", function (event) {
                event.stopPropagation();
                App.runTimelineSessionOperation("hideActivity", { summaryId: this.getAttribute("data-summary-id") });
            });
        }
        for (var si = 0; si < summaryContinuityKeys.length; si++) {
            var skey = summaryContinuityKeys[si];
            var summaryKey = skey.key || "";
            if (!summaryKey) continue;
            App._monotonicRenderState[summaryKey] = { lastSeconds: skey.sec };
        }
    }
    App.renderSessionDetails = renderSessionDetails;

    function renderSessionActivitySummary(data) {
        return renderSessionDetails(data);
    }
    App.renderSessionActivitySummary = renderSessionActivitySummary;


    function loadProjects() {
        // Load and cache the selectable projects list so we do not hit the bridge on every session select.
        if (App.projectsCache || App.projectsLoading) {
            return Promise.resolve(App.projectsCache);
        }
        App.projectsLoading = true;
        return App.bridge.listProjectsForTimeline().then(function (result) {
            App.projectsLoading = false;
            if (result && result.ok !== false && result.projects) {
                App.projectsCache = result.projects;
            }
            return App.projectsCache;
        }).catch(function () {
            App.projectsLoading = false;
            return null;
        });
    }
    App.loadProjects = loadProjects;

    function renderProjectSelect(projects, currentProjectId) {
        var select = document.getElementById("edit-project-select");
        if (!select) return;
        select.innerHTML = "";
        if (!projects || projects.length === 0) {
            var failOpt = document.createElement("option");
            failOpt.value = "";
            failOpt.textContent = "项目列表加载失败";
            select.appendChild(failOpt);
            select.disabled = true;
            return;
        }
        for (var i = 0; i < projects.length; i++) {
            var p = projects[i];
            var option = document.createElement("option");
            option.value = String(p.id);
            var label = p.name || "";
            if (p.description) {
                label += " (" + p.description + ")";
            }
            option.textContent = label;
            if (currentProjectId && String(p.id) === String(currentProjectId)) {
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
        var noteEl = document.getElementById("edit-note-text");
        var durInput = document.getElementById("edit-duration-input");
        var saveBtn = document.getElementById("edit-save-btn");
        var cancelBtn = document.getElementById("edit-cancel-btn");
        if (select) select.disabled = App.editSaving || !projectAllowed || !App.projectsCache;
        if (noteEl) noteEl.disabled = App.editSaving || !noteAllowed;
        if (durInput) durInput.disabled = App.editSaving || !durationAllowed;
        if (cancelBtn) cancelBtn.disabled = App.editSaving || !session;
        if (saveBtn) {
            var noteLength = noteEl ? noteEl.value.length : 0;
            saveBtn.disabled = App.editSaving
                || !hasEditableFields(session)
                || (noteAllowed && noteLength > 2000);
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

        // Project select: load projects lazily on first use, then reuse cache.
        var select = document.getElementById("edit-project-select");
        if (select && !App.projectsCache) {
            select.innerHTML = '<option value="">加载中…</option>';
            select.disabled = true;
            loadProjects().then(function (projects) {
                // Only render if we are still editing the same session.
                if (App.editingSession && App.editingSession.projection_instance_key === session.projection_instance_key) {
                    renderProjectSelect(projects, session.project_id);
                }
            });
        } else if (select && App.projectsCache) {
            renderProjectSelect(App.projectsCache, session.project_id);
        }

        // Duration override input (minutes). Derived from the session's
        // adjusted / raw / display seconds so the user sees the current
        // value. An empty input on save means "use real duration" (clear
        // the override).
        var durInput = document.getElementById("edit-duration-input");
        if (durInput) {
            var durSrc = (session.adjusted_duration_seconds != null)
                ? session.adjusted_duration_seconds
                : session.duration_seconds;
            var durMin = Math.round((parseInt(durSrc, 10) || 0) / 60);
            durInput.value = isNaN(durMin) ? "" : String(durMin);
            durInput.disabled = !canEditField(session, "can_edit_duration");
        }
        var durStatusEl = document.getElementById("edit-duration-status");
        if (durStatusEl) {
            durStatusEl.textContent = session.has_duration_override ? "已修正" : "";
        }

        var noteEl = document.getElementById("edit-note-text");
        if (noteEl) {
            noteEl.value = session.session_note || "";
            noteEl.disabled = !canEditField(session, "can_edit_note");
        }

        // Enable save/cancel first, then updateNoteCount applies the over-limit disable.
        var saveBtn = document.getElementById("edit-save-btn");
        var cancelBtn = document.getElementById("edit-cancel-btn");
        if (saveBtn) saveBtn.disabled = !hasEditableFields(session);
        if (cancelBtn) cancelBtn.disabled = false;
        if (noteEl) updateNoteCount();
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
        var noteEl = document.getElementById("edit-note-text");
        if (noteEl) {
            noteEl.value = "";
            noteEl.disabled = true;
        }
        var select = document.getElementById("edit-project-select");
        if (select) {
            select.innerHTML = '<option value="">加载中…</option>';
            select.disabled = true;
        }
        var durInput = document.getElementById("edit-duration-input");
        if (durInput) {
            durInput.value = "";
            durInput.disabled = true;
        }
        var durStatusEl = document.getElementById("edit-duration-status");
        if (durStatusEl) {
            durStatusEl.textContent = "";
        }
        var saveBtn = document.getElementById("edit-save-btn");
        var cancelBtn = document.getElementById("edit-cancel-btn");
        if (saveBtn) saveBtn.disabled = true;
        if (cancelBtn) cancelBtn.disabled = true;
        showEditStatus("", false);
    }
    App.clearEditPanel = clearEditPanel;

    function isEditDirty() {
        if (!App.editingSession) return false;
        var session = App.editingSession;
        var noteEl = document.getElementById("edit-note-text");
        var select = document.getElementById("edit-project-select");
        var durInput = document.getElementById("edit-duration-input");
        if (canEditField(session, "can_edit_note") && noteEl) {
            if (noteEl.value !== (session.session_note || "")) return true;
        }
        if (canEditField(session, "can_edit_project") && select && select.value) {
            if (select.value !== String(session.project_id || "")) return true;
        }
        if (canEditField(session, "can_edit_duration") && durInput) {
            var baselineSeconds = (session.adjusted_duration_seconds != null)
                ? session.adjusted_duration_seconds
                : session.duration_seconds;
            var baselineMin = Math.round((parseInt(baselineSeconds, 10) || 0) / 60);
            var baselineValue = isNaN(baselineMin) ? "" : String(baselineMin);
            if ((durInput.value || "").trim() !== baselineValue) return true;
        }
        return false;
    }
    App.isEditDirty = isEditDirty;

    function updateNoteCount() {
        var textarea = document.getElementById("edit-note-text");
        var counter = document.getElementById("edit-note-count");
        var status = document.getElementById("edit-status");
        if (!textarea || !counter) return;
        var len = textarea.value.length;
        counter.textContent = len + " / 2000";
        counter.classList.toggle("over-limit", len > 2000);
        if (len > 2000 && status) {
            status.textContent = "备注不能超过 2000 个字符";
            status.classList.add("error");
        } else if (status && status.textContent === "备注不能超过 2000 个字符") {
            showEditStatus("", false);
        }
        applyEditCapabilities(App.editingSession);
    }
    App.updateNoteCount = updateNoteCount;

    function showEditStatus(message, isError) {
        var statusEl = document.getElementById("edit-status");
        if (!statusEl) return;
        if (!message) {
            statusEl.hidden = true;
            statusEl.textContent = "";
            statusEl.className = "edit-status";
            return;
        }
        statusEl.hidden = false;
        statusEl.textContent = message;
        statusEl.className = "edit-status " + (isError ? "edit-status-error" : "edit-status-success");
    }
    App.showEditStatus = showEditStatus;

    function setEditSaving(saving) {
        App.editSaving = saving;
        if (saving) {
            var saveBtn = document.getElementById("edit-save-btn");
            var cancelBtn = document.getElementById("edit-cancel-btn");
            var select = document.getElementById("edit-project-select");
            var noteEl = document.getElementById("edit-note-text");
            var durInput = document.getElementById("edit-duration-input");
            if (saveBtn) saveBtn.disabled = true;
            if (cancelBtn) cancelBtn.disabled = true;
            if (select) select.disabled = true;
            if (noteEl) noteEl.disabled = true;
            if (durInput) durInput.disabled = true;
            return;
        }
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
            hint.projection_instance_key || hint.instance_key || hint.key || ""
        ) || null;
        App.selectedProjectionRevision = String(
            hint.projection_revision || hint.revision || ""
        );
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
        var noteEl = document.getElementById("edit-note-text");
        if (!select || !noteEl) return;

        var projectionInstanceKey = session.projection_instance_key || App.selectedProjectionInstanceKey;
        var projectionRevision = session.projection_revision || App.selectedProjectionRevision;
        if (!projectionInstanceKey || !projectionRevision) {
            showEditStatus("无法保存：时段版本无效，请刷新后重试", true);
            return;
        }

        var originalProjectId = String(session.project_id || "");
        var originalNote = session.session_note || "";
        var projectIdStr = canProject ? select.value : originalProjectId;
        var projectId = projectIdStr ? parseInt(projectIdStr, 10) : null;
        if (canProject && (!projectId || projectId <= 0)) {
            showEditStatus("请选择项目", true);
            return;
        }
        var selectedProject = projectId ? findCachedProject(projectId) : null;
        if (canProject && !selectedProject) {
            showEditStatus("项目列表已过期，请刷新后重试", true);
            return;
        }
        if (canProject && !App.projectSelectableForEditing(selectedProject)) {
            showEditStatus("所选项目当前不可编辑，请刷新后选择其他项目", true);
            return;
        }

        var note = canNote ? noteEl.value : originalNote;
        if (canNote && note.length > 2000) {
            showEditStatus("备注不能超过 2000 个字符", true);
            return;
        }
        var projectChanged = canProject && projectIdStr !== originalProjectId;
        var noteChanged = canNote && note !== originalNote;

        var adjustedDurationSeconds = null;
        var durationChanged = false;
        var durInput = document.getElementById("edit-duration-input");
        if (canDuration) {
            var durRawValue = durInput ? (durInput.value || "").trim() : "";
            if (durRawValue !== "") {
                var durMinutes = parseInt(durRawValue, 10);
                if (isNaN(durMinutes) || durMinutes < 0) {
                    showEditStatus("时长需为非负整数", true);
                    return;
                }
                adjustedDurationSeconds = durMinutes * 60;
            }
            var durBaselineSrc = (session.adjusted_duration_seconds != null)
                ? session.adjusted_duration_seconds
                : session.duration_seconds;
            var durBaselineMin = Math.round((parseInt(durBaselineSrc, 10) || 0) / 60);
            var durBaselineStr = isNaN(durBaselineMin) ? "" : String(durBaselineMin);
            durationChanged = durRawValue !== durBaselineStr;
        } else if (session.has_duration_override === true) {
            adjustedDurationSeconds = parseInt(session.adjusted_duration_seconds, 10);
            if (isNaN(adjustedDurationSeconds)) adjustedDurationSeconds = null;
        }

        if (!projectChanged && !noteChanged && !durationChanged) {
            showEditStatus("没有需要保存的更改", false);
            return;
        }

        var dateEl = document.getElementById("timeline-date-input");
        var reportDate = App.timelineDate || (dateEl ? dateEl.value : null);
        if (reportDate === "--" || reportDate === "") reportDate = null;
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
        var mutationOwner = App.timelineRequestState.nextMutationOwner(
            "save_timeline_session_edit",
            reportDate,
            projectionInstanceKey,
            projectionRevision,
            JSON.stringify([overrideProjectId, adjustedDurationSeconds, note])
        );
        if (!mutationOwner) {
            setEditSaving(false);
            blockDifferentMutationIntent();
            return;
        }
        mutationOwner.payload = [
            reportDate, projectionInstanceKey, projectionRevision, mutationOwner.requestId,
            overrideProjectId, adjustedDurationSeconds, note
        ];
        App.bridge.saveTimelineSessionEdit(reportDate,
            projectionInstanceKey,
            projectionRevision,
            mutationOwner.requestId,
            overrideProjectId,
            adjustedDurationSeconds,
            note
        ).then(function (result) {
            if (!App.timelineRequestState.isCurrentMutationOwner(mutationOwner)) return;
            if (!result || result.ok === false) {
                setEditSaving(false);
                showEditStatus(result && result.message ? result.message : "保存失败", true);
                App.timelineRequestState.releaseMutationOwner(mutationOwner, "confirmed_failure", result);
                return;
            }
            App.timelineRequestState.transitionMutation(mutationOwner, "confirmed_success", result);
            consumeMutationResult(result);
            setEditSaving(false);
            App.timelineRequestState.releaseMutationOwner(mutationOwner, "confirmed_success", result);
            showEditStatus("保存成功", false);
            return refreshAfterConfirmedMutation().catch(function () {
                showEditStatus("操作已保存，但刷新失败", true);
            });
        }).catch(function () {
            if (!App.timelineRequestState.isCurrentMutationOwner(mutationOwner)) return;
            markMutationUnknown(mutationOwner);
        });
    }
    App.saveEdit = saveEdit;


    function refreshTimelineAfterEdit() {
        return App.loadTimelineReport(currentTimelineReportDate(), {
            showLoading: false,
            resetSelection: false,
            errorMessage: "刷新失败"
        });
    }
    App.refreshTimelineAfterEdit = refreshTimelineAfterEdit;

    function cancelEdit() {
        if (App.editSaving) return;
        if (!App.editingSession) {
            clearEditPanel();
            return;
        }
        populateEditPanel(App.editingSession);
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
    hide: Object.freeze({ intent: "hide_timeline_session", invoke: function () { return App.bridge.hideTimelineSession.apply(null, arguments); } }),
    hideActivity: Object.freeze({ intent: "hide_timeline_session_activity", invoke: function () { return App.bridge.hideTimelineSessionActivity.apply(null, arguments); } }),
    merge: Object.freeze({ intent: "merge_timeline_session", invoke: function () { return App.bridge.mergeTimelineSession.apply(null, arguments); } }),
    split: Object.freeze({ intent: "split_timeline_session", invoke: function () { return App.bridge.splitTimelineSession.apply(null, arguments); } }),
    copy: Object.freeze({ intent: "copy_timeline_session", invoke: function () { return App.bridge.copyTimelineSession.apply(null, arguments); } })
});

function runTimelineSessionOperation(operationKey, options) {
    options = options || {};
    var operation = TIMELINE_OPERATIONS[operationKey];
    if (!operation) return Promise.reject(new Error("unsupported_timeline_operation"));
    var method = operation.intent;
    var key = App.selectedProjectionInstanceKey;
    var date = currentTimelineReportDate();
    var revision = App.selectedProjectionRevision || "";
    if (!key || !date) return Promise.resolve();
    var mergeTarget = operationKey === "merge" ? findMergeTarget(key, options.direction) : null;
    if (operationKey === "merge" && !mergeTarget) {
        showEditStatus("只能合并相邻时段。", true);
        return Promise.resolve();
    }
    var argsSignature = JSON.stringify([
        options || {},
        mergeTarget ? mergeTarget.projection_instance_key || "" : "",
        mergeTarget ? mergeTarget.projection_revision || "" : ""
    ]);
    var owner = App.timelineRequestState.nextMutationOwner(method, date, key, revision, argsSignature);
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
        if (!App.timelineRequestState.isCurrentMutationOwner(owner)) return null;
        markMutationUnknown(owner);
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
            if (targetIndex < 0 || targetIndex >= sessions.length) return null;
            return sessions[targetIndex];
        }
        return null;
    }


    function normalizeTimelineReportDate(date) {
        if (date === "--" || date === "") return null;
        return date || null;
    }
    App.normalizeTimelineReportDate = normalizeTimelineReportDate;

    function currentTimelineReportDate() {
        var dateEl = document.getElementById("timeline-date-input");
        return normalizeTimelineReportDate(App.timelineDate || (dateEl ? dateEl.value : null));
    }
    App.currentTimelineReportDate = currentTimelineReportDate;

    function resetTimelineReportSelection() {
        App.selectedProjectionInstanceKey = null;
        App.selectedProjectionRevision = null;
        App.detailsOwner = null;
        App.lastSessionDetailsViewModel = null;
        App.lastSessionActivitySummaryViewModel = null;
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        if (detailsHeader) detailsHeader.textContent = "选择左侧时段查看详情";
        if (detailsList) detailsList.innerHTML = "";
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
        var errorMessage = options.errorMessage || (showLoading ? "加载时间线失败" : "刷新失败");
        var rejectOnError = options.rejectOnError === true;
        var timelineOwner = App.timelineRequestState.nextTimelineOwner(date);
        App.timelineDate = date;
        if (resetSelection) {
            resetTimelineReportSelection();
        }
        var loadingOwner = "";
        if (showLoading) {
            loadingOwner = timelineOwner;
            App.timelineLoadingOwner = loadingOwner;
            App.setTimelineLoading(true);
            App.clearTimelineError();
        }
        var token = ++App.timelineRequestToken;
        return App.bridge.getTimeline(date).then(function (result) {
            if (token !== App.timelineRequestToken || App.timelineOwner !== timelineOwner) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                App.showTimelineError(msg || errorMessage);
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
            if (token !== App.timelineRequestToken || App.timelineOwner !== timelineOwner) return;  // stale response
            // Never surface raw exception text; use the stable fallback so
            // internal details do not leak into the UI.
            App.showTimelineError(errorMessage);
            if (rejectOnError) throw new Error("timeline_refresh_failed");
        }).then(function () {
            releaseTimelineLoadingOwner(loadingOwner);
        }, function (err) {
            releaseTimelineLoadingOwner(loadingOwner);
            throw err;
        });
    }

    function loadTimeline(date) {
        return App.loadTimelineReport(date, { showLoading: true, resetSelection: false });
    }
    App.loadTimeline = loadTimeline;
    App.loadTimelineReport = timelineReportRequest;

    function refreshTimeline() {
        // Silent refresh: do not show loading spinner, just reload data.
        // On error, keep showing the previous data so the user is not left
        // looking at an empty list; only the error banner is shown.
        return App.loadTimelineReport(currentTimelineReportDate(), {
            showLoading: false,
            resetSelection: false,
            errorMessage: "刷新失败"
        });
    }
    App.refreshTimeline = refreshTimeline;

    function reloadTimelineAfterRuntimeRefresh(date) {
        return App.loadTimelineReport(date, { showLoading: true, resetSelection: true });
    }


    function goPrevDay() {
        var dateEl = document.getElementById("timeline-date-input");
        var current = App.timelineDate || (dateEl ? dateEl.value : null);
        App.loadTimelineReport(App.shiftDate(current, -1), { showLoading: true, resetSelection: true });
    }
    App.goPrevDay = goPrevDay;

    function goNextDay() {
        var dateEl = document.getElementById("timeline-date-input");
        var current = App.timelineDate || (dateEl ? dateEl.value : null);
        App.loadTimelineReport(App.shiftDate(current, 1), { showLoading: true, resetSelection: true });
    }
    App.goNextDay = goNextDay;

    function goToday() {
        App.loadTimelineReport(null, { showLoading: true, resetSelection: true });
    }
    App.goToday = goToday;

})();
