// WorkTrace WebView frontend — timeline module: session list, detail list, edit panel, inline editors,
// session-level correction sections, date navigation.

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
            document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
            document.getElementById("timeline-details-list").innerHTML = "";
            App.selectedSessionId = null;
            App.selectedSessionLiveKey = null;
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
            // Live projection convergence: virtual live sessions are display-only; backend marks
            // ``edit_disabled=True`` so the edit panel stays disabled.
            if ((s.is_in_progress === true || s.is_live_projected === true)
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
            if (s.is_live_projected === true) cls += " live-projected";
            if (s.is_virtual_live === true) cls += " virtual-live";
            if (s.session_id === App.selectedSessionId) cls += " selected";
            // Stable live key data attribute so the ticker / selection continuity locates the session DOM across
            // the virtual_pending / absorbed_pending / persisted_open transition (stable_live_key_hash stays the same when session_id changes).
            var stableKeyHash = s.stable_live_key_hash || "";
            // Active-span anchored DOM attributes: the row stores a static
            // base plus active elapsed offset; the ticker supplies the one
            // Timeline page active elapsed sample.
            var sessSpanId = s.display_span_id || "";
            var rawSessionDurationSemantic = s.duration_semantic;
            var sessionDurationSemantic = String(rawSessionDurationSemantic || "").replace(/_/g, "-");
            if (sessSpanId && sessionDurationSemantic !== "aggregate-live") {
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
            html += '<div class="' + cls + '" data-session-id="' + App.escapeHtml(s.session_id) + '"'
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
            // "session-" + session_id key would break the virtual_pending / absorbed_pending / persisted_open transition.
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
                    var sid = itemEl.getAttribute("data-session-id");
                    selectTimelineSession(sid, sessions);
                });
            })(items[j]);
        }

        if (App.selectedSessionId !== null || App.selectedSessionLiveKey) {
            var found = null;
            // First try to match by stable_live_key_hash (handles virtual_pending / absorbed_pending / persisted_open transition).
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
                var skipDetailReload = (typeof App._timelineEditingActive === "function"
                    && App._timelineEditingActive());
                if (!skipDetailReload) {
                    loadSessionDetails(found.activity_ids, data.date);
                }
                // Only re-populate the edit panel if the user is not mid-edit AND the session is not edit-disabled.
                if (!found.edit_disabled
                    && (!App.editingSession || App.editingSession.session_id !== found.session_id || !isEditDirty())) {
                    populateEditPanel(found);
                } else if (found.edit_disabled) {
                    // Virtual / persisted_open live session: clear the edit panel since it cannot be edited.
                    clearEditPanel();
                }
                if (App.correctionShellOpen
                    && App.correctionShellSessionId === found.session_id
                    && !isEditDirty()
                    && !App.isAnyCorrectionWriteSaving()) {
                    App.renderCorrectionShell(
                        found,
                        App.getCurrentDetailActivities(),
                        App.correctionShellMode,
                        App.correctionShellActivityId
                    );
                }
            } else {
                // Selected session disappeared (e.g. re-grouped). Invalidate the pending detail request and clear
                // the detail cache so a stale response does not backfill the cleared panel.
                ++App.detailsRequestToken;
                App.lastSessionDetailsViewModel = null;
                App.selectedSessionId = null;
                App.selectedSessionLiveKey = null;
                document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
                document.getElementById("timeline-details-list").innerHTML = "";
                clearEditPanel();
            }
        }
    }
    App.showTimeline = showTimeline;

    function acceptTimelinePayload(data, date) {
        return App.acceptPagePayloadRuntime(data, "timeline", date);
    }
    App.acceptTimelinePayload = acceptTimelinePayload;

    function acceptTimelineDetailsPayload(data, date) {
        if (!App.isPagePayloadCompatibleWithRuntime(data, "timeline", date)) {
            App.noteRejectedPagePayload(data, "timeline", date);
            return false;
        }
        return true;
    }
    App.acceptTimelineDetailsPayload = acceptTimelineDetailsPayload;

    function selectTimelineSession(sessionId, sessions) {
        App.selectedSessionId = sessionId;
        // Switching sessions closes the correction shell (per-session workspace).
        if (App.correctionShellOpen && App.correctionShellSessionId !== sessionId) {
            App.resetCorrectionShellState();
        }
        // Update selected class without full re-render. Match by session_id AND stable_live_key_hash so the
        // virtual_pending / absorbed_pending / persisted_open transition keeps the visual selection.
        var items = document.querySelectorAll("#timeline-sessions-list .timeline-item");
        var newSelected = null;
        for (var j0 = 0; j0 < sessions.length; j0++) {
            if (sessions[j0].session_id === sessionId) {
                newSelected = sessions[j0];
                break;
            }
        }
        App.selectedSessionLiveKey = (newSelected && newSelected.stable_live_key_hash) || null;
        for (var i = 0; i < items.length; i++) {
            items[i].classList.remove("selected");
            var itemSid = items[i].getAttribute("data-session-id");
            var itemKey = items[i].getAttribute("data-stable-live-key-hash");
            if (itemSid === sessionId
                || (App.selectedSessionLiveKey && itemKey === App.selectedSessionLiveKey)) {
                items[i].classList.add("selected");
            }
        }
        var found = newSelected;
        if (found) {
            loadSessionDetails(found.activity_ids, App.timelineDate);
            // Virtual live sessions are display-only; a manual click must NOT open the edit panel. Clear it instead.
            if (found.edit_disabled === true || found.is_virtual === true) {
                clearEditPanel();
            } else {
                // A manual click always repopulates the edit panel, even if a prior auto-refresh skipped it.
                populateEditPanel(found);
            }
        }
    }
    App.selectTimelineSession = selectTimelineSession;

    function loadSessionDetails(activityIds, date) {
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        // Only show "loading" when the panel is empty; keep existing details visible during refresh.
        if (!detailsList.innerHTML.trim()) {
            detailsHeader.textContent = "加载详情…";
            detailsList.innerHTML = "";
        }

        var token = ++App.detailsRequestToken;
        App.callBridge("get_timeline_session_details", activityIds, date).then(function (result) {
            if (token !== App.detailsRequestToken) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                detailsHeader.textContent = "加载详情失败";
                detailsList.innerHTML = '<div class="timeline-empty">' + App.escapeHtml(msg) + '</div>';
            });
            if (!data) return;
            if (!acceptTimelineDetailsPayload(data, date)) return;
            renderSessionDetails(data);
        }).catch(function () {
            if (token !== App.detailsRequestToken) return;  // stale response
            detailsHeader.textContent = "加载详情失败";
            detailsList.innerHTML = '<div class="timeline-empty">无法加载详情，请稍后重试。</div>';
        });
    }
    App.loadSessionDetails = loadSessionDetails;

    function renderSessionDetails(data) {
        if (typeof App._timelineEditingActive === "function" && App._timelineEditingActive()) {
            return;
        }
        if ((App.editingActivityId !== null || App.editingSplitActivityId !== null)
            && typeof App.isEditDirty === "function" && App.isEditDirty()) {
            return;
        }
        if (App.activityTimeSaving || App.activitySplitSaving) {
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
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        var activities = data.activities || [];
        if (activities.length === 0) {
            detailsHeader.textContent = "该时段暂无活动详情";
            detailsList.innerHTML = '<div class="timeline-empty">暂无详情</div>';
            return;
        }
        detailsHeader.textContent = "活动详情（" + activities.length + " 条）";
        var html = "";
        var detailContinuityKeys = [];
        for (var i = 0; i < activities.length; i++) {
            var a = activities[i];
            // Simplified read-only detail row; advanced correction is via the "高级纠错" button → correction shell.
            if ((a.is_in_progress === true || a.is_live_projected === true)
                && !a.display_span_id
                && typeof App.recordLiveClockContractViolation === "function") {
                App.recordLiveClockContractViolation("", "timeline", "detail_live_row_missing_span_id");
            }
            var startTimeOnly = App.formatStartTimeOnly(a.start_time);
            var displayName = a.resource_name || a.app_name || "未知";
            var aDurSec = parseInt(a.duration_seconds, 10);
            var cls = "detail-item";
            if (a.is_in_progress) cls += " in-progress";
            if (a.is_virtual === true) cls += " virtual-live";
            var aid = a.activity_id || 0;
            // Stable live key data attribute so the detail ticker locates the row across the virtual_pending / absorbed_pending / persisted_open
            // transition (stable_live_key_hash stays the same when activity_id changes; ticker falls back to activity_id).
            var detailStableKey = a.stable_live_key_hash || "";
            // Active-span anchored DOM attributes: detail rows keep their
            // own offset but do not replace the Timeline page active clock.
            var detailSpanId = a.display_span_id || "";
            var detailContinuityKey = detailSpanId ? App.liveContinuityKey(a, "detail") : "";
            var detailDurationSemantic = String(a.duration_semantic || "current_live").replace(/_/g, "-");
            var detailDisplayBase = parseInt(a.display_base_seconds, 10);
            if (isNaN(detailDisplayBase)) detailDisplayBase = (!isNaN(aDurSec) && aDurSec >= 0) ? aDurSec : 0;
            var initialSec = (!isNaN(aDurSec) && aDurSec >= 0) ? aDurSec : 0;
            if (detailSpanId && projectClock) {
                initialSec = App.projectFromDisplayBase(detailDisplayBase, activeElapsedNowValue);
            }
            var detailPrev = detailContinuityKey ? App._monotonicRenderState[detailContinuityKey] : null;
            if (detailPrev && typeof detailPrev.lastSeconds === "number" && initialSec < detailPrev.lastSeconds) {
                initialSec = detailPrev.lastSeconds;
            }
            var aDurText = (!isNaN(aDurSec) && aDurSec >= 0)
                ? App.formatDuration(initialSec)
                : (a.duration || "00:00:00");
            html += '<div class="' + cls + '" data-activity-id="' + App.escapeHtml(String(aid)) + '"'
                + (detailStableKey ? ' data-stable-live-key-hash="' + App.escapeHtml(detailStableKey) + '"' : '')
                + (detailSpanId ? ' data-display-span-id="' + App.escapeHtml(detailSpanId) + '"' : '')
                + ' data-detail-index="' + i + '"'
                + '>'
                + '<div class="detail-item-time">' + App.escapeHtml(startTimeOnly) + '</div>'
                + '<div class="detail-item-name" title="' + App.escapeHtml(displayName) + '">' + App.escapeHtml(displayName) + '</div>'
                + '<div class="detail-item-project" title="' + App.escapeHtml(App.formatProjectLabel(a.project_name, a.project_description)) + '">' + App.escapeHtml(App.formatProjectLabel(a.project_name, a.project_description)) + '</div>'
                + '<div class="detail-item-duration"'
                + (detailSpanId ? ' data-live-duration-target="1"' : '')
                + (detailSpanId ? ' data-duration-semantic="' + App.escapeHtml(detailDurationSemantic) + '"' : '')
                + (detailSpanId ? ' data-display-span-id="' + App.escapeHtml(detailSpanId) + '"' : '')
                + (detailStableKey ? ' data-stable-live-key-hash="' + App.escapeHtml(detailStableKey) + '"' : '')
                + (detailSpanId ? ' data-display-base-seconds="' + detailDisplayBase + '"' : '')
                + (detailSpanId ? ' data-live-base-seconds="' + detailDisplayBase + '"' : '')
                + (detailSpanId ? ' data-live-role="timeline-detail"' : '')
                + (detailContinuityKey ? ' data-live-continuity-key="' + App.escapeHtml(detailContinuityKey) + '"' : '')
                + ' data-duration-seconds="' + initialSec + '">' + App.escapeHtml(aDurText) + '</div>'
                + '</div>';
            // Collect this row's continuity key so the monotonic state can
            // be seeded after the innerHTML swap.
            detailContinuityKeys.push({ index: i, sec: initialSec, key: detailContinuityKey });
        }
        detailsList.innerHTML = html;
        // Detail rows use App.liveContinuityKey() so virtual-to-persisted keys stay stable.
        // The key is the SAME string written to ``data-live-continuity-key``
        // so the render seed and the ticker share one monotonic guard.
        for (var di = 0; di < detailContinuityKeys.length; di++) {
            var dk = detailContinuityKeys[di];
            var detailKey = dk.key || "";
            if (!detailKey) continue;
            App._monotonicRenderState[detailKey] = { lastSeconds: dk.sec };
        }
    }
    App.renderSessionDetails = renderSessionDetails;


    function openActivityTimeEditor(activityId, startVal, endVal, btn) {
        if (!btn) return;
        // Close any other open inline editor first so only one is visible
        // at a time. This keeps the editing context unambiguous.
        closeAllActivityTimeEditors(activityId);
        // Also close any open split editor so the time editor is the only
        // inline editor visible.
        closeAllActivitySplitEditors(activityId);
        App.editingActivityId = activityId;
        var row = btn.closest(".detail-item");
        if (!row) return;
        var editor = row.querySelector(".detail-time-editor");
        if (!editor) return;
        var startInput = editor.querySelector(".detail-time-start");
        var endInput = editor.querySelector(".detail-time-end");
        if (startInput) startInput.value = App.backendToDatetimeLocal(startVal);
        if (endInput) endInput.value = App.backendToDatetimeLocal(endVal);
        if (startInput) startInput.disabled = false;
        if (endInput) endInput.disabled = false;
        var saveBtn = editor.querySelector(".detail-time-save-btn");
        var cancelBtn = editor.querySelector(".detail-time-cancel-btn");
        if (saveBtn) saveBtn.disabled = false;
        if (cancelBtn) cancelBtn.disabled = false;
        editor.hidden = false;
        setActivityTimeStatus(row, "", false);
        if (saveBtn) {
            saveBtn.onclick = function () { saveActivityTime(row); };
        }
        if (cancelBtn) {
            cancelBtn.onclick = function () { closeActivityTimeEditor(row); };
        }
    }
    App.openActivityTimeEditor = openActivityTimeEditor;

    function closeActivityTimeEditor(row) {
        if (!row) return;
        var editor = row.querySelector(".detail-time-editor");
        if (!editor) return;
        var startInput = editor.querySelector(".detail-time-start");
        var endInput = editor.querySelector(".detail-time-end");
        if (startInput) { startInput.value = ""; startInput.disabled = true; }
        if (endInput) { endInput.value = ""; endInput.disabled = true; }
        var saveBtn = editor.querySelector(".detail-time-save-btn");
        var cancelBtn = editor.querySelector(".detail-time-cancel-btn");
        if (saveBtn) { saveBtn.disabled = true; saveBtn.onclick = null; }
        if (cancelBtn) { cancelBtn.disabled = true; cancelBtn.onclick = null; }
        editor.hidden = true;
        setActivityTimeStatus(row, "", false);
        // Only clear editingActivityId if it matches the row being closed.
        var rowAid = parseInt(row.getAttribute("data-activity-id"), 10);
        if (App.editingActivityId === rowAid) {
            App.editingActivityId = null;
        }
    }
    App.closeActivityTimeEditor = closeActivityTimeEditor;

    function closeAllActivityTimeEditors(exceptActivityId) {
        var rows = document.querySelectorAll("#timeline-details-list .detail-item");
        for (var i = 0; i < rows.length; i++) {
            var aid = parseInt(rows[i].getAttribute("data-activity-id"), 10);
            if (aid !== exceptActivityId) {
                closeActivityTimeEditor(rows[i]);
            }
        }
    }
    App.closeAllActivityTimeEditors = closeAllActivityTimeEditors;

    function setActivityTimeStatus(row, message, isError) {
        if (!row) return;
        var statusEl = row.querySelector(".detail-time-status");
        if (!statusEl) return;
        if (!message) {
            statusEl.hidden = true;
            statusEl.textContent = "";
            statusEl.className = "detail-time-status edit-status";
            return;
        }
        statusEl.hidden = false;
        statusEl.textContent = message;
        statusEl.className = "detail-time-status edit-status "
            + (isError ? "edit-status-error" : "edit-status-success");
    }
    App.setActivityTimeStatus = setActivityTimeStatus;

    function setActivityTimeSaving(row, saving) {
        if (!row) return;
        App.activityTimeSaving = saving;
        var editor = row.querySelector(".detail-time-editor");
        if (!editor) return;
        var saveBtn = editor.querySelector(".detail-time-save-btn");
        var cancelBtn = editor.querySelector(".detail-time-cancel-btn");
        var startInput = editor.querySelector(".detail-time-start");
        var endInput = editor.querySelector(".detail-time-end");
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "保存中…" : "保存";
        }
        if (cancelBtn) cancelBtn.disabled = saving;
        if (startInput) startInput.disabled = saving;
        if (endInput) endInput.disabled = saving;
    }
    App.setActivityTimeSaving = setActivityTimeSaving;

    function saveActivityTime(row) {
        if (!row || App.activityTimeSaving) return;
        var aid = parseInt(row.getAttribute("data-activity-id"), 10);
        if (!aid || isNaN(aid)) {
            setActivityTimeStatus(row, "活动 ID 无效", true);
            return;
        }
        var editor = row.querySelector(".detail-time-editor");
        if (!editor) return;
        var startInput = editor.querySelector(".detail-time-start");
        var endInput = editor.querySelector(".detail-time-end");
        if (!startInput || !endInput) return;
        var startVal = App.datetimeLocalToBackend(startInput.value);
        var endVal = App.datetimeLocalToBackend(endInput.value);
        if (!startVal || !endVal) {
            setActivityTimeStatus(row, "时间无效", true);
            return;
        }
        if (endVal <= startVal) {
            setActivityTimeStatus(row, "结束时间必须晚于开始时间", true);
            return;
        }

        setActivityTimeSaving(row, true);
        setActivityTimeStatus(row, "", false);
        App.callBridge("update_timeline_activity_time", aid, startVal, endVal).then(function (result) {
            if (!result || result.ok === false) {
                setActivityTimeSaving(row, false);
                setActivityTimeStatus(
                    row,
                    result && result.error ? result.error : "保存时间失败",
                    true
                );
                return;
            }
            // Update the button's baseline so a subsequent auto-refresh does not revert the editor inputs.
            var btn = row.querySelector(".detail-edit-time-btn");
            if (btn) {
                btn.setAttribute("data-start", startVal);
                btn.setAttribute("data-end", endVal);
            }
            setActivityTimeStatus(row, "时间已更新", false);
            // Keep the editor open so the user can see the saved values; the next auto-refresh re-renders.
            setActivityTimeSaving(row, false);
            if (startInput) startInput.value = App.backendToDatetimeLocal(startVal);
            if (endInput) endInput.value = App.backendToDatetimeLocal(endVal);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setActivityTimeSaving(row, false);
            setActivityTimeStatus(row, "保存时间失败", true);
        });
    }
    App.saveActivityTime = saveActivityTime;


    function openActivitySplitEditor(activityId, startVal, endVal, btn) {
        if (!btn) return;
        // Close any other open inline editor first so only one is visible at a time.
        closeAllActivitySplitEditors(activityId);
        // Also close any open time editor.
        closeAllActivityTimeEditors(activityId);
        App.editingSplitActivityId = activityId;
        var row = btn.closest(".detail-item");
        if (!row) return;
        var editor = row.querySelector(".detail-split-editor");
        if (!editor) return;
        var splitInput = editor.querySelector(".detail-split-time");
        // Default the split point to the midpoint; use fixed-format string conversion (NOT Date parsing) to
        // avoid timezone shifts.
        if (splitInput) {
            var midVal = App.midpointTime(startVal, endVal);
            splitInput.value = App.backendToDatetimeLocal(midVal);
            splitInput.disabled = false;
        }
        var saveBtn = editor.querySelector(".detail-split-save-btn");
        var cancelBtn = editor.querySelector(".detail-split-cancel-btn");
        if (saveBtn) saveBtn.disabled = false;
        if (cancelBtn) cancelBtn.disabled = false;
        editor.hidden = false;
        setActivitySplitStatus(row, "", false);
        if (saveBtn) {
            saveBtn.onclick = function () { saveActivitySplit(row); };
        }
        if (cancelBtn) {
            cancelBtn.onclick = function () { closeActivitySplitEditor(row); };
        }
    }
    App.openActivitySplitEditor = openActivitySplitEditor;

    function closeActivitySplitEditor(row) {
        if (!row) return;
        var editor = row.querySelector(".detail-split-editor");
        if (!editor) return;
        var splitInput = editor.querySelector(".detail-split-time");
        if (splitInput) { splitInput.value = ""; splitInput.disabled = true; }
        var saveBtn = editor.querySelector(".detail-split-save-btn");
        var cancelBtn = editor.querySelector(".detail-split-cancel-btn");
        if (saveBtn) { saveBtn.disabled = true; saveBtn.onclick = null; }
        if (cancelBtn) { cancelBtn.disabled = true; cancelBtn.onclick = null; }
        editor.hidden = true;
        setActivitySplitStatus(row, "", false);
        // Only clear editingSplitActivityId if it matches the row being closed.
        var rowAid = parseInt(row.getAttribute("data-activity-id"), 10);
        if (App.editingSplitActivityId === rowAid) {
            App.editingSplitActivityId = null;
        }
    }
    App.closeActivitySplitEditor = closeActivitySplitEditor;

    function closeAllActivitySplitEditors(exceptActivityId) {
        var rows = document.querySelectorAll("#timeline-details-list .detail-item");
        for (var i = 0; i < rows.length; i++) {
            var aid = parseInt(rows[i].getAttribute("data-activity-id"), 10);
            if (aid !== exceptActivityId) {
                closeActivitySplitEditor(rows[i]);
            }
        }
    }
    App.closeAllActivitySplitEditors = closeAllActivitySplitEditors;

    function setActivitySplitStatus(row, message, isError) {
        if (!row) return;
        var statusEl = row.querySelector(".detail-split-status");
        if (!statusEl) return;
        if (!message) {
            statusEl.hidden = true;
            statusEl.textContent = "";
            statusEl.className = "detail-split-status edit-status";
            return;
        }
        statusEl.hidden = false;
        statusEl.textContent = message;
        statusEl.className = "detail-split-status edit-status "
            + (isError ? "edit-status-error" : "edit-status-success");
    }
    App.setActivitySplitStatus = setActivitySplitStatus;

    function setActivitySplitSaving(row, saving) {
        if (!row) return;
        App.activitySplitSaving = saving;
        var editor = row.querySelector(".detail-split-editor");
        if (!editor) return;
        var saveBtn = editor.querySelector(".detail-split-save-btn");
        var cancelBtn = editor.querySelector(".detail-split-cancel-btn");
        var splitInput = editor.querySelector(".detail-split-time");
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "拆分中…" : "拆分";
        }
        if (cancelBtn) cancelBtn.disabled = saving;
        if (splitInput) splitInput.disabled = saving;
    }
    App.setActivitySplitSaving = setActivitySplitSaving;

    function saveActivitySplit(row) {
        if (!row || App.activitySplitSaving) return;
        var aid = parseInt(row.getAttribute("data-activity-id"), 10);
        if (!aid || isNaN(aid)) {
            setActivitySplitStatus(row, "活动 ID 无效", true);
            return;
        }
        var editor = row.querySelector(".detail-split-editor");
        if (!editor) return;
        var splitInput = editor.querySelector(".detail-split-time");
        if (!splitInput) return;
        // The button's data-start/data-end hold the server-returned start/end; use them for the range check
        // so a stale editor on a re-rendered row cannot submit a bad split.
        var btn = row.querySelector(".detail-split-btn");
        var actStart = btn ? (btn.getAttribute("data-start") || "") : "";
        var actEnd = btn ? (btn.getAttribute("data-end") || "") : "";
        var splitVal = App.datetimeLocalToBackend(splitInput.value);
        if (!splitVal) {
            setActivitySplitStatus(row, "拆分时间无效", true);
            return;
        }
        // Frontend range check for immediate feedback; the backend re-validates.
        if (!actStart || !actEnd || splitVal <= actStart || splitVal >= actEnd) {
            setActivitySplitStatus(row, "拆分时间必须在活动时间范围内", true);
            return;
        }

        setActivitySplitSaving(row, true);
        setActivitySplitStatus(row, "", false);
        App.callBridge("split_timeline_activity", aid, splitVal).then(function (result) {
            if (!result || result.ok === false) {
                setActivitySplitSaving(row, false);
                setActivitySplitStatus(
                    row,
                    result && result.error ? result.error : "拆分失败",
                    true
                );
                return;
            }
            // Split succeeded; close the editor and refresh so the two new activities appear.
            setActivitySplitSaving(row, false);
            setActivitySplitStatus(row, "已拆分", false);
            // The split changes the activity's end_time and creates a new
            // activity, so the row's data-start/data-end are now stale.
            // Closing the editor and refreshing is the cleanest path.
            closeActivitySplitEditor(row);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setActivitySplitSaving(row, false);
            setActivitySplitStatus(row, "拆分失败", true);
        });
    }
    App.saveActivitySplit = saveActivitySplit;


    function setMergeStatus(btn, message, isError) {
        if (!btn) return;
        var row = btn.closest(".detail-item");
        if (!row) return;
        var statusEl = row.querySelector(".detail-merge-status");
        if (!statusEl) return;
        if (!message) {
            statusEl.hidden = true;
            statusEl.textContent = "";
            statusEl.className = "detail-merge-status edit-status";
            return;
        }
        statusEl.hidden = false;
        statusEl.textContent = message;
        statusEl.className = "detail-merge-status edit-status "
            + (isError ? "edit-status-error" : "edit-status-success");
    }
    App.setMergeStatus = setMergeStatus;

    function setMergeSaving(btn, saving) {
        App.mergeSaving = saving;
        App.mergingActivityId = saving ? parseInt(btn.getAttribute("data-activity-id"), 10) : null;
        if (btn) {
            btn.disabled = saving;
            btn.textContent = saving ? "合并中…" : "与下一条合并";
        }
        // Also disable the other action buttons on the same row during a
        // merge so the user cannot start a conflicting edit.
        var row = btn ? btn.closest(".detail-item") : null;
        if (row) {
            var editBtn = row.querySelector(".detail-edit-time-btn");
            var splitBtn = row.querySelector(".detail-split-btn");
            if (editBtn) editBtn.disabled = saving || editBtn.disabled;
            if (splitBtn) splitBtn.disabled = saving || splitBtn.disabled;
        }
    }
    App.setMergeSaving = setMergeSaving;

    function saveActivityMerge(btn, activityId, nextActivityId) {
        if (!btn || App.mergeSaving) return;
        if (!activityId || !nextActivityId) {
            setMergeStatus(btn, "活动 ID 无效", true);
            return;
        }
        // Guard against unsaved edits: merge triggers a refresh that would wipe unsaved inputs.
        if (isEditDirty()) {
            setMergeStatus(btn, "请先保存或取消当前编辑", true);
            return;
        }
        // Verify the activity id still matches the row so a stale button does not operate on a different session.
        var row = btn.closest(".detail-item");
        if (!row) return;
        var rowAid = parseInt(row.getAttribute("data-activity-id"), 10);
        if (rowAid !== activityId) return;

        setMergeSaving(btn, true);
        setMergeStatus(btn, "", false);
        App.callBridge("merge_timeline_activities", [activityId, nextActivityId]).then(function (result) {
            if (!result || result.ok === false) {
                setMergeSaving(btn, false);
                setMergeStatus(
                    btn,
                    result && result.error ? result.error : "合并失败",
                    true
                );
                return;
            }
            // Merge succeeded; refresh so the detail list reflects the soft-deleted next activity.
            setMergeSaving(btn, false);
            setMergeStatus(btn, "已合并", false);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setMergeSaving(btn, false);
            setMergeStatus(btn, "合并失败", true);
        });
    }
    App.saveActivityMerge = saveActivityMerge;


    function setVisibilityStatus(btn, message, isError) {
        if (!btn) return;
        var row = btn.closest(".detail-item");
        if (!row) return;
        var statusEl = row.querySelector(".detail-visibility-status");
        if (!statusEl) return;
        if (!message) {
            statusEl.hidden = true;
            statusEl.textContent = "";
            statusEl.className = "detail-visibility-status edit-status";
            return;
        }
        statusEl.hidden = false;
        statusEl.textContent = message;
        statusEl.className = "detail-visibility-status edit-status "
            + (isError ? "edit-status-error" : "edit-status-success");
    }
    App.setVisibilityStatus = setVisibilityStatus;

    function setHideSaving(btn, saving) {
        App.hideSaving = saving;
        App.hidingActivityId = saving ? parseInt(btn.getAttribute("data-activity-id"), 10) : null;
        if (btn) {
            btn.disabled = saving;
            btn.textContent = saving ? "隐藏中…" : "隐藏";
        }
        // Also disable the delete button on the same row during a hide.
        var row = btn ? btn.closest(".detail-item") : null;
        if (row) {
            var delBtn = row.querySelector(".detail-delete-btn");
            if (delBtn) delBtn.disabled = saving || delBtn.disabled;
        }
    }
    App.setHideSaving = setHideSaving;

    function setDeleteSaving(btn, saving) {
        App.deleteSaving = saving;
        App.deletingActivityId = saving ? parseInt(btn.getAttribute("data-activity-id"), 10) : null;
        if (btn) {
            btn.disabled = saving;
            btn.textContent = saving ? "删除中…" : "删除";
        }
        var row = btn ? btn.closest(".detail-item") : null;
        if (row) {
            var hideBtn = row.querySelector(".detail-hide-btn");
            if (hideBtn) hideBtn.disabled = saving || hideBtn.disabled;
        }
    }
    App.setDeleteSaving = setDeleteSaving;

    function saveActivityHide(btn, activityId) {
        if (!btn || App.hideSaving) return;
        if (!activityId) {
            setVisibilityStatus(btn, "活动 ID 无效", true);
            return;
        }
        // Guard against unsaved edits: hide triggers a refresh that would wipe unsaved inputs.
        if (isEditDirty()) {
            setVisibilityStatus(btn, "请先保存或取消当前编辑", true);
            return;
        }
        // Verify the activity id still exists in the current details list so a stale button does not misfire.
        var row = btn.closest(".detail-item");
        if (!row) return;
        var rowAid = parseInt(row.getAttribute("data-activity-id"), 10);
        if (rowAid !== activityId) return;

        setHideSaving(btn, true);
        setVisibilityStatus(btn, "", false);
        App.callBridge("hide_timeline_activity", activityId).then(function (result) {
            if (!result || result.ok === false) {
                setHideSaving(btn, false);
                setVisibilityStatus(
                    btn,
                    result && result.error ? result.error : "隐藏失败",
                    true
                );
                return;
            }
            setHideSaving(btn, false);
            setVisibilityStatus(btn, "已隐藏", false);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setHideSaving(btn, false);
            setVisibilityStatus(btn, "隐藏失败", true);
        });
    }
    App.saveActivityHide = saveActivityHide;

    function saveActivityDelete(btn, activityId) {
        if (!btn || App.deleteSaving) return;
        if (!activityId) {
            setVisibilityStatus(btn, "活动 ID 无效", true);
            return;
        }
        if (isEditDirty()) {
            setVisibilityStatus(btn, "请先保存或取消当前编辑", true);
            return;
        }
        var row = btn.closest(".detail-item");
        if (!row) return;
        var rowAid = parseInt(row.getAttribute("data-activity-id"), 10);
        if (rowAid !== activityId) return;

        // Lightweight confirmation (native window.confirm) so the user does not accidentally soft-delete.
        var confirmed = window.confirm("确定从 Timeline 删除这条记录吗？不会物理删除数据。");
        if (!confirmed) return;

        setDeleteSaving(btn, true);
        setVisibilityStatus(btn, "", false);
        App.callBridge("soft_delete_timeline_activity", activityId).then(function (result) {
            if (!result || result.ok === false) {
                setDeleteSaving(btn, false);
                setVisibilityStatus(
                    btn,
                    result && result.error ? result.error : "删除失败",
                    true
                );
                return;
            }
            setDeleteSaving(btn, false);
            setVisibilityStatus(btn, "已删除", false);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setDeleteSaving(btn, false);
            setVisibilityStatus(btn, "删除失败", true);
        });
    }
    App.saveActivityDelete = saveActivityDelete;


    function populateSessionVisibilitySection(session) {
        var singleEl = document.getElementById("edit-visibility-single");
        var multiEl = document.getElementById("edit-visibility-multi");
        var hideBtn = document.getElementById("edit-visibility-hide-btn");
        var deleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (!singleEl || !multiEl) return;

        var activityIds = session.activity_ids || [];
        var isMulti = activityIds.length > 1;
        var inProgress = !!session.is_in_progress;

        if (isMulti) {
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "多活动时段请在活动详情中逐条隐藏或删除。";
            showVisibilityStatus("", false);
            return;
        }
        if (inProgress) {
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "进行中记录无法隐藏或删除。";
            showVisibilityStatus("", false);
            return;
        }
        singleEl.hidden = false;
        multiEl.hidden = true;
        if (hideBtn) hideBtn.disabled = false;
        if (deleteBtn) deleteBtn.disabled = false;
        showVisibilityStatus("", false);
    }
    App.populateSessionVisibilitySection = populateSessionVisibilitySection;

    function resetSessionVisibilitySection() {
        App.hideSaving = false;
        App.hidingActivityId = null;
        App.deleteSaving = false;
        App.deletingActivityId = null;
        var singleEl = document.getElementById("edit-visibility-single");
        var multiEl = document.getElementById("edit-visibility-multi");
        var hideBtn = document.getElementById("edit-visibility-hide-btn");
        var deleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (singleEl) singleEl.hidden = true;
        if (multiEl) {
            multiEl.hidden = true;
            multiEl.textContent = "多活动时段请在活动详情中逐条隐藏或删除。";
        }
        if (hideBtn) { hideBtn.disabled = true; hideBtn.textContent = "隐藏此 session"; }
        if (deleteBtn) { deleteBtn.disabled = true; deleteBtn.textContent = "删除此 session"; }
        showVisibilityStatus("", false);
    }
    App.resetSessionVisibilitySection = resetSessionVisibilitySection;

    function showVisibilityStatus(message, isError) {
        var statusEl = document.getElementById("edit-visibility-status");
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
    App.showVisibilityStatus = showVisibilityStatus;

    function setSessionHideSaving(saving) {
        App.hideSaving = saving;
        var hideBtn = document.getElementById("edit-visibility-hide-btn");
        var deleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (hideBtn) {
            hideBtn.disabled = saving;
            hideBtn.textContent = saving ? "隐藏中…" : "隐藏此 session";
        }
        if (deleteBtn) deleteBtn.disabled = saving || deleteBtn.disabled;
    }
    App.setSessionHideSaving = setSessionHideSaving;

    function setSessionDeleteSaving(saving) {
        App.deleteSaving = saving;
        var hideBtn = document.getElementById("edit-visibility-hide-btn");
        var deleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (deleteBtn) {
            deleteBtn.disabled = saving;
            deleteBtn.textContent = saving ? "删除中…" : "删除此 session";
        }
        if (hideBtn) hideBtn.disabled = saving || hideBtn.disabled;
    }
    App.setSessionDeleteSaving = setSessionDeleteSaving;

    function saveSessionHide() {
        if (!App.editingSession || App.hideSaving) return;
        var activityIds = App.editingSession.activity_ids || [];
        if (activityIds.length !== 1) {
            showVisibilityStatus("多活动时段请在活动详情中逐条隐藏", true);
            return;
        }
        if (App.editingSession.is_in_progress) {
            showVisibilityStatus("进行中记录无法隐藏或删除", true);
            return;
        }
        if (isEditDirty()) {
            showVisibilityStatus("请先保存或取消当前编辑", true);
            return;
        }
        setSessionHideSaving(true);
        showVisibilityStatus("", false);
        App.callBridge("hide_timeline_session", activityIds).then(function (result) {
            if (!result || result.ok === false) {
                setSessionHideSaving(false);
                showVisibilityStatus(result && result.error ? result.error : "隐藏失败", true);
                return;
            }
            setSessionHideSaving(false);
            showVisibilityStatus("已隐藏", false);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setSessionHideSaving(false);
            showVisibilityStatus("隐藏失败", true);
        });
    }
    App.saveSessionHide = saveSessionHide;

    function saveSessionDelete() {
        if (!App.editingSession || App.deleteSaving) return;
        var activityIds = App.editingSession.activity_ids || [];
        if (activityIds.length !== 1) {
            showVisibilityStatus("多活动时段请在活动详情中逐条删除", true);
            return;
        }
        if (App.editingSession.is_in_progress) {
            showVisibilityStatus("进行中记录无法隐藏或删除", true);
            return;
        }
        if (isEditDirty()) {
            showVisibilityStatus("请先保存或取消当前编辑", true);
            return;
        }
        var confirmed = window.confirm("确定从 Timeline 删除这条记录吗？不会物理删除数据。");
        if (!confirmed) return;

        setSessionDeleteSaving(true);
        showVisibilityStatus("", false);
        App.callBridge("soft_delete_timeline_session", activityIds).then(function (result) {
            if (!result || result.ok === false) {
                setSessionDeleteSaving(false);
                showVisibilityStatus(result && result.error ? result.error : "删除失败", true);
                return;
            }
            setSessionDeleteSaving(false);
            showVisibilityStatus("已删除", false);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setSessionDeleteSaving(false);
            showVisibilityStatus("删除失败", true);
        });
    }
    App.saveSessionDelete = saveSessionDelete;


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
        // When switching to a different session, reset the per-activity
        // inline editor state so a stale editingActivityId from the
        // previous session does not leak into the new one. The detail list
        // DOM will be rebuilt by renderSessionDetails.
        if (App.editingSession && App.editingSession.session_id !== session.session_id) {
            App.editingActivityId = null;
            App.activityTimeSaving = false;
            // Reset per-activity inline split editor state too.
            App.editingSplitActivityId = null;
            App.activitySplitSaving = false;
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

        // Session-level time / split / visibility sections are hidden in the simplified edit panel (HTML retained
        // for the correction shell); their state is reset by clearEditPanel.

        showEditStatus("", false);
    }
    App.populateEditPanel = populateEditPanel;

    function clearEditPanel() {
        App.editingSession = null;
        App.editSaving = false;
        App.timeSaving = false;
        // Reset per-activity inline editor state so a stale editingActivityId does not leak into the next session.
        App.editingActivityId = null;
        App.activityTimeSaving = false;
        App.editingSplitActivityId = null;
        App.activitySplitSaving = false;
        App.sessionSplitSaving = false;
        App.mergeSaving = false;
        App.mergingActivityId = null;
        App.hideSaving = false;
        App.hidingActivityId = null;
        App.deleteSaving = false;
        App.deletingActivityId = null;
        // Reset batch project selection state so a stale selection does not leak into the next session.
        App.resetBatchProjectState();
        // Reset batch note state too so a stale note textarea / saving flag
        // does not leak into the next session.
        App.resetBatchNoteState();
        // Reset restore state too so a stale restore list / saving flag
        // does not leak into the next session.
        App.resetRestoreState();
        // Reset the correction shell state too so a stale shell does not
        // leak into the next session.
        App.resetCorrectionShellState();
        var panel = document.getElementById("timeline-edit-panel");
        if (panel) panel.hidden = true;
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
        // Reset the session-level time-correction section.
        resetSessionTimeSection();
        // Reset the session-level split section.
        resetSessionSplitSection();
        // Reset the session-level hide / soft-delete section.
        resetSessionVisibilitySection();
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
        if (noteOrDurationChanged && !reportDate) {
            showEditStatus("无法保存：日期无效", true);
            return;
        }

        setEditSaving(true);
        showEditStatus("", false);

        var promises = [];
        if (projectChanged) {
            promises.push(App.callBridge("update_timeline_project", activityIds, projectId).then(function (result) {
                if (!result || result.ok === false) {
                    throw new Error(result && result.error ? result.error : "保存项目失败");
                }
            }));
        }
        if (noteOrDurationChanged) {
            // The note and the duration override are saved together so they stay consistent.
            promises.push(App.callBridge(
                "update_timeline_note_and_duration",
                activityIds, note, adjustedDurationSeconds, reportDate
            ).then(function (result) {
                if (!result || result.ok === false) {
                    throw new Error(result && result.error ? result.error : "保存备注/时长失败");
                }
            }));
        }

        Promise.allSettled(promises).then(function (results) {
            var hasError = false;
            var errorMsg = "";
            for (var i = 0; i < results.length; i++) {
                if (results[i].status === "rejected") {
                    hasError = true;
                    // Never read .message from a rejected promise — could be a raw pywebview exception.
                    // Use the stable "保存失败" fallback so internal details never leak into the UI.
                    errorMsg = "保存失败";
                    break;
                }
            }
            if (hasError) {
                // Keep original data in the form; do not clear.
                setEditSaving(false);
                showEditStatus(errorMsg, true);
                return;
            }
            // Update the editingSession baseline to the saved values so isEditDirty() returns false and Cancel
            // after save does not revert to the pre-save values.
            if (App.editingSession) {
                if (projectChanged) {
                    App.editingSession.project_id = projectId;
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
        });
    }
    App.saveEdit = saveEdit;


    function populateSessionSplitSection(session) {
        var singleEl = document.getElementById("edit-split-single");
        var multiEl = document.getElementById("edit-split-multi");
        var splitEl = document.getElementById("edit-split-time");
        var saveBtn = document.getElementById("edit-split-save-btn");
        if (!singleEl || !multiEl) return;

        var activityIds = session.activity_ids || [];
        var isMulti = activityIds.length > 1;
        var inProgress = !!session.is_in_progress;

        if (isMulti) {
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "多活动时段请在活动详情中拆分单条活动。";
            showSplitStatus("", false);
            return;
        }
        if (inProgress) {
            // Single-activity but still open: splitting is not safe (displayed end_time may be projected).
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "进行中记录无法拆分。";
            showSplitStatus("", false);
            return;
        }
        // Single closed activity: show the split input. Default the split
        // point to the midpoint between start and end.
        singleEl.hidden = false;
        multiEl.hidden = true;
        if (splitEl) {
            var midVal = App.midpointTime(session.start_time, session.end_time);
            splitEl.value = App.backendToDatetimeLocal(midVal);
            splitEl.disabled = false;
        }
        if (saveBtn) saveBtn.disabled = false;
        showSplitStatus("", false);
    }
    App.populateSessionSplitSection = populateSessionSplitSection;

    function resetSessionSplitSection() {
        App.sessionSplitSaving = false;
        var singleEl = document.getElementById("edit-split-single");
        var multiEl = document.getElementById("edit-split-multi");
        var splitEl = document.getElementById("edit-split-time");
        var saveBtn = document.getElementById("edit-split-save-btn");
        if (singleEl) singleEl.hidden = true;
        if (multiEl) {
            multiEl.hidden = true;
            multiEl.textContent = "多活动时段请在活动详情中拆分单条活动。";
        }
        if (splitEl) { splitEl.value = ""; splitEl.disabled = true; }
        if (saveBtn) saveBtn.disabled = true;
        showSplitStatus("", false);
    }
    App.resetSessionSplitSection = resetSessionSplitSection;

    function showSplitStatus(message, isError) {
        var statusEl = document.getElementById("edit-split-status");
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
    App.showSplitStatus = showSplitStatus;

    function setSessionSplitSaving(saving) {
        App.sessionSplitSaving = saving;
        var saveBtn = document.getElementById("edit-split-save-btn");
        var splitEl = document.getElementById("edit-split-time");
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "拆分中…" : "拆分";
        }
        if (splitEl) splitEl.disabled = saving;
    }
    App.setSessionSplitSaving = setSessionSplitSaving;

    function saveSessionSplit() {
        if (!App.editingSession || App.sessionSplitSaving) return;
        var activityIds = App.editingSession.activity_ids || [];
        if (activityIds.length !== 1) {
            showSplitStatus("多活动时段请在活动详情中拆分单条活动", true);
            return;
        }
        if (App.editingSession.is_in_progress) {
            showSplitStatus("进行中记录无法拆分", true);
            return;
        }
        var splitEl = document.getElementById("edit-split-time");
        if (!splitEl) return;
        var splitVal = App.datetimeLocalToBackend(splitEl.value);
        if (!splitVal) {
            showSplitStatus("拆分时间无效", true);
            return;
        }
        // Frontend range check: split must be strictly between start and end (backend re-validates).
        var startVal = App.editingSession.start_time || "";
        var endVal = App.editingSession.end_time || "";
        if (!startVal || !endVal || splitVal <= startVal || splitVal >= endVal) {
            showSplitStatus("拆分时间必须在活动时间范围内", true);
            return;
        }

        setSessionSplitSaving(true);
        showSplitStatus("", false);
        App.callBridge("split_timeline_session", activityIds, splitVal).then(function (result) {
            if (!result || result.ok === false) {
                setSessionSplitSaving(false);
                showSplitStatus(result && result.error ? result.error : "拆分失败", true);
                return;
            }
            // Split succeeded; the refresh path handles session regrouping gracefully.
            setSessionSplitSaving(false);
            showSplitStatus("已拆分", false);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setSessionSplitSaving(false);
            showSplitStatus("拆分失败", true);
        });
    }
    App.saveSessionSplit = saveSessionSplit;

    function refreshTimelineAfterEdit() {
        var dateEl = document.getElementById("timeline-date-input");
        var date = App.timelineDate || (dateEl ? dateEl.value : null);
        if (date === "--" || date === "") date = null;
        var token = ++App.timelineRequestToken;
        App.callBridge("get_timeline", date).then(function (result) {
            if (token !== App.timelineRequestToken) return;
            var data = App.handleResult(result, function (msg) {
                App.showTimelineError(msg || "刷新失败");
            });
            if (!data) return;
            if (!acceptTimelinePayload(data, date)) return;
            showTimeline(data);
            App.clearTimelineError();
        }).catch(function () {
            if (token !== App.timelineRequestToken) return;
            // Use the stable "刷新失败" fallback.
            App.showTimelineError("刷新失败");
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


    function populateSessionTimeSection(session) {
        var singleEl = document.getElementById("edit-time-single");
        var multiEl = document.getElementById("edit-time-multi");
        var startEl = document.getElementById("edit-start-time");
        var endEl = document.getElementById("edit-end-time");
        var saveBtn = document.getElementById("edit-time-save-btn");
        if (!singleEl || !multiEl) return;

        var activityIds = session.activity_ids || [];
        var isMulti = activityIds.length > 1;
        var inProgress = !!session.is_in_progress;

        if (isMulti) {
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "多活动时段请在活动详情中修改单条活动时间。";
            showTimeStatus("", false);
            return;
        }
        if (inProgress) {
            // Single-activity but still open: displayed end_time may be projected, so editing is not safe.
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "进行中记录无法修改时间。";
            showTimeStatus("", false);
            return;
        }
        singleEl.hidden = false;
        multiEl.hidden = true;
        if (startEl) startEl.value = App.backendToDatetimeLocal(session.start_time);
        if (endEl) endEl.value = App.backendToDatetimeLocal(session.end_time);
        if (startEl) startEl.disabled = false;
        if (endEl) endEl.disabled = false;
        if (saveBtn) saveBtn.disabled = false;
        showTimeStatus("", false);
    }
    App.populateSessionTimeSection = populateSessionTimeSection;

    function resetSessionTimeSection() {
        App.timeSaving = false;
        var singleEl = document.getElementById("edit-time-single");
        var multiEl = document.getElementById("edit-time-multi");
        var startEl = document.getElementById("edit-start-time");
        var endEl = document.getElementById("edit-end-time");
        var saveBtn = document.getElementById("edit-time-save-btn");
        if (singleEl) singleEl.hidden = true;
        if (multiEl) {
            multiEl.hidden = true;
            multiEl.textContent = "多活动时段请在活动详情中修改单条活动时间。";
        }
        if (startEl) { startEl.value = ""; startEl.disabled = true; }
        if (endEl) { endEl.value = ""; endEl.disabled = true; }
        if (saveBtn) saveBtn.disabled = true;
        showTimeStatus("", false);
    }
    App.resetSessionTimeSection = resetSessionTimeSection;

    function showTimeStatus(message, isError) {
        var statusEl = document.getElementById("edit-time-status");
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
    App.showTimeStatus = showTimeStatus;

    function setTimeSaving(saving) {
        App.timeSaving = saving;
        var saveBtn = document.getElementById("edit-time-save-btn");
        var startEl = document.getElementById("edit-start-time");
        var endEl = document.getElementById("edit-end-time");
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "保存中…" : "保存时间";
        }
        if (startEl) startEl.disabled = saving;
        if (endEl) endEl.disabled = saving;
    }
    App.setTimeSaving = setTimeSaving;

    function saveSessionTime() {
        if (!App.editingSession || App.timeSaving) return;
        var activityIds = App.editingSession.activity_ids || [];
        if (activityIds.length !== 1) {
            showTimeStatus("多活动时段无法修改整体时间", true);
            return;
        }
        if (App.editingSession.is_in_progress) {
            showTimeStatus("进行中记录无法修改时间", true);
            return;
        }
        var startEl = document.getElementById("edit-start-time");
        var endEl = document.getElementById("edit-end-time");
        if (!startEl || !endEl) return;
        var startVal = App.datetimeLocalToBackend(startEl.value);
        var endVal = App.datetimeLocalToBackend(endEl.value);
        if (!startVal || !endVal) {
            showTimeStatus("时间无效", true);
            return;
        }
        if (endVal <= startVal) {
            showTimeStatus("结束时间必须晚于开始时间", true);
            return;
        }

        setTimeSaving(true);
        showTimeStatus("", false);
        App.callBridge("update_timeline_session_time", activityIds, startVal, endVal).then(function (result) {
            if (!result || result.ok === false) {
                setTimeSaving(false);
                showTimeStatus(result && result.error ? result.error : "保存时间失败", true);
                return;
            }
            // Update the baseline so a subsequent auto-refresh does not
            // revert the inputs to the pre-save values, and dirty checks
            // reflect the saved state.
            if (App.editingSession) {
                App.editingSession.start_time = startVal;
                App.editingSession.end_time = endVal;
            }
            // Reset the saving state before refreshing so the button is
            // re-enabled regardless of whether the refresh succeeds. The
            // save itself succeeded; a refresh failure is a separate concern
            // surfaced via the error banner.
            setTimeSaving(false);
            showTimeStatus("时间已更新", false);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setTimeSaving(false);
            showTimeStatus("保存时间失败", true);
        });
    }
    App.saveSessionTime = saveSessionTime;


    function loadTimeline(date) {
        App.setTimelineLoading(true);
        App.clearTimelineError();
        var token = ++App.timelineRequestToken;
        App.callBridge("get_timeline", date).then(function (result) {
            if (token !== App.timelineRequestToken) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                App.showTimelineError(msg || "加载时间线失败");
            });
            App.setTimelineLoading(false);
            if (!data) return;
            if (!acceptTimelinePayload(data, date)) return;
            App.timelineLoaded = true;
            showTimeline(data);
        }).catch(function () {
            if (token !== App.timelineRequestToken) return;  // stale response
            App.setTimelineLoading(false);
            // Never surface raw exception text; use the stable fallback so
            // internal details do not leak into the UI.
            App.showTimelineError("加载时间线失败");
        });
    }
    App.loadTimeline = loadTimeline;

    function refreshTimeline() {
        // Silent refresh: do not show loading spinner, just reload data.
        // On error, keep showing the previous data so the user is not left
        // looking at an empty list; only the error banner is shown.
        var dateEl = document.getElementById("timeline-date-input");
        var date = App.timelineDate || (dateEl ? dateEl.value : null);
        if (date === "--" || date === "") date = null;
        var token = ++App.timelineRequestToken;
        App.callBridge("get_timeline", date).then(function (result) {
            if (token !== App.timelineRequestToken) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                App.showTimelineError(msg || "刷新失败");
            });
            if (!data) return;
            if (!acceptTimelinePayload(data, date)) return;
            showTimeline(data);
            App.clearTimelineError();
        }).catch(function () {
            if (token !== App.timelineRequestToken) return;  // stale response
            // Only show error banner; keep lastTimelineData on screen.
            // Use the stable "刷新失败" fallback.
            App.showTimelineError("刷新失败");
        });
    }
    App.refreshTimeline = refreshTimeline;

    function reloadTimelineAfterRuntimeRefresh(date) {
        if (typeof App.setLiveRuntimeScope === "function") {
            App.setLiveRuntimeScope("timeline", date);
        }
        if (typeof App.refreshCurrentPageData === "function") {
            App.refreshCurrentPageData().then(function () {
                if (App.liveRuntime && App.liveRuntime.page === "timeline") {
                    loadTimeline(date);
                }
            });
        } else {
            loadTimeline(date);
        }
    }


    function goPrevDay() {
        var dateEl = document.getElementById("timeline-date-input");
        var current = App.timelineDate || (dateEl ? dateEl.value : null);
        App.timelineDate = App.shiftDate(current, -1);
        App.selectedSessionId = null;
        App.selectedSessionLiveKey = null;
        // Invalidate pending detail requests and clear the detail cache on
        // date switch so a stale response from the previous date does not
        // backfill the new date's detail panel.
        ++App.detailsRequestToken;
        App.lastSessionDetailsViewModel = null;
        // Close the correction shell on date switch so the shell context
        // does not carry over to a different day.
        App.resetCorrectionShellState();
        reloadTimelineAfterRuntimeRefresh(App.timelineDate);
    }
    App.goPrevDay = goPrevDay;

    function goNextDay() {
        var dateEl = document.getElementById("timeline-date-input");
        var current = App.timelineDate || (dateEl ? dateEl.value : null);
        App.timelineDate = App.shiftDate(current, 1);
        App.selectedSessionId = null;
        App.selectedSessionLiveKey = null;
        // Invalidate pending detail requests and clear the detail cache on
        // date switch.
        ++App.detailsRequestToken;
        App.lastSessionDetailsViewModel = null;
        // Close the correction shell on date switch.
        App.resetCorrectionShellState();
        reloadTimelineAfterRuntimeRefresh(App.timelineDate);
    }
    App.goNextDay = goNextDay;

    function goToday() {
        App.timelineDate = null;
        App.selectedSessionId = null;
        App.selectedSessionLiveKey = null;
        // Invalidate pending detail requests and clear the detail cache on
        // date switch.
        ++App.detailsRequestToken;
        App.lastSessionDetailsViewModel = null;
        // Close the correction shell on date switch.
        App.resetCorrectionShellState();
        reloadTimelineAfterRuntimeRefresh(null);
    }
    App.goToday = goToday;

})();
