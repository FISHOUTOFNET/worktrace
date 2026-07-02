// WorkTrace WebView frontend — timeline correction module.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    // new write capability. Activity summaries are read from the already-

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

    // write capability is introduced; the helpers only coordinate existing

    function isAnyCorrectionWriteSaving() {
        return !!(App.batchProjectSaving || App.batchNoteSaving || App.restoreSaving);
    }
    App.isAnyCorrectionWriteSaving = isAnyCorrectionWriteSaving;

    // Unified cross-save refusal helper. Surfaces the stable Chinese
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

    // baseline. Used on shell open and on successful writes so stale
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
        if (App.correctionShellHighlightTimer !== null) {
            clearTimeout(App.correctionShellHighlightTimer);
            App.correctionShellHighlightTimer = null;
        }
        // Clear the batch project selection so a stale selection does not
        resetBatchProjectState();
        // Clear the batch note textarea / saving flag too so a stale note
        resetBatchNoteState();
        // Clear the restore list / saving flag too so a stale restore list
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

    // its own write buttons, so no new write path is introduced.
    function renderCorrectionShell(session, activities, mode, activityId) {
        var subEl = document.getElementById("correction-shell-subtitle");
        var ctxEl = document.getElementById("correction-shell-context");
        var actsEl = document.getElementById("correction-shell-activities");
        var actionsEl = document.getElementById("correction-shell-actions");
        if (!ctxEl || !session) return;

        // shell never reads / displays raw sensitive backend columns
        var dateEl = document.getElementById("timeline-date-input");
        var dateTxt = App.safeText(App.timelineDate || (dateEl ? dateEl.value : ""), "");
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

        if (actsEl) {
            if (!activities || activities.length === 0) {
                actsEl.innerHTML = '<div class="correction-shell-activities-title">活动明细</div>'
                    + '<div class="correction-shell-activities-empty">暂无活动详情，请在左侧活动详情中查看。</div>';
            } else {
                var html = '<div class="correction-shell-activities-title">活动明细（点击定位到对应活动）</div>';
                for (var i = 0; i < activities.length; i++) {
                    var a = activities[i];
                    var rawId = String(a.activity_id || "");
                    // non-clickable row so the user never gets a stale-target
                    var numericId = /^[0-9]+$/.test(rawId) ? rawId : "";
                    var cls = "correction-shell-activity-row";
                    if (!numericId) cls += " is-static";
                    if (mode === "activity" && activityId && rawId === String(activityId)) {
                        cls += " is-selected";
                    }
                    var isInProgress = !!a.is_in_progress;
                    if (isInProgress) cls += " is-in-progress";
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
                // Prune stale selected ids that no longer exist in the
                pruneStaleBatchSelection(activities);
                // matching detail row; it performs no write and calls no
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
                            if (event.stopPropagation) {
                                event.stopPropagation();
                            }
                        });
                    })(checkboxes[k]);
                }
            }
        }

        if (actionsEl) {
            var guidance = '<div class="correction-shell-actions-title">纠错操作</div>'
                + '<div class="correction-shell-actions-hint">'
                + '会话级操作（项目与备注 / 时间修正 / 拆分 / 可见性）请在上方“编辑当前时段”面板中执行；'
                + '单条活动操作（编辑时间 / 拆分 / 与下一条合并 / 隐藏 / 删除）请在左侧活动详情列表中对应行执行。'
                + ' <span class="danger-note">隐藏与删除为软操作，不会物理删除数据。</span>'
                + '</div>';
            actionsEl.innerHTML = guidance;
        }

        // project list (projectsCache) so no extra bridge call is needed
        renderBatchProjectSection(session, activities);
        // selectedBatchActivityIds selection. The user picks activities once
        renderBatchNoteSection(session, activities);
        renderRestoreSection(session, activities);
    }
    App.renderCorrectionShell = renderCorrectionShell;

    // the existing per-activity action buttons. No write is performed and
    function highlightDetailRow(activityId) {
        if (!activityId) return;
        var row = document.querySelector(
            '#timeline-details-list .detail-item[data-activity-id="' + activityId + '"]'
        );
        if (!row) {
            setCorrectionShellStatus("该活动已不在当前详情中，可能已刷新，请重试。", true);
            return;
        }
        var all = document.querySelectorAll("#timeline-details-list .detail-item");
        for (var i = 0; i < all.length; i++) {
            all[i].classList.remove("shell-target");
            all[i].classList.remove("detail-item-highlight");
        }
        row.classList.add("shell-target");
        // Brief transient highlight for immediate feedback. A single tracked
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
        if (App.isEditDirty()) {
            if (App.showEditStatus) App.showEditStatus("请先保存或取消当前编辑", true);
            return;
        }
        var session = getSelectedSession();
        if (!session) {
            if (App.showEditStatus) App.showEditStatus("请先选择左侧时段", true);
            return;
        }
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
                if (App.showEditStatus) App.showEditStatus("该活动已不存在，请刷新后重试", true);
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
        // Clear every action status area on open so stale messages from a
        resetCorrectionActionStatus();
        var titleEl = document.querySelector(".correction-shell-title");
        if (titleEl) {
            if (titleEl.scrollIntoView) {
                titleEl.scrollIntoView({ behavior: "smooth", block: "start" });
            }
            if (titleEl.focus) {
                titleEl.setAttribute("tabindex", "-1");
                titleEl.focus();
            }
        }
    }
    App.openCorrectionShell = openCorrectionShell;

    function closeCorrectionShell() {
        // selectedSessionId is preserved so the user returns to the same session.
        var wasOpen = App.correctionShellOpen;
        resetCorrectionShellState();
        if (wasOpen) {
            setCorrectionShellStatus("", false);
        }
    }
    App.closeCorrectionShell = closeCorrectionShell;

    // reclassify them to the same project in a single atomic transaction

    function resetBatchProjectState() {
        App.selectedBatchActivityIds = {};
        App.batchProjectSaving = false;
        App.batchProjectTargetId = null;
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
        var checkboxes = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]"
        );
        for (var i = 0; i < checkboxes.length; i++) {
            var eligible = checkboxes[i].hasAttribute("data-batch-activity-id");
            if (eligible) {
                checkboxes[i].disabled = saving;
            }
        }
        var noteText = document.getElementById("correction-shell-batch-note-text");
        if (noteText) noteText.disabled = saving || App.batchNoteSaving;
        if (!saving) {
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

    function renderBatchProjectSection(session, activities) {
        var section = document.getElementById("correction-shell-batch-project-section");
        if (!section) return;
        section.hidden = false;
        pruneStaleBatchSelection(activities);
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
        if (App.batchProjectTargetId) {
            select.value = String(App.batchProjectTargetId);
        }
        select.disabled = App.batchProjectSaving;
    }
    App.populateBatchProjectSelect = populateBatchProjectSelect;

    function saveBatchProject() {
        if (App.batchProjectSaving) return;
        // the two write paths never race on the same session.
        if (App.isEditDirty()) {
            showBatchProjectStatus("请先保存或取消当前编辑", true);
            return;
        }
        // which would race with an in-flight batch note save or single
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
        // rendered shell activity rows. Stale ids (e.g. an auto-refresh
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
                // The bridge returns a stable Chinese error message; we
                var msg = (result && result.error) ? result.error : "操作失败";
                showBatchProjectStatus(msg, true);
                return;
            }
            var updatedCount = result.updated_count || cleanIds.length;
            showBatchProjectStatus("已批量更新项目（共 " + updatedCount + " 条）", false);
            App.selectedBatchActivityIds = {};
            App.batchProjectTargetId = null;
            updateBatchSelectionCount();
            // re-grouped), the auto-refresh / disappear path will close
            refreshTimelineForBatchSave();
        }).catch(function () {
            setBatchProjectSaving(false);
            showBatchProjectStatus("操作失败", true);
        });
    }
    App.saveBatchProject = saveBatchProject;

    // existing loadTimeline path so the sessions list, detail list, and
    function refreshTimelineForBatchSave() {
        var dateEl = document.getElementById("timeline-date-input");
        var date = App.timelineDate || (dateEl ? dateEl.value : null);
        // loadTimeline path's auto-refresh branch already re-renders the
        App.loadTimeline(date);
    }
    App.refreshTimelineForBatchSave = refreshTimelineForBatchSave;

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

    // single atomic transaction (the bridge -> API -> service path uses a

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
        var checkboxes = document.querySelectorAll(
            "#correction-shell-activities .correction-shell-activity-checkbox[data-batch-activity-id]"
        );
        for (var i = 0; i < checkboxes.length; i++) {
            var eligible = checkboxes[i].hasAttribute("data-batch-activity-id");
            if (eligible) {
                checkboxes[i].disabled = saving || App.batchProjectSaving;
            }
        }
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

    // and reuses the same selectedBatchActivityIds selection.
    function renderBatchNoteSection(session, activities) {
        var section = document.getElementById("correction-shell-batch-note-section");
        if (!section) return;
        section.hidden = false;
        // flight. pruneStaleBatchSelection (called by renderBatchProjectSection)
        var noteText = document.getElementById("correction-shell-batch-note-text");
        if (noteText) {
            noteText.disabled = App.batchNoteSaving || App.batchProjectSaving;
        }
        updateBatchNoteCount();
        updateBatchNoteSaveButtonState();
        if (!App.batchNoteSaving) {
            showBatchNoteStatus("", false);
        }
    }
    App.renderBatchNoteSection = renderBatchNoteSection;

    function saveBatchNote() {
        if (App.batchNoteSaving) return;
        // the two write paths never race on the same session.
        if (App.isEditDirty()) {
            showBatchNoteStatus("请先保存或取消当前编辑", true);
            return;
        }
        // which would race with an in-flight batch project save or single
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
        // rendered shell activity rows. Stale ids (e.g. an auto-refresh
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
                // user can retry. The bridge returns a stable Chinese error
                var msg = (result && result.error) ? result.error : "操作失败";
                showBatchNoteStatus(msg, true);
                return;
            }
            var updatedCount = result.updated_count || cleanIds.length;
            showBatchNoteStatus("已批量更新备注（共 " + updatedCount + " 条）", false);
            App.selectedBatchActivityIds = {};
            if (noteEl) noteEl.value = "";
            updateBatchSelectionCount();
            updateBatchNoteCount();
            updateBatchNoteSaveButtonState();
            updateBatchSaveButtonState();
            // auto-refresh / disappear path will close the shell safely.
            refreshTimelineForBatchSave();
        }).catch(function () {
            setBatchNoteSaving(false);
            showBatchNoteStatus("操作失败", true);
        });
    }
    App.saveBatchNote = saveBatchNote;

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
        var buttons = document.querySelectorAll(
            "#correction-shell-restore-list .correction-shell-restore-btn"
        );
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].disabled = saving;
        }
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

    // flight, the list is not reloaded (the in-flight save must complete
    function renderRestoreSection(session, activities) {
        var section = document.getElementById("correction-shell-restore-section");
        if (!section) return;
        section.hidden = false;
        if (App.restoreSaving) return;
        var dateEl = document.getElementById("timeline-date-input");
        var date = App.timelineDate || (dateEl ? dateEl.value : null);
        if (date === "--" || date === "") date = null;
        loadRestorableActivities(date);
    }
    App.renderRestoreSection = renderRestoreSection;

    function loadRestorableActivities(date) {
        var listEl = document.getElementById("correction-shell-restore-list");
        if (!listEl) return;
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
            return;
        }
        for (var i = 0; i < activities.length; i++) {
            var a = activities[i];
            var aid = String(a.activity_id || "");
            // raw sensitive backend columns (titles, paths, copy buffers,
            var startTime = App.safeText(a.start_time, "");
            var endTime = App.safeText(a.end_time, "");
            var timeRange = App.safeText(App.formatTimeRange(startTime, endTime, false), "");
            var duration = App.safeText(a.duration, "");
            var appName = App.safeText(a.app_name, "");
            var resourceType = App.safeText(a.resource_type, "");
            var resourceName = App.safeText(a.resource_name, "");
            var projectName = App.safeText(a.project_name, "未归类");
            var restoreState = App.safeText(a.restore_state, "");
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
        // call the bridge. This guards against a stale row whose state may
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
        if (App.isEditDirty()) {
            showRestoreStatus("请先保存或取消当前编辑", true);
            return;
        }
        // would race with an in-flight batch project / batch note save.
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
            // session disappeared, the auto-refresh / disappear path will
            App.refreshTimelineAfterEdit();
        }).catch(function () {
            setRestoreSaving(false, null);
            showRestoreStatus("恢复失败", true);
        });
    }
    App.saveActivityRestore = saveActivityRestore;

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
