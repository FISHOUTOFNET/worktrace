// WorkTrace WebView frontend.
// Phase 3A: Overview and Timeline pages are production pages. The Timeline
// page supports minimal editing (project reclassification + session note).
// Only communicates with Python through pywebview API bridge.
// Does not persist sensitive data in browser storage APIs.
// Does not access any external network resources.
// Phase 2.1 hardening: request token guards against stale responses,
// selected session is preserved across auto-refresh, in-progress sessions
// are clearly marked, long text is truncated with safe tooltips, and
// bridge errors keep the prior data visible instead of clearing it.
// Phase 3A editing: project reclassification and session-note editing go
// through the bridge only; saving state, error state, and post-save
// refresh preserve the Phase 2.1 privacy boundaries.

(function () {
    "use strict";

    var REFRESH_INTERVAL_MS = 8000;
    var NOTE_MAX_LENGTH = 2000;
    var refreshTimer = null;

    // --- Timeline state -------------------------------------------------
    var currentPage = "overview";
    var timelineDate = null;       // null = today (backend decides)
    var timelineLoaded = false;    // whether timeline has been loaded at least once
    var timelineLoading = false;   // whether a timeline load is in progress
    var selectedSessionId = null;  // currently selected session for detail view

    // Request tokens prevent stale bridge responses from overwriting newer
    // data when the user rapidly switches dates. Each load increments the
    // token; only the response whose token equals the current value is
    // applied to the DOM.
    var timelineRequestToken = 0;
    var detailsRequestToken = 0;

    // --- Phase 3A: Timeline editing state -------------------------------
    // projectsCache holds the selectable projects list (id/name/description)
    // loaded once from the bridge. currentSessions holds the latest session
    // list so the edit panel can look up the selected session's fields.
    // editingSession holds the session object currently loaded into the edit
    // form. editSaving guards the save button against double-submits.
    var projectsCache = null;
    var projectsLoading = false;
    var currentSessions = [];
    var editingSession = null;
    var editSaving = false;

    // --- Phase 3B.1: Timeline time-correction state ---------------------
    // timeSaving guards the session-level "保存时间" button. activityTimeSaving
    // guards the per-activity inline editor. editingActivityId is the activity
    // id whose inline time editor is currently open (null = none). These are
    // intentionally separate from editSaving so the project/note and time
    // save flows do not pollute each other's state.
    var timeSaving = false;
    var editingActivityId = null;
    var activityTimeSaving = false;

    // --- Phase 3B.2: Timeline activity-split state -----------------------
    // sessionSplitSaving guards the session-level "拆分" button.
    // activitySplitSaving guards the per-activity inline split editor.
    // editingSplitActivityId is the activity id whose inline split editor is
    // currently open (null = none). These are intentionally separate from
    // editSaving/timeSaving/activityTimeSaving so the split save flow does
    // not pollute the other save flows' state.
    var sessionSplitSaving = false;
    var editingSplitActivityId = null;
    var activitySplitSaving = false;

    // --- Phase 3B.3: Timeline activity-merge state -----------------------
    // mergeSaving guards the per-activity "与下一条合并" button. It is
    // intentionally separate from editSaving/timeSaving/activityTimeSaving/
    // activitySplitSaving/sessionSplitSaving so the merge save flow does
    // not pollute the other save flows' state. mergingActivityId is the
    // activity id whose merge button is currently saving (null = none).
    var mergeSaving = false;
    var mergingActivityId = null;

    // --- Phase 3B.4: Timeline hide / soft delete state -------------------
    // hideSaving guards any hide operation (per-activity or session-level).
    // deleteSaving guards any soft-delete operation. They are intentionally
    // separate from each other and from all other saving states so the
    // hide and delete flows do not pollute each other or the project/note/
    // time/split/merge flows. hidingActivityId / deletingActivityId track
    // which activity's per-activity button is currently saving (null = none).
    var hideSaving = false;
    var hidingActivityId = null;
    var deleteSaving = false;
    var deletingActivityId = null;

    // --- Bridge helper --------------------------------------------------

    function callBridge(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        if (typeof window.pywebview === "undefined" || !window.pywebview.api) {
            return Promise.reject(new Error("bridge unavailable"));
        }
        return window.pywebview.api[method].apply(window.pywebview.api, args);
    }

    // --- Overview error banner ------------------------------------------

    function showError(message) {
        var banner = document.getElementById("overview-error");
        if (!banner) return;
        if (!message) {
            banner.hidden = true;
            banner.textContent = "加载失败，请稍后重试。";
            return;
        }
        banner.hidden = false;
        banner.textContent = message;
    }

    function clearError() {
        showError("");
    }

    // --- Timeline error / loading ---------------------------------------

    function showTimelineError(message) {
        var banner = document.getElementById("timeline-error");
        if (!banner) return;
        if (!message) {
            banner.hidden = true;
            banner.textContent = "加载失败，请稍后重试。";
            return;
        }
        banner.hidden = false;
        banner.textContent = message;
    }

    function clearTimelineError() {
        showTimelineError("");
    }

    function setTimelineLoading(loading) {
        timelineLoading = loading;
        var el = document.getElementById("timeline-loading");
        if (el) el.hidden = !loading;
    }

    // --- Generic result handler -----------------------------------------

    function handleResult(result, onError) {
        if (result && result.ok === false) {
            onError(result.error || "操作失败");
            return null;
        }
        return result;
    }

    // --- Overview rendering ---------------------------------------------

    function showStatus(statusResult) {
        if (!statusResult) return;
        var display = document.getElementById("status-display");
        var btn = document.getElementById("toggle-pause-btn");
        display.textContent = statusResult.display || "未知";
        display.className = "status-display";
        if (statusResult.status === "running" && !statusResult.paused) {
            display.classList.add("recording");
            btn.textContent = "暂停记录";
            btn.className = "toggle-btn pause-style";
        } else {
            display.classList.add("paused");
            btn.textContent = "开始记录";
            btn.className = "toggle-btn";
        }
    }

    function showOverview(overview) {
        if (!overview) return;
        document.getElementById("kpi-date").textContent = overview.date || "--";
        document.getElementById("kpi-total").textContent = overview.total_duration || "00:00:00";
        document.getElementById("kpi-classified").textContent = overview.classified_duration || "00:00:00";
        document.getElementById("kpi-uncategorized").textContent = overview.uncategorized_duration || "00:00:00";
        document.getElementById("kpi-projects").textContent = String(overview.project_count || 0);
        var current = overview.current_activity || {};
        var currentEl = document.getElementById("current-activity");
        if (current.active) {
            currentEl.textContent = "当前活动：" + current.display;
        } else {
            currentEl.textContent = "当前活动：无";
        }
    }

    function showRecent(recentResult) {
        var listEl = document.getElementById("recent-list");
        if (!recentResult || !recentResult.activities || recentResult.activities.length === 0) {
            listEl.innerHTML = '<div class="recent-empty">暂无活动</div>';
            return;
        }
        var html = "";
        for (var i = 0; i < recentResult.activities.length; i++) {
            var item = recentResult.activities[i];
            var inProgress = !item.end_time;
            var timeRange = formatTimeRange(item.start_time, item.end_time, inProgress);
            html += '<div class="recent-item">'
                + '<div>'
                + '<div class="recent-item-project">' + escapeHtml(item.project_name) + '</div>'
                + '<div class="recent-item-time">' + escapeHtml(timeRange) + '</div>'
                + '<div class="recent-item-status">' + escapeHtml(item.status || "") + '</div>'
                + '</div>'
                + '<div class="recent-item-duration">' + escapeHtml(item.duration) + '</div>'
                + '</div>';
        }
        listEl.innerHTML = html;
    }

    // --- Timeline rendering ---------------------------------------------

    // Last successfully rendered Timeline payload. When a refresh fails, the
    // page keeps showing this data instead of clearing, so the user is never
    // left looking at an empty list with only an error banner.
    var lastTimelineData = null;

    function formatTimeRange(start, end, inProgress) {
        var startTxt = (start || "").slice(11, 16);
        var endTxt = (end || "").slice(11, 16);
        if (inProgress || !endTxt) {
            return startTxt + "-进行中";
        }
        return startTxt + "-" + endTxt;
    }

    function showTimeline(data) {
        if (!data) return;
        lastTimelineData = data;
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
        currentSessions = sessions;
        if (sessions.length === 0) {
            listEl.innerHTML = '<div class="timeline-empty">当日暂无活动记录</div>';
            // Clear details when there are no sessions
            document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
            document.getElementById("timeline-details-list").innerHTML = "";
            selectedSessionId = null;
            clearEditPanel();
            return;
        }

        // Build the full HTML string before replacing to avoid flicker.
        var html = "";
        for (var i = 0; i < sessions.length; i++) {
            var s = sessions[i];
            var timeRange = formatTimeRange(s.start_time, s.end_time, s.is_in_progress);
            var projectLabel = s.project_name || "未归类";
            if (s.project_description) {
                projectLabel += " (" + s.project_description + ")";
            }
            var cls = "timeline-item";
            if (s.is_uncategorized) cls += " uncategorized";
            if (s.is_in_progress) cls += " in-progress";
            if (s.session_id === selectedSessionId) cls += " selected";
            html += '<div class="' + cls + '" data-session-id="' + escapeHtml(s.session_id) + '"'
                + ' title="' + escapeHtml(projectLabel) + '｜' + escapeHtml(timeRange) + '｜' + escapeHtml(s.duration) + '"'
                + '>'
                + '<div class="timeline-item-main">'
                + '<div class="timeline-item-project">' + escapeHtml(projectLabel) + '</div>'
                + '<div class="timeline-item-time">' + escapeHtml(timeRange) + '</div>'
                + '<div class="timeline-item-status">' + escapeHtml(s.status || "") + '</div>'
                + '</div>'
                + '<div class="timeline-item-side">'
                + '<div class="timeline-item-duration">' + escapeHtml(s.duration) + '</div>'
                + '<div class="timeline-item-count">' + escapeHtml(String(s.event_count || 0) + " 条") + '</div>'
                + '</div>'
                + '</div>';
        }
        listEl.innerHTML = html;

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
        if (selectedSessionId !== null) {
            var found = null;
            for (var k = 0; k < sessions.length; k++) {
                if (sessions[k].session_id === selectedSessionId) {
                    found = sessions[k];
                    break;
                }
            }
            if (found) {
                // Phase 3B.1: skip the detail reload when the user has
                // unsaved edits (project, note, session-level time, or
                // per-activity inline time editor). Auto-refresh must not
                // wipe in-progress edits. After a successful save the
                // baseline is updated so isEditDirty() returns false and
                // the reload proceeds normally.
                var skipDetailReload = editingSession
                    && editingSession.session_id === found.session_id
                    && isEditDirty();
                if (!skipDetailReload) {
                    loadSessionDetails(found.activity_ids, data.date);
                }
                // Only re-populate the edit panel if the user is not mid-edit.
                // Auto-refresh must not overwrite unsaved edits.
                if (!editingSession || editingSession.session_id !== found.session_id || !isEditDirty()) {
                    populateEditPanel(found);
                }
            } else {
                // Selected session disappeared (e.g. session ended and was
                // re-grouped). Clear selection gracefully without throwing.
                selectedSessionId = null;
                document.getElementById("timeline-details-header").textContent = "选择左侧时段查看详情";
                document.getElementById("timeline-details-list").innerHTML = "";
                clearEditPanel();
            }
        }
    }

    function selectTimelineSession(sessionId, sessions) {
        selectedSessionId = sessionId;
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
            // Populate the edit panel with the selected session's fields.
            // A manual click always repopulates, even if a prior auto-refresh
            // had skipped repopulation due to unsaved edits.
            populateEditPanel(found);
        }
    }

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

        var token = ++detailsRequestToken;
        callBridge("get_timeline_session_details", activityIds, date).then(function (result) {
            if (token !== detailsRequestToken) return;  // stale response
            var data = handleResult(result, function (msg) {
                detailsHeader.textContent = "加载详情失败";
                detailsList.innerHTML = '<div class="timeline-empty">' + escapeHtml(msg) + '</div>';
            });
            if (!data) return;
            renderSessionDetails(data);
        }).catch(function () {
            if (token !== detailsRequestToken) return;  // stale response
            detailsHeader.textContent = "加载详情失败";
            detailsList.innerHTML = '<div class="timeline-empty">无法加载详情，请稍后重试。</div>';
        });
    }

    function renderSessionDetails(data) {
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
        for (var i = 0; i < activities.length; i++) {
            var a = activities[i];
            var timeRange = formatTimeRange(a.start_time, a.end_time, a.is_in_progress);
            var displayName = a.resource_name || a.app_name || "未知";
            var cls = "detail-item";
            if (a.is_in_progress) cls += " in-progress";
            // Per-activity inline time editor (Phase 3B.1). The button is
            // disabled for in-progress activities because their displayed
            // end_time may be a projected value. The editor container is
            // hidden by default and only shown when the user clicks the
            // button. Only one inline editor can be open at a time.
            // Phase 3B.2 also adds an inline split editor with the same
            // in-progress/missing-id disable rules.
            var aid = a.activity_id || 0;
            var editBtnDisabled = a.is_in_progress || !aid;
            var editBtnTitle = a.is_in_progress
                ? "进行中记录暂不支持时间修正"
                : (aid ? "编辑该活动时间" : "活动 ID 缺失，无法编辑");
            var splitBtnTitle = a.is_in_progress
                ? "进行中记录暂不支持拆分"
                : (aid ? "在该时间点拆分此活动" : "活动 ID 缺失，无法拆分");
            // Phase 3B.3: per-activity "与下一条合并" button. The button is
            // disabled when there is no next activity, when either the
            // current or next activity is in-progress, or when the current
            // activity id is missing. The backend re-validates all merge
            // preconditions (project, resource, status, adjacency).
            var hasNext = i < activities.length - 1;
            var nextInProgress = hasNext && activities[i + 1].is_in_progress;
            var mergeBtnDisabled = !aid || a.is_in_progress || !hasNext || nextInProgress;
            var mergeBtnTitle = !aid
                ? "活动 ID 缺失，无法合并"
                : (a.is_in_progress
                    ? "进行中记录暂不支持合并"
                    : (!hasNext
                        ? "已是最后一条活动，没有下一条可合并"
                        : (nextInProgress
                            ? "下一条活动进行中，暂不支持合并"
                            : "将此活动与下一条活动合并")));
            // Phase 3B.4: per-activity "隐藏" and "删除" buttons. Both are
            // disabled for in-progress activities (raw end_time IS NULL) and
            // when the activity id is missing. The delete button uses a
            // confirmation dialog (window.confirm) before calling the bridge.
            var visibilityBtnDisabled = a.is_in_progress || !aid;
            var visibilityBtnTitle = a.is_in_progress
                ? "进行中记录暂不支持隐藏或删除"
                : (aid ? "从 Timeline 隐藏或删除此活动" : "活动 ID 缺失，无法操作");
            html += '<div class="' + cls + '" data-activity-id="' + escapeHtml(String(aid)) + '">'
                + '<div class="detail-item-time">' + escapeHtml(timeRange) + '</div>'
                + '<div class="detail-item-name" title="' + escapeHtml(displayName) + '">' + escapeHtml(displayName) + '</div>'
                + '<div class="detail-item-meta">'
                + '<span class="detail-item-type">' + escapeHtml(a.resource_type || "") + '</span>'
                + '<span class="detail-item-app">' + escapeHtml(a.app_name || "") + '</span>'
                + '</div>'
                + '<div class="detail-item-project" title="' + escapeHtml(a.project_name || "未归类") + '">' + escapeHtml(a.project_name || "未归类") + '</div>'
                + '<div class="detail-item-duration">' + escapeHtml(a.duration) + '</div>'
                + '<div class="detail-item-actions">'
                + '<button type="button" class="detail-edit-time-btn"'
                + ' data-activity-id="' + escapeHtml(String(aid)) + '"'
                + ' data-start="' + escapeHtml(a.start_time || "") + '"'
                + ' data-end="' + escapeHtml(a.end_time || "") + '"'
                + (editBtnDisabled ? ' disabled' : '')
                + ' title="' + escapeHtml(editBtnTitle) + '"'
                + '>编辑时间</button>'
                + '<button type="button" class="detail-split-btn"'
                + ' data-activity-id="' + escapeHtml(String(aid)) + '"'
                + ' data-start="' + escapeHtml(a.start_time || "") + '"'
                + ' data-end="' + escapeHtml(a.end_time || "") + '"'
                + (editBtnDisabled ? ' disabled' : '')
                + ' title="' + escapeHtml(splitBtnTitle) + '"'
                + '>拆分</button>'
                + '<button type="button" class="detail-merge-btn"'
                + ' data-activity-id="' + escapeHtml(String(aid)) + '"'
                + ' data-next-activity-id="' + escapeHtml(String(hasNext ? (activities[i + 1].activity_id || 0) : 0)) + '"'
                + (mergeBtnDisabled ? ' disabled' : '')
                + ' title="' + escapeHtml(mergeBtnTitle) + '"'
                + '>与下一条合并</button>'
                + '<button type="button" class="detail-hide-btn"'
                + ' data-activity-id="' + escapeHtml(String(aid)) + '"'
                + (visibilityBtnDisabled ? ' disabled' : '')
                + ' title="' + escapeHtml(visibilityBtnTitle) + '"'
                + '>隐藏</button>'
                + '<button type="button" class="detail-delete-btn"'
                + ' data-activity-id="' + escapeHtml(String(aid)) + '"'
                + (visibilityBtnDisabled ? ' disabled' : '')
                + ' title="' + escapeHtml(visibilityBtnTitle) + '"'
                + '>删除</button>'
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
        }
        detailsList.innerHTML = html;

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
                    if (btn.disabled || mergeSaving) return;
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
        if (mergingActivityId !== null && mergeSaving) {
            var mergeStillThere = false;
            for (var mCheck = 0; mCheck < mergeBtns.length; mCheck++) {
                if (parseInt(mergeBtns[mCheck].getAttribute("data-activity-id"), 10) === mergingActivityId) {
                    mergeStillThere = true;
                    setMergeSaving(mergeBtns[mCheck], true);
                    break;
                }
            }
            if (!mergeStillThere) {
                mergingActivityId = null;
                mergeSaving = false;
            }
        }

        // Phase 3B.4: bind per-activity "隐藏" and "删除" button handlers.
        var hideBtns = detailsList.querySelectorAll(".detail-hide-btn");
        for (var hIdx = 0; hIdx < hideBtns.length; hIdx++) {
            (function (btn) {
                btn.addEventListener("click", function () {
                    if (btn.disabled || hideSaving) return;
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
                    if (btn.disabled || deleteSaving) return;
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
        if (hidingActivityId !== null && hideSaving) {
            var hideStillThere = false;
            for (var hCheck = 0; hCheck < hideBtns.length; hCheck++) {
                if (parseInt(hideBtns[hCheck].getAttribute("data-activity-id"), 10) === hidingActivityId) {
                    hideStillThere = true;
                    setHideSaving(hideBtns[hCheck], true);
                    break;
                }
            }
            if (!hideStillThere) {
                hidingActivityId = null;
                hideSaving = false;
            }
        }
        if (deletingActivityId !== null && deleteSaving) {
            var deleteStillThere = false;
            for (var dCheck = 0; dCheck < deleteBtns.length; dCheck++) {
                if (parseInt(deleteBtns[dCheck].getAttribute("data-activity-id"), 10) === deletingActivityId) {
                    deleteStillThere = true;
                    setDeleteSaving(deleteBtns[dCheck], true);
                    break;
                }
            }
            if (!deleteStillThere) {
                deletingActivityId = null;
                deleteSaving = false;
            }
        }

        // If an inline editor was open for an activity that still exists,
        // re-open it with the refreshed values so the user's editing context
        // is preserved across auto-refresh. If the activity disappeared, the
        // editor state is cleared below.
        if (editingActivityId !== null) {
            var stillOpen = false;
            var refreshedBtn = null;
            for (var k = 0; k < editBtns.length; k++) {
                if (parseInt(editBtns[k].getAttribute("data-activity-id"), 10) === editingActivityId) {
                    stillOpen = true;
                    refreshedBtn = editBtns[k];
                    break;
                }
            }
            if (stillOpen && refreshedBtn && !refreshedBtn.disabled && !activityTimeSaving) {
                openActivityTimeEditor(
                    editingActivityId,
                    refreshedBtn.getAttribute("data-start") || "",
                    refreshedBtn.getAttribute("data-end") || "",
                    refreshedBtn
                );
            } else if (!stillOpen) {
                // Activity disappeared (e.g. session regroup). Reset state.
                editingActivityId = null;
                activityTimeSaving = false;
            }
        }

        // Phase 3B.2: re-open the inline split editor if it was open and the
        // activity still exists. If the activity disappeared, reset state.
        if (editingSplitActivityId !== null) {
            var splitStillOpen = false;
            var refreshedSplitBtn = null;
            for (var m = 0; m < splitBtns.length; m++) {
                if (parseInt(splitBtns[m].getAttribute("data-activity-id"), 10) === editingSplitActivityId) {
                    splitStillOpen = true;
                    refreshedSplitBtn = splitBtns[m];
                    break;
                }
            }
            if (splitStillOpen && refreshedSplitBtn && !refreshedSplitBtn.disabled && !activitySplitSaving) {
                openActivitySplitEditor(
                    editingSplitActivityId,
                    refreshedSplitBtn.getAttribute("data-start") || "",
                    refreshedSplitBtn.getAttribute("data-end") || "",
                    refreshedSplitBtn
                );
            } else if (!splitStillOpen) {
                editingSplitActivityId = null;
                activitySplitSaving = false;
            }
        }
    }

    // --- Phase 3B.1: per-activity inline time editor -------------------

    function openActivityTimeEditor(activityId, startVal, endVal, btn) {
        if (!btn) return;
        // Close any other open inline editor first so only one is visible
        // at a time. This keeps the editing context unambiguous.
        closeAllActivityTimeEditors(activityId);
        // Phase 3B.2: also close any open split editor so the time editor is
        // the only inline editor visible.
        closeAllActivitySplitEditors(activityId);
        editingActivityId = activityId;
        var row = btn.closest(".detail-item");
        if (!row) return;
        var editor = row.querySelector(".detail-time-editor");
        if (!editor) return;
        var startInput = editor.querySelector(".detail-time-start");
        var endInput = editor.querySelector(".detail-time-end");
        if (startInput) startInput.value = backendToDatetimeLocal(startVal);
        if (endInput) endInput.value = backendToDatetimeLocal(endVal);
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
        if (editingActivityId === rowAid) {
            editingActivityId = null;
        }
    }

    function closeAllActivityTimeEditors(exceptActivityId) {
        var rows = document.querySelectorAll("#timeline-details-list .detail-item");
        for (var i = 0; i < rows.length; i++) {
            var aid = parseInt(rows[i].getAttribute("data-activity-id"), 10);
            if (aid !== exceptActivityId) {
                closeActivityTimeEditor(rows[i]);
            }
        }
    }

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

    function setActivityTimeSaving(row, saving) {
        if (!row) return;
        activityTimeSaving = saving;
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

    function saveActivityTime(row) {
        if (!row || activityTimeSaving) return;
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
        var startVal = datetimeLocalToBackend(startInput.value);
        var endVal = datetimeLocalToBackend(endInput.value);
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
        callBridge("update_timeline_activity_time", aid, startVal, endVal).then(function (result) {
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
            if (startInput) startInput.value = backendToDatetimeLocal(startVal);
            if (endInput) endInput.value = backendToDatetimeLocal(endVal);
            refreshTimelineAfterEdit();
        }).catch(function () {
            setActivityTimeSaving(row, false);
            setActivityTimeStatus(row, "保存时间失败", true);
        });
    }

    // --- Phase 3B.2: per-activity inline split editor ------------------

    function openActivitySplitEditor(activityId, startVal, endVal, btn) {
        if (!btn) return;
        // Close any other open inline editor first so only one is visible
        // at a time. This keeps the editing context unambiguous.
        closeAllActivitySplitEditors(activityId);
        // Also close any open time editor so the split editor is the only
        // inline editor visible.
        closeAllActivityTimeEditors(activityId);
        editingSplitActivityId = activityId;
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
            var midVal = midpointTime(startVal, endVal);
            splitInput.value = backendToDatetimeLocal(midVal);
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
        if (editingSplitActivityId === rowAid) {
            editingSplitActivityId = null;
        }
    }

    function closeAllActivitySplitEditors(exceptActivityId) {
        var rows = document.querySelectorAll("#timeline-details-list .detail-item");
        for (var i = 0; i < rows.length; i++) {
            var aid = parseInt(rows[i].getAttribute("data-activity-id"), 10);
            if (aid !== exceptActivityId) {
                closeActivitySplitEditor(rows[i]);
            }
        }
    }

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

    function setActivitySplitSaving(row, saving) {
        if (!row) return;
        activitySplitSaving = saving;
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

    function saveActivitySplit(row) {
        if (!row || activitySplitSaving) return;
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
        var splitVal = datetimeLocalToBackend(splitInput.value);
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
        callBridge("split_timeline_activity", aid, splitVal).then(function (result) {
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

    function setMergeSaving(btn, saving) {
        mergeSaving = saving;
        mergingActivityId = saving ? parseInt(btn.getAttribute("data-activity-id"), 10) : null;
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

    function saveActivityMerge(btn, activityId, nextActivityId) {
        if (!btn || mergeSaving) return;
        if (!activityId || !nextActivityId) {
            setMergeStatus(btn, "活动 ID 无效", true);
            return;
        }
        setMergeSaving(btn, true);
        setMergeStatus(btn, "", false);
        callBridge("merge_timeline_activities", [activityId, nextActivityId]).then(function (result) {
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

    function setHideSaving(btn, saving) {
        hideSaving = saving;
        hidingActivityId = saving ? parseInt(btn.getAttribute("data-activity-id"), 10) : null;
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

    function setDeleteSaving(btn, saving) {
        deleteSaving = saving;
        deletingActivityId = saving ? parseInt(btn.getAttribute("data-activity-id"), 10) : null;
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

    function saveActivityHide(btn, activityId) {
        if (!btn || hideSaving) return;
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
        callBridge("hide_timeline_activity", activityId).then(function (result) {
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

    function saveActivityDelete(btn, activityId) {
        if (!btn || deleteSaving) return;
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
        var confirmed = window.confirm("确定从 Timeline 删除这条记录吗？本阶段不会物理删除数据。");
        if (!confirmed) return;

        setDeleteSaving(btn, true);
        setVisibilityStatus(btn, "", false);
        callBridge("soft_delete_timeline_activity", activityId).then(function (result) {
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
            multiEl.textContent = "多活动 session 暂不支持整体隐藏/删除，请在活动详情中逐条处理。";
            showVisibilityStatus("", false);
            return;
        }
        if (inProgress) {
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "进行中记录暂不支持隐藏或删除。";
            showVisibilityStatus("", false);
            return;
        }
        singleEl.hidden = false;
        multiEl.hidden = true;
        if (hideBtn) hideBtn.disabled = false;
        if (deleteBtn) deleteBtn.disabled = false;
        showVisibilityStatus("", false);
    }

    function resetSessionVisibilitySection() {
        hideSaving = false;
        hidingActivityId = null;
        deleteSaving = false;
        deletingActivityId = null;
        var singleEl = document.getElementById("edit-visibility-single");
        var multiEl = document.getElementById("edit-visibility-multi");
        var hideBtn = document.getElementById("edit-visibility-hide-btn");
        var deleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (singleEl) singleEl.hidden = true;
        if (multiEl) {
            multiEl.hidden = true;
            multiEl.textContent = "多活动 session 暂不支持整体隐藏/删除，请在活动详情中逐条处理。";
        }
        if (hideBtn) { hideBtn.disabled = true; hideBtn.textContent = "隐藏此 session"; }
        if (deleteBtn) { deleteBtn.disabled = true; deleteBtn.textContent = "删除此 session"; }
        showVisibilityStatus("", false);
    }

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

    function setSessionHideSaving(saving) {
        hideSaving = saving;
        var hideBtn = document.getElementById("edit-visibility-hide-btn");
        var deleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (hideBtn) {
            hideBtn.disabled = saving;
            hideBtn.textContent = saving ? "隐藏中…" : "隐藏此 session";
        }
        if (deleteBtn) deleteBtn.disabled = saving || deleteBtn.disabled;
    }

    function setSessionDeleteSaving(saving) {
        deleteSaving = saving;
        var hideBtn = document.getElementById("edit-visibility-hide-btn");
        var deleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (deleteBtn) {
            deleteBtn.disabled = saving;
            deleteBtn.textContent = saving ? "删除中…" : "删除此 session";
        }
        if (hideBtn) hideBtn.disabled = saving || hideBtn.disabled;
    }

    function saveSessionHide() {
        if (!editingSession || hideSaving) return;
        var activityIds = editingSession.activity_ids || [];
        if (activityIds.length !== 1) {
            showVisibilityStatus("多活动 session 暂不支持整体隐藏，请在活动详情中逐条处理", true);
            return;
        }
        if (editingSession.is_in_progress) {
            showVisibilityStatus("进行中记录暂不支持隐藏或删除", true);
            return;
        }
        if (isEditDirty()) {
            showVisibilityStatus("请先保存或取消当前编辑", true);
            return;
        }
        setSessionHideSaving(true);
        showVisibilityStatus("", false);
        callBridge("hide_timeline_session", activityIds).then(function (result) {
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

    function saveSessionDelete() {
        if (!editingSession || deleteSaving) return;
        var activityIds = editingSession.activity_ids || [];
        if (activityIds.length !== 1) {
            showVisibilityStatus("多活动 session 暂不支持整体删除，请在活动详情中逐条处理", true);
            return;
        }
        if (editingSession.is_in_progress) {
            showVisibilityStatus("进行中记录暂不支持隐藏或删除", true);
            return;
        }
        if (isEditDirty()) {
            showVisibilityStatus("请先保存或取消当前编辑", true);
            return;
        }
        var confirmed = window.confirm("确定从 Timeline 删除这条记录吗？本阶段不会物理删除数据。");
        if (!confirmed) return;

        setSessionDeleteSaving(true);
        showVisibilityStatus("", false);
        callBridge("soft_delete_timeline_session", activityIds).then(function (result) {
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

    // --- Phase 3A: Timeline editing (project reclassification + note) ----

    function loadProjects() {
        // Load the selectable projects list once and cache it. Subsequent
        // calls reuse the cache so we do not hit the bridge every time the
        // user selects a session.
        if (projectsCache || projectsLoading) {
            return Promise.resolve(projectsCache);
        }
        projectsLoading = true;
        return callBridge("list_projects_for_timeline").then(function (result) {
            projectsLoading = false;
            if (result && result.ok !== false && result.projects) {
                projectsCache = result.projects;
            }
            return projectsCache;
        }).catch(function () {
            projectsLoading = false;
            return null;
        });
    }

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

    function populateEditPanel(session) {
        if (!session) {
            clearEditPanel();
            return;
        }
        // Phase 3B.1: when switching to a different session, reset the
        // per-activity inline editor state so a stale editingActivityId
        // from the previous session does not leak into the new one. The
        // detail list DOM will be rebuilt by renderSessionDetails.
        if (editingSession && editingSession.session_id !== session.session_id) {
            editingActivityId = null;
            activityTimeSaving = false;
            // Phase 3B.2: reset per-activity inline split editor state too.
            editingSplitActivityId = null;
            activitySplitSaving = false;
        }
        editingSession = session;
        var panel = document.getElementById("timeline-edit-panel");
        if (panel) panel.hidden = false;

        // Project select: load projects lazily on first use, then reuse cache.
        var select = document.getElementById("edit-project-select");
        if (select && !projectsCache) {
            select.innerHTML = '<option value="">加载中…</option>';
            select.disabled = true;
            loadProjects().then(function (projects) {
                // Only render if we are still editing the same session.
                if (editingSession && editingSession.session_id === session.session_id) {
                    renderProjectSelect(projects, session.project_id);
                }
            });
        } else if (select && projectsCache) {
            renderProjectSelect(projectsCache, session.project_id);
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

    function clearEditPanel() {
        editingSession = null;
        editSaving = false;
        timeSaving = false;
        // Phase 3B.1: reset per-activity inline editor state. The detail
        // list DOM is typically rebuilt by renderSessionDetails, but the
        // tracking variables must be cleared so a stale editingActivityId
        // does not leak into the next session.
        editingActivityId = null;
        activityTimeSaving = false;
        // Phase 3B.2: reset per-activity inline split editor state too.
        editingSplitActivityId = null;
        activitySplitSaving = false;
        sessionSplitSaving = false;
        // Phase 3B.3: reset per-activity merge state too.
        mergeSaving = false;
        mergingActivityId = null;
        // Phase 3B.4: reset per-activity hide / delete state too.
        hideSaving = false;
        hidingActivityId = null;
        deleteSaving = false;
        deletingActivityId = null;
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

    function isEditDirty() {
        if (!editingSession) return false;
        var noteEl = document.getElementById("edit-note-text");
        var select = document.getElementById("edit-project-select");
        if (noteEl) {
            var currentNote = noteEl.value || "";
            var originalNote = editingSession.session_note || "";
            if (currentNote !== originalNote) return true;
        }
        if (select && select.value) {
            var currentProjectId = select.value;
            var originalProjectId = String(editingSession.project_id || 0);
            if (currentProjectId !== originalProjectId) return true;
        }
        // Phase 3B.1: session-level time inputs. If the user has modified
        // either the start or end time, the edit panel is dirty so
        // auto-refresh does not revert the inputs to the server values.
        var startEl = document.getElementById("edit-start-time");
        var endEl = document.getElementById("edit-end-time");
        if (startEl && !startEl.disabled) {
            var currentStart = datetimeLocalToBackend(startEl.value);
            var originalStart = editingSession.start_time || "";
            if (currentStart !== originalStart) return true;
        }
        if (endEl && !endEl.disabled) {
            var currentEnd = datetimeLocalToBackend(endEl.value);
            var originalEnd = editingSession.end_time || "";
            if (currentEnd !== originalEnd) return true;
        }
        // Phase 3B.1: per-activity inline editor. If an editor is open and
        // the user has modified the inputs, treat the panel as dirty so the
        // detail list is not re-rendered (which would lose the edits).
        if (editingActivityId !== null) {
            var editorRow = document.querySelector(
                '#timeline-details-list .detail-item[data-activity-id="'
                + editingActivityId + '"]'
            );
            if (editorRow) {
                var editor = editorRow.querySelector(".detail-time-editor");
                if (editor && !editor.hidden) {
                    var actStart = editor.querySelector(".detail-time-start");
                    var actEnd = editor.querySelector(".detail-time-end");
                    var actBtn = editorRow.querySelector(".detail-edit-time-btn");
                    if (actStart && actEnd && actBtn) {
                        var curActStart = datetimeLocalToBackend(actStart.value);
                        var curActEnd = datetimeLocalToBackend(actEnd.value);
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
        if (editingSplitActivityId !== null) {
            var splitEditorRow = document.querySelector(
                '#timeline-details-list .detail-item[data-activity-id="'
                + editingSplitActivityId + '"]'
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

    function updateNoteCount() {
        var noteEl = document.getElementById("edit-note-text");
        var countEl = document.getElementById("edit-note-count");
        if (!noteEl || !countEl) return;
        var len = (noteEl.value || "").length;
        countEl.textContent = len + " / " + NOTE_MAX_LENGTH;
        // Visual warning when over the limit.
        if (len > NOTE_MAX_LENGTH) {
            countEl.classList.add("edit-note-count-over");
        } else {
            countEl.classList.remove("edit-note-count-over");
        }
        // Disable the save button when the note is over the limit so the
        // user gets immediate feedback instead of an error on click. Only
        // toggle when not actively saving (setEditSaving controls the
        // button during save and re-enables it on completion).
        var saveBtn = document.getElementById("edit-save-btn");
        if (saveBtn && !editSaving && editingSession) {
            saveBtn.disabled = len > NOTE_MAX_LENGTH;
        }
    }

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

    function setEditSaving(saving) {
        editSaving = saving;
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
        if (!saving && editingSession) {
            updateNoteCount();
        }
    }

    function saveEdit() {
        if (!editingSession || editSaving) return;
        var activityIds = editingSession.activity_ids;
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
        if (note.length > NOTE_MAX_LENGTH) {
            showEditStatus("备注过长", true);
            return;
        }

        // Determine what changed so we only call the bridges that are needed.
        var originalProjectId = String(editingSession.project_id || 0);
        var originalNote = editingSession.session_note || "";
        var projectChanged = projectIdStr !== originalProjectId;
        var noteChanged = note !== originalNote;

        if (!projectChanged && !noteChanged) {
            showEditStatus("没有需要保存的更改", false);
            return;
        }

        var dateEl = document.getElementById("timeline-date-display");
        var reportDate = timelineDate || (dateEl ? dateEl.textContent : null);
        if (reportDate === "--") reportDate = null;
        if (noteChanged && !reportDate) {
            showEditStatus("无法保存备注：日期无效", true);
            return;
        }

        setEditSaving(true);
        showEditStatus("", false);

        var promises = [];
        if (projectChanged) {
            promises.push(callBridge("update_timeline_project", activityIds, projectId).then(function (result) {
                if (!result || result.ok === false) {
                    throw new Error(result && result.error ? result.error : "保存项目失败");
                }
            }));
        }
        if (noteChanged) {
            promises.push(callBridge("update_timeline_note", activityIds, note, reportDate).then(function (result) {
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
                    errorMsg = results[i].reason && results[i].reason.message
                        ? results[i].reason.message
                        : "保存失败";
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
            if (editingSession) {
                if (projectChanged) {
                    editingSession.project_id = projectId;
                }
                if (noteChanged) {
                    editingSession.session_note = note;
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
            multiEl.textContent = "多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动。";
            showSplitStatus("", false);
            return;
        }
        if (inProgress) {
            // Single-activity but still open: splitting is not safe because
            // the displayed end_time may be a projected value.
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "进行中记录暂不支持拆分。";
            showSplitStatus("", false);
            return;
        }
        // Single closed activity: show the split input. Default the split
        // point to the midpoint between start and end.
        singleEl.hidden = false;
        multiEl.hidden = true;
        if (splitEl) {
            var midVal = midpointTime(session.start_time, session.end_time);
            splitEl.value = backendToDatetimeLocal(midVal);
            splitEl.disabled = false;
        }
        if (saveBtn) saveBtn.disabled = false;
        showSplitStatus("", false);
    }

    function resetSessionSplitSection() {
        sessionSplitSaving = false;
        var singleEl = document.getElementById("edit-split-single");
        var multiEl = document.getElementById("edit-split-multi");
        var splitEl = document.getElementById("edit-split-time");
        var saveBtn = document.getElementById("edit-split-save-btn");
        if (singleEl) singleEl.hidden = true;
        if (multiEl) {
            multiEl.hidden = true;
            multiEl.textContent = "多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动。";
        }
        if (splitEl) { splitEl.value = ""; splitEl.disabled = true; }
        if (saveBtn) saveBtn.disabled = true;
        showSplitStatus("", false);
    }

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

    function setSessionSplitSaving(saving) {
        sessionSplitSaving = saving;
        var saveBtn = document.getElementById("edit-split-save-btn");
        var splitEl = document.getElementById("edit-split-time");
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "拆分中…" : "拆分";
        }
        if (splitEl) splitEl.disabled = saving;
    }

    function saveSessionSplit() {
        if (!editingSession || sessionSplitSaving) return;
        var activityIds = editingSession.activity_ids || [];
        if (activityIds.length !== 1) {
            showSplitStatus("多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动", true);
            return;
        }
        if (editingSession.is_in_progress) {
            showSplitStatus("进行中记录暂不支持拆分", true);
            return;
        }
        var splitEl = document.getElementById("edit-split-time");
        if (!splitEl) return;
        var splitVal = datetimeLocalToBackend(splitEl.value);
        if (!splitVal) {
            showSplitStatus("拆分时间无效", true);
            return;
        }
        // Frontend range check: split must be strictly between start and end.
        var startVal = editingSession.start_time || "";
        var endVal = editingSession.end_time || "";
        if (!startVal || !endVal || splitVal <= startVal || splitVal >= endVal) {
            showSplitStatus("拆分时间必须在活动时间范围内", true);
            return;
        }

        setSessionSplitSaving(true);
        showSplitStatus("", false);
        callBridge("split_timeline_session", activityIds, splitVal).then(function (result) {
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

    function refreshTimelineAfterEdit() {
        var dateEl = document.getElementById("timeline-date-display");
        var date = timelineDate || (dateEl ? dateEl.textContent : null);
        if (date === "--") date = null;
        var token = ++timelineRequestToken;
        callBridge("get_timeline", date).then(function (result) {
            if (token !== timelineRequestToken) return;
            var data = handleResult(result, function (msg) {
                showTimelineError(msg || "刷新时间详情失败，请稍后重试。");
            });
            if (!data) return;
            showTimeline(data);
            clearTimelineError();
        }).catch(function () {
            if (token !== timelineRequestToken) return;
            showTimelineError("刷新时间详情失败，请稍后重试。");
        });
    }

    function cancelEdit() {
        if (editSaving) return;
        if (!editingSession) {
            clearEditPanel();
            return;
        }
        // Revert to original values from the session object.
        populateEditPanel(editingSession);
    }

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
            multiEl.textContent = "多活动 session 暂不支持整体时间修改，请在活动详情中修改单条活动时间。";
            showTimeStatus("", false);
            return;
        }
        if (inProgress) {
            // Single-activity but still open: the displayed end_time may be a
            // projected value, so editing is not safe. Show the hint instead.
            singleEl.hidden = true;
            multiEl.hidden = false;
            multiEl.textContent = "进行中记录暂不支持时间修正。";
            showTimeStatus("", false);
            return;
        }
        // Single closed activity: show the inputs.
        singleEl.hidden = false;
        multiEl.hidden = true;
        if (startEl) startEl.value = backendToDatetimeLocal(session.start_time);
        if (endEl) endEl.value = backendToDatetimeLocal(session.end_time);
        if (startEl) startEl.disabled = false;
        if (endEl) endEl.disabled = false;
        if (saveBtn) saveBtn.disabled = false;
        showTimeStatus("", false);
    }

    function resetSessionTimeSection() {
        timeSaving = false;
        var singleEl = document.getElementById("edit-time-single");
        var multiEl = document.getElementById("edit-time-multi");
        var startEl = document.getElementById("edit-start-time");
        var endEl = document.getElementById("edit-end-time");
        var saveBtn = document.getElementById("edit-time-save-btn");
        if (singleEl) singleEl.hidden = true;
        if (multiEl) {
            multiEl.hidden = true;
            multiEl.textContent = "多活动 session 暂不支持整体时间修改，请在活动详情中修改单条活动时间。";
        }
        if (startEl) { startEl.value = ""; startEl.disabled = true; }
        if (endEl) { endEl.value = ""; endEl.disabled = true; }
        if (saveBtn) saveBtn.disabled = true;
        showTimeStatus("", false);
    }

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

    function setTimeSaving(saving) {
        timeSaving = saving;
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

    function saveSessionTime() {
        if (!editingSession || timeSaving) return;
        var activityIds = editingSession.activity_ids || [];
        if (activityIds.length !== 1) {
            showTimeStatus("多活动 session 暂不支持整体时间修改", true);
            return;
        }
        if (editingSession.is_in_progress) {
            showTimeStatus("进行中记录暂不支持时间修正", true);
            return;
        }
        var startEl = document.getElementById("edit-start-time");
        var endEl = document.getElementById("edit-end-time");
        if (!startEl || !endEl) return;
        var startVal = datetimeLocalToBackend(startEl.value);
        var endVal = datetimeLocalToBackend(endEl.value);
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
        callBridge("update_timeline_session_time", activityIds, startVal, endVal).then(function (result) {
            if (!result || result.ok === false) {
                setTimeSaving(false);
                showTimeStatus(result && result.error ? result.error : "保存时间失败", true);
                return;
            }
            // Update the baseline so a subsequent auto-refresh does not
            // revert the inputs to the pre-save values, and dirty checks
            // reflect the saved state.
            if (editingSession) {
                editingSession.start_time = startVal;
                editingSession.end_time = endVal;
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

    // --- Timeline loading -----------------------------------------------

    function loadTimeline(date) {
        setTimelineLoading(true);
        clearTimelineError();
        var token = ++timelineRequestToken;
        callBridge("get_timeline", date).then(function (result) {
            if (token !== timelineRequestToken) return;  // stale response
            var data = handleResult(result, function (msg) {
                showTimelineError(msg || "加载时间详情失败，请稍后重试。");
            });
            setTimelineLoading(false);
            if (!data) return;
            timelineLoaded = true;
            showTimeline(data);
        }).catch(function (err) {
            if (token !== timelineRequestToken) return;  // stale response
            setTimelineLoading(false);
            showTimelineError(err && err.message ? err.message : "加载时间详情失败，请稍后重试。");
        });
    }

    function refreshTimeline() {
        // Silent refresh: do not show loading spinner, just reload data.
        // On error, keep showing the previous data so the user is not left
        // looking at an empty list; only the error banner is shown.
        var dateEl = document.getElementById("timeline-date-display");
        var date = timelineDate || (dateEl ? dateEl.textContent : null);
        if (date === "--") date = null;
        var token = ++timelineRequestToken;
        callBridge("get_timeline", date).then(function (result) {
            if (token !== timelineRequestToken) return;  // stale response
            var data = handleResult(result, function (msg) {
                showTimelineError(msg || "刷新时间详情失败，请稍后重试。");
            });
            if (!data) return;
            showTimeline(data);
            clearTimelineError();
        }).catch(function () {
            if (token !== timelineRequestToken) return;  // stale response
            // Only show error banner; keep lastTimelineData on screen.
            showTimelineError("刷新时间详情失败，请稍后重试。");
        });
    }

    // --- Timeline date navigation ---------------------------------------

    function shiftDate(dateStr, days) {
        // dateStr is "YYYY-MM-DD" or null (meaning today)
        var base;
        if (!dateStr || dateStr === "--") {
            base = new Date();
        } else {
            var parts = dateStr.split("-");
            base = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        }
        base.setDate(base.getDate() + days);
        var y = base.getFullYear();
        var m = String(base.getMonth() + 1).padStart(2, "0");
        var d = String(base.getDate()).padStart(2, "0");
        return y + "-" + m + "-" + d;
    }

    function goPrevDay() {
        var dateEl = document.getElementById("timeline-date-display");
        var current = timelineDate || (dateEl ? dateEl.textContent : null);
        timelineDate = shiftDate(current, -1);
        selectedSessionId = null;
        loadTimeline(timelineDate);
    }

    function goNextDay() {
        var dateEl = document.getElementById("timeline-date-display");
        var current = timelineDate || (dateEl ? dateEl.textContent : null);
        timelineDate = shiftDate(current, 1);
        selectedSessionId = null;
        loadTimeline(timelineDate);
    }

    function goToday() {
        timelineDate = null;
        selectedSessionId = null;
        loadTimeline(null);
    }

    // --- Utility --------------------------------------------------------

    function escapeHtml(text) {
        if (text === null || text === undefined) return "";
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    // Backend stores time as "YYYY-MM-DD HH:MM:SS". <input type="datetime-local">
    // uses "YYYY-MM-DDTHH:MM:SS" (T separator). These helpers convert between
    // the two fixed formats without relying on Date parsing (which would
    // interpret the value as local time and could shift it).
    function backendToDatetimeLocal(value) {
        if (!value || typeof value !== "string") return "";
        return value.replace(" ", "T");
    }

    function datetimeLocalToBackend(value) {
        if (!value || typeof value !== "string") return "";
        return value.replace("T", " ");
    }

    // Compute the midpoint between two ``YYYY-MM-DD HH:MM:SS`` timestamps
    // and return it in the same fixed format. This is used to default the
    // split-time input to a reasonable starting value. The computation uses
    // explicit Date.UTC construction to avoid local-timezone interpretation
    // of the parsed components, then formats the resulting UTC seconds back
    // into the fixed ``YYYY-MM-DD HH:MM:SS`` shape. This does NOT rely on
    // Date's automatic string parsing (which would interpret the value as
    // local time and could shift it).
    function midpointTime(startVal, endVal) {
        if (!startVal || !endVal) return "";
        var s = parseBackendTimeParts(startVal);
        var e = parseBackendTimeParts(endVal);
        if (!s || !e) return "";
        var midMs = (s.ts + e.ts) / 2;
        var d = new Date(midMs);
        return formatUtcParts(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate(),
            d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds());
    }

    // Parse a ``YYYY-MM-DD HH:MM:SS`` string into a UTC timestamp. Returns
    // ``null`` on failure. Uses Date.UTC so the components are interpreted
    // as-is without a local-timezone shift.
    function parseBackendTimeParts(value) {
        var m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/.exec(value || "");
        if (!m) return null;
        var ts = Date.UTC(
            parseInt(m[1], 10),
            parseInt(m[2], 10) - 1,
            parseInt(m[3], 10),
            parseInt(m[4], 10),
            parseInt(m[5], 10),
            parseInt(m[6], 10)
        );
        return { ts: ts };
    }

    // Format numeric UTC components into ``YYYY-MM-DD HH:MM:SS`` with
    // zero-padding. No Date object is involved so there is no timezone risk.
    function formatUtcParts(y, mo, d, h, mi, s) {
        function pad(n) { return n < 10 ? "0" + n : String(n); }
        return y + "-" + pad(mo) + "-" + pad(d) + " " + pad(h) + ":" + pad(mi) + ":" + pad(s);
    }

    // --- Refresh orchestration ------------------------------------------

    function refreshAll() {
        var statusPromise = callBridge("get_status").then(function (result) {
            var status = handleResult(result, function (msg) {
                throw new Error(msg);
            });
            showStatus(status);
        }).catch(function (err) {
            showError(err && err.message ? err.message : "无法连接采集器状态，请稍后重试。");
            throw err;
        });

        var overviewPromise = callBridge("get_overview").then(function (result) {
            var overview = handleResult(result, function (msg) {
                throw new Error(msg);
            });
            showOverview(overview);
        }).catch(function (err) {
            showError(err && err.message ? err.message : "加载今日概览失败，请稍后重试。");
            throw err;
        });

        var recentPromise = callBridge("get_recent_activities").then(function (result) {
            var recent = handleResult(result, function (msg) {
                throw new Error(msg);
            });
            showRecent(recent);
        }).catch(function (err) {
            showError(err && err.message ? err.message : "加载最近活动失败，请稍后重试。");
            throw err;
        });

        var promises = [statusPromise, overviewPromise, recentPromise];

        // If the Timeline page is currently active, also refresh it.
        if (currentPage === "timeline" && timelineLoaded) {
            var timelinePromise = new Promise(function (resolve, reject) {
                var dateEl = document.getElementById("timeline-date-display");
                var date = timelineDate || (dateEl ? dateEl.textContent : null);
                if (date === "--") date = null;
                var token = ++timelineRequestToken;
                callBridge("get_timeline", date).then(function (result) {
                    if (token !== timelineRequestToken) { resolve(); return; }  // stale
                    var data = handleResult(result, function (msg) {
                        showTimelineError(msg || "刷新时间详情失败，请稍后重试。");
                        throw new Error(msg);
                    });
                    if (data) {
                        showTimeline(data);
                        clearTimelineError();
                    }
                    resolve();
                }).catch(function (err) {
                    if (token !== timelineRequestToken) { resolve(); return; }  // stale
                    // Keep lastTimelineData on screen; just surface the error.
                    showTimelineError("刷新时间详情失败，请稍后重试。");
                    reject(err);
                });
            });
            promises.push(timelinePromise);
        }

        Promise.allSettled(promises).then(function (results) {
            var anyError = false;
            for (var i = 0; i < results.length; i++) {
                if (results[i].status === "rejected") {
                    anyError = true;
                    break;
                }
            }
            if (!anyError) {
                clearError();
            }
        });
    }

    function togglePause() {
        callBridge("toggle_pause").then(function (result) {
            var status = handleResult(result, function (msg) {
                showError(msg);
            });
            showStatus(status);
        }).catch(function () {
            showError("切换暂停状态失败，请稍后重试。");
        });
    }

    // --- Navigation -----------------------------------------------------

    function switchPage(pageId) {
        var navItems = document.querySelectorAll(".nav-item");
        var pages = document.querySelectorAll(".page");
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].classList.remove("active");
        }
        for (var j = 0; j < pages.length; j++) {
            pages[j].classList.remove("active");
        }
        var navTarget = document.querySelector('.nav-item[data-page="' + pageId + '"]');
        var pageTarget = document.getElementById("page-" + pageId);
        if (navTarget) navTarget.classList.add("active");
        if (pageTarget) pageTarget.classList.add("active");

        currentPage = pageId;

        // Lazy-load Timeline data when navigating to it for the first time.
        if (pageId === "timeline" && !timelineLoaded && !timelineLoading) {
            loadTimeline(timelineDate);
        }
    }

    function initNav() {
        var navItems = document.querySelectorAll(".nav-item");
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].addEventListener("click", function () {
                switchPage(this.getAttribute("data-page"));
            });
        }
    }

    function initButtons() {
        document.getElementById("toggle-pause-btn").addEventListener("click", togglePause);
        document.getElementById("refresh-btn").addEventListener("click", refreshAll);
        // Timeline date navigation
        document.getElementById("timeline-prev-btn").addEventListener("click", goPrevDay);
        document.getElementById("timeline-next-btn").addEventListener("click", goNextDay);
        document.getElementById("timeline-today-btn").addEventListener("click", goToday);
        // Phase 3A: Timeline editing handlers
        document.getElementById("edit-save-btn").addEventListener("click", saveEdit);
        document.getElementById("edit-cancel-btn").addEventListener("click", cancelEdit);
        var noteEl = document.getElementById("edit-note-text");
        if (noteEl) {
            noteEl.addEventListener("input", updateNoteCount);
        }
        // Phase 3B.1: session-level time correction handler. Per-activity
        // inline editor buttons are bound inside renderSessionDetails because
        // they are recreated on each render.
        var sessionTimeSaveBtn = document.getElementById("edit-time-save-btn");
        if (sessionTimeSaveBtn) {
            sessionTimeSaveBtn.addEventListener("click", saveSessionTime);
        }
        // Phase 3B.2: session-level split handler. Per-activity inline split
        // buttons are bound inside renderSessionDetails.
        var sessionSplitSaveBtn = document.getElementById("edit-split-save-btn");
        if (sessionSplitSaveBtn) {
            sessionSplitSaveBtn.addEventListener("click", saveSessionSplit);
        }
        // Phase 3B.4: session-level hide / soft-delete handlers. Per-activity
        // hide/delete buttons are bound inside renderSessionDetails.
        var sessionHideBtn = document.getElementById("edit-visibility-hide-btn");
        if (sessionHideBtn) {
            sessionHideBtn.addEventListener("click", saveSessionHide);
        }
        var sessionDeleteBtn = document.getElementById("edit-visibility-delete-btn");
        if (sessionDeleteBtn) {
            sessionDeleteBtn.addEventListener("click", saveSessionDelete);
        }
    }

    function startAutoRefresh() {
        if (refreshTimer !== null) clearInterval(refreshTimer);
        refreshTimer = setInterval(refreshAll, REFRESH_INTERVAL_MS);
    }

    function init() {
        initNav();
        initButtons();
        refreshAll();
        startAutoRefresh();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
