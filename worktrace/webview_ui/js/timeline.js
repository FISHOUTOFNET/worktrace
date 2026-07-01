// WorkTrace WebView frontend — timeline module (Phase R2 split).
// Timeline page: session list, detail list, edit panel, per-activity
// inline editors (time / split / merge / hide / delete), session-level
// correction sections, date navigation.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Timeline rendering ---------------------------------------------

    function showTimeline(data) {
        if (!data) return;
        App.lastTimelineData = data;
        document.getElementById("timeline-date-display").textContent = data.date || "--";
        document.getElementById("timeline-total").textContent = data.total_duration || "00:00:00";
        var current = data.current_activity || {};
        var currentEl = document.getElementById("timeline-current");
        if (current.active) {
            currentEl.textContent = "当前活动：" + current.display;
        } else {
            currentEl.textContent = "当前活动：无";
        }

        var listEl = document.getElementById("timeline-sessions-list");
        var sessions = data.sessions || [];
        App.currentSessions = sessions;
        if (sessions.length === 0) {
            listEl.innerHTML = '<div class="timeline-empty">当日暂无活动记录</div>';
            // Verification item 22: invalidate any pending detail request so
            // a stale ``get_timeline_session_details`` response does not
            // backfill the cleared detail panel. Also clear the detail cache
            // so the ticker does not project against a stale payload.
            ++App.detailsRequestToken;
            App.lastSessionDetailsData = null;
            document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
            document.getElementById("timeline-details-list").innerHTML = "";
            App.selectedSessionId = null;
            clearEditPanel();
            return;
        }

        // Build the full HTML string before replacing to avoid flicker.
        var html = "";
        // Phase 6H-followup: collect continuity keys to reset after the
        // innerHTML swap so the fresh backend snapshot duration replaces any prior ticker
        // projection without a false "rollback" guard.
        var sessionContinuityKeys = [];
        for (var i = 0; i < sessions.length; i++) {
            var s = sessions[i];
            var timeRange = App.formatTimeRange(s.start_time, s.end_time, s.is_in_progress);
            var projectLabel = s.project_name || "未归类";
            if (s.project_description) {
                projectLabel += " (" + s.project_description + ")";
            }
            // Phase 6H-followup: prefer ``duration_seconds`` (raw int from
            // the backend) over the pre-formatted ``duration`` string so
            // the ticker / monotonic helper can recompute from a stable
            // baseline. The ``duration`` string is kept as a fallback.
            var sDurSec = parseInt(s.duration_seconds, 10);
            var sDurText = (!isNaN(sDurSec) && sDurSec >= 0)
                ? App.formatDuration(sDurSec)
                : (s.duration || "00:00:00");
            var cls = "timeline-item";
            if (s.is_uncategorized) cls += " uncategorized";
            if (s.is_in_progress) cls += " in-progress";
            if (s.is_live_projected === true) cls += " live-projected";
            if (s.is_virtual === true) cls += " virtual-live";
            if (s.session_id === App.selectedSessionId) cls += " selected";
            html += '<div class="' + cls + '" data-session-id="' + App.escapeHtml(s.session_id) + '"'
                + ' title="' + App.escapeHtml(projectLabel) + '｜' + App.escapeHtml(timeRange) + '｜' + App.escapeHtml(sDurText) + '"'
                + '>'
                + '<div class="timeline-item-main">'
                + '<div class="timeline-item-project">' + App.escapeHtml(projectLabel) + '</div>'
                + '<div class="timeline-item-time">' + App.escapeHtml(timeRange) + '</div>'
                + '<div class="timeline-item-status">' + App.escapeHtml(s.status || "") + '</div>'
                + '</div>'
                + '<div class="timeline-item-side">'
                + '<div class="timeline-item-duration" data-duration-seconds="' + (isNaN(sDurSec) ? 0 : sDurSec) + '">' + App.escapeHtml(sDurText) + '</div>'
                + '<div class="timeline-item-count">' + App.escapeHtml(String(s.event_count || 0) + " 条") + '</div>'
                + '</div>'
                + '</div>';
            // The continuity key MUST use App.liveContinuityKey() so the
            // ticker (which also uses liveContinuityKey) can locate the
            // seeded state. Using "session-" + session_id would break the
            // virtual → persisted_open transition because the ticker key
            // is based on stable_live_key_hash, not session_id.
            sessionContinuityKeys.push({ key: App.liveContinuityKey(s, "session"), sec: isNaN(sDurSec) ? 0 : sDurSec });
        }
        listEl.innerHTML = html;
        // Phase 6H-followup: reset + seed the monotonic render state for
        // each session so the fresh backend snapshot duration replaces any prior ticker
        // projection and the ticker's first delta does not appear to roll back.
        for (var ci = 0; ci < sessionContinuityKeys.length; ci++) {
            var ck = sessionContinuityKeys[ci];
            App._monotonicRenderState[ck.key] = { lastSeconds: ck.sec };
        }
        // Also reset the timeline-total continuity so the fresh backend total
        // duration replaces any prior ticker projection.
        var tlTotalSec = parseInt(data.today_total_seconds, 10) || 0;
        App._monotonicRenderState["timeline-total"] = { lastSeconds: tlTotalSec };

        // Bind click handlers to session items
        var items = listEl.querySelectorAll(".timeline-item");
        for (var j = 0; j < items.length; j++) {
            (function (itemEl) {
                itemEl.addEventListener("click", function () {
                    var sid = itemEl.getAttribute("data-session-id");
                    selectTimelineSession(sid, sessions);
                });
            })(items[j]);
        }

        // If the previously selected session still exists, reload its details.
        if (App.selectedSessionId !== null) {
            var found = null;
            for (var k = 0; k < sessions.length; k++) {
                if (sessions[k].session_id === App.selectedSessionId) {
                    found = sessions[k];
                    break;
                }
            }
            if (found) {
                // Phase R3 issues 11/17: skip the detail reload when any
                // Timeline editing is active — unsaved session edits, open
                // inline time/split editors, saving states, or correction
                // shell. Auto-refresh / revision-change refresh must never
                // wipe in-progress edits or overwrite user input. After a
                // successful save the baseline is updated so isEditDirty()
                // returns false and the reload proceeds normally.
                var skipDetailReload = (typeof App._timelineEditingActive === "function"
                    && App._timelineEditingActive());
                if (!skipDetailReload) {
                    loadSessionDetails(found.activity_ids, data.date);
                }
                // Only re-populate the edit panel if the user is not mid-edit
                // AND the session is not edit-disabled (virtual live session).
                // Auto-refresh must not overwrite unsaved edits.
                if (!found.edit_disabled
                    && (!App.editingSession || App.editingSession.session_id !== found.session_id || !isEditDirty())) {
                    populateEditPanel(found);
                } else if (found.edit_disabled) {
                    // Virtual live session: clear the edit panel since it
                    // cannot be edited.
                    clearEditPanel();
                }
                // Phase 3B.5B: if the correction shell is open for this
                // session, refresh its context summary from the updated
                // session object. The activity summary is re-read from the
                // rendered detail rows. No write is performed.
                // Phase 3B.9.1: also skip the re-render while any
                // correction-shell write is in flight (batch project / batch
                // note / single restore) so the saving state, selection,
                // textarea, and status messages are not overwritten mid-save.
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
                // Selected session disappeared (e.g. session ended and was
                // re-grouped). Clear selection gracefully without throwing.
                // Verification item 22: invalidate any pending detail request
                // and clear the detail cache so a stale response does not
                // backfill the cleared detail panel.
                ++App.detailsRequestToken;
                App.lastSessionDetailsData = null;
                App.selectedSessionId = null;
                document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
                document.getElementById("timeline-details-list").innerHTML = "";
                clearEditPanel();
            }
        }
    }
    App.showTimeline = showTimeline;

    function selectTimelineSession(sessionId, sessions) {
        App.selectedSessionId = sessionId;
        // Phase 3B.5B: switching sessions closes the correction shell so
        // the shell context does not get confused across sessions. The
        // shell is a per-session workspace.
        if (App.correctionShellOpen && App.correctionShellSessionId !== sessionId) {
            App.resetCorrectionShellState();
        }
        // Update selected class without full re-render
        var items = document.querySelectorAll("#timeline-sessions-list .timeline-item");
        for (var i = 0; i < items.length; i++) {
            items[i].classList.remove("selected");
            if (items[i].getAttribute("data-session-id") === sessionId) {
                items[i].classList.add("selected");
            }
        }
        // Find the session to get activity_ids
        var found = null;
        for (var j = 0; j < sessions.length; j++) {
            if (sessions[j].session_id === sessionId) {
                found = sessions[j];
                break;
            }
        }
        if (found) {
            var dateEl = document.getElementById("timeline-date-display");
            loadSessionDetails(found.activity_ids, dateEl ? dateEl.textContent : null);
            // Verification item 4: virtual live sessions are display-only.
            // A manual click on a virtual session must NOT open the edit
            // panel — it has no persisted activity_ids and cannot be
            // edited. Clear the edit panel instead so any prior session's
            // edit panel is dismissed.
            if (found.edit_disabled === true || found.is_virtual === true) {
                clearEditPanel();
            } else {
                // Populate the edit panel with the selected session's fields.
                // A manual click always repopulates, even if a prior auto-refresh
                // had skipped repopulation due to unsaved edits.
                populateEditPanel(found);
            }
        }
    }
    App.selectTimelineSession = selectTimelineSession;

    function loadSessionDetails(activityIds, date) {
        var detailsHeader = document.getElementById("timeline-details-header");
        var detailsList = document.getElementById("timeline-details-list");
        // Only show the "loading" placeholder when the panel is empty. If
        // we already have details on screen, keep them visible while the
        // new data loads so a refresh does not flash an empty panel.
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
            renderSessionDetails(data);
        }).catch(function () {
            if (token !== App.detailsRequestToken) return;  // stale response
            detailsHeader.textContent = "加载详情失败";
            detailsList.innerHTML = '<div class="timeline-empty">无法加载详情，请稍后重试。</div>';
        });
    }
    App.loadSessionDetails = loadSessionDetails;

    function renderSessionDetails(data) {
        // Phase R3 issue 17: skip the full re-render when the user has
        // unsaved inline editor / split editor input or a save is in
        // progress. The heartbeat / revision refresh must not overwrite
        // user input by re-rendering the detail list (which would reset
        // inline editor inputs to backend values). After a successful
        // save, isEditDirty() returns false so the re-render proceeds.
        //
        // Verification item 14: when the DOM render is skipped, ALSO skip
        // the cache update. Previously ``App.lastSessionDetailsData`` was set
        // BEFORE the dirty-editor guard, so the ticker would project against
        // a newer payload while the DOM still showed the old one, causing
        // cache/DOM desync. Now the cache is updated only when the DOM is
        // actually rendered, keeping them atomic.
        if ((App.editingActivityId !== null || App.editingSplitActivityId !== null)
            && typeof App.isEditDirty === "function" && App.isEditDirty()) {
            return;
        }
        if (App.activityTimeSaving || App.activitySplitSaving) {
            return;
        }
        // Phase 6H-followup: cache the session-details payload so the
        // 1-second heartbeat ticker can increment the live-projected
        // detail row's duration without a bridge round-trip. The ticker
        // only updates DOM text; it never re-renders the whole list so
        // inline edit state is preserved across heartbeat refreshes.
        App.lastSessionDetailsData = data;
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
        // Phase 6H-followup: collect detail continuity keys for seeding.
        var detailContinuityKeys = [];
        for (var i = 0; i < activities.length; i++) {
            var a = activities[i];
            var timeRange = App.formatTimeRange(a.start_time, a.end_time, a.is_in_progress);
            var displayName = a.resource_name || a.app_name || "未知";
            // Phase 6H-followup: prefer ``duration_seconds`` (raw int from
            // the backend) over the pre-formatted ``duration`` string so
            // the ticker / monotonic helper can recompute from a stable
            // baseline. The ``duration`` string is kept as a fallback.
            var aDurSec = parseInt(a.duration_seconds, 10);
            var aDurText = (!isNaN(aDurSec) && aDurSec >= 0)
                ? App.formatDuration(aDurSec)
                : (a.duration || "00:00:00");
            var cls = "detail-item";
            if (a.is_in_progress) cls += " in-progress";
            if (a.is_virtual === true) cls += " virtual-live";
            // Per-activity inline time editor (Phase 3B.1). The button is
            // disabled for in-progress activities because their displayed
            // end_time may be a projected value. The editor container is
            // hidden by default and only shown when the user clicks the
            // button. Only one inline editor can be open at a time.
            // Phase 3B.2 also adds an inline split editor with the same
            // in-progress/missing-id disable rules.
            // Phase R3: virtual detail rows (edit_disabled) also disable
            // all action buttons since the activity is not yet persisted.
            var aid = a.activity_id || 0;
            var editBtnDisabled = a.is_in_progress || !aid || a.edit_disabled === true;
            var disableReason = a.disable_reason || "";
            var editBtnTitle = disableReason
                ? disableReason
                : (a.is_in_progress
                    ? "进行中记录无法修改时间"
                    : (aid ? "编辑该活动时间" : "活动 ID 缺失，无法编辑"));
            var splitBtnTitle = disableReason
                ? disableReason
                : (a.is_in_progress
                    ? "进行中记录无法拆分"
                    : (aid ? "在该时间点拆分此活动" : "活动 ID 缺失，无法拆分"));
            // Phase 3B.3: per-activity "与下一条合并" button. The button is
            // disabled when there is no next activity, when either the
            // current or next activity is in-progress, or when the current
            // activity id is missing. The backend re-validates all merge
            // preconditions (project, resource, status, adjacency).
            var hasNext = i < activities.length - 1;
            var nextInProgress = hasNext && activities[i + 1].is_in_progress;
            var mergeBtnDisabled = !aid || a.is_in_progress || !hasNext || nextInProgress || a.edit_disabled === true;
            var mergeBtnTitle = disableReason
                ? disableReason
                : (!aid
                    ? "活动 ID 缺失，无法合并"
                    : (a.is_in_progress
                        ? "进行中记录无法合并"
                        : (!hasNext
                            ? "已是最后一条活动，没有下一条可合并"
                            : (nextInProgress
                                ? "下一条活动进行中，无法合并"
                                : "将此活动与下一条活动合并"))));
            // Phase 3B.4: per-activity "隐藏" and "删除" buttons. Both are
            // disabled for in-progress activities (raw end_time IS NULL) and
            // when the activity id is missing. The delete button uses a
            // confirmation dialog (window.confirm) before calling the bridge.
            var visibilityBtnDisabled = a.is_in_progress || !aid || a.edit_disabled === true;
            var visibilityBtnTitle = disableReason
                ? disableReason
                : (a.is_in_progress
                    ? "进行中记录无法隐藏或删除"
                    : (aid ? "从 Timeline 隐藏或删除此活动" : "活动 ID 缺失，无法操作"));
            html += '<div class="' + cls + '" data-activity-id="' + App.escapeHtml(String(aid)) + '"'
                + ' data-detail-index="' + i + '"'
                + '>'
                + '<div class="detail-item-time">' + App.escapeHtml(timeRange) + '</div>'
                + '<div class="detail-item-name" title="' + App.escapeHtml(displayName) + '">' + App.escapeHtml(displayName) + '</div>'
                + '<div class="detail-item-meta">'
                + '<span class="detail-item-type">' + App.escapeHtml(a.resource_type || "") + '</span>'
                + '<span class="detail-item-app">' + App.escapeHtml(a.app_name || "") + '</span>'
                + '</div>'
                + '<div class="detail-item-project" title="' + App.escapeHtml(a.project_name || "未归类") + '">' + App.escapeHtml(a.project_name || "未归类") + '</div>'
                + '<div class="detail-item-duration" data-duration-seconds="' + (isNaN(aDurSec) ? 0 : aDurSec) + '">' + App.escapeHtml(aDurText) + '</div>'
                // Phase 3B.5A: per-activity correction actions are grouped
                // into three visually distinct groups with a stable order:
                // edit group (编辑时间 → 拆分) → merge group (与下一条合并)
                // → danger group (隐藏 → 删除). No new actions are added;
                // the wrappers only consolidate existing buttons so the
                // destructive actions are clearly separated from edits.
                + '<div class="detail-item-actions">'
                + '<div class="detail-action-edit-group">'
                + '<button type="button" class="detail-edit-time-btn"'
                + ' data-activity-id="' + App.escapeHtml(String(aid)) + '"'
                + ' data-start="' + App.escapeHtml(a.start_time || "") + '"'
                + ' data-end="' + App.escapeHtml(a.end_time || "") + '"'
                + (editBtnDisabled ? ' disabled' : '')
                + ' title="' + App.escapeHtml(editBtnTitle) + '"'
                + '>编辑时间</button>'
                + '<button type="button" class="detail-split-btn"'
                + ' data-activity-id="' + App.escapeHtml(String(aid)) + '"'
                + ' data-start="' + App.escapeHtml(a.start_time || "") + '"'
                + ' data-end="' + App.escapeHtml(a.end_time || "") + '"'
                + (editBtnDisabled ? ' disabled' : '')
                + ' title="' + App.escapeHtml(splitBtnTitle) + '"'
                + '>拆分</button>'
                + '</div>'
                + '<div class="detail-action-merge-group">'
                + '<button type="button" class="detail-merge-btn"'
                + ' data-activity-id="' + App.escapeHtml(String(aid)) + '"'
                + ' data-next-activity-id="' + App.escapeHtml(String(hasNext ? (activities[i + 1].activity_id || 0) : 0)) + '"'
                + (mergeBtnDisabled ? ' disabled' : '')
                + ' title="' + App.escapeHtml(mergeBtnTitle) + '"'
                + '>与下一条合并</button>'
                + '</div>'
                + '<div class="detail-action-danger-group">'
                + '<button type="button" class="detail-hide-btn"'
                + ' data-activity-id="' + App.escapeHtml(String(aid)) + '"'
                + (visibilityBtnDisabled ? ' disabled' : '')
                + ' title="' + App.escapeHtml(visibilityBtnTitle) + '"'
                + '>隐藏</button>'
                + '<button type="button" class="detail-delete-btn"'
                + ' data-activity-id="' + App.escapeHtml(String(aid)) + '"'
                + (visibilityBtnDisabled ? ' disabled' : '')
                + ' title="' + App.escapeHtml(visibilityBtnTitle) + '"'
                + '>删除</button>'
                + '</div>'
                + '</div>'
                + '<div class="detail-time-editor" hidden>'
                + '<div class="detail-time-row">'
                + '<label>开始</label>'
                + '<input type="datetime-local" class="detail-time-input detail-time-start" step="1">'
                + '</div>'
                + '<div class="detail-time-row">'
                + '<label>结束</label>'
                + '<input type="datetime-local" class="detail-time-input detail-time-end" step="1">'
                + '</div>'
                + '<div class="detail-time-actions">'
                + '<button type="button" class="detail-time-save-btn">保存</button>'
                + '<button type="button" class="detail-time-cancel-btn">取消</button>'
                + '</div>'
                + '<div class="detail-time-status edit-status" hidden></div>'
                + '</div>'
                + '<div class="detail-split-editor" hidden>'
                + '<div class="detail-time-row">'
                + '<label>拆分点</label>'
                + '<input type="datetime-local" class="detail-time-input detail-split-time" step="1">'
                + '</div>'
                + '<div class="detail-time-actions">'
                + '<button type="button" class="detail-split-save-btn">拆分</button>'
                + '<button type="button" class="detail-split-cancel-btn">取消</button>'
                + '</div>'
                + '<div class="detail-split-status edit-status" hidden></div>'
                + '</div>'
                + '<div class="detail-merge-status edit-status" hidden></div>'
                + '<div class="detail-visibility-status edit-status" hidden></div>'
                + '</div>';
            // Phase 6H-followup: collect this row's continuity key so the
            // monotonic state can be seeded after the innerHTML swap.
            detailContinuityKeys.push({ index: i, sec: isNaN(aDurSec) ? 0 : aDurSec });
        }
        detailsList.innerHTML = html;
        // Phase 6H-followup: seed the monotonic render state for each detail
        // row so the ticker's first projection does not appear to roll back.
        // The continuity key MUST use App.liveContinuityKey() so the ticker
        // (which also uses liveContinuityKey) can locate the seeded state.
        // Using "detail-" + activity_id would break the virtual →
        // persisted_open transition because the ticker key is based on
        // stable_live_key_hash, not activity_id.
        for (var di = 0; di < detailContinuityKeys.length; di++) {
            var dk = detailContinuityKeys[di];
            var activitiesRef = data.activities || [];
            var detailItem = activitiesRef[dk.index] || {};
            var detailKey = App.liveContinuityKey(detailItem, "detail");
            App._monotonicRenderState[detailKey] = { lastSeconds: dk.sec };
        }

        // Bind per-activity "编辑时间" button handlers. Event delegation is
        // used so re-rendering the list does not leak listeners.
        var editBtns = detailsList.querySelectorAll(".detail-edit-time-btn");
        for (var j = 0; j < editBtns.length; j++) {
            (function (btn) {
                btn.addEventListener("click", function () {
                    if (btn.disabled) return;
                    var id = parseInt(btn.getAttribute("data-activity-id"), 10);
                    var startVal = btn.getAttribute("data-start") || "";
                    var endVal = btn.getAttribute("data-end") || "";
                    openActivityTimeEditor(id, startVal, endVal, btn);
                });
            })(editBtns[j]);
        }

        // Phase 3B.2: bind per-activity "拆分" button handlers.
        var splitBtns = detailsList.querySelectorAll(".detail-split-btn");
        for (var s = 0; s < splitBtns.length; s++) {
            (function (btn) {
                btn.addEventListener("click", function () {
                    if (btn.disabled) return;
                    var id = parseInt(btn.getAttribute("data-activity-id"), 10);
                    var startVal = btn.getAttribute("data-start") || "";
                    var endVal = btn.getAttribute("data-end") || "";
                    openActivitySplitEditor(id, startVal, endVal, btn);
                });
            })(splitBtns[s]);
        }

        // Phase 3B.3: bind per-activity "与下一条合并" button handlers.
        var mergeBtns = detailsList.querySelectorAll(".detail-merge-btn");
        for (var mIdx = 0; mIdx < mergeBtns.length; mIdx++) {
            (function (btn) {
                btn.addEventListener("click", function () {
                    if (btn.disabled || App.mergeSaving) return;
                    var id = parseInt(btn.getAttribute("data-activity-id"), 10);
                    var nextId = parseInt(btn.getAttribute("data-next-activity-id"), 10);
                    if (!id || !nextId) return;
                    saveActivityMerge(btn, id, nextId);
                });
            })(mergeBtns[mIdx]);
        }

        // Phase 3B.3: if a merge save is in progress for an activity that
        // still exists, re-apply the saving state to the refreshed button so
        // the user sees consistent "合并中…" feedback across auto-refresh.
        // If the activity disappeared (session regroup), reset the merge
        // state so the UI does not get stuck.
        if (App.mergingActivityId !== null && App.mergeSaving) {
            var mergeStillThere = false;
            for (var mCheck = 0; mCheck < mergeBtns.length; mCheck++) {
                if (parseInt(mergeBtns[mCheck].getAttribute("data-activity-id"), 10) === App.mergingActivityId) {
                    mergeStillThere = true;
                    setMergeSaving(mergeBtns[mCheck], true);
                    break;
                }
            }
            if (!mergeStillThere) {
                App.mergingActivityId = null;
                App.mergeSaving = false;
            }
        }

        // Phase 3B.4: bind per-activity "隐藏" and "删除" button handlers.
        var hideBtns = detailsList.querySelectorAll(".detail-hide-btn");
        for (var hIdx = 0; hIdx < hideBtns.length; hIdx++) {
            (function (btn) {
                btn.addEventListener("click", function () {
                    if (btn.disabled || App.hideSaving) return;
                    var id = parseInt(btn.getAttribute("data-activity-id"), 10);
                    if (!id) return;
                    saveActivityHide(btn, id);
                });
            })(hideBtns[hIdx]);
        }
        var deleteBtns = detailsList.querySelectorAll(".detail-delete-btn");
        for (var dIdx = 0; dIdx < deleteBtns.length; dIdx++) {
            (function (btn) {
                btn.addEventListener("click", function () {
                    if (btn.disabled || App.deleteSaving) return;
                    var id = parseInt(btn.getAttribute("data-activity-id"), 10);
                    if (!id) return;
                    saveActivityDelete(btn, id);
                });
            })(deleteBtns[dIdx]);
        }

        // Phase 3B.4: if a hide or delete save is in progress for an
        // activity that still exists, re-apply the saving state so the user
        // sees consistent feedback across auto-refresh. If the activity
        // disappeared (session regroup), reset the state so the UI does not
        // get stuck.
        if (App.hidingActivityId !== null && App.hideSaving) {
            var hideStillThere = false;
            for (var hCheck = 0; hCheck < hideBtns.length; hCheck++) {
                if (parseInt(hideBtns[hCheck].getAttribute("data-activity-id"), 10) === App.hidingActivityId) {
                    hideStillThere = true;
                    setHideSaving(hideBtns[hCheck], true);
                    break;
                }
            }
            if (!hideStillThere) {
                App.hidingActivityId = null;
                App.hideSaving = false;
            }
        }
        if (App.deletingActivityId !== null && App.deleteSaving) {
            var deleteStillThere = false;
            for (var dCheck = 0; dCheck < deleteBtns.length; dCheck++) {
                if (parseInt(deleteBtns[dCheck].getAttribute("data-activity-id"), 10) === App.deletingActivityId) {
                    deleteStillThere = true;
                    setDeleteSaving(deleteBtns[dCheck], true);
                    break;
                }
            }
            if (!deleteStillThere) {
                App.deletingActivityId = null;
                App.deleteSaving = false;
            }
        }

        // If an inline editor was open for an activity that still exists,
        // re-open it with the refreshed values so the user's editing context
        // is preserved across auto-refresh. If the activity disappeared, the
        // editor state is cleared below.
        if (App.editingActivityId !== null) {
            var stillOpen = false;
            var refreshedBtn = null;
            for (var k = 0; k < editBtns.length; k++) {
                if (parseInt(editBtns[k].getAttribute("data-activity-id"), 10) === App.editingActivityId) {
                    stillOpen = true;
                    refreshedBtn = editBtns[k];
                    break;
                }
            }
            if (stillOpen && refreshedBtn && !refreshedBtn.disabled && !App.activityTimeSaving) {
                openActivityTimeEditor(
                    App.editingActivityId,
                    refreshedBtn.getAttribute("data-start") || "",
                    refreshedBtn.getAttribute("data-end") || "",
                    refreshedBtn
                );
            } else if (!stillOpen) {
                // Activity disappeared (e.g. session regroup). Reset state.
                App.editingActivityId = null;
                App.activityTimeSaving = false;
            }
        }

        // Phase 3B.2: re-open the inline split editor if it was open and the
        // activity still exists. If the activity disappeared, reset state.
        if (App.editingSplitActivityId !== null) {
            var splitStillOpen = false;
            var refreshedSplitBtn = null;
            for (var m = 0; m < splitBtns.length; m++) {
                if (parseInt(splitBtns[m].getAttribute("data-activity-id"), 10) === App.editingSplitActivityId) {
                    splitStillOpen = true;
                    refreshedSplitBtn = splitBtns[m];
                    break;
                }
            }
            if (splitStillOpen && refreshedSplitBtn && !refreshedSplitBtn.disabled && !App.activitySplitSaving) {
                openActivitySplitEditor(
                    App.editingSplitActivityId,
                    refreshedSplitBtn.getAttribute("data-start") || "",
                    refreshedSplitBtn.getAttribute("data-end") || "",
                    refreshedSplitBtn
                );
            } else if (!splitStillOpen) {
                App.editingSplitActivityId = null;
                App.activitySplitSaving = false;
            }
        }
    }
    App.renderSessionDetails = renderSessionDetails;

    // --- Phase 3B.1: per-activity inline time editor -------------------

    function openActivityTimeEditor(activityId, startVal, endVal, btn) {
        if (!btn) return;
        // Close any other open inline editor first so only one is visible
        // at a time. This keeps the editing context unambiguous.
        closeAllActivityTimeEditors(activityId);
        // Phase 3B.2: also close any open split editor so the time editor is
        // the only inline editor visible.
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
        // Wire up save/cancel for this editor instance. Re-binding is safe
        // because we replace the listener by cloning is unnecessary — we
        // simply attach and rely on the editor being hidden after close.
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
        // Only clear editingActivityId if it matches the row being closed,
        // so closing one editor does not wipe state for a different one.
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
            // Update the button's baseline so a subsequent auto-refresh
            // does not revert the editor inputs to the pre-save values.
            var btn = row.querySelector(".detail-edit-time-btn");
            if (btn) {
                btn.setAttribute("data-start", startVal);
                btn.setAttribute("data-end", endVal);
            }
            setActivityTimeStatus(row, "时间已更新", false);
            // Keep the editor open but re-enable inputs so the user can see
            // the saved values. The next auto-refresh will re-render with
            // the new server data.
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

    // --- Phase 3B.2: per-activity inline split editor ------------------

    function openActivitySplitEditor(activityId, startVal, endVal, btn) {
        if (!btn) return;
        // Close any other open inline editor first so only one is visible
        // at a time. This keeps the editing context unambiguous.
        closeAllActivitySplitEditors(activityId);
        // Also close any open time editor so the split editor is the only
        // inline editor visible.
        closeAllActivityTimeEditors(activityId);
        App.editingSplitActivityId = activityId;
        var row = btn.closest(".detail-item");
        if (!row) return;
        var editor = row.querySelector(".detail-split-editor");
        if (!editor) return;
        var splitInput = editor.querySelector(".detail-split-time");
        // Default the split point to the midpoint between start and end so
        // the user has a reasonable starting value. Use the fixed-format
        // string conversion helpers, NOT Date parsing, to avoid timezone
        // shifts.
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
        // Only clear editingSplitActivityId if it matches the row being
        // closed, so closing one editor does not wipe state for a different
        // one.
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
        // The button's data-start/data-end attributes hold the activity's
        // current server-returned start/end; use them for the range check so
        // a stale editor on a re-rendered row cannot submit a bad split.
        var btn = row.querySelector(".detail-split-btn");
        var actStart = btn ? (btn.getAttribute("data-start") || "") : "";
        var actEnd = btn ? (btn.getAttribute("data-end") || "") : "";
        var splitVal = App.datetimeLocalToBackend(splitInput.value);
        if (!splitVal) {
            setActivitySplitStatus(row, "拆分时间无效", true);
            return;
        }
        // Frontend range check: split must be strictly between start and end.
        // The backend re-validates this, but the frontend check gives the
        // user immediate feedback without a round-trip.
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
            // Split succeeded. Close the editor and refresh the Timeline so
            // the two new activities appear. Reset the saving state before
            // refreshing so the inputs are re-enabled regardless of whether
            // the refresh succeeds.
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

    // --- Phase 3B.3: per-activity merge with next activity ------------

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
        // Phase 3B.5A: guard against unsaved edits, consistent with hide /
        // delete. Merge triggers a refresh that would wipe unsaved
        // project/note/time/split inputs, so require the user to save or
        // cancel first.
        if (isEditDirty()) {
            setMergeStatus(btn, "请先保存或取消当前编辑", true);
            return;
        }
        // Verify the activity id still matches the row so a stale button
        // (e.g. after rapid session switching) does not operate on a
        // different session's activity. Consistent with hide / delete.
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
            // Merge succeeded. Reset saving state before refreshing so the
            // button is re-enabled regardless of whether the refresh
            // succeeds. The merge changes the activity's end_time and
            // soft-deletes the next activity, so the detail list must be
            // refreshed.
            setMergeSaving(btn, false);
            setMergeStatus(btn, "已合并", false);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setMergeSaving(btn, false);
            setMergeStatus(btn, "合并失败", true);
        });
    }
    App.saveActivityMerge = saveActivityMerge;

    // --- Phase 3B.4: per-activity hide / soft delete ------------------

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
        // Also disable the delete button on the same row during a hide so
        // the user cannot start a conflicting operation.
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
        // Guard against unsaved edits: hide is an immediate action that
        // triggers a refresh, which would wipe unsaved project/note/time/
        // split inputs. Require the user to save or cancel first.
        if (isEditDirty()) {
            setVisibilityStatus(btn, "请先保存或取消当前编辑", true);
            return;
        }
        // Verify the activity id still exists in the current details list
        // so a stale button (e.g. after rapid session switching) does not
        // operate on a different session's activity.
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

        // Lightweight confirmation so the user does not accidentally
        // soft-delete. The message makes clear this is not a permanent
        // delete. Uses native window.confirm — no third-party library.
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

    // --- Phase 3B.4: session-level hide / soft delete -----------------

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

    // --- Phase 3A: Timeline editing (project reclassification + note) ----

    function loadProjects() {
        // Load the selectable projects list once and cache it. Subsequent
        // calls reuse the cache so we do not hit the bridge every time the
        // user selects a session.
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
        // Phase 3B.1: when switching to a different session, reset the
        // per-activity inline editor state so a stale editingActivityId
        // from the previous session does not leak into the new one. The
        // detail list DOM will be rebuilt by renderSessionDetails.
        if (App.editingSession && App.editingSession.session_id !== session.session_id) {
            App.editingActivityId = null;
            App.activityTimeSaving = false;
            // Phase 3B.2: reset per-activity inline split editor state too.
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

        // Note textarea: load existing note (the editing target only).
        var noteEl = document.getElementById("edit-note-text");
        if (noteEl) {
            noteEl.value = session.session_note || "";
            noteEl.disabled = false;
        }

        // Enable save/cancel buttons first, then let updateNoteCount apply
        // the over-limit disable so the length check has the final say.
        var saveBtn = document.getElementById("edit-save-btn");
        var cancelBtn = document.getElementById("edit-cancel-btn");
        if (saveBtn) saveBtn.disabled = false;
        if (cancelBtn) cancelBtn.disabled = false;
        if (noteEl) updateNoteCount();

        // Phase 3B.1: populate the session-level time-correction section.
        populateSessionTimeSection(session);
        // Phase 3B.2: populate the session-level split section.
        populateSessionSplitSection(session);
        // Phase 3B.4: populate the session-level hide / soft-delete section.
        populateSessionVisibilitySection(session);

        // Clear any prior status message
        showEditStatus("", false);
    }
    App.populateEditPanel = populateEditPanel;

    function clearEditPanel() {
        App.editingSession = null;
        App.editSaving = false;
        App.timeSaving = false;
        // Phase 3B.1: reset per-activity inline editor state. The detail
        // list DOM is typically rebuilt by renderSessionDetails, but the
        // tracking variables must be cleared so a stale editingActivityId
        // does not leak into the next session.
        App.editingActivityId = null;
        App.activityTimeSaving = false;
        // Phase 3B.2: reset per-activity inline split editor state too.
        App.editingSplitActivityId = null;
        App.activitySplitSaving = false;
        App.sessionSplitSaving = false;
        // Phase 3B.3: reset per-activity merge state too.
        App.mergeSaving = false;
        App.mergingActivityId = null;
        // Phase 3B.4: reset per-activity hide / delete state too.
        App.hideSaving = false;
        App.hidingActivityId = null;
        App.deleteSaving = false;
        App.deletingActivityId = null;
        // Phase 3B.6: reset batch project selection state so a stale batch
        // selection from the previous session does not leak into the next
        // session. The reset also clears the project select / status so the
        // panel returns to a clean baseline.
        App.resetBatchProjectState();
        // Phase 3B.7: reset batch note state too so a stale note textarea /
        // saving flag does not leak into the next session.
        App.resetBatchNoteState();
        // Phase 3B.8: reset restore state too so a stale restore list /
        // saving flag does not leak into the next session.
        App.resetRestoreState();
        // Phase 3B.5B: reset the correction shell state too so a stale
        // shell does not leak into the next session.
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
        var saveBtn = document.getElementById("edit-save-btn");
        var cancelBtn = document.getElementById("edit-cancel-btn");
        if (saveBtn) saveBtn.disabled = true;
        if (cancelBtn) cancelBtn.disabled = true;
        showEditStatus("", false);
        // Phase 3B.1: reset the session-level time-correction section.
        resetSessionTimeSection();
        // Phase 3B.2: reset the session-level split section.
        resetSessionSplitSection();
        // Phase 3B.4: reset the session-level hide / soft-delete section.
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
        // Phase 3B.1: session-level time inputs. If the user has modified
        // either the start or end time, the edit panel is dirty so
        // auto-refresh does not revert the inputs to the server values.
        var startEl = document.getElementById("edit-start-time");
        var endEl = document.getElementById("edit-end-time");
        if (startEl && !startEl.disabled) {
            var currentStart = App.datetimeLocalToBackend(startEl.value);
            var originalStart = App.editingSession.start_time || "";
            if (currentStart !== originalStart) return true;
        }
        if (endEl && !endEl.disabled) {
            var currentEnd = App.datetimeLocalToBackend(endEl.value);
            var originalEnd = App.editingSession.end_time || "";
            if (currentEnd !== originalEnd) return true;
        }
        // Phase 3B.1: per-activity inline editor. If an editor is open and
        // the user has modified the inputs, treat the panel as dirty so the
        // detail list is not re-rendered (which would lose the edits).
        if (App.editingActivityId !== null) {
            var editorRow = document.querySelector(
                '#timeline-details-list .detail-item[data-activity-id="'
                + App.editingActivityId + '"]'
            );
            if (editorRow) {
                var editor = editorRow.querySelector(".detail-time-editor");
                if (editor && !editor.hidden) {
                    var actStart = editor.querySelector(".detail-time-start");
                    var actEnd = editor.querySelector(".detail-time-end");
                    var actBtn = editorRow.querySelector(".detail-edit-time-btn");
                    if (actStart && actEnd && actBtn) {
                        var curActStart = App.datetimeLocalToBackend(actStart.value);
                        var curActEnd = App.datetimeLocalToBackend(actEnd.value);
                        var origActStart = actBtn.getAttribute("data-start") || "";
                        var origActEnd = actBtn.getAttribute("data-end") || "";
                        if (curActStart !== origActStart || curActEnd !== origActEnd) {
                            return true;
                        }
                    }
                }
            }
        }
        // Phase 3B.2: session-level split input. If the user has entered a
        // split time, the edit panel is dirty so auto-refresh does not wipe
        // the unsaved split input.
        var splitEl = document.getElementById("edit-split-time");
        if (splitEl && !splitEl.disabled && splitEl.value) {
            return true;
        }
        // Phase 3B.2: per-activity inline split editor. If an editor is open
        // and has a non-empty split time, treat the panel as dirty so the
        // detail list is not re-rendered (which would lose the edit).
        if (App.editingSplitActivityId !== null) {
            var splitEditorRow = document.querySelector(
                '#timeline-details-list .detail-item[data-activity-id="'
                + App.editingSplitActivityId + '"]'
            );
            if (splitEditorRow) {
                var splitEditor = splitEditorRow.querySelector(".detail-split-editor");
                if (splitEditor && !splitEditor.hidden) {
                    var splitInput = splitEditor.querySelector(".detail-split-time");
                    if (splitInput && splitInput.value) {
                        return true;
                    }
                }
            }
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
        // Visual warning when over the limit.
        if (len > App.NOTE_MAX_LENGTH) {
            countEl.classList.add("edit-note-count-over");
        } else {
            countEl.classList.remove("edit-note-count-over");
        }
        // Disable the save button when the note is over the limit so the
        // user gets immediate feedback instead of an error on click. Only
        // toggle when not actively saving (setEditSaving controls the
        // button during save and re-enables it on completion).
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
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "保存中…" : "保存";
        }
        if (cancelBtn) cancelBtn.disabled = saving;
        if (select) select.disabled = saving;
        if (noteEl) noteEl.disabled = saving;
        // When stopping a save, re-apply the note-length limit so the
        // button stays disabled if the user typed past the limit during
        // the save (the textarea is disabled during save, but this is a
        // defensive guard).
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

        if (!projectChanged && !noteChanged) {
            showEditStatus("没有需要保存的更改", false);
            return;
        }

        var dateEl = document.getElementById("timeline-date-display");
        var reportDate = App.timelineDate || (dateEl ? dateEl.textContent : null);
        if (reportDate === "--") reportDate = null;
        if (noteChanged && !reportDate) {
            showEditStatus("无法保存备注：日期无效", true);
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
        if (noteChanged) {
            promises.push(App.callBridge("update_timeline_note", activityIds, note, reportDate).then(function (result) {
                if (!result || result.ok === false) {
                    throw new Error(result && result.error ? result.error : "保存备注失败");
                }
            }));
        }

        Promise.allSettled(promises).then(function (results) {
            var hasError = false;
            var errorMsg = "";
            for (var i = 0; i < results.length; i++) {
                if (results[i].status === "rejected") {
                    hasError = true;
                    // Phase 3C.1: never read .message from a rejected
                    // promise — it could be a raw pywebview exception.
                    // Use the stable "保存失败" fallback so internal
                    // details never leak into the UI.
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
            // Success: update the editingSession baseline to the saved
            // values so isEditDirty() returns false. This clears the dirty
            // state, lets the subsequent refresh repopulate the edit panel
            // with the new server-returned baseline, and ensures Cancel
            // after save does not revert to the pre-save values.
            if (App.editingSession) {
                if (projectChanged) {
                    App.editingSession.project_id = projectId;
                }
                if (noteChanged) {
                    App.editingSession.session_note = note;
                }
            }
            showEditStatus("保存成功", false);
            // Reset the saving state before refreshing so the button is
            // re-enabled regardless of whether the refresh succeeds. The
            // save itself succeeded; a refresh failure is a separate concern.
            setEditSaving(false);
            refreshTimelineAfterEdit();
        });
    }
    App.saveEdit = saveEdit;

    // --- Phase 3B.2: session-level activity split ---------------------

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
            // Single-activity but still open: splitting is not safe because
            // the displayed end_time may be a projected value.
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
        // Frontend range check: split must be strictly between start and end.
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
            // Split succeeded. Reset the saving state before refreshing so
            // the button is re-enabled regardless of whether the refresh
            // succeeds. The split changes the session structure, so the
            // selected session may regroup or disappear; the refresh path
            // handles that gracefully by clearing the selection.
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
        var dateEl = document.getElementById("timeline-date-display");
        var date = App.timelineDate || (dateEl ? dateEl.textContent : null);
        if (date === "--") date = null;
        var token = ++App.timelineRequestToken;
        App.callBridge("get_timeline", date).then(function (result) {
            if (token !== App.timelineRequestToken) return;
            var data = App.handleResult(result, function (msg) {
                App.showTimelineError(msg || "刷新失败");
            });
            if (!data) return;
            showTimeline(data);
            App.clearTimelineError();
        }).catch(function () {
            if (token !== App.timelineRequestToken) return;
            // Phase 3C.1: use the stable "刷新失败" fallback.
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
        // Revert to original values from the session object.
        populateEditPanel(App.editingSession);
    }
    App.cancelEdit = cancelEdit;

    // --- Phase 3B.1: session-level time correction ---------------------

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
            // Single-activity but still open: the displayed end_time may be a
            // projected value, so editing is not safe. Show the hint instead.
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "进行中记录无法修改时间。";
            showTimeStatus("", false);
            return;
        }
        // Single closed activity: show the inputs.
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

    // --- Timeline loading -----------------------------------------------

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
            App.timelineLoaded = true;
            showTimeline(data);
        }).catch(function () {
            if (token !== App.timelineRequestToken) return;  // stale response
            App.setTimelineLoading(false);
            // Phase 3C.1: never surface raw exception text; use the stable
            // fallback so internal details do not leak into the UI.
            App.showTimelineError("加载时间线失败");
        });
    }
    App.loadTimeline = loadTimeline;

    function refreshTimeline() {
        // Silent refresh: do not show loading spinner, just reload data.
        // On error, keep showing the previous data so the user is not left
        // looking at an empty list; only the error banner is shown.
        var dateEl = document.getElementById("timeline-date-display");
        var date = App.timelineDate || (dateEl ? dateEl.textContent : null);
        if (date === "--") date = null;
        var token = ++App.timelineRequestToken;
        App.callBridge("get_timeline", date).then(function (result) {
            if (token !== App.timelineRequestToken) return;  // stale response
            var data = App.handleResult(result, function (msg) {
                App.showTimelineError(msg || "刷新失败");
            });
            if (!data) return;
            showTimeline(data);
            App.clearTimelineError();
        }).catch(function () {
            if (token !== App.timelineRequestToken) return;  // stale response
            // Only show error banner; keep lastTimelineData on screen.
            // Phase 3C.1: use the stable "刷新失败" fallback.
            App.showTimelineError("刷新失败");
        });
    }
    App.refreshTimeline = refreshTimeline;

    // --- Timeline date navigation ---------------------------------------

    function goPrevDay() {
        var dateEl = document.getElementById("timeline-date-display");
        var current = App.timelineDate || (dateEl ? dateEl.textContent : null);
        App.timelineDate = App.shiftDate(current, -1);
        App.selectedSessionId = null;
        // Verification item 22: invalidate pending detail requests and clear
        // the detail cache on date switch so a stale response from the
        // previous date does not backfill the new date's detail panel.
        ++App.detailsRequestToken;
        App.lastSessionDetailsData = null;
        // Phase 3B.5B: close the correction shell on date switch so the
        // shell context does not carry over to a different day.
        App.resetCorrectionShellState();
        loadTimeline(App.timelineDate);
    }
    App.goPrevDay = goPrevDay;

    function goNextDay() {
        var dateEl = document.getElementById("timeline-date-display");
        var current = App.timelineDate || (dateEl ? dateEl.textContent : null);
        App.timelineDate = App.shiftDate(current, 1);
        App.selectedSessionId = null;
        // Verification item 22: invalidate pending detail requests and clear
        // the detail cache on date switch.
        ++App.detailsRequestToken;
        App.lastSessionDetailsData = null;
        // Phase 3B.5B: close the correction shell on date switch.
        App.resetCorrectionShellState();
        loadTimeline(App.timelineDate);
    }
    App.goNextDay = goNextDay;

    function goToday() {
        App.timelineDate = null;
        App.selectedSessionId = null;
        // Verification item 22: invalidate pending detail requests and clear
        // the detail cache on date switch.
        ++App.detailsRequestToken;
        App.lastSessionDetailsData = null;
        // Phase 3B.5B: close the correction shell on date switch.
        App.resetCorrectionShellState();
        loadTimeline(null);
    }
    App.goToday = goToday;

})();
