// WorkTrace WebView frontend — timeline correction module (Phase R2 split).
// Correction shell + batch project / batch note / single activity restore.
// Reuses display-safe fields only; never reads raw sensitive backend columns.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // --- Phase 3B.5B: Timeline correction shell helpers -----------------
    // The shell is a read-only context + navigation layout. It reuses the
    // existing edit panel / detail row controls; it does not introduce any
    // new write capability. Activity summaries are read from the already-
    // rendered detail rows (which contain only display-safe fields), so no
    // new bridge call and no new backend method are needed.

    function getSelectedSession() {
        if (!App.selectedSessionId) return null;
        for (var i = 0; i < App.currentSessions.length; i++) {
            if (App.currentSessions[i].session_id === App.selectedSessionId) {
                return App.currentSessions[i];
            }
        }
        return null;
    }
    App.getSelectedSession = getSelectedSession;

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
    App.getCurrentDetailActivities = getCurrentDetailActivities;

    // --- Phase 3B.9: correction shell consolidation helpers ------------
    // These helpers consolidate the cross-phase saving / status / display
    // logic so single / batch / restore sections share one source of truth.
    // No new write capability is introduced; the helpers only coordinate
    // existing state and DOM.

    // Cross-save guard: returns true when ANY correction-shell write is in
    // flight (batch project, batch note, or single restore). The existing
    // edit / time / split / merge / hide / delete saving states are owned
    // by clearEditPanel and are intentionally not consulted here; those
    // flows run inside the edit panel and have their own dirty guard.
    // Used by every correction-shell write path to refuse a competing
    // write with a unified "请等待当前操作完成" message instead of calling
    // the bridge.
    function isAnyCorrectionWriteSaving() {
        return !!(App.batchProjectSaving || App.batchNoteSaving || App.restoreSaving);
    }
    App.isAnyCorrectionWriteSaving = isAnyCorrectionWriteSaving;

    // Unified cross-save refusal helper. Surfaces the stable Chinese
    // message on the most specific open status area (batch project / batch
    // note / restore / shell) so the user sees the refusal where they
    // clicked. Does not call the bridge.
    function refuseCrossSaveStatus() {
        var msg = "请等待当前操作完成";
        if (App.restoreSaving) {
            showRestoreStatus(msg, true);
            return;
        }
        if (App.batchNoteSaving) {
            showBatchNoteStatus(msg, true);
            return;
        }
        if (App.batchProjectSaving) {
            showBatchProjectStatus(msg, true);
            return;
        }
        setCorrectionShellStatus(msg, true);
    }
    App.refuseCrossSaveStatus = refuseCrossSaveStatus;

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
    App.resetCorrectionActionStatus = resetCorrectionActionStatus;

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
    App.setCorrectionShellStatus = setCorrectionShellStatus;

    function resetCorrectionShellState() {
        App.correctionShellOpen = false;
        App.correctionShellSessionId = null;
        App.correctionShellActivityId = null;
        App.correctionShellMode = null;
        // Phase 3B.5B.1: cancel any pending highlight timer so a shell
        // close / reset never leaves a dangling timer that mutates a
        // detail row's class list after the shell is gone.
        if (App.correctionShellHighlightTimer !== null) {
            clearTimeout(App.correctionShellHighlightTimer);
            App.correctionShellHighlightTimer = null;
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
    App.resetCorrectionShellState = resetCorrectionShellState;

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
        var dateTxt = App.safeText(dateEl ? dateEl.textContent : "", "");
        var projectLabel = App.safeText(session.project_name, "未归类");
        if (session.project_description) {
            projectLabel += " (" + App.safeText(session.project_description, "") + ")";
        }
        var timeRange = App.safeText(App.formatTimeRange(session.start_time, session.end_time, session.is_in_progress), "");
        var statusTxt = App.safeText(session.status, "");
        var inProgressTxt = session.is_in_progress ? "进行中" : "已结束";
        if (subEl) {
            subEl.textContent = dateTxt + " ｜ " + timeRange + " ｜ " + projectLabel;
        }
        var ctxHtml = '<div class="correction-shell-context-row">'
            + '<span class="correction-shell-context-label">日期：</span>'
            + '<span class="correction-shell-context-value">' + App.escapeHtml(dateTxt) + '</span>'
            + '<span class="correction-shell-context-label">项目：</span>'
            + '<span class="correction-shell-context-value">' + App.escapeHtml(projectLabel) + '</span>'
            + '<span class="correction-shell-context-label">时段：</span>'
            + '<span class="correction-shell-context-value">' + App.escapeHtml(timeRange) + '</span>'
            + '<span class="correction-shell-context-label">时长：</span>'
            + '<span class="correction-shell-context-value">' + App.escapeHtml(App.safeText(session.duration, "")) + '</span>'
            + '<span class="correction-shell-context-label">活动数：</span>'
            + '<span class="correction-shell-context-value">' + App.escapeHtml(App.safeText(session.event_count, "0")) + '</span>'
            + '<span class="correction-shell-context-label">状态：</span>'
            + '<span class="correction-shell-context-value' + (session.is_in_progress ? " in-progress" : "") + '">' + App.escapeHtml(statusTxt || inProgressTxt) + '</span>'
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
                    if (batchEligible && App.selectedBatchActivityIds[numericId]) {
                        checkedAttr = " checked";
                    }
                    html += '<div class="' + cls + '"'
                        + (numericId ? ' data-correction-activity-id="' + App.escapeHtml(numericId) + '"' : '')
                        + '>'
                        + (batchEligible
                            ? '<input type="checkbox" class="correction-shell-activity-checkbox"'
                                + ' data-batch-activity-id="' + App.escapeHtml(numericId) + '"'
                                + (App.batchProjectSaving ? ' disabled' : '')
                                + checkedAttr + '>'
                            : '<input type="checkbox" class="correction-shell-activity-checkbox" disabled>')
                        + '<span class="correction-shell-activity-time">' + App.escapeHtml(App.safeText(a.time_range, "")) + '</span>'
                        + '<span class="correction-shell-activity-name" title="' + App.escapeHtml(App.safeText(a.resource_name, "")) + '">' + App.escapeHtml(App.safeText(a.resource_name, "")) + '</span>'
                        + '<span class="correction-shell-activity-duration">' + App.escapeHtml(App.safeText(a.duration, "")) + '</span>'
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
    App.renderCorrectionShell = renderCorrectionShell;

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
        if (App.correctionShellHighlightTimer !== null) {
            clearTimeout(App.correctionShellHighlightTimer);
            App.correctionShellHighlightTimer = null;
        }
        App.correctionShellHighlightTimer = setTimeout(function () {
            row.classList.remove("detail-item-highlight");
            App.correctionShellHighlightTimer = null;
        }, 1800);
        if (row.scrollIntoView) {
            row.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        setCorrectionShellStatus("", false);
    }
    App.highlightDetailRow = highlightDetailRow;

    function openCorrectionShell(mode, activityId) {
        // Refuse to open while there are unsaved edits so the shell does
        // not override in-progress inputs.
        if (App.isEditDirty()) {
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
        App.correctionShellOpen = true;
        App.correctionShellSessionId = session.session_id;
        App.correctionShellActivityId = effectiveMode === "activity" ? activityId : null;
        App.correctionShellMode = effectiveMode;

        var shell = document.getElementById("timeline-correction-shell");
        if (shell) shell.hidden = false;
        var detailsCol = document.querySelector(".timeline-details");
        if (detailsCol) detailsCol.classList.add("shell-open");

        renderCorrectionShell(
            session,
            getCurrentDetailActivities(),
            effectiveMode,
            App.correctionShellActivityId
        );
        // Phase 3B.9: clear every action status area on open so stale
        // messages from a previous shell session do not linger.
        resetCorrectionActionStatus();
    }
    App.openCorrectionShell = openCorrectionShell;

    function closeCorrectionShell() {
        // Closing the shell returns to the Timeline details / edit panel.
        // The selected session is intentionally preserved so the user
        // returns to the same context.
        var wasOpen = App.correctionShellOpen;
        resetCorrectionShellState();
        // selectedSessionId is intentionally NOT cleared here.
        if (wasOpen) {
            // Phase 3B.9: resetCorrectionShellState already clears the
            // shell-only status areas via the per-section reset helpers;
            // this extra clear is a no-op safety net.
            setCorrectionShellStatus("", false);
        }
    }
    App.closeCorrectionShell = closeCorrectionShell;

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
        App.selectedBatchActivityIds = {};
        App.batchProjectSaving = false;
        App.batchProjectTargetId = null;
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
    App.resetBatchProjectState = resetBatchProjectState;

    // Remove selected ids that are no longer present in the freshly rendered
    // activity list. Activities that disappeared (e.g. hidden / deleted by
    // another session, or grouped differently after an auto-refresh) are
    // silently dropped so the selection is always a subset of the current
    // shell activities.
    function pruneStaleBatchSelection(activities) {
        if (!activities) {
            App.selectedBatchActivityIds = {};
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
        var keys = Object.keys(App.selectedBatchActivityIds);
        for (var k = 0; k < keys.length; k++) {
            if (validIds[keys[k]]) {
                next[keys[k]] = true;
            } else {
                changed = true;
            }
        }
        if (changed) {
            App.selectedBatchActivityIds = next;
            updateBatchSelectionCount();
        }
    }
    App.pruneStaleBatchSelection = pruneStaleBatchSelection;

    function toggleBatchActivity(activityId, checked) {
        if (App.batchProjectSaving || App.batchNoteSaving) return;
        if (!activityId) return;
        var key = String(activityId);
        if (checked) {
            App.selectedBatchActivityIds[key] = true;
        } else {
            delete App.selectedBatchActivityIds[key];
        }
        updateBatchSelectionCount();
        updateBatchSaveButtonState();
        updateBatchNoteSaveButtonState();
    }
    App.toggleBatchActivity = toggleBatchActivity;

    function selectAllBatchActivities() {
        if (App.batchProjectSaving || App.batchNoteSaving) return;
        var rows = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]:not([disabled])"
        );
        for (var i = 0; i < rows.length; i++) {
            var aid = rows[i].getAttribute("data-batch-activity-id");
            if (aid) {
                App.selectedBatchActivityIds[aid] = true;
                rows[i].checked = true;
            }
        }
        updateBatchSelectionCount();
        updateBatchSaveButtonState();
        updateBatchNoteSaveButtonState();
    }
    App.selectAllBatchActivities = selectAllBatchActivities;

    function clearBatchSelection() {
        if (App.batchProjectSaving || App.batchNoteSaving) return;
        App.selectedBatchActivityIds = {};
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
    App.clearBatchSelection = clearBatchSelection;

    function updateBatchSelectionCount() {
        var countEl = document.getElementById("correction-shell-batch-count");
        if (!countEl) return;
        var count = Object.keys(App.selectedBatchActivityIds).length;
        countEl.textContent = "已选择 " + count + " 条";
    }
    App.updateBatchSelectionCount = updateBatchSelectionCount;

    function updateBatchSaveButtonState() {
        var saveBtn = document.getElementById("correction-shell-batch-save-btn");
        if (!saveBtn) return;
        var count = Object.keys(App.selectedBatchActivityIds).length;
        var select = document.getElementById("correction-shell-batch-project-select");
        var hasProject = !!(select && select.value);
        saveBtn.disabled = App.batchProjectSaving || count < 2 || !hasProject;
    }
    App.updateBatchSaveButtonState = updateBatchSaveButtonState;

    function setBatchProjectSaving(saving) {
        App.batchProjectSaving = saving;
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
        if (noteText) noteText.disabled = saving || App.batchNoteSaving;
        if (!saving) {
            // Re-apply the project/count-based gating after save ends.
            updateBatchSaveButtonState();
            updateBatchNoteSaveButtonState();
        }
    }
    App.setBatchProjectSaving = setBatchProjectSaving;

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
    App.showBatchProjectStatus = showBatchProjectStatus;

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
        if (select && !App.projectsCache) {
            select.innerHTML = '<option value="">加载中…</option>';
            select.disabled = true;
            App.loadProjects().then(function (projects) {
                populateBatchProjectSelect(projects);
            });
        } else if (select && App.projectsCache) {
            populateBatchProjectSelect(App.projectsCache);
        }
        updateBatchSelectionCount();
        updateBatchSaveButtonState();
        // Phase 3B.9.1: do not clear the status area while a save is in
        // flight. The save success / failure handler owns the status during
        // saving; an auto-refresh re-render must not wipe a just-shown
        // error or success message.
        if (!App.batchProjectSaving) {
            showBatchProjectStatus("", false);
        }
    }
    App.renderBatchProjectSection = renderBatchProjectSection;

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
        if (App.batchProjectTargetId) {
            select.value = String(App.batchProjectTargetId);
        }
        select.disabled = App.batchProjectSaving;
    }
    App.populateBatchProjectSelect = populateBatchProjectSelect;

    function saveBatchProject() {
        if (App.batchProjectSaving) return;
        // Block the batch save while there are unsaved per-session edits so
        // the two write paths never race on the same session.
        if (App.isEditDirty()) {
            showBatchProjectStatus("请先保存或取消当前编辑", true);
            return;
        }
        // Phase 3B.9: cross-save guard. A batch project save triggers a
        // Timeline refresh which would race with an in-flight batch note
        // save or single restore. Refuse with the unified message instead
        // of calling the bridge.
        if (App.batchNoteSaving || App.restoreSaving) {
            showBatchProjectStatus("请等待当前操作完成", true);
            return;
        }
        var selectedIds = Object.keys(App.selectedBatchActivityIds);
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
            App.selectedBatchActivityIds = {};
            for (var k in renderedIds) {
                if (renderedIds.hasOwnProperty(k)) App.selectedBatchActivityIds[k] = true;
            }
            updateBatchSelectionCount();
            updateBatchSaveButtonState();
            showBatchProjectStatus("所选活动已失效，请重新选择", true);
            return;
        }
        App.batchProjectTargetId = projectId;
        setBatchProjectSaving(true);
        showBatchProjectStatus("", false);
        App.callBridge("batch_update_timeline_activities_project", cleanIds, projectId).then(function (result) {
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
            App.selectedBatchActivityIds = {};
            App.batchProjectTargetId = null;
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
    App.saveBatchProject = saveBatchProject;

    // Refresh the Timeline data after a successful batch save. We reuse the
    // existing loadTimeline path so the sessions list, detail list, and
    // edit panel are all rebuilt from the fresh backend state. If the
    // shell's session is still present after the refresh, the shell is
    // re-rendered with the updated activity list; otherwise the shell is
    // closed safely.
    function refreshTimelineForBatchSave() {
        var dateEl = document.getElementById("timeline-date-display");
        var date = App.timelineDate || (dateEl ? dateEl.textContent : null);
        // Defer the shell re-render to after the timeline reloads; the
        // loadTimeline path's auto-refresh branch already re-renders the
        // shell if it is still open for the refreshed session.
        App.loadTimeline(date);
    }
    App.refreshTimelineForBatchSave = refreshTimelineForBatchSave;

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
                App.batchProjectTargetId = select.value ? parseInt(select.value, 10) : null;
                updateBatchSaveButtonState();
            });
        }
    }
    App.bindBatchProjectControls = bindBatchProjectControls;

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
        App.batchNoteSaving = false;
        var noteText = document.getElementById("correction-shell-batch-note-text");
        if (noteText) {
            noteText.value = "";
            noteText.disabled = true;
        }
        var saveBtn = document.getElementById("correction-shell-batch-note-save-btn");
        if (saveBtn) saveBtn.disabled = true;
        var countEl = document.getElementById("correction-shell-batch-note-count");
        if (countEl) {
            countEl.textContent = "0 / " + App.NOTE_MAX_LENGTH;
            countEl.classList.remove("edit-note-count-over");
        }
        showBatchNoteStatus("", false);
    }
    App.resetBatchNoteState = resetBatchNoteState;

    function updateBatchNoteCount() {
        var noteEl = document.getElementById("correction-shell-batch-note-text");
        var countEl = document.getElementById("correction-shell-batch-note-count");
        if (!noteEl || !countEl) return;
        var len = (noteEl.value || "").length;
        countEl.textContent = len + " / " + App.NOTE_MAX_LENGTH;
        if (len > App.NOTE_MAX_LENGTH) {
            countEl.classList.add("edit-note-count-over");
        } else {
            countEl.classList.remove("edit-note-count-over");
        }
        // Re-apply the save button gating so the user gets immediate
        // feedback when the note exceeds the limit.
        if (!App.batchNoteSaving) {
            updateBatchNoteSaveButtonState();
        }
    }
    App.updateBatchNoteCount = updateBatchNoteCount;

    function updateBatchNoteSaveButtonState() {
        var saveBtn = document.getElementById("correction-shell-batch-note-save-btn");
        if (!saveBtn) return;
        var count = Object.keys(App.selectedBatchActivityIds).length;
        var noteEl = document.getElementById("correction-shell-batch-note-text");
        var overLimit = false;
        if (noteEl) {
            overLimit = (noteEl.value || "").length > App.NOTE_MAX_LENGTH;
        }
        saveBtn.disabled = App.batchNoteSaving || App.batchProjectSaving || count < 2 || overLimit;
    }
    App.updateBatchNoteSaveButtonState = updateBatchNoteSaveButtonState;

    function setBatchNoteSaving(saving) {
        App.batchNoteSaving = saving;
        var saveBtn = document.getElementById("correction-shell-batch-note-save-btn");
        var noteText = document.getElementById("correction-shell-batch-note-text");
        if (saveBtn) {
            saveBtn.disabled = saving;
            saveBtn.textContent = saving ? "保存中…" : "批量覆盖备注";
        }
        if (noteText) noteText.disabled = saving || App.batchProjectSaving;
        // Disable / re-enable every batch checkbox so the user cannot
        // change selection while a note save is in flight.
        var checkboxes = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]"
        );
        for (var i = 0; i < checkboxes.length; i++) {
            var eligible = checkboxes[i].hasAttribute("data-batch-activity-id");
            if (eligible) {
                checkboxes[i].disabled = saving || App.batchProjectSaving;
            }
        }
        // Also keep the batch project controls in sync so the user cannot
        // start a competing project save while a note save is in flight.
        var projectSaveBtn = document.getElementById("correction-shell-batch-save-btn");
        var selectAllBtn = document.getElementById("correction-shell-batch-select-all-btn");
        var clearBtn = document.getElementById("correction-shell-batch-clear-btn");
        var projectSelect = document.getElementById("correction-shell-batch-project-select");
        if (projectSaveBtn) projectSaveBtn.disabled = saving || App.batchProjectSaving;
        if (selectAllBtn) selectAllBtn.disabled = saving || App.batchProjectSaving;
        if (clearBtn) clearBtn.disabled = saving || App.batchProjectSaving;
        if (projectSelect) projectSelect.disabled = saving || App.batchProjectSaving;
        if (!saving) {
            updateBatchNoteSaveButtonState();
            updateBatchSaveButtonState();
        }
    }
    App.setBatchNoteSaving = setBatchNoteSaving;

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
    App.showBatchNoteStatus = showBatchNoteStatus;

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
            noteText.disabled = App.batchNoteSaving || App.batchProjectSaving;
        }
        updateBatchNoteCount();
        updateBatchNoteSaveButtonState();
        // Phase 3B.9.1: do not clear the status area while a save is in
        // flight. The save success / failure handler owns the status during
        // saving; an auto-refresh re-render must not wipe a just-shown
        // error or success message.
        if (!App.batchNoteSaving) {
            showBatchNoteStatus("", false);
        }
    }
    App.renderBatchNoteSection = renderBatchNoteSection;

    function saveBatchNote() {
        if (App.batchNoteSaving) return;
        // Block the batch save while there are unsaved per-session edits so
        // the two write paths never race on the same session.
        if (App.isEditDirty()) {
            showBatchNoteStatus("请先保存或取消当前编辑", true);
            return;
        }
        // Phase 3B.9 / 3B.9.1: cross-save guard. A batch note save triggers
        // a Timeline refresh which would race with an in-flight batch
        // project save or single restore. Refuse with the unified message
        // instead of calling the bridge.
        if (App.batchProjectSaving || App.restoreSaving) {
            showBatchNoteStatus("请等待当前操作完成", true);
            return;
        }
        var selectedIds = Object.keys(App.selectedBatchActivityIds);
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
        if (note.length > App.NOTE_MAX_LENGTH) {
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
            App.selectedBatchActivityIds = {};
            for (var k in renderedIds) {
                if (renderedIds.hasOwnProperty(k)) App.selectedBatchActivityIds[k] = true;
            }
            updateBatchSelectionCount();
            updateBatchNoteSaveButtonState();
            showBatchNoteStatus("所选活动已失效，请重新选择", true);
            return;
        }
        setBatchNoteSaving(true);
        showBatchNoteStatus("", false);
        App.callBridge("batch_update_timeline_activities_note", cleanIds, note).then(function (result) {
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
            App.selectedBatchActivityIds = {};
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
    App.saveBatchNote = saveBatchNote;

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
    App.bindBatchNoteControls = bindBatchNoteControls;

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
        App.restoreSaving = false;
        App.restoreSavingActivityId = null;
        var listEl = document.getElementById("correction-shell-restore-list");
        if (listEl) listEl.innerHTML = "";
        showRestoreStatus("", false);
    }
    App.resetRestoreState = resetRestoreState;

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
    App.showRestoreStatus = showRestoreStatus;

    function setRestoreSaving(saving, activityId) {
        App.restoreSaving = saving;
        App.restoreSavingActivityId = saving ? activityId : null;
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
    App.setRestoreSaving = setRestoreSaving;

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
        if (App.restoreSaving) return;
        var dateEl = document.getElementById("timeline-date-display");
        var date = App.timelineDate || (dateEl ? dateEl.textContent : null);
        if (date === "--") date = null;
        loadRestorableActivities(date);
    }
    App.renderRestoreSection = renderRestoreSection;

    function loadRestorableActivities(date) {
        var listEl = document.getElementById("correction-shell-restore-list");
        if (!listEl) return;
        // Show a loading placeholder while the list loads.
        listEl.innerHTML = '<div class="correction-shell-restore-loading">加载中…</div>';
        showRestoreStatus("", false);
        App.callBridge("get_timeline_restorable_activities", date).then(function (result) {
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
    App.loadRestorableActivities = loadRestorableActivities;

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
            var startTime = App.safeText(a.start_time, "");
            var endTime = App.safeText(a.end_time, "");
            var timeRange = App.safeText(App.formatTimeRange(startTime, endTime, false), "");
            var duration = App.safeText(a.duration, "");
            var appName = App.safeText(a.app_name, "");
            var resourceType = App.safeText(a.resource_type, "");
            var resourceName = App.safeText(a.resource_name, "");
            var projectName = App.safeText(a.project_name, "未归类");
            var restoreState = App.safeText(a.restore_state, "");
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
            if (appName) metaParts.push(App.escapeHtml(appName));
            if (resourceType) metaParts.push(App.escapeHtml(resourceType));
            if (resourceName) metaParts.push(App.escapeHtml(resourceName));
            if (projectName) metaParts.push(App.escapeHtml(projectName));
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
            btn.disabled = App.restoreSaving;

            row.appendChild(info);
            row.appendChild(btn);
            listEl.appendChild(row);
        }
    }
    App.renderRestorableActivities = renderRestorableActivities;

    function saveActivityRestore(activityId, btn) {
        if (App.restoreSaving) return;
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
        if (App.isEditDirty()) {
            showRestoreStatus("请先保存或取消当前编辑", true);
            return;
        }
        // Phase 3B.9: cross-save guard. A restore triggers a Timeline refresh
        // which would race with an in-flight batch project / batch note save.
        // Refuse with the unified message instead of calling the bridge.
        if (App.batchProjectSaving || App.batchNoteSaving) {
            showRestoreStatus("请等待当前操作完成", true);
            return;
        }
        setRestoreSaving(true, activityId);
        showRestoreStatus("", false);
        App.callBridge("restore_timeline_activity", activityId).then(function (result) {
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
            App.refreshTimelineAfterEdit();
        }).catch(function () {
            setRestoreSaving(false, null);
            showRestoreStatus("恢复失败", true);
        });
    }
    App.saveActivityRestore = saveActivityRestore;

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
    App.bindRestoreControls = bindRestoreControls;

})();
