// WorkTrace WebView frontend — timeline editor state owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function findCachedProject(projectId) {
        var projects = App.projectCatalog ? App.projectCatalog.getEditing() : [];
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

    function setTimelineReadOnlyNotice(session) {
        var notice = document.getElementById("timeline-readonly-notice");
        if (!notice) return;
        notice.hidden = !(session && session.is_in_progress === true);
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
        var noteChanged = !!(
            noteAllowed
            && note
            && session
            && note.value !== String(session.session_note || "")
        );
        if (select) select.disabled = !projectAllowed || !App.projectCatalog || !App.projectCatalog.getEditing().length;
        if (note) note.disabled = !noteAllowed;
        if (duration) duration.disabled = !durationAllowed;
        if (cancel) cancel.disabled = App.editSaving || !session;
        if (save) {
            save.disabled = App.editSaving
                || !hasEditableFields(session)
                || (
                    noteChanged
                    && note.value.length
                    > App.TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH
                );
        }
        App.updateFDWorkEntryButton();
    }
    App.applyTimelineEditCapabilities = applyEditCapabilities;

    function populateEditPanel(session) {
        if (!session) {
            clearEditPanel();
            return;
        }
        App.editingSession = session;
        setTimelineReadOnlyNotice(null);
        var panel = document.getElementById("timeline-edit-panel");
        if (panel) panel.hidden = false;
        var select = document.getElementById("edit-project-select");
        if (select) {
            var cachedProjects = App.projectCatalog ? App.projectCatalog.getEditing() : [];
            if (cachedProjects.length > 0) {
                renderProjectSelect(cachedProjects, session.project_id);
            } else {
                select.innerHTML = '<option value="">加载中…</option>';
                select.disabled = true;
                App.loadTimelineProjects().then(function (projects) {
                    if (
                        App.editingSession
                        && App.editingSession.projection_instance_key === session.projection_instance_key
                    ) {
                        renderProjectSelect(projects, session.project_id);
                    }
                });
            }
        }
        var duration = document.getElementById("edit-duration-input");
        if (duration) {
            var source = session.adjusted_duration_seconds !== null
                && session.adjusted_duration_seconds !== undefined
                ? session.adjusted_duration_seconds
                : session.duration_seconds;
            var seconds = parseInt(source, 10);
            duration.value = isNaN(seconds)
                ? ""
                : (Math.max(0, seconds) / 3600).toFixed(1);
        }
        App.timelineDurationDraftTouched = false;
        App.timelineDurationDraftInvalid = false;
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
        if (App.timelineAutosaveTimer) window.clearTimeout(App.timelineAutosaveTimer);
        App.timelineAutosaveTimer = null;
        App.timelineAutosaveQueued = false;
        App.timelineCompositionActive = false;
        App.editingSession = null;
        App.editSaving = false;
        App.submittedDraft = null;
        App.timelineDurationDraftTouched = false;
        App.timelineDurationDraftInvalid = false;
        var panel = document.getElementById("timeline-edit-panel");
        if (panel) panel.hidden = true;
        setTimelineReadOnlyNotice(null);
        App.updateSessionActionButtons(null);
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
        App.showFDWorkStatus("", false);
        App.updateFDWorkEntryButton();
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
        if (
            canEditField(session, "can_edit_duration")
            && duration
            && App.timelineDurationDraftTouched === true
        ) {
            var durationText = (duration.value || "").trim();
            var existingOverride = session.has_duration_override === true
                ? parseInt(session.adjusted_duration_seconds, 10) : null;
            if (isNaN(existingOverride)) existingOverride = null;
            if (durationText === "") return existingOverride !== null;
            var normalized = normalizeTimelineDurationInput(durationText);
            if (!normalized.valid) return true;
            var adjustedSeconds = normalized.seconds;
            if (existingOverride === null || adjustedSeconds !== existingOverride) return true;
        }
        return false;
    }
    App.isEditDirty = isEditDirty;

    function updateNoteCount() {
        var textarea = document.getElementById("edit-note-text");
        var counter = document.getElementById("edit-note-count");
        if (!textarea || !counter) return;
        var length = textarea.value.length;
        var noteChanged = !!(
            App.editingSession
            && textarea.value !== String(App.editingSession.session_note || "")
        );
        counter.textContent = length + " / " + App.TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH;
        counter.classList.toggle(
            "over-limit",
            noteChanged && length > App.TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH
        );
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

    function cancelTimelineAutosaveTimer() {
        if (App.timelineAutosaveTimer) {
            window.clearTimeout(App.timelineAutosaveTimer);
        }
        App.timelineAutosaveTimer = null;
    }

    function handleTimelineCompositionStart() {
        App.timelineCompositionActive = true;
        cancelTimelineAutosaveTimer();
    }
    App.handleTimelineCompositionStart = handleTimelineCompositionStart;

    function handleTimelineNoteInput(event) {
        App.fdWorkStatusOverride = null;
        updateNoteCount();
        if (
            (event && event.isComposing === true)
            || App.timelineCompositionActive === true
        ) {
            return;
        }
        scheduleTimelineAutosave(650);
    }
    App.handleTimelineNoteInput = handleTimelineNoteInput;

    function handleTimelineCompositionEnd() {
        App.timelineCompositionActive = false;
        updateNoteCount();
        if (!App.editSaving) App.timelineAutosaveQueued = false;
        scheduleTimelineAutosave(650);
    }
    App.handleTimelineCompositionEnd = handleTimelineCompositionEnd;

    function handleTimelineNoteBlur() {
        if (App.timelineCompositionActive === true) return;
        scheduleTimelineAutosave(0);
    }
    App.handleTimelineNoteBlur = handleTimelineNoteBlur;

    function normalizeTimelineDurationInput(value) {
        var raw = String(value === null || value === undefined ? "" : value).trim();
        if (raw === "") {
            return { valid: true, cleared: true, text: "", seconds: null, reason: "" };
        }
        var hours = Number(raw);
        if (!Number.isFinite(hours) || hours < 0) {
            return { valid: false, cleared: false, text: raw, seconds: null, reason: "时长需为非负数" };
        }
        var tenths = Math.floor((hours * 10) + 0.5 + 1e-9);
        var text = (tenths / 10).toFixed(1);
        if (tenths < 1) {
            return { valid: false, cleared: false, text: text, seconds: null, reason: "人工修正时长至少为 0.1 小时" };
        }
        var seconds = tenths * 360;
        if (seconds > 86400) {
            return { valid: false, cleared: false, text: text, seconds: null, reason: "人工修正时长不能超过 24.0 小时" };
        }
        return { valid: true, cleared: false, text: text, seconds: seconds, reason: "" };
    }
    App.normalizeTimelineDurationInput = normalizeTimelineDurationInput;

    function handleTimelineDurationChange() {
        App.fdWorkStatusOverride = null;
        App.timelineDurationDraftTouched = true;
        var input = document.getElementById("edit-duration-input");
        var normalized = normalizeTimelineDurationInput(input ? input.value : "");
        if (input) input.value = normalized.text;
        App.timelineDurationDraftInvalid = !normalized.valid;
        App.updateFDWorkEntryButton();
        if (!normalized.valid) {
            cancelTimelineAutosaveTimer();
            showEditStatus(normalized.reason, true);
            return;
        }
        scheduleTimelineAutosave(0);
    }
    App.handleTimelineDurationChange = handleTimelineDurationChange;

    function scheduleTimelineAutosave(delay) {
        if (!App.editingSession) return;
        cancelTimelineAutosaveTimer();
        if (App.timelineCompositionActive === true) {
            App.timelineAutosaveQueued = true;
            return;
        }
        if (App.editSaving) {
            App.timelineAutosaveQueued = true;
            showEditStatus("有新更改，等待保存", false);
            return;
        }
        if (!isEditDirty()) {
            showEditStatus("已保存", false);
            return;
        }
        showEditStatus("等待自动保存", false);
        App.timelineAutosaveTimer = window.setTimeout(function () {
            App.timelineAutosaveTimer = null;
            App.saveEdit();
        }, Math.max(0, parseInt(delay, 10) || 0));
    }
    App.scheduleTimelineAutosave = scheduleTimelineAutosave;

    App.focusTimelineEditorField = function (target) {
        var id = target === "project" ? "edit-project-select"
            : target === "description" ? "edit-note-text" : "timeline-details-close";
        var element = document.getElementById(id);
        App.openTimelineDrawer(element);
        if (element && element.focus) element.focus();
    };

    function setEditSaving(saving) {
        App.editSaving = saving;
        applyEditCapabilities(App.editingSession);
        App.updateSessionActionButtons(App.editingSession);
        App.updateFDWorkEntryButton();
    }
    App.setEditSaving = setEditSaving;

    App.timelineEditorState = Object.freeze({
        canEditField: canEditField,
        findCachedProject: findCachedProject,
        setReadOnlyNotice: setTimelineReadOnlyNotice,
        cancelAutosaveTimer: cancelTimelineAutosaveTimer
    });
})();
