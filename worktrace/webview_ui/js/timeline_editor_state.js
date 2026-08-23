// WorkTrace WebView frontend — timeline editor state owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    var editingSession = null;
    var compositionActive = false;
    var durationDraftTouched = false;
    var durationDraftInvalid = false;
    var autosaveTimer = null;
    var autosaveQueued = false;
    var eventsBound = false;

    function element(id) { return document.getElementById(id); }

    function mutationSaving() {
        return !!(
            App.timelineEditMutation
            && typeof App.timelineEditMutation.isSaving === "function"
            && App.timelineEditMutation.isSaving()
        );
    }

    function findCachedProject(projectId) {
        var projects = App.projectCatalog ? App.projectCatalog.getEditing() : [];
        for (var index = 0; index < projects.length; index++) {
            if (String(projects[index].id) === String(projectId)) return projects[index];
        }
        return null;
    }

    function canEditField(session, field) {
        return !!session && session.edit_disabled !== true && session[field] !== false;
    }

    function hasEditableFields(session) {
        return canEditField(session, "can_edit_project")
            || canEditField(session, "can_edit_note")
            || canEditField(session, "can_edit_duration");
    }

    function setTimelineReadOnlyNotice(session) {
        var notice = element("timeline-readonly-notice");
        if (notice) notice.hidden = !(session && session.is_in_progress === true);
    }

    function showEditStatus(message, isError) {
        var status = element("edit-status");
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

    function applyEditCapabilities(session) {
        var projectAllowed = canEditField(session, "can_edit_project");
        var noteAllowed = canEditField(session, "can_edit_note");
        var durationAllowed = canEditField(session, "can_edit_duration");
        var select = element("edit-project-select");
        var note = element("edit-note-text");
        var duration = element("edit-duration-input");
        var save = element("edit-save-btn");
        var cancel = element("edit-cancel-btn");
        var saving = mutationSaving();
        var noteChanged = !!(
            noteAllowed
            && note
            && session
            && note.value !== String(session.session_note || "")
        );
        if (select) {
            select.disabled = !projectAllowed
                || !App.projectCatalog
                || !App.projectCatalog.getEditing().length;
        }
        if (note) note.disabled = !noteAllowed;
        if (duration) duration.disabled = !durationAllowed;
        if (cancel) cancel.disabled = saving || !session;
        if (save) {
            save.disabled = saving
                || !hasEditableFields(session)
                || (
                    noteChanged
                    && note.value.length > App.TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH
                );
        }
        if (App.updateFDWorkEntryButton) App.updateFDWorkEntryButton();
    }

    function renderProjectSelect(projects, currentProjectId) {
        var select = element("edit-project-select");
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
        for (var index = 0; index < projects.length; index++) {
            var project = projects[index];
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
        applyEditCapabilities(editingSession);
    }

    function updateNoteCount() {
        var textarea = element("edit-note-text");
        var counter = element("edit-note-count");
        if (!textarea || !counter) return;
        var length = textarea.value.length;
        var noteChanged = !!(
            editingSession
            && textarea.value !== String(editingSession.session_note || "")
        );
        counter.textContent = length + " / " + App.TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH;
        counter.classList.toggle(
            "over-limit",
            noteChanged && length > App.TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH
        );
        applyEditCapabilities(editingSession);
    }

    function populate(session) {
        if (!session) {
            clear();
            return;
        }
        editingSession = session;
        setTimelineReadOnlyNotice(null);
        var panel = element("timeline-edit-panel");
        if (panel) panel.hidden = false;
        var select = element("edit-project-select");
        if (select) {
            var cachedProjects = App.projectCatalog ? App.projectCatalog.getEditing() : [];
            if (cachedProjects.length > 0) {
                renderProjectSelect(cachedProjects, session.project_id);
            } else {
                select.innerHTML = '<option value="">加载中…</option>';
                select.disabled = true;
                App.loadTimelineProjects().then(function (projects) {
                    if (
                        editingSession
                        && editingSession.projection_instance_key
                            === session.projection_instance_key
                    ) {
                        renderProjectSelect(projects, session.project_id);
                    }
                });
            }
        }
        var duration = element("edit-duration-input");
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
        durationDraftTouched = false;
        durationDraftInvalid = false;
        var durationStatus = element("edit-duration-status");
        if (durationStatus) {
            durationStatus.textContent = session.has_duration_override ? "已修正" : "";
        }
        var note = element("edit-note-text");
        if (note) note.value = session.session_note || "";
        var cancel = element("edit-cancel-btn");
        if (cancel) cancel.disabled = false;
        updateNoteCount();
        applyEditCapabilities(session);
        showEditStatus("", false);
    }

    function cancelAutosave() {
        if (autosaveTimer) window.clearTimeout(autosaveTimer);
        autosaveTimer = null;
    }

    function clear() {
        cancelAutosave();
        autosaveQueued = false;
        compositionActive = false;
        editingSession = null;
        durationDraftTouched = false;
        durationDraftInvalid = false;
        var panel = element("timeline-edit-panel");
        if (panel) panel.hidden = true;
        setTimelineReadOnlyNotice(null);
        if (App.updateSessionActionButtons) App.updateSessionActionButtons(null);
        var note = element("edit-note-text");
        if (note) {
            note.value = "";
            note.disabled = true;
        }
        var select = element("edit-project-select");
        if (select) {
            select.innerHTML = '<option value="">加载中…</option>';
            select.disabled = true;
        }
        var duration = element("edit-duration-input");
        if (duration) {
            duration.value = "";
            duration.disabled = true;
        }
        var durationStatus = element("edit-duration-status");
        if (durationStatus) durationStatus.textContent = "";
        var save = element("edit-save-btn");
        var cancel = element("edit-cancel-btn");
        if (save) save.disabled = true;
        if (cancel) cancel.disabled = true;
        showEditStatus("", false);
        if (App.showFDWorkStatus) App.showFDWorkStatus("", false);
        if (App.updateFDWorkEntryButton) App.updateFDWorkEntryButton();
    }

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

    function draftFacts() {
        var session = editingSession;
        if (!session) return null;
        var select = element("edit-project-select");
        var noteElement = element("edit-note-text");
        var durationElement = element("edit-duration-input");
        var canProject = canEditField(session, "can_edit_project");
        var canNote = canEditField(session, "can_edit_note");
        var canDuration = canEditField(session, "can_edit_duration");
        var originalProjectId = String(session.project_id || "");
        var projectIdText = canProject && select ? select.value : originalProjectId;
        var projectId = projectIdText ? parseInt(projectIdText, 10) : null;
        var originalNote = session.session_note || "";
        var note = canNote && noteElement ? noteElement.value : originalNote;
        var existingDurationOverride = session.has_duration_override === true
            ? parseInt(session.adjusted_duration_seconds, 10) : null;
        if (isNaN(existingDurationOverride)) existingDurationOverride = null;
        return {
            session: session,
            select: select,
            durationElement: durationElement,
            canProject: canProject,
            canNote: canNote,
            canDuration: canDuration,
            originalProjectId: originalProjectId,
            projectIdText: projectIdText,
            projectId: projectId,
            projectChanged: canProject && projectIdText !== originalProjectId,
            originalNote: originalNote,
            note: note,
            noteChanged: canNote && note !== originalNote,
            existingDurationOverride: existingDurationOverride
        };
    }

    function captureSaveIntent() {
        var facts = draftFacts();
        if (!facts) return Object.freeze({ valid: false, changed: false, reason: "" });
        var session = facts.session;
        if (!facts.canProject && !facts.canNote && !facts.canDuration) {
            return Object.freeze({
                valid: false,
                changed: false,
                reason: session.disable_reason || "当前时段不可编辑",
                session: session
            });
        }
        if (!facts.select || !element("edit-note-text")) {
            return Object.freeze({
                valid: false,
                changed: false,
                reason: "无法保存：编辑器不可用",
                session: session
            });
        }
        var key = session.projection_instance_key || "";
        var revision = session.projection_revision || "";
        if (!key || !revision) {
            return Object.freeze({
                valid: false,
                changed: false,
                reason: "无法保存：时段版本无效，请刷新后重试",
                session: session
            });
        }
        if (
            facts.projectChanged
            && (!facts.projectId || !findCachedProject(facts.projectId))
        ) {
            return Object.freeze({
                valid: false,
                changed: false,
                reason: "项目列表已过期，请刷新后重试",
                session: session
            });
        }
        if (
            facts.noteChanged
            && facts.note.length > App.TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH
        ) {
            return Object.freeze({
                valid: false,
                changed: false,
                reason: "描述不能超过 200 个字符",
                session: session
            });
        }
        var durationTouched = facts.canDuration && durationDraftTouched === true;
        var adjustedDurationSeconds = null;
        var durationChanged = false;
        if (durationTouched) {
            var durationText = facts.durationElement
                ? (facts.durationElement.value || "").trim()
                : "";
            var normalized = normalizeTimelineDurationInput(durationText);
            durationDraftInvalid = !normalized.valid;
            if (!normalized.valid) {
                return Object.freeze({
                    valid: false,
                    changed: false,
                    reason: normalized.reason || "时长无效",
                    session: session
                });
            }
            if (facts.durationElement) facts.durationElement.value = normalized.text;
            if (normalized.cleared) {
                durationChanged = facts.existingDurationOverride !== null;
            } else {
                adjustedDurationSeconds = normalized.seconds;
                durationChanged = facts.existingDurationOverride === null
                    || adjustedDurationSeconds !== facts.existingDurationOverride;
            }
        }
        var overrideProjectId = facts.canProject
            && (facts.projectChanged || session.has_project_override === true)
            ? facts.projectId
            : null;
        return Object.freeze({
            valid: true,
            changed: facts.projectChanged || facts.noteChanged || durationChanged,
            reason: "",
            session: session,
            projectionInstanceKey: key,
            projectionRevision: revision,
            projectId: facts.projectId,
            overrideProjectId: overrideProjectId,
            projectChanged: facts.projectChanged,
            note: facts.note,
            noteChanged: facts.noteChanged,
            durationTouched: durationTouched,
            adjustedDurationSeconds: adjustedDurationSeconds,
            durationChanged: durationChanged
        });
    }

    function isDirty() {
        var facts = draftFacts();
        if (!facts) return false;
        if (facts.noteChanged || facts.projectChanged) return true;
        if (!facts.canDuration || durationDraftTouched !== true) return false;
        var durationText = facts.durationElement
            ? (facts.durationElement.value || "").trim()
            : "";
        if (durationText === "") return facts.existingDurationOverride !== null;
        var normalized = normalizeTimelineDurationInput(durationText);
        if (!normalized.valid) return true;
        return facts.existingDurationOverride === null
            || normalized.seconds !== facts.existingDurationOverride;
    }

    function preview() {
        var facts = draftFacts();
        if (!facts) return null;
        var selected = facts.select && facts.select.options
            ? facts.select.options[facts.select.selectedIndex]
            : null;
        var project = findCachedProject(facts.projectId);
        var projectName = selected
            ? String(selected.textContent || "").trim()
            : String(project && project.name || facts.session.project_name || "").trim();
        var narrative = String(facts.note || "").trim();
        var previewDuration = facts.session.adjusted_duration_seconds !== null
            && facts.session.adjusted_duration_seconds !== undefined
            ? facts.session.adjusted_duration_seconds
            : facts.session.duration_seconds;
        var durationSeconds = Math.max(0, parseInt(previewDuration, 10) || 0);
        if (facts.canDuration && facts.durationElement) {
            var normalized = normalizeTimelineDurationInput(facts.durationElement.value);
            if (!normalized.valid) {
                return Object.freeze({
                    valid: false,
                    reason: normalized.reason,
                    session: facts.session,
                    projectId: facts.projectId,
                    projectName: projectName,
                    narrative: narrative,
                    durationSeconds: durationSeconds
                });
            }
            if (!normalized.cleared) durationSeconds = normalized.seconds;
        }
        return Object.freeze({
            valid: true,
            reason: "",
            session: facts.session,
            projectId: facts.projectId,
            projectName: projectName,
            narrative: narrative,
            durationSeconds: durationSeconds
        });
    }

    function queueAutosave() { autosaveQueued = true; }

    function consumeQueuedAutosave() {
        var queued = autosaveQueued === true;
        autosaveQueued = false;
        return queued;
    }

    function scheduleAutosave(delay) {
        if (!editingSession) return;
        cancelAutosave();
        if (compositionActive) {
            queueAutosave();
            return;
        }
        if (mutationSaving()) {
            queueAutosave();
            showEditStatus("有新更改，等待保存", false);
            return;
        }
        if (!isDirty()) {
            showEditStatus("已保存", false);
            return;
        }
        showEditStatus("等待自动保存", false);
        autosaveTimer = window.setTimeout(function () {
            autosaveTimer = null;
            if (App.timelineEditMutation) App.timelineEditMutation.save();
        }, Math.max(0, parseInt(delay, 10) || 0));
    }

    function handleCompositionStart() {
        compositionActive = true;
        cancelAutosave();
    }

    function handleNoteInput(event) {
        App.fdWorkStatusOverride = null;
        updateNoteCount();
        if ((event && event.isComposing === true) || compositionActive) return;
        scheduleAutosave(650);
    }

    function handleCompositionEnd() {
        compositionActive = false;
        updateNoteCount();
        if (!mutationSaving()) autosaveQueued = false;
        scheduleAutosave(650);
    }

    function handleNoteBlur() {
        if (!compositionActive) scheduleAutosave(0);
    }

    function handleDurationChange() {
        App.fdWorkStatusOverride = null;
        durationDraftTouched = true;
        var input = element("edit-duration-input");
        var normalized = normalizeTimelineDurationInput(input ? input.value : "");
        if (input) input.value = normalized.text;
        durationDraftInvalid = !normalized.valid;
        if (App.updateFDWorkEntryButton) App.updateFDWorkEntryButton();
        if (!normalized.valid) {
            cancelAutosave();
            showEditStatus(normalized.reason, true);
            return;
        }
        scheduleAutosave(0);
    }

    function bindEvents() {
        if (eventsBound) return;
        eventsBound = true;
        var project = element("edit-project-select");
        if (project) {
            project.addEventListener("change", function () {
                App.fdWorkStatusOverride = null;
                if (App.updateFDWorkEntryButton) App.updateFDWorkEntryButton();
                scheduleAutosave(0);
            });
        }
        var note = element("edit-note-text");
        if (note) {
            note.addEventListener("compositionstart", handleCompositionStart);
            note.addEventListener("compositionend", handleCompositionEnd);
            note.addEventListener("input", handleNoteInput);
            note.addEventListener("blur", handleNoteBlur);
        }
        var duration = element("edit-duration-input");
        if (duration) duration.addEventListener("change", handleDurationChange);
    }

    function rebase(session) {
        if (!session || !editingSession) return false;
        if (session.projection_instance_key !== editingSession.projection_instance_key) {
            return false;
        }
        editingSession = session;
        applyEditCapabilities(session);
        return true;
    }

    function settleSubmittedIntent(intent) {
        if (!intent || intent.durationTouched !== true || durationDraftTouched !== true) return;
        var duration = element("edit-duration-input");
        var normalized = normalizeTimelineDurationInput(duration ? duration.value : "");
        if (normalized.valid && normalized.seconds === intent.adjustedDurationSeconds) {
            durationDraftTouched = false;
            durationDraftInvalid = false;
        }
    }

    function syncMutationState() {
        applyEditCapabilities(editingSession);
        if (App.updateFDWorkEntryButton) App.updateFDWorkEntryButton();
    }

    function resetGeneration() {
        clear();
    }

    function focusField(target) {
        var id = target === "project" ? "edit-project-select"
            : target === "description" ? "edit-note-text" : "timeline-details-close";
        var targetElement = element(id);
        App.openTimelineDrawer(targetElement);
        if (targetElement && targetElement.focus) targetElement.focus();
    }

    App.timelineEditorState = Object.freeze({
        bindEvents: bindEvents,
        canEditField: canEditField,
        cancelAutosave: cancelAutosave,
        captureSaveIntent: captureSaveIntent,
        clear: clear,
        consumeQueuedAutosave: consumeQueuedAutosave,
        currentSession: function () { return editingSession; },
        focusField: focusField,
        hasQueuedAutosave: function () { return autosaveQueued === true; },
        isComposing: function () { return compositionActive === true; },
        isDirty: isDirty,
        populate: populate,
        preview: preview,
        queueAutosave: queueAutosave,
        rebase: rebase,
        renderProjectSelect: renderProjectSelect,
        resetGeneration: resetGeneration,
        scheduleAutosave: scheduleAutosave,
        setReadOnlyNotice: setTimelineReadOnlyNotice,
        settleSubmittedIntent: settleSubmittedIntent,
        showStatus: showEditStatus,
        syncMutationState: syncMutationState
    });

    // Compatibility surface for cross-page navigation and existing UI tests;
    // authoritative state remains module-private behind timelineEditorState.
    App.renderProjectSelect = renderProjectSelect;
    App.populateEditPanel = populate;
    App.clearEditPanel = clear;
    App.isEditDirty = isDirty;
    App.updateNoteCount = updateNoteCount;
    App.showEditStatus = showEditStatus;
    App.handleTimelineCompositionStart = handleCompositionStart;
    App.handleTimelineNoteInput = handleNoteInput;
    App.handleTimelineCompositionEnd = handleCompositionEnd;
    App.handleTimelineNoteBlur = handleNoteBlur;
    App.normalizeTimelineDurationInput = normalizeTimelineDurationInput;
    App.handleTimelineDurationChange = handleDurationChange;
    App.scheduleTimelineAutosave = scheduleAutosave;
    App.focusTimelineEditorField = focusField;
})();
