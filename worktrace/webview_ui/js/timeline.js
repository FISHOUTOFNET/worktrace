// WorkTrace WebView frontend — timeline module: session list, summary panel, P0 edit panel, and date navigation.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};


    function showTimeline(data) {
        if (!data) return;
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
        var sessions = data.sessions || [];
        App.currentSessions = sessions;
        if (sessions.length === 0) {
            listEl.innerHTML = '<div class="timeline-empty">当日暂无活动记录</div>';
            // Invalidate any pending detail request and clear the detail cache so a stale response does not
            // backfill the cleared panel and the ticker does not project against a stale payload.
            ++App.detailsRequestToken;
            App.lastSessionDetailsViewModel = null;
            App.lastSessionActivitySummaryViewModel = null;
            document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
            document.getElementById("timeline-details-list").innerHTML = "";
            App.selectedSessionId = null;
            App.selectedSessionLiveKey = null;
            App.selectedProjectionInstanceKey = null;
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
            if (s.projection_instance_key === App.selectedProjectionInstanceKey || s.session_id === App.selectedSessionId) cls += " selected";
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
            html += '<div class="' + cls + '" data-session-id="' + App.escapeHtml(s.session_id) + '" data-projection-instance-key="' + App.escapeHtml(s.projection_instance_key || "") + '"'
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

        if (App.selectedProjectionInstanceKey || App.selectedSessionId !== null || App.selectedSessionLiveKey) {
            var found = null;
            if (App.selectedProjectionInstanceKey) {
                for (var pk = 0; pk < sessions.length; pk++) {
                    if (sessions[pk].projection_instance_key === App.selectedProjectionInstanceKey) {
                        found = sessions[pk];
                        break;
                    }
                }
            }
            // First try to match by stable_live_key_hash (handles pending / persisted transitions).
            if (App.selectedSessionLiveKey) {
                for (var sk = 0; sk < sessions.length; sk++) {
                    if (sessions[sk].stable_live_key_hash
                        && sessions[sk].stable_live_key_hash === App.selectedSessionLiveKey) {
                        found = sessions[sk];
                        break;
                    }
                }
            }
            // Fall back to session_id match (closed sessions, or live
            // sessions that have not transitioned yet).
            if (!found && App.selectedSessionId !== null) {
                for (var k = 0; k < sessions.length; k++) {
                    if (sessions[k].session_id === App.selectedSessionId) {
                        found = sessions[k];
                        break;
                    }
                }
            }
            if (found) {
                // Update the selection anchors so a subsequent refresh can still find the session.
                App.selectedSessionId = found.session_id;
                App.selectedSessionLiveKey = found.stable_live_key_hash || null;
                App.selectedProjectionInstanceKey = found.projection_instance_key || null;
                var skipDetailReload = (typeof App._timelineEditingActive === "function"
                    && App._timelineEditingActive());
                if (!skipDetailReload) {
                    loadSessionActivitySummary(found.projection_instance_key, data.date);
                }
                // Only re-populate the edit panel if the user is not mid-edit AND the session is not edit-disabled.
                if (!found.edit_disabled
                    && (!App.editingSession || App.editingSession.session_id !== found.session_id || !isEditDirty())) {
                    populateEditPanel(found);
                } else if (found.edit_disabled) {
            // Persisted-open live session: clear the edit panel since it cannot be edited.
                    clearEditPanel();
                }
                updateSessionActionButtons(found);
            } else {
                // Selected session disappeared (e.g. re-grouped). Invalidate the pending detail request and clear
                // the detail cache so a stale response does not backfill the cleared panel.
                ++App.detailsRequestToken;
                App.lastSessionDetailsViewModel = null;
                App.lastSessionActivitySummaryViewModel = null;
                App.selectedSessionId = null;
                App.selectedSessionLiveKey = null;
                App.selectedProjectionInstanceKey = null;
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
        if (App.isPagePayloadCompatibleWithRuntime(data, "timeline", date)) {
            App.acceptLiveRuntimePayload(data, "timeline", date, {
                source: "page_model"
            });
        } else {
            App.noteRejectedPagePayload(data, "timeline", date);
        }
        return true;
    }
    App.acceptTimelinePayload = acceptTimelinePayload;

    function acceptTimelineDetailsPayload(data, date) {
        var expectedDate = App.runtimeReportDateForPage("timeline", date);
        var payloadDate = App.payloadReportDate(data, "timeline", date);
        if (expectedDate && payloadDate && expectedDate !== payloadDate) {
            App.noteRejectedPagePayload(data, "timeline", date);
            return false;
        }
        if (App.isPagePayloadCompatibleWithRuntime(data, "timeline", date)) {
            App.acceptLiveRuntimePayload(data, "timeline", date, {
                source: "details_model"
            });
        } else {
            App.noteRejectedPagePayload(data, "timeline", date);
        }
        return true;
    }
    App.acceptTimelineDetailsPayload = acceptTimelineDetailsPayload;

    function selectTimelineSession(projectionInstanceKey, sessions) {
        App.selectedProjectionInstanceKey = projectionInstanceKey;
        // Update selected class without full re-render. Match by session_id AND stable_live_key_hash so
        // Persisted-open projection refreshes keep the visual selection.
        var items = document.querySelectorAll("#timeline-sessions-list .timeline-item");
        var newSelected = null;
        for (var j0 = 0; j0 < sessions.length; j0++) {
            if (sessions[j0].projection_instance_key === projectionInstanceKey) {
                newSelected = sessions[j0];
                break;
            }
        }
        App.selectedSessionId = newSelected ? newSelected.session_id : null;
        App.selectedSessionLiveKey = (newSelected && newSelected.stable_live_key_hash) || null;
        for (var i = 0; i < items.length; i++) {
            items[i].classList.remove("selected");
            var itemSid = items[i].getAttribute("data-session-id");
            var itemKey = items[i].getAttribute("data-stable-live-key-hash");
            if (items[i].getAttribute("data-projection-instance-key") === projectionInstanceKey
                || itemSid === App.selectedSessionId
                || (App.selectedSessionLiveKey && itemKey === App.selectedSessionLiveKey)) {
                items[i].classList.add("selected");
            }
        }
        var found = newSelected;
        if (found) {
            loadSessionActivitySummary(found.projection_instance_key, App.timelineDate);
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

    function loadSessionActivitySummary(projectionInstanceKey, date) {
        return loadSessionDetails(projectionInstanceKey, date);
    }
    App.loadSessionActivitySummary = loadSessionActivitySummary;

    function loadSessionDetails(projectionInstanceKey, date) {
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        // Only show loading when the panel is empty; keep existing summaries visible during refresh.
        if (!detailsList.innerHTML.trim()) {
            detailsHeader.textContent = "加载项目活动耗时…";
            detailsList.innerHTML = "";
        }

        var token = ++App.detailsRequestToken;
        App.callBridge("get_timeline_session_activity_summary", projectionInstanceKey || "", date).then(function (result) {
            if (token !== App.detailsRequestToken) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                detailsHeader.textContent = "加载项目活动耗时失败";
                detailsList.innerHTML = '<div class="timeline-empty">' + App.escapeHtml(msg) + '</div>';
            });
            if (!data) return;
            if (!acceptTimelineDetailsPayload(data, date)) return;
            renderSessionDetails(data);
        }).catch(function () {
            if (token !== App.detailsRequestToken) return;  // stale response
            detailsHeader.textContent = "加载项目活动耗时失败";
            detailsList.innerHTML = '<div class="timeline-empty">无法加载项目活动耗时，请稍后重试。</div>';
        });
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
                App.runTimelineSessionOperation("hide_timeline_session_activity", this.getAttribute("data-summary-id"));
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
        return App.callBridge("list_projects_for_timeline").then(function (result) {
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
        select.disabled = false;
    }
    App.renderProjectSelect = renderProjectSelect;

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
                if (App.editingSession && App.editingSession.session_id === session.session_id) {
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
                : ((session.raw_duration_seconds != null)
                    ? session.raw_duration_seconds
                    : session.duration_seconds);
            var durMin = Math.round((parseInt(durSrc, 10) || 0) / 60);
            durInput.value = isNaN(durMin) ? "" : String(durMin);
            durInput.disabled = false;
        }
        var durStatusEl = document.getElementById("edit-duration-status");
        if (durStatusEl) {
            durStatusEl.textContent = session.has_duration_override ? "已修正" : "";
        }

        var noteEl = document.getElementById("edit-note-text");
        if (noteEl) {
            noteEl.value = session.session_note || "";
            noteEl.disabled = false;
        }

        // Enable save/cancel first, then updateNoteCount applies the over-limit disable.
        var saveBtn = document.getElementById("edit-save-btn");
        var cancelBtn = document.getElementById("edit-cancel-btn");
        if (saveBtn) saveBtn.disabled = false;
        if (cancelBtn) cancelBtn.disabled = false;
        if (noteEl) updateNoteCount();

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
        var noteEl = document.getElementById("edit-note-text");
        var select = document.getElementById("edit-project-select");
        if (noteEl) {
            var currentNote = noteEl.value || "";
            var originalNote = App.editingSession.session_note || "";
            if (currentNote !== originalNote) return true;
        }
        if (select && select.value) {
            var currentProjectId = select.value;
            var originalProjectId = String(App.editingSession.project_id || 0);
            if (currentProjectId !== originalProjectId) return true;
        }
        // Duration override input: if minutes differ from the baseline, the panel is dirty.
        var durInput = document.getElementById("edit-duration-input");
        if (durInput && !durInput.disabled) {
            var durBaselineSrc = (App.editingSession.adjusted_duration_seconds != null)
                ? App.editingSession.adjusted_duration_seconds
                : App.editingSession.raw_duration_seconds;
            var durBaselineMin = Math.round((parseInt(durBaselineSrc, 10) || 0) / 60);
            var durBaselineStr = isNaN(durBaselineMin) ? "" : String(durBaselineMin);
            if ((durInput.value || "") !== durBaselineStr) return true;
        }
        return false;
    }
    App.isEditDirty = isEditDirty;

    function updateNoteCount() {
        var noteEl = document.getElementById("edit-note-text");
        var countEl = document.getElementById("edit-note-count");
        if (!noteEl || !countEl) return;
        var len = (noteEl.value || "").length;
        countEl.textContent = len + " / " + App.NOTE_MAX_LENGTH;
        if (len > App.NOTE_MAX_LENGTH) {
            countEl.classList.add("edit-note-count-over");
        } else {
            countEl.classList.remove("edit-note-count-over");
        }
        // Disable save when the note is over the limit; only toggle when not actively saving.
        var saveBtn = document.getElementById("edit-save-btn");
        if (saveBtn && !App.editSaving && App.editingSession) {
            saveBtn.disabled = len > App.NOTE_MAX_LENGTH;
        }
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
        var saveBtn = document.getElementById("edit-save-btn");
        var cancelBtn = document.getElementById("edit-cancel-btn");
        var select = document.getElementById("edit-project-select");
        var noteEl = document.getElementById("edit-note-text");
        var durInput = document.getElementById("edit-duration-input");
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "保存中…" : "保存";
        }
        if (cancelBtn) cancelBtn.disabled = saving;
        if (select) select.disabled = saving;
        if (noteEl) noteEl.disabled = saving;
        if (durInput) durInput.disabled = saving;
        // When stopping a save, re-apply the note-length limit as a defensive guard.
        if (!saving && App.editingSession) {
            updateNoteCount();
        }
    }
    App.setEditSaving = setEditSaving;

    function saveEdit() {
        if (!App.editingSession || App.editSaving) return;
        var activityIds = App.editingSession.activity_ids;
        if (!activityIds || activityIds.length === 0) {
            showEditStatus("无法保存：缺少活动信息", true);
            return;
        }
        var activityMemberHash = App.editingSession.activity_member_hash || "";
        if (!activityMemberHash) {
            showEditStatus("无法保存：活动时段已变化，请刷新后重试", true);
            return;
        }
        var select = document.getElementById("edit-project-select");
        var noteEl = document.getElementById("edit-note-text");
        if (!select || !noteEl) return;

        var projectIdStr = select.value;
        if (!projectIdStr) {
            showEditStatus("请选择项目", true);
            return;
        }
        var projectId = parseInt(projectIdStr, 10);
        if (!projectId || projectId <= 0) {
            showEditStatus("请选择有效的项目", true);
            return;
        }
        var note = noteEl.value || "";
        if (note.length > App.NOTE_MAX_LENGTH) {
            showEditStatus("备注过长", true);
            return;
        }

        // Determine what changed so we only call the bridges that are needed.
        var originalProjectId = String(App.editingSession.project_id || 0);
        var originalNote = App.editingSession.session_note || "";
        var projectChanged = projectIdStr !== originalProjectId;
        var noteChanged = note !== originalNote;

        // Duration override: empty input clears the override (null); non-empty is minutes → seconds.
        var durInput = document.getElementById("edit-duration-input");
        var durRawValue = durInput ? (durInput.value || "").trim() : "";
        var adjustedDurationSeconds = null;
        if (durRawValue !== "") {
            var durMinutes = parseInt(durRawValue, 10);
            if (isNaN(durMinutes) || durMinutes < 0) {
                showEditStatus("时长需为非负整数", true);
                return;
            }
            adjustedDurationSeconds = durMinutes * 60;
        }
        // Duration is considered changed when the input differs from the baseline, matching isEditDirty.
        var durBaselineSrc = (App.editingSession.adjusted_duration_seconds != null)
            ? App.editingSession.adjusted_duration_seconds
            : App.editingSession.raw_duration_seconds;
        var durBaselineMin = Math.round((parseInt(durBaselineSrc, 10) || 0) / 60);
        var durBaselineStr = isNaN(durBaselineMin) ? "" : String(durBaselineMin);
        var durationChanged = durRawValue !== durBaselineStr;
        var noteOrDurationChanged = noteChanged || durationChanged;

        if (!projectChanged && !noteOrDurationChanged) {
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

        var overrideProjectId = (projectChanged || App.editingSession.has_project_override === true)
            ? projectId
            : null;
        App.callBridge(
            "save_timeline_session_override",
            activityIds,
            activityMemberHash,
            overrideProjectId,
            adjustedDurationSeconds,
            note,
            reportDate
        ).then(function (result) {
            if (!result || result.ok === false) {
                // Keep original data in the form; do not clear.
                setEditSaving(false);
                showEditStatus(result && result.error ? result.error : "保存失败", true);
                return;
            }
            // Update the editingSession baseline to the saved values so isEditDirty() returns false and Cancel
            // after save does not revert to the pre-save values.
            if (App.editingSession) {
                if (projectChanged) {
                    App.editingSession.project_id = projectId;
                    App.editingSession.has_project_override = true;
                }
                if (noteOrDurationChanged) {
                    App.editingSession.session_note = note;
                    App.editingSession.adjusted_duration_seconds = adjustedDurationSeconds;
                    App.editingSession.has_duration_override = (adjustedDurationSeconds != null);
                    App.editingSession.display_duration_seconds = (adjustedDurationSeconds != null)
                        ? adjustedDurationSeconds
                        : (App.editingSession.raw_duration_seconds != null
                            ? App.editingSession.raw_duration_seconds
                            : App.editingSession.duration_seconds);
                    // Keep duration_seconds aligned with the display value so a stale snapshot is not rendered before refresh.
                    App.editingSession.duration_seconds = App.editingSession.display_duration_seconds;
                }
            }
            showEditStatus("保存成功", false);
            // Reset saving state before refreshing; a refresh failure is a separate concern.
            setEditSaving(false);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setEditSaving(false);
            showEditStatus("保存失败", true);
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

    function runTimelineSessionOperation(method, summaryId) {
        var key = App.selectedProjectionInstanceKey;
        var date = currentTimelineReportDate();
        if (!key || !date) return Promise.resolve();
        var args = method === "hide_timeline_session_activity"
            ? [date, key, summaryId]
            : [date, key];
        return App.callBridge.apply(null, [method].concat(args)).then(function (result) {
            var data = App.handleResult(result, function (message) {
                showEditStatus(message || "操作失败，请刷新后重试。", true);
            });
            if (!data) return;
            return refreshTimeline();
        }).catch(function () {
            showEditStatus("操作失败，请刷新后重试。", true);
        });
    }
    App.runTimelineSessionOperation = runTimelineSessionOperation;


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
        App.selectedSessionId = null;
        App.selectedSessionLiveKey = null;
        App.selectedProjectionInstanceKey = null;
        ++App.detailsRequestToken;
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
        App.timelineDate = date;
        if (resetSelection) {
            resetTimelineReportSelection();
        }
        var loadingOwner = "";
        if (showLoading) {
            loadingOwner = "timeline-report-" + String(App.timelineRequestToken + 1);
            App.timelineLoadingOwner = loadingOwner;
            App.setTimelineLoading(true);
            App.clearTimelineError();
        }
        var token = ++App.timelineRequestToken;
        return App.callBridge("get_timeline", date).then(function (result) {
            if (token !== App.timelineRequestToken) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                App.showTimelineError(msg || errorMessage);
            });
            if (!data) return;
            if (!acceptTimelinePayload(data, date)) return;
            App.timelineLoaded = true;
            showTimeline(data);
            App.clearTimelineError();
        }).catch(function () {
            if (token !== App.timelineRequestToken) return;  // stale response
            // Never surface raw exception text; use the stable fallback so
            // internal details do not leak into the UI.
            App.showTimelineError(errorMessage);
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
