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

    // --- Phase 3B.5B: Timeline correction shell state -------------------
    // The correction shell is a read-only context + navigation layout that
    // lives inside #timeline-details. It does not introduce new write
    // capability; it only summarizes the selected session/activities using
    // display-safe fields and guides the user back to the existing
    // per-activity / session-level action buttons. These variables are
    // intentionally separate from the edit/time/split/merge/hide/delete
    // saving states so shell state never pollutes them.
    var correctionShellOpen = false;
    var correctionShellSessionId = null;
    var correctionShellActivityId = null;
    var correctionShellMode = null;  // "session" | "activity" | null
    // Phase 3B.5B.1: a single tracked highlight timer so repeated
    // click-to-locate clicks never accumulate timers or throw. It is
    // cleared before each new schedule and on shell reset.
    var correctionShellHighlightTimer = null;
    // Phase 3B.6: batch project reassignment selection state. This is the
    // first batch write capability: only project reassignment on multiple
    // closed, non-hidden, non-deleted activities in the current shell
    // session. Selected ids are kept in a Set so dedup is automatic; the
    // ids must always be a subset of the currently rendered shell activity
    // ids (stale ids are removed on every render / refresh). Selection is
    // never persisted to browser storage.
    var selectedBatchActivityIds = {};
    var batchProjectSaving = false;
    var batchProjectTargetId = null;
    // Phase 3B.7: batch note overwrite state. This is the second batch
    // write capability: only note overwrite on multiple closed, non-hidden,
    // non-deleted activities in the current shell session. It reuses the
    // same selectedBatchActivityIds selection as batch project so the user
    // picks activities once and chooses either "set project" or "overwrite
    // note". The note text lives in memory only (never persisted to browser
    // storage). Empty string is a valid value and clears the notes.
    var batchNoteSaving = false;
    // Phase 3B.8: single activity restore state. This is the restore
    // foundation: only single hidden / soft-deleted activities can be
    // restored. restoreSaving guards any restore operation;
    // restoreSavingActivityId tracks which activity's restore button is
    // currently saving (null = none). They are intentionally separate from
    // all other saving states so the restore flow does not pollute the
    // project / note / time / split / merge / hide / delete / batch flows.
    var restoreSaving = false;
    var restoreSavingActivityId = null;

    // --- Phase 4A: Statistics / Export read-only state ------------------
    // The Statistics / Export page is a read-only page: it only loads
    // display-safe aggregated data via get_statistics_export_summary and
    // never writes a file, opens a save dialog, or calls an export action.
    // statisticsLoaded tracks whether the page has been loaded at least
    // once; statisticsLoading guards the load button against double-clicks;
    // statisticsRequestToken prevents stale responses from overwriting newer
    // data when the user rapidly changes the date range. No state is ever
    // persisted to browser storage.
    var statisticsLoaded = false;
    var statisticsLoading = false;
    var statisticsRequestToken = 0;

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

    // --- Phase 3C: Unified Timeline status semantics -------------------
    // Centralized status TYPE → CSS class mapping and standard Chinese
    // text so loading / empty / error / success / info / saving states are
    // consistent across the Timeline list, detail panel, edit panel, and
    // correction shell. These helpers are ADDITIVE: the existing per-area
    // helpers (showEditStatus, showTimeStatus, setCorrectionShellStatus,
    // etc.) remain unchanged and continue to own their DOM elements. The
    // unified helpers centralize the vocabulary so future code and tests
    // can rely on a single status-type contract.
    var STATUS_TYPE_CLASS = {
        info: "edit-status-info",
        success: "edit-status-success",
        error: "edit-status-error",
        loading: "edit-status-loading",
        empty: "edit-status-empty"
    };

    function statusClassFor(type) {
        return STATUS_TYPE_CLASS[type] || STATUS_TYPE_CLASS.info;
    }

    // Apply a status type class to a status element that uses the shared
    // ``edit-status`` base. Used by the per-area helpers when they want to
    // express info / loading / empty states in addition to error / success.
    // Phase 3C.1 hardening: only toggle the status-type classes, preserve
    // any structural classes the element already has, and never splice
    // user input into the class name — only the whitelisted
    // STATUS_TYPE_CLASS values are ever applied.
    var STATUS_TYPE_CLASS_VALUES = [
        "edit-status-info", "edit-status-success", "edit-status-error",
        "edit-status-loading", "edit-status-empty"
    ];
    function applyStatusType(el, type) {
        if (!el) return;
        var preserved = [];
        if (typeof el.className === "string" && el.className) {
            preserved = el.className.split(/\s+/).filter(function (cls) {
                return cls && STATUS_TYPE_CLASS_VALUES.indexOf(cls) === -1;
            });
        }
        if (preserved.indexOf("edit-status") === -1) {
            preserved.unshift("edit-status");
        }
        preserved.push(statusClassFor(type));
        el.className = preserved.join(" ");
    }

    // Unified Timeline list-level status (loading / empty / error / info).
    // Delegates to the existing #timeline-error banner and #timeline-loading
    // indicator so the DOM contract is unchanged.
    function setTimelineStatus(message, type) {
        if (!message) {
            clearTimelineError();
            setTimelineLoading(false);
            return;
        }
        if (type === "loading") {
            setTimelineLoading(true);
            clearTimelineError();
            return;
        }
        setTimelineLoading(false);
        if (type === "error") {
            showTimelineError(message);
            return;
        }
        clearTimelineError();
    }

    // Unified detail panel status (header text). When message is empty the
    // header returns to the stable "请选择一条时间记录" prompt.
    function setDetailStatus(message, type) {
        var header = document.getElementById("timeline-details-header");
        if (!header) return;
        if (!message) {
            header.textContent = "请选择一条时间记录";
            return;
        }
        header.textContent = message;
    }

    // Unified edit panel status. Delegates to showEditStatus for backward
    // compatibility while mapping the unified type to error/success.
    function setEditStatus(message, type) {
        if (!message) {
            showEditStatus("", false);
            return;
        }
        showEditStatus(message, type === "error");
    }

    // Unified correction shell status. Delegates to
    // setCorrectionShellStatus for backward compatibility.
    function setCorrectionStatus(message, type) {
        setCorrectionShellStatus(message, type === "error");
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
                // Phase 3B.5B: if the correction shell is open for this
                // session, refresh its context summary from the updated
                // session object. The activity summary is re-read from the
                // rendered detail rows. No write is performed.
                // Phase 3B.9.1: also skip the re-render while any
                // correction-shell write is in flight (batch project / batch
                // note / single restore) so the saving state, selection,
                // textarea, and status messages are not overwritten mid-save.
                if (correctionShellOpen
                    && correctionShellSessionId === found.session_id
                    && !isEditDirty()
                    && !isAnyCorrectionWriteSaving()) {
                    renderCorrectionShell(
                        found,
                        getCurrentDetailActivities(),
                        correctionShellMode,
                        correctionShellActivityId
                    );
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
        // Phase 3B.5B: switching sessions closes the correction shell so
        // the shell context does not get confused across sessions. The
        // shell is a per-session workspace.
        if (correctionShellOpen && correctionShellSessionId !== sessionId) {
            resetCorrectionShellState();
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
                // Phase 3B.5A: per-activity correction actions are grouped
                // into three visually distinct groups with a stable order:
                // edit group (编辑时间 → 拆分) → merge group (与下一条合并)
                // → danger group (隐藏 → 删除). No new actions are added;
                // the wrappers only consolidate existing buttons so the
                // destructive actions are clearly separated from edits.
                + '<div class="detail-item-actions">'
                + '<div class="detail-action-edit-group">'
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
                + '</div>'
                + '<div class="detail-action-merge-group">'
                + '<button type="button" class="detail-merge-btn"'
                + ' data-activity-id="' + escapeHtml(String(aid)) + '"'
                + ' data-next-activity-id="' + escapeHtml(String(hasNext ? (activities[i + 1].activity_id || 0) : 0)) + '"'
                + (mergeBtnDisabled ? ' disabled' : '')
                + ' title="' + escapeHtml(mergeBtnTitle) + '"'
                + '>与下一条合并</button>'
                + '</div>'
                + '<div class="detail-action-danger-group">'
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
        // Phase 3B.6: reset batch project selection state so a stale batch
        // selection from the previous session does not leak into the next
        // session. The reset also clears the project select / status so the
        // panel returns to a clean baseline.
        resetBatchProjectState();
        // Phase 3B.7: reset batch note state too so a stale note textarea /
        // saving flag does not leak into the next session.
        resetBatchNoteState();
        // Phase 3B.8: reset restore state too so a stale restore list /
        // saving flag does not leak into the next session.
        resetRestoreState();
        // Phase 3B.5B: reset the correction shell state too so a stale
        // shell does not leak into the next session.
        resetCorrectionShellState();
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

    // --- Phase 3B.5B: Timeline correction shell helpers -----------------
    // The shell is a read-only context + navigation layout. It reuses the
    // existing edit panel / detail row controls; it does not introduce any
    // new write capability. Activity summaries are read from the already-
    // rendered detail rows (which contain only display-safe fields), so no
    // new bridge call and no new backend method are needed.

    function getSelectedSession() {
        if (!selectedSessionId) return null;
        for (var i = 0; i < currentSessions.length; i++) {
            if (currentSessions[i].session_id === selectedSessionId) {
                return currentSessions[i];
            }
        }
        return null;
    }

    // Read display-safe activity fields from the rendered detail rows. The
    // detail rows are produced by renderSessionDetails and only ever contain
    // display-safe fields (activity_id, time range, resource_name, app_name,
    // resource_type, project_name, duration, is_in_progress class). This
    // helper never reads raw sensitive backend fields (window titles, file
    // paths, copied-text metadata, or note internals) because those are
    // never rendered into the DOM.
    function getCurrentDetailActivities() {
        var list = document.getElementById("timeline-details-list");
        if (!list) return [];
        var rows = list.querySelectorAll(".detail-item");
        var out = [];
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var aid = row.getAttribute("data-activity-id") || "";
            var timeEl = row.querySelector(".detail-item-time");
            var nameEl = row.querySelector(".detail-item-name");
            var typeEl = row.querySelector(".detail-item-type");
            var appEl = row.querySelector(".detail-item-app");
            var projEl = row.querySelector(".detail-item-project");
            var durEl = row.querySelector(".detail-item-duration");
            out.push({
                activity_id: aid,
                time_range: timeEl ? timeEl.textContent : "",
                resource_name: nameEl ? nameEl.textContent : "",
                resource_type: typeEl ? typeEl.textContent : "",
                app_name: appEl ? appEl.textContent : "",
                project_name: projEl ? projEl.textContent : "",
                duration: durEl ? durEl.textContent : "",
                is_in_progress: row.classList.contains("in-progress")
            });
        }
        return out;
    }

    // --- Phase 3B.9: correction shell consolidation helpers ------------
    // These helpers consolidate the cross-phase saving / status / display
    // logic so single / batch / restore sections share one source of truth.
    // No new write capability is introduced; the helpers only coordinate
    // existing state and DOM.

    // Display-safe text helper. Returns a fallback when the value is null /
    // undefined / empty so the shell never renders "undefined" or "null".
    // The returned string is intended to be passed through escapeHtml by
    // the caller before insertion into innerHTML; it never reads raw
    // sensitive backend columns (titles, paths, copy buffers, note internals).
    function safeText(value, fallback) {
        if (value === null || value === undefined || value === "") {
            return fallback || "";
        }
        return String(value);
    }

    // Cross-save guard: returns true when ANY correction-shell write is in
    // flight (batch project, batch note, or single restore). The existing
    // edit / time / split / merge / hide / delete saving states are owned
    // by clearEditPanel and are intentionally not consulted here; those
    // flows run inside the edit panel and have their own dirty guard.
    // Used by every correction-shell write path to refuse a competing
    // write with a unified "请等待当前操作完成" message instead of calling
    // the bridge.
    function isAnyCorrectionWriteSaving() {
        return !!(batchProjectSaving || batchNoteSaving || restoreSaving);
    }

    // Unified cross-save refusal helper. Surfaces the stable Chinese
    // message on the most specific open status area (batch project / batch
    // note / restore / shell) so the user sees the refusal where they
    // clicked. Does not call the bridge.
    function refuseCrossSaveStatus() {
        var msg = "请等待当前操作完成";
        if (restoreSaving) {
            showRestoreStatus(msg, true);
            return;
        }
        if (batchNoteSaving) {
            showBatchNoteStatus(msg, true);
            return;
        }
        if (batchProjectSaving) {
            showBatchProjectStatus(msg, true);
            return;
        }
        setCorrectionShellStatus(msg, true);
    }

    // Reset every correction-shell action status area to the hidden / empty
    // baseline. Used on shell open and on successful writes so stale
    // messages do not linger. Does not reset saving state (saving state is
    // owned by the per-action reset helpers).
    function resetCorrectionActionStatus() {
        setCorrectionShellStatus("", false);
        showBatchProjectStatus("", false);
        showBatchNoteStatus("", false);
        showRestoreStatus("", false);
    }

    function setCorrectionShellStatus(message, isError) {
        var statusEl = document.getElementById("correction-shell-status");
        if (!statusEl) return;
        if (!message) {
            statusEl.hidden = true;
            statusEl.textContent = "";
            statusEl.className = "edit-status correction-shell-status";
            return;
        }
        statusEl.hidden = false;
        statusEl.textContent = message;
        statusEl.className = "edit-status correction-shell-status "
            + (isError ? "edit-status-error" : "edit-status-success");
    }

    function resetCorrectionShellState() {
        correctionShellOpen = false;
        correctionShellSessionId = null;
        correctionShellActivityId = null;
        correctionShellMode = null;
        // Phase 3B.5B.1: cancel any pending highlight timer so a shell
        // close / reset never leaves a dangling timer that mutates a
        // detail row's class list after the shell is gone.
        if (correctionShellHighlightTimer !== null) {
            clearTimeout(correctionShellHighlightTimer);
            correctionShellHighlightTimer = null;
        }
        // Phase 3B.6: clear the batch project selection so a stale selection
        // does not carry over to the next shell open. selectedSessionId is
        // intentionally NOT cleared here (preserved by closeCorrectionShell).
        resetBatchProjectState();
        // Phase 3B.7: clear the batch note textarea / saving flag too so a
        // stale note does not carry over to the next shell open.
        resetBatchNoteState();
        // Phase 3B.8: clear the restore list / saving flag too so a stale
        // restore list does not carry over to the next shell open.
        resetRestoreState();
        var shell = document.getElementById("timeline-correction-shell");
        if (shell) shell.hidden = true;
        var detailsCol = document.querySelector(".timeline-details");
        if (detailsCol) detailsCol.classList.remove("shell-open");
        var statusEl = document.getElementById("correction-shell-status");
        if (statusEl) {
            statusEl.hidden = true;
            statusEl.textContent = "";
            statusEl.className = "edit-status";
        }
        var ctxEl = document.getElementById("correction-shell-context");
        if (ctxEl) ctxEl.innerHTML = "";
        var actsEl = document.getElementById("correction-shell-activities");
        if (actsEl) actsEl.innerHTML = "";
        var actionsEl = document.getElementById("correction-shell-actions");
        if (actionsEl) actionsEl.innerHTML = "";
        var subEl = document.getElementById("correction-shell-subtitle");
        if (subEl) subEl.textContent = "选择一个时段后打开";
    }

    // Render the shell context, activity summary, and action guidance. Only
    // display-safe fields are used. The action area guides the user back to
    // the existing per-activity / session-level controls; it does not render
    // its own write buttons, so no new write path is introduced.
    function renderCorrectionShell(session, activities, mode, activityId) {
        var subEl = document.getElementById("correction-shell-subtitle");
        var ctxEl = document.getElementById("correction-shell-context");
        var actsEl = document.getElementById("correction-shell-activities");
        var actionsEl = document.getElementById("correction-shell-actions");
        if (!ctxEl || !session) return;

        // --- Context summary (display-safe only) ---
        // Phase 3B.9: every dynamic value passes through safeText + escapeHtml
        // so the shell never reads / displays raw sensitive backend columns
        // (titles, paths, copy buffers, note internals). Only display-safe
        // fields (date, project label, time range, duration, count, status)
        // are used.
        var dateEl = document.getElementById("timeline-date-display");
        var dateTxt = safeText(dateEl ? dateEl.textContent : "", "");
        var projectLabel = safeText(session.project_name, "未归类");
        if (session.project_description) {
            projectLabel += " (" + safeText(session.project_description, "") + ")";
        }
        var timeRange = safeText(formatTimeRange(session.start_time, session.end_time, session.is_in_progress), "");
        var statusTxt = safeText(session.status, "");
        var inProgressTxt = session.is_in_progress ? "进行中" : "已结束";
        if (subEl) {
            subEl.textContent = dateTxt + " ｜ " + timeRange + " ｜ " + projectLabel;
        }
        var ctxHtml = '<div class="correction-shell-context-row">'
            + '<span class="correction-shell-context-label">日期：</span>'
            + '<span class="correction-shell-context-value">' + escapeHtml(dateTxt) + '</span>'
            + '<span class="correction-shell-context-label">项目：</span>'
            + '<span class="correction-shell-context-value">' + escapeHtml(projectLabel) + '</span>'
            + '<span class="correction-shell-context-label">时段：</span>'
            + '<span class="correction-shell-context-value">' + escapeHtml(timeRange) + '</span>'
            + '<span class="correction-shell-context-label">时长：</span>'
            + '<span class="correction-shell-context-value">' + escapeHtml(safeText(session.duration, "")) + '</span>'
            + '<span class="correction-shell-context-label">活动数：</span>'
            + '<span class="correction-shell-context-value">' + escapeHtml(safeText(session.event_count, "0")) + '</span>'
            + '<span class="correction-shell-context-label">状态：</span>'
            + '<span class="correction-shell-context-value' + (session.is_in_progress ? " in-progress" : "") + '">' + escapeHtml(statusTxt || inProgressTxt) + '</span>'
            + '</div>';
        ctxEl.innerHTML = ctxHtml;

        // --- Activity list summary (read from rendered detail rows) ---
        if (actsEl) {
            if (!activities || activities.length === 0) {
                actsEl.innerHTML = '<div class="correction-shell-activities-title">活动明细</div>'
                    + '<div class="correction-shell-activities-empty">暂无活动详情，请在左侧活动详情中查看。</div>';
            } else {
                var html = '<div class="correction-shell-activities-title">活动明细（点击定位到对应活动）</div>';
                for (var i = 0; i < activities.length; i++) {
                    var a = activities[i];
                    var rawId = String(a.activity_id || "");
                    // Phase 3B.5B.1: only a numeric activity id is a valid
                    // click-to-locate target. An invalid / missing id is
                    // rendered as a non-clickable row so the user never
                    // gets a stale-target error from an id that could never
                    // match a real .detail-item.
                    var numericId = /^[0-9]+$/.test(rawId) ? rawId : "";
                    var cls = "correction-shell-activity-row";
                    if (!numericId) cls += " is-static";
                    if (mode === "activity" && activityId && rawId === String(activityId)) {
                        cls += " is-selected";
                    }
                    // Phase 3B.6: in-progress activities cannot be batch
                    // edited (their displayed end_time may be projected).
                    var isInProgress = !!a.is_in_progress;
                    if (isInProgress) cls += " is-in-progress";
                    // Eligible for batch project edit only when closed and
                    // has a valid numeric id. Hidden / deleted activities
                    // never reach the rendered detail rows.
                    var batchEligible = !!numericId && !isInProgress;
                    var checkedAttr = "";
                    if (batchEligible && selectedBatchActivityIds[numericId]) {
                        checkedAttr = " checked";
                    }
                    html += '<div class="' + cls + '"'
                        + (numericId ? ' data-correction-activity-id="' + escapeHtml(numericId) + '"' : '')
                        + '>'
                        + (batchEligible
                            ? '<input type="checkbox" class="correction-shell-activity-checkbox"'
                                + ' data-batch-activity-id="' + escapeHtml(numericId) + '"'
                                + (batchProjectSaving ? ' disabled' : '')
                                + checkedAttr + '>'
                            : '<input type="checkbox" class="correction-shell-activity-checkbox" disabled>')
                        + '<span class="correction-shell-activity-time">' + escapeHtml(safeText(a.time_range, "")) + '</span>'
                        + '<span class="correction-shell-activity-name" title="' + escapeHtml(safeText(a.resource_name, "")) + '">' + escapeHtml(safeText(a.resource_name, "")) + '</span>'
                        + '<span class="correction-shell-activity-duration">' + escapeHtml(safeText(a.duration, "")) + '</span>'
                        + '</div>';
                }
                actsEl.innerHTML = html;
                // Phase 3B.6: prune stale selected ids that no longer exist
                // in the freshly rendered activity list so the selection is
                // always a subset of the current shell activities.
                pruneStaleBatchSelection(activities);
                // Bind click handlers only on rows that carry a valid
                // numeric id. The handler only scrolls to / highlights the
                // matching detail row; it performs no write and calls no
                // bridge method. Clicks on the batch checkbox are stopped
                // so they do not also trigger the row click-to-locate.
                var rows = actsEl.querySelectorAll(
                    ".correction-shell-activity-row[data-correction-activity-id]"
                );
                for (var j = 0; j < rows.length; j++) {
                    (function (rowEl) {
                        rowEl.addEventListener("click", function (event) {
                            if (event.target
                                && event.target.classList
                                && event.target.classList.contains("correction-shell-activity-checkbox")) {
                                return;
                            }
                            var aid = rowEl.getAttribute("data-correction-activity-id");
                            highlightDetailRow(aid);
                        });
                    })(rows[j]);
                }
                // Phase 3B.6: bind batch checkbox change handlers so toggling
                // a checkbox updates the selection state without re-rendering
                // the whole shell (which would lose the user's checkbox focus).
                var checkboxes = actsEl.querySelectorAll(
                    ".correction-shell-activity-checkbox[data-batch-activity-id]"
                );
                for (var k = 0; k < checkboxes.length; k++) {
                    (function (cbEl) {
                        cbEl.addEventListener("change", function () {
                            var aid = cbEl.getAttribute("data-batch-activity-id");
                            toggleBatchActivity(aid, cbEl.checked);
                        });
                        cbEl.addEventListener("click", function (event) {
                            // Stop propagation so the row click-to-locate
                            // handler does not fire when the user clicks the
                            // checkbox.
                            if (event.stopPropagation) {
                                event.stopPropagation();
                            }
                        });
                    })(checkboxes[k]);
                }
            }
        }

        // --- Action guidance (no write buttons rendered here) ---
        if (actionsEl) {
            var guidance = '<div class="correction-shell-actions-title">纠错操作</div>'
                + '<div class="correction-shell-actions-hint">'
                + '会话级操作（项目与备注 / 时间修正 / 拆分 / 可见性）请在上方“编辑当前时段”面板中执行；'
                + '单条活动操作（编辑时间 / 拆分 / 与下一条合并 / 隐藏 / 删除）请在左侧活动详情列表中对应行执行。'
                + ' <span class="danger-note">隐藏与删除为软操作，本阶段不会物理删除数据。</span>'
                + '</div>';
            actionsEl.innerHTML = guidance;
        }

        // --- Phase 3B.6: batch project reassignment section ---
        // The batch section is always rendered when the shell is open so the
        // user can start a batch project reassignment. It reuses the cached
        // project list (projectsCache) so no extra bridge call is needed
        // after the first load.
        renderBatchProjectSection(session, activities);
        // --- Phase 3B.7: batch note overwrite section ---
        // Rendered alongside the batch project section and reuses the same
        // selectedBatchActivityIds selection. The user picks activities once
        // and can choose either "set project" or "overwrite note".
        renderBatchNoteSection(session, activities);
        // --- Phase 3B.8: single activity restore section ---
        // Loads the restorable activities for the current date and renders
        // a read-only recovery list. Only single hidden / soft-deleted
        // activities can be restored; no batch restore, undo stack, or
        // permanent delete.
        renderRestoreSection(session, activities);
    }

    // Scroll to and briefly highlight a detail row so the user can locate
    // the existing per-activity action buttons. No write is performed and
    // no bridge method is called. Repeated clicks reuse a single tracked
    // timer so timers never accumulate.
    function highlightDetailRow(activityId) {
        if (!activityId) return;
        var row = document.querySelector(
            '#timeline-details-list .detail-item[data-activity-id="' + activityId + '"]'
        );
        if (!row) {
            setCorrectionShellStatus("该活动已不在当前详情中，可能已刷新，请重试。", true);
            return;
        }
        // Clear any prior selected / highlight class on sibling rows.
        var all = document.querySelectorAll("#timeline-details-list .detail-item");
        for (var i = 0; i < all.length; i++) {
            all[i].classList.remove("shell-target");
            all[i].classList.remove("detail-item-highlight");
        }
        row.classList.add("shell-target");
        // Phase 3B.5B.1: brief transient highlight for immediate feedback.
        // A single tracked timer is used: clear the previous before
        // scheduling a new one so repeated clicks never accumulate timers
        // or throw. .shell-target remains as the persistent locator.
        row.classList.add("detail-item-highlight");
        if (correctionShellHighlightTimer !== null) {
            clearTimeout(correctionShellHighlightTimer);
            correctionShellHighlightTimer = null;
        }
        correctionShellHighlightTimer = setTimeout(function () {
            row.classList.remove("detail-item-highlight");
            correctionShellHighlightTimer = null;
        }, 1800);
        if (row.scrollIntoView) {
            row.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        setCorrectionShellStatus("", false);
    }

    function openCorrectionShell(mode, activityId) {
        // Refuse to open while there are unsaved edits so the shell does
        // not override in-progress inputs.
        if (isEditDirty()) {
            setCorrectionShellStatus("请先保存或取消当前编辑", true);
            return;
        }
        var session = getSelectedSession();
        if (!session) {
            setCorrectionShellStatus("请先选择一个时段", true);
            return;
        }
        // activity-level open requires the activity id to still exist in the
        // current detail list.
        var effectiveMode = mode === "activity" ? "activity" : "session";
        if (effectiveMode === "activity") {
            var activities = getCurrentDetailActivities();
            var found = false;
            for (var i = 0; i < activities.length; i++) {
                if (String(activities[i].activity_id) === String(activityId)) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                setCorrectionShellStatus("该活动已不存在，请刷新后重试", true);
                return;
            }
        }
        correctionShellOpen = true;
        correctionShellSessionId = session.session_id;
        correctionShellActivityId = effectiveMode === "activity" ? activityId : null;
        correctionShellMode = effectiveMode;

        var shell = document.getElementById("timeline-correction-shell");
        if (shell) shell.hidden = false;
        var detailsCol = document.querySelector(".timeline-details");
        if (detailsCol) detailsCol.classList.add("shell-open");

        renderCorrectionShell(
            session,
            getCurrentDetailActivities(),
            effectiveMode,
            correctionShellActivityId
        );
        // Phase 3B.9: clear every action status area on open so stale
        // messages from a previous shell session do not linger.
        resetCorrectionActionStatus();
    }

    function closeCorrectionShell() {
        // Closing the shell returns to the Timeline details / edit panel.
        // The selected session is intentionally preserved so the user
        // returns to the same context.
        var wasOpen = correctionShellOpen;
        resetCorrectionShellState();
        // selectedSessionId is intentionally NOT cleared here.
        if (wasOpen) {
            // Phase 3B.9: resetCorrectionShellState already clears the
            // shell-only status areas via the per-section reset helpers;
            // this extra clear is a no-op safety net.
            setCorrectionShellStatus("", false);
        }
    }

    // ====================================================================
    // Phase 3B.6: Timeline batch project editing foundation
    // ====================================================================
    //
    // This is the first batch write capability in the WebView Timeline. It
    // allows the user to select multiple closed, non-hidden, non-deleted
    // activities in the current correction shell session and reclassify them
    // to the same project in a single atomic transaction (the bridge ->
    // API -> service path uses a rowcount guard + rollback so no partial
    // write is ever persisted).
    //
    // Scope boundaries (enforced by the backend, mirrored here):
    // - Only project reassignment. No batch hide / delete / time / split /
    //   merge / undo / restore / permanent delete / auto-rule / overlap.
    // - Only closed activities (end_time IS NOT NULL). In-progress rows
    //   render a disabled checkbox.
    // - Only activities in the current shell session. Stale ids that
    //   disappear after a refresh are pruned automatically.
    // - No browser storage. Selection lives in memory only.

    function resetBatchProjectState() {
        selectedBatchActivityIds = {};
        batchProjectSaving = false;
        batchProjectTargetId = null;
        // Reset the batch project select / status DOM so the section
        // returns to a clean baseline. The section element itself is
        // shown/hidden together with the shell; only its inner controls
        // are reset here.
        var select = document.getElementById("correction-shell-batch-project-select");
        if (select) {
            select.value = "";
            select.disabled = true;
        }
        var saveBtn = document.getElementById("correction-shell-batch-save-btn");
        if (saveBtn) saveBtn.disabled = true;
        var selectAllBtn = document.getElementById("correction-shell-batch-select-all-btn");
        var clearBtn = document.getElementById("correction-shell-batch-clear-btn");
        if (selectAllBtn) selectAllBtn.disabled = true;
        if (clearBtn) clearBtn.disabled = true;
        var countEl = document.getElementById("correction-shell-batch-count");
        if (countEl) countEl.textContent = "已选择 0 条";
        showBatchProjectStatus("", false);
    }

    // Remove selected ids that are no longer present in the freshly rendered
    // activity list. Activities that disappeared (e.g. hidden / deleted by
    // another session, or grouped differently after an auto-refresh) are
    // silently dropped so the selection is always a subset of the current
    // shell activities.
    function pruneStaleBatchSelection(activities) {
        if (!activities) {
            selectedBatchActivityIds = {};
            updateBatchSelectionCount();
            return;
        }
        var validIds = {};
        for (var i = 0; i < activities.length; i++) {
            var rawId = String(activities[i].activity_id || "");
            if (!/^[0-9]+$/.test(rawId)) continue;
            if (activities[i].is_in_progress) continue;
            validIds[rawId] = true;
        }
        var next = {};
        var changed = false;
        var keys = Object.keys(selectedBatchActivityIds);
        for (var k = 0; k < keys.length; k++) {
            if (validIds[keys[k]]) {
                next[keys[k]] = true;
            } else {
                changed = true;
            }
        }
        if (changed) {
            selectedBatchActivityIds = next;
            updateBatchSelectionCount();
        }
    }

    function toggleBatchActivity(activityId, checked) {
        if (batchProjectSaving || batchNoteSaving) return;
        if (!activityId) return;
        var key = String(activityId);
        if (checked) {
            selectedBatchActivityIds[key] = true;
        } else {
            delete selectedBatchActivityIds[key];
        }
        updateBatchSelectionCount();
        updateBatchSaveButtonState();
        updateBatchNoteSaveButtonState();
    }

    function selectAllBatchActivities() {
        if (batchProjectSaving || batchNoteSaving) return;
        var rows = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]:not([disabled])"
        );
        for (var i = 0; i < rows.length; i++) {
            var aid = rows[i].getAttribute("data-batch-activity-id");
            if (aid) {
                selectedBatchActivityIds[aid] = true;
                rows[i].checked = true;
            }
        }
        updateBatchSelectionCount();
        updateBatchSaveButtonState();
        updateBatchNoteSaveButtonState();
    }

    function clearBatchSelection() {
        if (batchProjectSaving || batchNoteSaving) return;
        selectedBatchActivityIds = {};
        var rows = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]"
        );
        for (var i = 0; i < rows.length; i++) {
            rows[i].checked = false;
        }
        updateBatchSelectionCount();
        updateBatchSaveButtonState();
        updateBatchNoteSaveButtonState();
    }

    function updateBatchSelectionCount() {
        var countEl = document.getElementById("correction-shell-batch-count");
        if (!countEl) return;
        var count = Object.keys(selectedBatchActivityIds).length;
        countEl.textContent = "已选择 " + count + " 条";
    }

    function updateBatchSaveButtonState() {
        var saveBtn = document.getElementById("correction-shell-batch-save-btn");
        if (!saveBtn) return;
        var count = Object.keys(selectedBatchActivityIds).length;
        var select = document.getElementById("correction-shell-batch-project-select");
        var hasProject = !!(select && select.value);
        saveBtn.disabled = batchProjectSaving || count < 2 || !hasProject;
    }

    function setBatchProjectSaving(saving) {
        batchProjectSaving = saving;
        var saveBtn = document.getElementById("correction-shell-batch-save-btn");
        var selectAllBtn = document.getElementById("correction-shell-batch-select-all-btn");
        var clearBtn = document.getElementById("correction-shell-batch-clear-btn");
        var select = document.getElementById("correction-shell-batch-project-select");
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "保存中…" : "批量设置项目";
        }
        if (selectAllBtn) selectAllBtn.disabled = saving;
        if (clearBtn) clearBtn.disabled = saving;
        if (select) select.disabled = saving;
        // Disable / re-enable every batch checkbox so the user cannot
        // change selection while a save is in flight.
        var checkboxes = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]"
        );
        for (var i = 0; i < checkboxes.length; i++) {
            // Preserve the "is-in-progress" disabled state: only eligible
            // (closed) rows get toggled. We re-derive eligibility from
            // whether the checkbox carries data-batch-activity-id.
            var eligible = checkboxes[i].hasAttribute("data-batch-activity-id");
            if (eligible) {
                checkboxes[i].disabled = saving;
            }
        }
        // Phase 3B.7: also disable the batch note textarea / save button so
        // the user cannot start a competing note save while a project save
        // is in flight.
        var noteText = document.getElementById("correction-shell-batch-note-text");
        if (noteText) noteText.disabled = saving || batchNoteSaving;
        if (!saving) {
            // Re-apply the project/count-based gating after save ends.
            updateBatchSaveButtonState();
            updateBatchNoteSaveButtonState();
        }
    }

    function showBatchProjectStatus(message, isError) {
        var statusEl = document.getElementById("correction-shell-batch-status");
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

    // Render the batch project section. The section is always present in
    // the HTML; this function populates the project select (reusing
    // projectsCache) and refreshes the count / save button state. The
    // section is shown whenever the shell is open.
    function renderBatchProjectSection(session, activities) {
        var section = document.getElementById("correction-shell-batch-project-section");
        if (!section) return;
        // The section is always visible when the shell is open so the user
        // can start a batch reassignment at any time. It does not need to
        // be hidden based on session in-progress state (an in-progress
        // session simply has no eligible closed activities).
        section.hidden = false;
        // Re-prune the selection in case the activity list changed.
        pruneStaleBatchSelection(activities);
        // Populate the project select using the cached project list. If the
        // cache is empty (first use), load it lazily and re-populate.
        var select = document.getElementById("correction-shell-batch-project-select");
        if (select && !projectsCache) {
            select.innerHTML = '<option value="">加载中…</option>';
            select.disabled = true;
            loadProjects().then(function (projects) {
                populateBatchProjectSelect(projects);
            });
        } else if (select && projectsCache) {
            populateBatchProjectSelect(projectsCache);
        }
        updateBatchSelectionCount();
        updateBatchSaveButtonState();
        // Phase 3B.9.1: do not clear the status area while a save is in
        // flight. The save success / failure handler owns the status during
        // saving; an auto-refresh re-render must not wipe a just-shown
        // error or success message.
        if (!batchProjectSaving) {
            showBatchProjectStatus("", false);
        }
    }

    function populateBatchProjectSelect(projects) {
        var select = document.getElementById("correction-shell-batch-project-select");
        if (!select) return;
        select.innerHTML = "";
        var placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "请选择项目";
        select.appendChild(placeholder);
        if (!projects || projects.length === 0) {
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
            select.appendChild(option);
        }
        // Restore the previously chosen target project if any (e.g. after
        // an auto-refresh re-rendered the select).
        if (batchProjectTargetId) {
            select.value = String(batchProjectTargetId);
        }
        select.disabled = batchProjectSaving;
    }

    function saveBatchProject() {
        if (batchProjectSaving) return;
        // Block the batch save while there are unsaved per-session edits so
        // the two write paths never race on the same session.
        if (isEditDirty()) {
            showBatchProjectStatus("请先保存或取消当前编辑", true);
            return;
        }
        // Phase 3B.9: cross-save guard. A batch project save triggers a
        // Timeline refresh which would race with an in-flight batch note
        // save or single restore. Refuse with the unified message instead
        // of calling the bridge.
        if (batchNoteSaving || restoreSaving) {
            showBatchProjectStatus("请等待当前操作完成", true);
            return;
        }
        var selectedIds = Object.keys(selectedBatchActivityIds);
        if (selectedIds.length < 2) {
            showBatchProjectStatus("请选择至少两个活动", true);
            return;
        }
        var select = document.getElementById("correction-shell-batch-project-select");
        if (!select) {
            showBatchProjectStatus("操作失败", true);
            return;
        }
        var projectIdStr = select.value;
        if (!projectIdStr) {
            showBatchProjectStatus("请选择有效的项目", true);
            return;
        }
        var projectId = parseInt(projectIdStr, 10);
        if (!projectId || projectId <= 0) {
            showBatchProjectStatus("请选择有效的项目", true);
            return;
        }
        // Phase 3B.6: re-check every selected id is still present in the
        // currently rendered shell activity rows. Stale ids (e.g. an
        // auto-refresh removed a row between the user checking the box and
        // clicking save) are dropped silently; if fewer than 2 remain we
        // abort with a clear message instead of calling the bridge.
        var renderedIds = {};
        var rows = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]:not([disabled])"
        );
        for (var i = 0; i < rows.length; i++) {
            var aid = rows[i].getAttribute("data-batch-activity-id");
            if (aid) renderedIds[aid] = true;
        }
        var cleanIds = [];
        for (var j = 0; j < selectedIds.length; j++) {
            if (renderedIds[selectedIds[j]]) {
                cleanIds.push(parseInt(selectedIds[j], 10));
            }
        }
        if (cleanIds.length < 2) {
            // Update the in-memory selection to match the rendered rows so
            // the count display stays accurate, then abort.
            selectedBatchActivityIds = {};
            for (var k in renderedIds) {
                if (renderedIds.hasOwnProperty(k)) selectedBatchActivityIds[k] = true;
            }
            updateBatchSelectionCount();
            updateBatchSaveButtonState();
            showBatchProjectStatus("所选活动已失效，请重新选择", true);
            return;
        }
        batchProjectTargetId = projectId;
        setBatchProjectSaving(true);
        showBatchProjectStatus("", false);
        callBridge("batch_update_timeline_activities_project", cleanIds, projectId).then(function (result) {
            setBatchProjectSaving(false);
            if (!result || result.ok === false) {
                // Keep the selection / detail list so the user can retry.
                // The bridge returns a stable Chinese error message; we
                // surface it verbatim without echoing internal error detail.
                var msg = (result && result.error) ? result.error : "操作失败";
                showBatchProjectStatus(msg, true);
                return;
            }
            // Success: clear selection, refresh Timeline, keep the shell
            // context if the session is still present.
            var updatedCount = result.updated_count || cleanIds.length;
            showBatchProjectStatus("已批量更新项目（共 " + updatedCount + " 条）", false);
            selectedBatchActivityIds = {};
            batchProjectTargetId = null;
            updateBatchSelectionCount();
            // Refresh the Timeline so the new project assignment is
            // reflected in the sessions list and the detail list. The
            // shell will re-render from the refreshed data if the session
            // is still present; if the session disappeared (e.g. it was
            // re-grouped), the auto-refresh / disappear path will close
            // the shell safely.
            refreshTimelineForBatchSave();
        }).catch(function () {
            setBatchProjectSaving(false);
            showBatchProjectStatus("操作失败", true);
        });
    }

    // Refresh the Timeline data after a successful batch save. We reuse the
    // existing loadTimeline path so the sessions list, detail list, and
    // edit panel are all rebuilt from the fresh backend state. If the
    // shell's session is still present after the refresh, the shell is
    // re-rendered with the updated activity list; otherwise the shell is
    // closed safely.
    function refreshTimelineForBatchSave() {
        var dateEl = document.getElementById("timeline-date-display");
        var date = timelineDate || (dateEl ? dateEl.textContent : null);
        // Defer the shell re-render to after the timeline reloads; the
        // loadTimeline path's auto-refresh branch already re-renders the
        // shell if it is still open for the refreshed session.
        loadTimeline(date);
    }

    // Bind the batch project section controls. Called once during init.
    function bindBatchProjectControls() {
        var saveBtn = document.getElementById("correction-shell-batch-save-btn");
        if (saveBtn) {
            saveBtn.addEventListener("click", saveBatchProject);
        }
        var selectAllBtn = document.getElementById("correction-shell-batch-select-all-btn");
        if (selectAllBtn) {
            selectAllBtn.addEventListener("click", selectAllBatchActivities);
        }
        var clearBtn = document.getElementById("correction-shell-batch-clear-btn");
        if (clearBtn) {
            clearBtn.addEventListener("click", clearBatchSelection);
        }
        var select = document.getElementById("correction-shell-batch-project-select");
        if (select) {
            select.addEventListener("change", function () {
                batchProjectTargetId = select.value ? parseInt(select.value, 10) : null;
                updateBatchSaveButtonState();
            });
        }
    }

    // ====================================================================
    // Phase 3B.7: Timeline batch note editing foundation
    // ====================================================================
    //
    // This is the second batch write capability in the WebView Timeline. It
    // overwrites the note on multiple closed, non-hidden, non-deleted
    // activities with the same note value in a single atomic transaction
    // (the bridge -> API -> service path uses a rowcount guard + rollback
    // so no partial write is ever persisted).
    //
    // Scope boundaries (enforced by the backend, mirrored here):
    // - Only note overwrite. No batch note append / merge, no batch hide /
    //   delete / time / split / merge / undo / restore / permanent delete /
    //   auto-rule / overlap.
    // - Only closed activities (end_time IS NOT NULL). In-progress rows
    //   render a disabled checkbox.
    // - Only activities in the current shell session. Stale ids that
    //   disappear after a refresh are pruned automatically.
    // - Empty note is allowed and is used to batch-clear notes.
    // - Only activity_log.note and updated_at are modified (source is not
    //   changed, unlike single-activity note editing).
    // - No browser storage. Note text lives in memory only.
    // - Reuses selectedBatchActivityIds from the batch project section so
    //   the user selects activities once and picks the write action.

    function resetBatchNoteState() {
        batchNoteSaving = false;
        var noteText = document.getElementById("correction-shell-batch-note-text");
        if (noteText) {
            noteText.value = "";
            noteText.disabled = true;
        }
        var saveBtn = document.getElementById("correction-shell-batch-note-save-btn");
        if (saveBtn) saveBtn.disabled = true;
        var countEl = document.getElementById("correction-shell-batch-note-count");
        if (countEl) {
            countEl.textContent = "0 / " + NOTE_MAX_LENGTH;
            countEl.classList.remove("edit-note-count-over");
        }
        showBatchNoteStatus("", false);
    }

    function updateBatchNoteCount() {
        var noteEl = document.getElementById("correction-shell-batch-note-text");
        var countEl = document.getElementById("correction-shell-batch-note-count");
        if (!noteEl || !countEl) return;
        var len = (noteEl.value || "").length;
        countEl.textContent = len + " / " + NOTE_MAX_LENGTH;
        if (len > NOTE_MAX_LENGTH) {
            countEl.classList.add("edit-note-count-over");
        } else {
            countEl.classList.remove("edit-note-count-over");
        }
        // Re-apply the save button gating so the user gets immediate
        // feedback when the note exceeds the limit.
        if (!batchNoteSaving) {
            updateBatchNoteSaveButtonState();
        }
    }

    function updateBatchNoteSaveButtonState() {
        var saveBtn = document.getElementById("correction-shell-batch-note-save-btn");
        if (!saveBtn) return;
        var count = Object.keys(selectedBatchActivityIds).length;
        var noteEl = document.getElementById("correction-shell-batch-note-text");
        var overLimit = false;
        if (noteEl) {
            overLimit = (noteEl.value || "").length > NOTE_MAX_LENGTH;
        }
        saveBtn.disabled = batchNoteSaving || batchProjectSaving || count < 2 || overLimit;
    }

    function setBatchNoteSaving(saving) {
        batchNoteSaving = saving;
        var saveBtn = document.getElementById("correction-shell-batch-note-save-btn");
        var noteText = document.getElementById("correction-shell-batch-note-text");
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "保存中…" : "批量覆盖备注";
        }
        if (noteText) noteText.disabled = saving || batchProjectSaving;
        // Disable / re-enable every batch checkbox so the user cannot
        // change selection while a note save is in flight.
        var checkboxes = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]"
        );
        for (var i = 0; i < checkboxes.length; i++) {
            var eligible = checkboxes[i].hasAttribute("data-batch-activity-id");
            if (eligible) {
                checkboxes[i].disabled = saving || batchProjectSaving;
            }
        }
        // Also keep the batch project controls in sync so the user cannot
        // start a competing project save while a note save is in flight.
        var projectSaveBtn = document.getElementById("correction-shell-batch-save-btn");
        var selectAllBtn = document.getElementById("correction-shell-batch-select-all-btn");
        var clearBtn = document.getElementById("correction-shell-batch-clear-btn");
        var projectSelect = document.getElementById("correction-shell-batch-project-select");
        if (projectSaveBtn) projectSaveBtn.disabled = saving || batchProjectSaving;
        if (selectAllBtn) selectAllBtn.disabled = saving || batchProjectSaving;
        if (clearBtn) clearBtn.disabled = saving || batchProjectSaving;
        if (projectSelect) projectSelect.disabled = saving || batchProjectSaving;
        if (!saving) {
            updateBatchNoteSaveButtonState();
            updateBatchSaveButtonState();
        }
    }

    function showBatchNoteStatus(message, isError) {
        var statusEl = document.getElementById("correction-shell-batch-note-status");
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

    // Render the batch note section. The section is always present in the
    // HTML; this function enables the textarea and refreshes the count /
    // save button state. The section is shown whenever the shell is open
    // and reuses the same selectedBatchActivityIds selection.
    function renderBatchNoteSection(session, activities) {
        var section = document.getElementById("correction-shell-batch-note-section");
        if (!section) return;
        section.hidden = false;
        // The textarea is enabled when the shell is open and no save is in
        // flight. pruneStaleBatchSelection (called by renderBatchProjectSection)
        // already keeps the selection in sync with the rendered activities.
        var noteText = document.getElementById("correction-shell-batch-note-text");
        if (noteText) {
            noteText.disabled = batchNoteSaving || batchProjectSaving;
        }
        updateBatchNoteCount();
        updateBatchNoteSaveButtonState();
        // Phase 3B.9.1: do not clear the status area while a save is in
        // flight. The save success / failure handler owns the status during
        // saving; an auto-refresh re-render must not wipe a just-shown
        // error or success message.
        if (!batchNoteSaving) {
            showBatchNoteStatus("", false);
        }
    }

    function saveBatchNote() {
        if (batchNoteSaving) return;
        // Block the batch save while there are unsaved per-session edits so
        // the two write paths never race on the same session.
        if (isEditDirty()) {
            showBatchNoteStatus("请先保存或取消当前编辑", true);
            return;
        }
        // Phase 3B.9 / 3B.9.1: cross-save guard. A batch note save triggers
        // a Timeline refresh which would race with an in-flight batch
        // project save or single restore. Refuse with the unified message
        // instead of calling the bridge.
        if (batchProjectSaving || restoreSaving) {
            showBatchNoteStatus("请等待当前操作完成", true);
            return;
        }
        var selectedIds = Object.keys(selectedBatchActivityIds);
        if (selectedIds.length < 2) {
            showBatchNoteStatus("请选择至少两个活动", true);
            return;
        }
        var noteEl = document.getElementById("correction-shell-batch-note-text");
        if (!noteEl) {
            showBatchNoteStatus("操作失败", true);
            return;
        }
        var note = noteEl.value || "";
        if (typeof note !== "string") {
            showBatchNoteStatus("请输入有效备注", true);
            return;
        }
        if (note.length > NOTE_MAX_LENGTH) {
            showBatchNoteStatus("备注过长", true);
            return;
        }
        // Re-check every selected id is still present in the currently
        // rendered shell activity rows. Stale ids (e.g. an auto-refresh
        // removed a row between the user checking the box and clicking
        // save) are dropped silently; if fewer than 2 remain we abort with
        // a clear message instead of calling the bridge.
        var renderedIds = {};
        var rows = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]:not([disabled])"
        );
        for (var i = 0; i < rows.length; i++) {
            var aid = rows[i].getAttribute("data-batch-activity-id");
            if (aid) renderedIds[aid] = true;
        }
        var cleanIds = [];
        for (var j = 0; j < selectedIds.length; j++) {
            if (renderedIds[selectedIds[j]]) {
                cleanIds.push(parseInt(selectedIds[j], 10));
            }
        }
        if (cleanIds.length < 2) {
            // Update the in-memory selection to match the rendered rows so
            // the count display stays accurate, then abort.
            selectedBatchActivityIds = {};
            for (var k in renderedIds) {
                if (renderedIds.hasOwnProperty(k)) selectedBatchActivityIds[k] = true;
            }
            updateBatchSelectionCount();
            updateBatchNoteSaveButtonState();
            showBatchNoteStatus("所选活动已失效，请重新选择", true);
            return;
        }
        setBatchNoteSaving(true);
        showBatchNoteStatus("", false);
        callBridge("batch_update_timeline_activities_note", cleanIds, note).then(function (result) {
            setBatchNoteSaving(false);
            if (!result || result.ok === false) {
                // Keep the selection / detail list / note textarea so the
                // user can retry. The bridge returns a stable Chinese error
                // message; we surface it verbatim without echoing internal
                // error detail.
                var msg = (result && result.error) ? result.error : "操作失败";
                showBatchNoteStatus(msg, true);
                return;
            }
            // Success: clear selection, clear the note textarea, refresh
            // Timeline, keep the shell context if the session is still
            // present.
            var updatedCount = result.updated_count || cleanIds.length;
            showBatchNoteStatus("已批量更新备注（共 " + updatedCount + " 条）", false);
            selectedBatchActivityIds = {};
            if (noteEl) noteEl.value = "";
            updateBatchSelectionCount();
            updateBatchNoteCount();
            updateBatchNoteSaveButtonState();
            updateBatchSaveButtonState();
            // Refresh the Timeline so the new note is reflected in the
            // sessions list and the detail list. The shell will re-render
            // from the refreshed data if the session is still present; if
            // the session disappeared (e.g. it was re-grouped), the
            // auto-refresh / disappear path will close the shell safely.
            refreshTimelineForBatchSave();
        }).catch(function () {
            setBatchNoteSaving(false);
            showBatchNoteStatus("操作失败", true);
        });
    }

    // Bind the batch note section controls. Called once during init.
    function bindBatchNoteControls() {
        var saveBtn = document.getElementById("correction-shell-batch-note-save-btn");
        if (saveBtn) {
            saveBtn.addEventListener("click", saveBatchNote);
        }
        var noteText = document.getElementById("correction-shell-batch-note-text");
        if (noteText) {
            noteText.addEventListener("input", updateBatchNoteCount);
        }
    }

    // ====================================================================
    // Phase 3B.8: Timeline single activity restore foundation
    // ====================================================================
    //
    // This is the single activity restore capability in the WebView
    // Timeline. It allows the user to restore a single hidden or
    // soft-deleted activity by setting is_hidden = 0 and is_deleted = 0 in
    // a single atomic UPDATE (the bridge -> API -> service path uses a
    // rowcount guard so no partial write is ever persisted).
    //
    // Scope boundaries (enforced by the backend, mirrored here):
    // - Only single activity restore. No batch restore, undo stack,
    //   permanent delete, or any new DB schema.
    // - Only closed activities (end_time IS NOT NULL). In-progress rows
    //   are excluded from the recovery list by the service.
    // - Only activities in the current Timeline date. The recovery list
    //   is a read-only, display-safe summary.
    // - Only is_hidden, is_deleted, and updated_at are modified; no other
    //   fields, resource rows, assignment rows, or session notes are
    //   touched.
    // - No browser storage. Restore state lives in memory only.

    function resetRestoreState() {
        restoreSaving = false;
        restoreSavingActivityId = null;
        var listEl = document.getElementById("correction-shell-restore-list");
        if (listEl) listEl.innerHTML = "";
        showRestoreStatus("", false);
    }

    function showRestoreStatus(message, isError) {
        var statusEl = document.getElementById("correction-shell-restore-status");
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

    function setRestoreSaving(saving, activityId) {
        restoreSaving = saving;
        restoreSavingActivityId = saving ? activityId : null;
        // Disable / re-enable every restore button so the user cannot
        // start a competing restore while one is in flight.
        var buttons = document.querySelectorAll(
            "#correction-shell-restore-list .correction-shell-restore-btn"
        );
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].disabled = saving;
        }
        // Add a visual saving indicator to the row whose restore is in
        // flight.
        var rows = document.querySelectorAll(
            "#correction-shell-restore-list .correction-shell-restore-row"
        );
        for (var j = 0; j < rows.length; j++) {
            var rowAid = rows[j].getAttribute("data-activity-id");
            if (saving && rowAid === String(activityId)) {
                rows[j].classList.add("restore-saving");
            } else {
                rows[j].classList.remove("restore-saving");
            }
        }
    }

    // Render the restore section. The section is always present in the
    // HTML; this function shows it and triggers loading of the restorable
    // activities for the current Timeline date. If a restore is in
    // flight, the list is not reloaded (the in-flight save must complete
    // first).
    function renderRestoreSection(session, activities) {
        var section = document.getElementById("correction-shell-restore-section");
        if (!section) return;
        section.hidden = false;
        // Do not reload the list while a restore save is in flight; the
        // success / failure handler will trigger a reload after the save
        // completes.
        if (restoreSaving) return;
        var dateEl = document.getElementById("timeline-date-display");
        var date = timelineDate || (dateEl ? dateEl.textContent : null);
        if (date === "--") date = null;
        loadRestorableActivities(date);
    }

    function loadRestorableActivities(date) {
        var listEl = document.getElementById("correction-shell-restore-list");
        if (!listEl) return;
        // Show a loading placeholder while the list loads.
        listEl.innerHTML = '<div class="correction-shell-restore-loading">加载中…</div>';
        showRestoreStatus("", false);
        callBridge("get_timeline_restorable_activities", date).then(function (result) {
            if (!result || result.ok === false) {
                // Keep the list empty; surface the bridge error.
                listEl.innerHTML = "";
                var msg = (result && result.error) ? result.error : "加载可恢复记录失败";
                showRestoreStatus(msg, true);
                return;
            }
            var activities = (result && result.activities) || [];
            renderRestorableActivities(activities);
            showRestoreStatus("", false);
        }).catch(function () {
            listEl.innerHTML = "";
            showRestoreStatus("加载可恢复记录失败", true);
        });
    }

    function renderRestorableActivities(activities) {
        var listEl = document.getElementById("correction-shell-restore-list");
        if (!listEl) return;
        listEl.innerHTML = "";
        if (!activities || activities.length === 0) {
            // The CSS :empty::after rule shows "暂无可恢复记录".
            return;
        }
        for (var i = 0; i < activities.length; i++) {
            var a = activities[i];
            var aid = String(a.activity_id || "");
            // Phase 3B.9: every dynamic value passes through safeText so the
            // restore list never renders "undefined" / "null". Only display-
            // safe fields (activity_id, time range, app_name, resource_type,
            // resource_name, project_name, duration, restore_state) are used;
            // raw sensitive backend columns (titles, paths, copy buffers,
            // note internals) are never read.
            var startTime = safeText(a.start_time, "");
            var endTime = safeText(a.end_time, "");
            var timeRange = safeText(formatTimeRange(startTime, endTime, false), "");
            var duration = safeText(a.duration, "");
            var appName = safeText(a.app_name, "");
            var resourceType = safeText(a.resource_type, "");
            var resourceName = safeText(a.resource_name, "");
            var projectName = safeText(a.project_name, "未归类");
            var restoreState = safeText(a.restore_state, "");
            // Badge text and class based on restore_state.
            var badgeText = "";
            var badgeClass = "correction-shell-restore-badge";
            if (restoreState === "hidden") {
                badgeText = "已隐藏";
            } else if (restoreState === "deleted") {
                badgeText = "已删除";
                badgeClass += " is-deleted";
            } else if (restoreState === "hidden+deleted") {
                badgeText = "已隐藏且已删除";
                badgeClass += " is-hidden-deleted";
            }
            // Build the meta line: app · resource_type · resource_name · project
            var metaParts = [];
            if (appName) metaParts.push(escapeHtml(appName));
            if (resourceType) metaParts.push(escapeHtml(resourceType));
            if (resourceName) metaParts.push(escapeHtml(resourceName));
            if (projectName) metaParts.push(escapeHtml(projectName));
            var metaLine = metaParts.join(" · ");

            var row = document.createElement("div");
            row.className = "correction-shell-restore-row";
            row.setAttribute("data-activity-id", aid);

            var info = document.createElement("div");
            info.className = "correction-shell-restore-info";

            var timeEl = document.createElement("div");
            timeEl.className = "correction-shell-restore-time";
            timeEl.textContent = timeRange + (duration ? "  ·  " + duration : "");

            var metaEl = document.createElement("div");
            metaEl.className = "correction-shell-restore-meta";
            if (badgeText) {
                var badge = document.createElement("span");
                badge.className = badgeClass;
                badge.textContent = badgeText;
                metaEl.appendChild(badge);
            }
            var metaText = document.createElement("span");
            metaText.textContent = metaLine;
            metaEl.appendChild(metaText);

            info.appendChild(timeEl);
            info.appendChild(metaEl);

            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "edit-btn correction-shell-restore-btn";
            btn.textContent = "恢复";
            btn.setAttribute("data-restore-activity-id", aid);
            btn.disabled = restoreSaving;

            row.appendChild(info);
            row.appendChild(btn);
            listEl.appendChild(row);
        }
    }

    function saveActivityRestore(activityId, btn) {
        if (restoreSaving) return;
        if (!activityId) {
            showRestoreStatus("请选择有效的活动", true);
            return;
        }
        // Phase 3B.8.1: confirm the activity id still exists in the
        // current restore list. If the list was reloaded (e.g. by an
        // auto-refresh) and the activity is no longer present, surface a
        // safe message and do not call the bridge. This guards against a
        // stale row whose state may have already changed.
        var listEl = document.getElementById("correction-shell-restore-list");
        if (listEl) {
            var staleRow = listEl.querySelector(
                '.correction-shell-restore-row[data-activity-id="'
                + String(activityId) + '"]'
            );
            if (!staleRow) {
                showRestoreStatus("该活动已不在可恢复列表中，请刷新后重试", true);
                return;
            }
        }
        // Guard against unsaved edits: restore is an immediate action that
        // triggers a refresh, which would wipe unsaved project/note/time/
        // split inputs. Require the user to save or cancel first.
        if (isEditDirty()) {
            showRestoreStatus("请先保存或取消当前编辑", true);
            return;
        }
        // Phase 3B.9: cross-save guard. A restore triggers a Timeline refresh
        // which would race with an in-flight batch project / batch note save.
        // Refuse with the unified message instead of calling the bridge.
        if (batchProjectSaving || batchNoteSaving) {
            showRestoreStatus("请等待当前操作完成", true);
            return;
        }
        setRestoreSaving(true, activityId);
        showRestoreStatus("", false);
        callBridge("restore_timeline_activity", activityId).then(function (result) {
            if (!result || result.ok === false) {
                setRestoreSaving(false, null);
                var msg = (result && result.error) ? result.error : "恢复失败";
                showRestoreStatus(msg, true);
                return;
            }
            setRestoreSaving(false, null);
            showRestoreStatus("已恢复", false);
            // Refresh the Timeline so the restored activity reappears in
            // the sessions list and the detail list. The shell will
            // re-render from the refreshed data (which also reloads the
            // recovery list) if the session is still present; if the
            // session disappeared, the auto-refresh / disappear path will
            // close the shell safely.
            refreshTimelineAfterEdit();
        }).catch(function () {
            setRestoreSaving(false, null);
            showRestoreStatus("恢复失败", true);
        });
    }

    // Bind the restore section controls via event delegation. Called once
    // during init. The restore buttons are rendered dynamically, so event
    // delegation on the list container avoids re-binding on every render.
    function bindRestoreControls() {
        var listEl = document.getElementById("correction-shell-restore-list");
        if (listEl) {
            listEl.addEventListener("click", function (ev) {
                var target = ev.target;
                if (!target) return;
                if (!target.classList.contains("correction-shell-restore-btn")) return;
                if (target.disabled) return;
                var aid = target.getAttribute("data-restore-activity-id");
                if (!aid) return;
                saveActivityRestore(parseInt(aid, 10), target);
            });
        }
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
                showTimelineError(msg || "刷新失败");
            });
            if (!data) return;
            showTimeline(data);
            clearTimelineError();
        }).catch(function () {
            if (token !== timelineRequestToken) return;
            // Phase 3C.1: use the stable "刷新失败" fallback.
            showTimelineError("刷新失败");
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
                showTimelineError(msg || "加载时间线失败");
            });
            setTimelineLoading(false);
            if (!data) return;
            timelineLoaded = true;
            showTimeline(data);
        }).catch(function () {
            if (token !== timelineRequestToken) return;  // stale response
            setTimelineLoading(false);
            // Phase 3C.1: never surface raw exception text; use the stable
            // fallback so internal details do not leak into the UI.
            showTimelineError("加载时间线失败");
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
                showTimelineError(msg || "刷新失败");
            });
            if (!data) return;
            showTimeline(data);
            clearTimelineError();
        }).catch(function () {
            if (token !== timelineRequestToken) return;  // stale response
            // Only show error banner; keep lastTimelineData on screen.
            // Phase 3C.1: use the stable "刷新失败" fallback.
            showTimelineError("刷新失败");
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
        // Phase 3B.5B: close the correction shell on date switch so the
        // shell context does not carry over to a different day.
        resetCorrectionShellState();
        loadTimeline(timelineDate);
    }

    function goNextDay() {
        var dateEl = document.getElementById("timeline-date-display");
        var current = timelineDate || (dateEl ? dateEl.textContent : null);
        timelineDate = shiftDate(current, 1);
        selectedSessionId = null;
        // Phase 3B.5B: close the correction shell on date switch.
        resetCorrectionShellState();
        loadTimeline(timelineDate);
    }

    function goToday() {
        timelineDate = null;
        selectedSessionId = null;
        // Phase 3B.5B: close the correction shell on date switch.
        resetCorrectionShellState();
        loadTimeline(null);
    }

    // --- Phase 4A: Statistics / Export read-only page -------------------

    function localTodayStr() {
        var d = new Date();
        var y = d.getFullYear();
        var m = String(d.getMonth() + 1).padStart(2, "0");
        var day = String(d.getDate()).padStart(2, "0");
        return y + "-" + m + "-" + day;
    }

    function formatDuration(seconds) {
        var s = Math.max(0, parseInt(seconds, 10) || 0);
        var h = Math.floor(s / 3600);
        var rem = s % 3600;
        var m = Math.floor(rem / 60);
        var sec = rem % 60;
        function pad(n) { return n < 10 ? "0" + n : String(n); }
        return pad(h) + ":" + pad(m) + ":" + pad(sec);
    }

    function showStatisticsError(message) {
        var banner = document.getElementById("statistics-error");
        if (!banner) return;
        if (!message) {
            banner.hidden = true;
            banner.textContent = "加载统计失败";
            return;
        }
        banner.hidden = false;
        banner.textContent = message;
    }

    function clearStatisticsError() {
        showStatisticsError("");
    }

    function setStatisticsLoading(loading) {
        statisticsLoading = loading;
        var el = document.getElementById("statistics-loading");
        if (el) el.hidden = !loading;
        var btn = document.getElementById("statistics-load-btn");
        if (btn) btn.disabled = loading;
    }

    function loadStatisticsExportSummary() {
        // Phase 4A.1 hardening: refuse concurrent loads. The load button is
        // already disabled while loading, but this guard also covers any
        // programmatic trigger path (quick range buttons, lazy load).
        if (statisticsLoading) return;
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        var dateFrom = fromEl ? fromEl.value : "";
        var dateTo = toEl ? toEl.value : "";
        if (!dateFrom || !dateTo) {
            showStatisticsError("请选择有效日期");
            return;
        }
        // Phase 4A.1: client-side range pre-check so the user gets an
        // immediate clear message without a bridge round-trip. The bridge
        // and service still perform the canonical validation.
        var rangeMsg = validateStatisticsDateRange(dateFrom, dateTo);
        if (rangeMsg) {
            showStatisticsError(rangeMsg);
            return;
        }
        setStatisticsLoading(true);
        clearStatisticsError();
        var token = ++statisticsRequestToken;
        callBridge("get_statistics_export_summary", dateFrom, dateTo).then(function (result) {
            if (token !== statisticsRequestToken) return;  // stale response
            var data = handleResult(result, function (msg) {
                // Phase 4A: never surface raw exception text; the bridge
                // already collapsed to a stable Chinese message.
                showStatisticsError(msg || "加载统计失败");
            });
            setStatisticsLoading(false);
            if (!data) return;  // keep prior rendered data on error
            statisticsLoaded = true;
            showStatistics(data.summary);
            clearStatisticsError();
        }).catch(function () {
            if (token !== statisticsRequestToken) return;  // stale response
            setStatisticsLoading(false);
            // Keep prior data on screen; just surface the error.
            showStatisticsError("加载统计失败");
        });
    }

    function validateStatisticsDateRange(dateFrom, dateTo) {
        // Returns a Chinese error message string if the range is invalid,
        // or null if it passes the client-side pre-check.
        if (!dateFrom || !dateTo) return "请选择有效日期";
        var fromParts = dateFrom.split("-");
        var toParts = dateTo.split("-");
        if (fromParts.length !== 3 || toParts.length !== 3) return "请选择有效日期";
        var from = new Date(
            parseInt(fromParts[0], 10),
            parseInt(fromParts[1], 10) - 1,
            parseInt(fromParts[2], 10)
        );
        var to = new Date(
            parseInt(toParts[0], 10),
            parseInt(toParts[1], 10) - 1,
            parseInt(toParts[2], 10)
        );
        if (isNaN(from.getTime()) || isNaN(to.getTime())) return "请选择有效日期";
        if (from > to) return "请选择有效日期范围";
        // 31-day inclusive max (same as service STATISTICS_SUMMARY_MAX_RANGE_DAYS).
        var diffDays = Math.round((to - from) / (1000 * 60 * 60 * 24));
        if (diffDays > 30) return "日期范围过大";
        return null;
    }

    function showStatistics(summary) {
        if (!summary) return;
        document.getElementById("stats-total").textContent = summary.total_duration || "00:00:00";
        document.getElementById("stats-activity-count").textContent = String(summary.activity_count || 0);
        document.getElementById("stats-project-count").textContent = String(summary.project_count || 0);
        document.getElementById("stats-app-count").textContent = String(summary.app_count || 0);
        renderStatsTable("stats-by-project", "stats-empty-project", summary.by_project || []);
        renderStatsTable("stats-by-app", "stats-empty-app", summary.by_app || []);
        renderStatsTable("stats-by-status", "stats-empty-status", summary.by_status || []);
        renderExportPreview(summary.export_preview || {}, summary.date_from, summary.date_to);
    }

    function renderStatsTable(tbodyId, emptyId, groups) {
        var tbody = document.getElementById(tbodyId);
        var empty = document.getElementById(emptyId);
        if (!tbody) return;
        if (!groups || !groups.length) {
            tbody.innerHTML = "";
            if (empty) empty.hidden = false;
            return;
        }
        if (empty) empty.hidden = true;
        var html = "";
        for (var i = 0; i < groups.length; i++) {
            var g = groups[i];
            var name = safeText(g.display_name, "");
            var duration = safeText(g.duration, "00:00:00");
            var count = String(g.activity_count || 0);
            var pct = String(g.percentage || 0) + "%";
            html += '<tr class="stats-table-row">'
                + '<td class="stats-table-name" title="' + escapeHtml(name) + '">' + escapeHtml(name) + '</td>'
                + '<td class="stats-table-duration">' + escapeHtml(duration) + '</td>'
                + '<td class="stats-table-count">' + escapeHtml(count) + '</td>'
                + '<td class="stats-table-pct">' + escapeHtml(pct) + '</td>'
                + '</tr>';
        }
        tbody.innerHTML = html;
    }

    function renderExportPreview(preview, dateFrom, dateTo) {
        var rangeEl = document.getElementById("stats-export-range");
        var countEl = document.getElementById("stats-export-count");
        var durationEl = document.getElementById("stats-export-duration");
        var formatsEl = document.getElementById("stats-export-formats");
        if (rangeEl) rangeEl.textContent = escapeHtml(safeText(dateFrom, "") + " 至 " + safeText(dateTo, ""));
        if (countEl) countEl.textContent = String(preview.included_activity_count || 0);
        if (durationEl) durationEl.textContent = preview.included_duration || "00:00:00";
        if (formatsEl) {
            var formats = preview.available_formats || [];
            formatsEl.textContent = formats.length ? escapeHtml(formats.join("、")) : "--";
        }
    }

    function applyStatisticsQuickRange(type) {
        var today = localTodayStr();
        var from, to;
        if (type === "today") {
            from = today;
            to = today;
        } else if (type === "7d") {
            from = shiftDate(today, -6);
            to = today;
        } else if (type === "month") {
            var parts = today.split("-");
            from = parts[0] + "-" + parts[1] + "-01";
            to = today;
        } else {
            return;
        }
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        if (fromEl) fromEl.value = from;
        if (toEl) toEl.value = to;
        loadStatisticsExportSummary();
    }

    function initStatisticsDefaults() {
        var today = localTodayStr();
        var fromEl = document.getElementById("statistics-date-from");
        var toEl = document.getElementById("statistics-date-to");
        if (fromEl && !fromEl.value) fromEl.value = today;
        if (toEl && !toEl.value) toEl.value = today;
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
            // Phase 3C.1: never surface raw exception text; use the stable
            // fallback so internal details do not leak into the UI.
            showError("刷新失败");
            throw err;
        });

        var overviewPromise = callBridge("get_overview").then(function (result) {
            var overview = handleResult(result, function (msg) {
                throw new Error(msg);
            });
            showOverview(overview);
        }).catch(function (err) {
            // Phase 3C.1: never surface raw exception text; use the stable
            // fallback so internal details do not leak into the UI.
            showError("刷新失败");
            throw err;
        });

        var recentPromise = callBridge("get_recent_activities").then(function (result) {
            var recent = handleResult(result, function (msg) {
                throw new Error(msg);
            });
            showRecent(recent);
        }).catch(function (err) {
            // Phase 3C.1: never surface raw exception text; use the stable
            // fallback so internal details do not leak into the UI.
            showError("刷新失败");
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
                        showTimelineError(msg || "刷新失败");
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
                    // Phase 3C.1: use the stable "刷新失败" fallback.
                    showTimelineError("刷新失败");
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
        // Phase 4A: lazy-load Statistics / Export read-only summary when
        // navigating to the page for the first time. Defaults to today's
        // date range. No write / file / dialog action is triggered.
        if (pageId === "statistics" && !statisticsLoaded && !statisticsLoading) {
            initStatisticsDefaults();
            loadStatisticsExportSummary();
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
        // Phase 3B.5B: correction shell open / close handlers. The shell
        // only reads display-safe data and guides the user back to the
        // existing action buttons; no new write path is wired here.
        var shellOpenBtn = document.getElementById("open-correction-shell-btn");
        if (shellOpenBtn) {
            shellOpenBtn.addEventListener("click", function () {
                openCorrectionShell("session", null);
            });
        }
        var shellCloseBtn = document.getElementById("correction-shell-close-btn");
        if (shellCloseBtn) {
            shellCloseBtn.addEventListener("click", closeCorrectionShell);
        }
        // Phase 3B.6: batch project reassignment controls inside the
        // correction shell. The save button calls the bridge's
        // batch_update_timeline_activities_project method; the select-all /
        // clear buttons only manipulate in-memory selection state.
        bindBatchProjectControls();
        // Phase 3B.7: batch note overwrite controls inside the correction
        // shell. The save button calls the bridge's
        // batch_update_timeline_activities_note method; the textarea input
        // updates the count / save button state in-memory only.
        bindBatchNoteControls();
        // Phase 3B.8: single activity restore controls inside the correction
        // shell. The restore buttons are rendered dynamically, so event
        // delegation on the list container handles clicks without
        // re-binding on every render.
        bindRestoreControls();
        // Phase 4A: Statistics / Export read-only page controls. The load
        // button triggers a read-only bridge call; the quick-range buttons
        // only update the in-memory date inputs and re-trigger the read.
        // No export / file / dialog action is wired here.
        var statsLoadBtn = document.getElementById("statistics-load-btn");
        if (statsLoadBtn) {
            statsLoadBtn.addEventListener("click", loadStatisticsExportSummary);
        }
        var statsTodayBtn = document.getElementById("statistics-today-btn");
        if (statsTodayBtn) {
            statsTodayBtn.addEventListener("click", function () {
                applyStatisticsQuickRange("today");
            });
        }
        var stats7dBtn = document.getElementById("statistics-7d-btn");
        if (stats7dBtn) {
            stats7dBtn.addEventListener("click", function () {
                applyStatisticsQuickRange("7d");
            });
        }
        var statsMonthBtn = document.getElementById("statistics-month-btn");
        if (statsMonthBtn) {
            statsMonthBtn.addEventListener("click", function () {
                applyStatisticsQuickRange("month");
            });
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
