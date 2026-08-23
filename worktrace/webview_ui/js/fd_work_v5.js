// Shared frontend owner for the optional FD Work capability.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    App.fdWorkStatus = null;
    App.FD_WORK_CASE_LABEL_MAX_LENGTH = 100;

    var sessionStates = ["disabled", "deferred_by_privacy", "idle", "probing", "login_required", "ready", "error", "shutdown"];
    var operations = ["none", "user_auth", "user_picker", "automation_fill"];
    var pagePhases = ["none", "login_credentials", "login_confirmation", "work_shell", "unauthorized", "error", "unknown"];
    var operationStatuses = ["pending", "save_completed", "operation_canceled", "failed"];
    var statusHost = { onStatusChanged: function () {} };

    function validStatus(status) {
        return !!status
            && typeof status === "object"
            && typeof status.supported === "boolean"
            && typeof status.enabled === "boolean"
            && sessionStates.indexOf(status.session_state) >= 0
            && operations.indexOf(status.operation) >= 0
            && typeof status.ready === "boolean"
            && typeof status.login_required === "boolean"
            && (status.error_code === null || typeof status.error_code === "string")
            && (status.page_phase === undefined || pagePhases.indexOf(status.page_phase) >= 0)
            && (status.operation_status === undefined
                || operationStatuses.indexOf(status.operation_status) >= 0)
            && (status.operation_generation === undefined
                || (Number.isInteger(status.operation_generation)
                    && status.operation_generation >= 0))
            && (status.operation_result_owner === undefined
                || operations.indexOf(status.operation_result_owner) > 0)
            && (status.navigation_generation === undefined
                || (Number.isInteger(status.navigation_generation)
                    && status.navigation_generation >= 0));
    }

    function bindStatusHost(host) {
        statusHost = {
            onStatusChanged: host && typeof host.onStatusChanged === "function"
                ? host.onStatusChanged : function () {}
        };
    }

    function notifyStatusHost(status) {
        try { statusHost.onStatusChanged(status); } catch (_error) {}
    }

    App.receiveFDWorkStatus = function (status) {
        if (!validStatus(status)) return false;
        var previousStatus = App.fdWorkStatus;
        var previousOperation = previousStatus && previousStatus.operation;
        var incomingGeneration = Number.isInteger(status.navigation_generation)
            ? status.navigation_generation : null;
        var currentGeneration = previousStatus
            && Number.isInteger(previousStatus.navigation_generation)
            ? previousStatus.navigation_generation : null;
        var incomingOperationGeneration = Number.isInteger(status.operation_generation)
            ? status.operation_generation : null;
        var currentOperationGeneration = previousStatus
            && Number.isInteger(previousStatus.operation_generation)
            ? previousStatus.operation_generation : null;
        if (incomingGeneration !== null
            && currentGeneration !== null
            && incomingGeneration < currentGeneration) return false;
        if (incomingGeneration !== null
            && currentGeneration !== null
            && incomingGeneration === currentGeneration
            && incomingOperationGeneration !== null
            && currentOperationGeneration !== null
            && incomingOperationGeneration < currentOperationGeneration) return false;
        var terminalStates = ["login_required", "ready", "error"];
        if (incomingGeneration !== null
            && incomingGeneration === currentGeneration
            && previousStatus
            && terminalStates.indexOf(previousStatus.session_state) >= 0
            && status.session_state === "probing") return false;
        App.fdWorkStatus = Object.freeze({
            supported: status.supported === true,
            enabled: status.enabled === true,
            session_state: status.session_state,
            operation: status.operation,
            interaction_owner: status.interaction_owner || status.operation,
            ready: status.ready === true,
            login_required: status.login_required === true,
            error_code: status.error_code || null,
            page_phase: status.page_phase || "none",
            navigation_generation: incomingGeneration,
            operation_status: status.operation_status || null,
            operation_generation: incomingOperationGeneration,
            operation_result_owner: status.operation_result_owner || null
        });
        notifyStatusHost(App.fdWorkStatus);
        var fillTerminal = status.operation === "none" && (
            status.operation_result_owner === "automation_fill"
            || (previousOperation === "automation_fill"
                && status.operation_result_owner === undefined)
        );
        if (fillTerminal) {
            App.fdWorkOpenPromise = null;
            if (typeof App.showFDWorkStatus === "function") {
                if (status.operation_status === "save_completed") {
                    App.showFDWorkStatus("已保存到 FD Work", false);
                } else if (status.operation_status === "operation_canceled") {
                    App.showFDWorkStatus(
                        status.error_code === "window_closed"
                            ? "FD Work 窗口已关闭，操作已取消"
                            : "FD Work 操作已取消",
                        false
                    );
                } else if (status.error_code === "save_outcome_unknown") {
                    App.showFDWorkStatus(
                        "FD Work 保存结果未确认，请先在 FD Work 页面核对；确认前不要重复填入",
                        true
                    );
                } else {
                    App.showFDWorkStatus("保存到 FD Work 失败，请重试", false);
                }
            }
        }
        return true;
    };

    App.fdWorkStatusText = function (status) {
        status = status || App.fdWorkStatus || {};
        if (!status.enabled) return "插件关闭";
        if (status.session_state === "deferred_by_privacy") return "等待隐私授权";
        if (status.operation === "user_auth") return "等待用户登录";
        if (status.operation === "user_picker") return "用户正在选择案件";
        if (status.operation === "automation_fill") return "正在填入 FD Work…";
        if (status.session_state === "probing") return "正在检查登录状态";
        if (status.session_state === "ready") return "已连接";
        if (status.page_phase === "login_confirmation") return "请确认登录";
        if (status.session_state === "login_required") return "需要登录";
        if (status.error_code === "session_start_timeout") return "连接超时";
        if (status.error_code === "renderer_unavailable") return "WebView2 不可用";
        if (status.session_state === "error") return "页面不可用";
        return "尚未连接";
    };

    function ensureSession() {
        if (!App.bridge || typeof App.bridge.showFDWorkLogin !== "function") {
            return Promise.resolve({
                ok: false,
                error: "fd_work_window_unavailable",
                message: "打开 FD Work 失败"
            });
        }
        return App.bridge.showFDWorkLogin().then(function (result) {
            if (result && result.capability_status && App.receiveFDWorkStatus) {
                App.receiveFDWorkStatus(result.capability_status);
            }
            return result || {
                ok: false,
                error: "fd_work_window_unavailable",
                message: "打开 FD Work 失败"
            };
        }).catch(function () {
            return {
                ok: false,
                error: "fd_work_window_unavailable",
                message: "打开 FD Work 失败"
            };
        });
    }

    var identityState = {
        selectionProof: null,
        selectedLabel: "",
        originalName: "",
        originalBound: false,
        editingProjectId: null,
        editorGeneration: 0,
        projectBusy: false,
        pickerRequestId: null,
        pickerEditorGeneration: null,
        pickerPending: false,
        pickerCounter: 0,
        saveIntent: "local",
        host: {
            onStateChanged: function () {},
            onBindingChanged: function () {}
        }
    };

    function identityEnabled() {
        return (App.fdWorkStatus || {}).enabled === true;
    }

    function projectNameInput() {
        return document.getElementById("rules-panel-project-name");
    }

    function refreshRulesWriteState() {
        try { identityState.host.onStateChanged(); } catch (_error) {}
    }

    function notifyBindingChanged() {
        try {
            var pending = identityState.host.onBindingChanged();
            if (pending && typeof pending.catch === "function") pending.catch(function () {});
        } catch (_error) {}
    }

    function bindIdentityHost(host) {
        host = host || {};
        identityState.host = {
            onStateChanged: typeof host.onStateChanged === "function"
                ? host.onStateChanged : function () {},
            onBindingChanged: typeof host.onBindingChanged === "function"
                ? host.onBindingChanged : function () {}
        };
    }

    function showIdentityStatus(message, isError) {
        var target = document.getElementById("rules-panel-fd-work-status");
        if (!target) return;
        target.hidden = !message;
        target.textContent = message || "";
        target.className = "inline-status" + (isError ? " edit-status-error" : "");
    }

    function hideLegacySelectedCaseField() {
        var selected = document.getElementById("rules-panel-fd-work-selected-label");
        if (!selected) return;
        var row = selected.closest ? selected.closest("label") : selected.parentElement;
        if (row) row.hidden = true;
    }

    function clearIdentityPickerTransient() {
        identityState.pickerRequestId = null;
        identityState.pickerEditorGeneration = null;
        identityState.pickerPending = false;
    }

    function resetIdentityEditor() {
        identityState.editorGeneration += 1;
        identityState.selectionProof = null;
        identityState.selectedLabel = "";
        identityState.originalName = "";
        identityState.originalBound = false;
        identityState.editingProjectId = null;
        identityState.projectBusy = false;
        clearIdentityPickerTransient();
        identityState.saveIntent = "local";
        showIdentityStatus("", false);
    }

    function prepareIdentityEditor(project) {
        resetIdentityEditor();
        var projectId = Number(project && project.id);
        identityState.editingProjectId = Number.isInteger(projectId) && projectId > 0
            ? projectId : null;
        identityState.originalName = project ? App.safeText(project.name, "") : "";
        identityState.originalBound = !!(project && project.fd_work_bound === true);
        if (project && identityState.originalBound) {
            showIdentityStatus("已关联 FD Work", false);
        }
        var pick = document.getElementById("rules-panel-fd-work-pick");
        if (pick) pick.textContent = identityState.originalBound ? "更换案件" : "选择案件";
        hideLegacySelectedCaseField();
    }

    function isCurrentPickerRequest(requestId, editorGeneration) {
        return requestId === identityState.pickerRequestId
            && editorGeneration === identityState.pickerEditorGeneration
            && editorGeneration === identityState.editorGeneration;
    }

    function openIdentityPicker() {
        if (identityState.pickerPending || identityState.projectBusy) return;
        if (!identityEnabled()) return;
        var editorGeneration = identityState.editorGeneration;
        var requestId = "rules-picker-" + editorGeneration + "-" + (++identityState.pickerCounter);
        identityState.pickerPending = true;
        identityState.pickerRequestId = requestId;
        identityState.pickerEditorGeneration = editorGeneration;
        showIdentityStatus("正在打开案件选择器…", false);
        refreshRulesWriteState();
        App.bridge.openFDWorkCasePicker(requestId).then(function (result) {
            if (!isCurrentPickerRequest(requestId, editorGeneration)) return;
            if (!result || result.ok === false) {
                clearIdentityPickerTransient();
                showIdentityStatus(result && result.message || "打开案件选择器失败", true);
                refreshRulesWriteState();
                return;
            }
            showIdentityStatus(
                result.operation_status === "authentication_required"
                    ? "请登录 FD Work"
                    : "请在 FD Work 中选择案件",
                false
            );
        }).catch(function () {
            if (!isCurrentPickerRequest(requestId, editorGeneration)) return;
            clearIdentityPickerTransient();
            showIdentityStatus("打开案件选择器失败", true);
            refreshRulesWriteState();
        });
    }

    function clearIdentitySelection() {
        if (identityState.pickerPending) return;
        identityState.selectionProof = null;
        identityState.selectedLabel = "";
        if (identityState.originalBound && identityState.editingProjectId) {
            var editorGeneration = identityState.editorGeneration;
            var editingProjectId = identityState.editingProjectId;
            identityState.pickerPending = true;
            refreshRulesWriteState();
            App.bridge.clearFDWorkBindingForRules(editingProjectId).then(function (result) {
                if (editorGeneration !== identityState.editorGeneration) return;
                identityState.pickerPending = false;
                if (!result || result.ok === false) {
                    showIdentityStatus(result && result.error || "取消关联失败", true);
                    refreshRulesWriteState();
                    return;
                }
                identityState.originalBound = false;
                showIdentityStatus("已取消 FD Work 关联", false);
                notifyBindingChanged();
                refreshRulesWriteState();
            }).catch(function () {
                if (editorGeneration !== identityState.editorGeneration) return;
                identityState.pickerPending = false;
                showIdentityStatus("取消关联失败", true);
                refreshRulesWriteState();
            });
            return;
        }
        showIdentityStatus("", false);
        refreshRulesWriteState();
    }

    function receiveIdentityPickerResult(result) {
        if (!result || typeof result !== "object") return false;
        var editorGeneration = identityState.pickerEditorGeneration;
        if (!isCurrentPickerRequest(result.request_id, editorGeneration)) return false;
        clearIdentityPickerTransient();
        if (result.ok !== true) {
            showIdentityStatus(
                result.error === "picker_canceled" ? "案件选择已取消" : "案件选择已失效",
                result.error !== "picker_canceled"
            );
            refreshRulesWriteState();
            return true;
        }
        if (typeof result.selected_label !== "string"
            || !result.selected_label
            || typeof result.selection_token !== "string"
            || !result.selection_token) {
            showIdentityStatus("案件选择结果无效", true);
            refreshRulesWriteState();
            return false;
        }
        identityState.selectedLabel = result.selected_label.trim();
        identityState.selectionProof = result.selection_token;
        var input = projectNameInput();
        if (input) input.value = identityState.selectedLabel;
        showIdentityStatus("已选择 FD Work 案件", false);
        refreshRulesWriteState();
        return true;
    }

    function handleIdentityNameInput() {
        var input = projectNameInput();
        var name = String(input && input.value || "").trim();
        if (identityState.selectionProof
            && name !== String(identityState.selectedLabel || "").trim()) {
            identityState.selectionProof = null;
            identityState.selectedLabel = "";
        }
        if (!identityEnabled()) {
            showIdentityStatus("", false);
        } else if (identityState.selectionProof) {
            showIdentityStatus("已选择 FD Work 案件", false);
        } else if (identityState.originalBound && name === identityState.originalName) {
            showIdentityStatus("已关联 FD Work", false);
        } else if (identityState.originalBound && name !== identityState.originalName) {
            showIdentityStatus("名称已修改，保存后将取消 FD Work 关联", false);
        } else {
            showIdentityStatus("", false);
        }
        refreshRulesWriteState();
    }

    function buildIdentitySave(localName, editing) {
        var name = String(localName || "").trim();
        if (!name) {
            identityState.saveIntent = "local";
            return { ok: false, error: "请输入项目名称" };
        }

        if (!identityEnabled()) {
            identityState.selectionProof = null;
            identityState.selectedLabel = "";
            identityState.saveIntent = "local";
            return { ok: true, name: name, proof: null, verifyBinding: false };
        }

        if (identityState.selectionProof) {
            var selected = String(identityState.selectedLabel || "").trim();
            if (name === selected) {
                identityState.saveIntent = "external";
                return {
                    ok: true,
                    name: selected,
                    proof: identityState.selectionProof,
                    verifyBinding: true
                };
            }
            identityState.selectionProof = null;
            identityState.selectedLabel = "";
        }

        if (editing && identityState.originalBound && name === identityState.originalName) {
            identityState.saveIntent = "preserve";
        } else {
            identityState.saveIntent = "local";
        }
        return { ok: true, name: name, proof: null, verifyBinding: false };
    }

    function verifyIdentityPersistence(result, saved, project) {
        if (identityState.saveIntent !== "external") return true;
        if (!saved
            || String(saved.name || "") !== String(project && project.name || "")) {
            return false;
        }
        var binding = (result && result.fd_work_binding) || {};
        return binding.bound === true
            && binding.verified === true
            && saved.fd_work_bound === true;
    }

    function syncIdentityStatus() {
        var capability = App.fdWorkStatus || {};
        var enabled = identityEnabled();
        var label = document.getElementById("rules-panel-project-name-label");
        var help = document.getElementById("rules-panel-fd-work-help");
        var input = projectNameInput();
        if (label) label.textContent = "项目名称";
        if (help) {
            help.hidden = true;
            help.textContent = "";
        }
        var picker = document.getElementById("rules-panel-fd-work-picker");
        if (picker) picker.hidden = !enabled;
        hideLegacySelectedCaseField();
        if (!enabled || capability.session_state === "shutdown") {
            identityState.selectionProof = null;
            identityState.selectedLabel = "";
            if (identityState.pickerPending) clearIdentityPickerTransient();
            showIdentityStatus("", false);
        } else if (identityState.pickerPending) {
            if (capability.operation === "user_auth") {
                showIdentityStatus(
                    capability.page_phase === "login_confirmation"
                        ? "请确认登录"
                        : "请登录 FD Work",
                    false
                );
            } else if (capability.operation === "user_picker") {
                showIdentityStatus("请在 FD Work 中选择案件", false);
            } else if (capability.session_state === "error") {
                clearIdentityPickerTransient();
                showIdentityStatus(App.fdWorkStatusText(capability), true);
            }
        }
        if (input) {
            input.hidden = false;
            input.readOnly = identityState.pickerPending;
        }
        refreshRulesWriteState();
    }

    function updateIdentityControls(projectBusy) {
        identityState.projectBusy = !!projectBusy;
        var pending = identityState.pickerPending;
        var pick = document.getElementById("rules-panel-fd-work-pick");
        var clear = document.getElementById("rules-panel-fd-work-clear");
        var input = projectNameInput();
        var name = String((input || {}).value || "").trim();
        if (input) input.readOnly = pending;
        if (pick) {
            pick.disabled = identityState.projectBusy || pending || !identityEnabled();
            pick.textContent = pending
                ? "正在打开……"
                : (identityState.selectionProof || identityState.originalBound ? "更换案件" : "选择案件");
        }
        if (clear) {
            clear.disabled = identityState.projectBusy || pending;
            clear.hidden = !(identityState.selectionProof || identityState.originalBound);
        }
        return {
            pending: pending,
            hasName: !!name
        };
    }

    function bindIdentityEvents() {
        var pick = document.getElementById("rules-panel-fd-work-pick");
        var clear = document.getElementById("rules-panel-fd-work-clear");
        var input = projectNameInput();
        if (pick && pick.getAttribute("data-bound") !== "1") {
            pick.setAttribute("data-bound", "1");
            pick.addEventListener("click", openIdentityPicker);
        }
        if (clear && clear.getAttribute("data-bound") !== "1") {
            clear.setAttribute("data-bound", "1");
            clear.addEventListener("click", clearIdentitySelection);
        }
        if (input && input.getAttribute("data-fd-work-identity-bound") !== "1") {
            input.setAttribute("data-fd-work-identity-bound", "1");
            input.addEventListener("input", handleIdentityNameInput);
        }
        hideLegacySelectedCaseField();
        installTimelineProjectGate();
    }

    function validProjectSessionForFDWorkGate(session) {
        return !!session
            && session.is_in_progress !== true
            && !!session.end_time
            && session.row_kind === "project_session"
            && session.is_report_project === true
            && session.is_report_uncategorized !== true
            && session.is_uncategorized !== true
            && session.project_is_deleted !== true;
    }

    function selectedTimelineProject() {
        var session = App.editingSession;
        if (!validProjectSessionForFDWorkGate(session)) return null;
        var select = document.getElementById("edit-project-select");
        var projectId = parseInt(select && select.value || session.project_id || 0, 10);
        if (!(projectId > 0)) return null;
        var projects = App.projectCatalog
            ? App.projectCatalog.getEditing()
            : [];
        for (var index = 0; index < projects.length; index++) {
            if (parseInt(projects[index] && projects[index].id, 10) === projectId) {
                return projects[index];
            }
        }
        return null;
    }

    function clearLocalProjectGateStatus(status) {
        if (!status || String(status.textContent || "").trim() !== "此项目未关联 FD Work") return;
        status.textContent = "";
        status.hidden = true;
    }

    function enforceTimelineProjectGate() {
        var area = document.getElementById("fd-work-entry-area");
        var button = document.getElementById("fd-work-entry-btn");
        var status = document.getElementById("fd-work-status");
        if (!area || !button || !status) return;
        if (!identityEnabled() || area.hidden) {
            if (button.textContent === "非 FD Work 项目") button.textContent = "填入 FD Work";
            clearLocalProjectGateStatus(status);
            return;
        }
        var project = selectedTimelineProject();
        if (!project) {
            if (button.textContent === "非 FD Work 项目") button.textContent = "填入 FD Work";
            clearLocalProjectGateStatus(status);
            return;
        }
        if (project.fd_work_bound === true) {
            if (button.textContent === "非 FD Work 项目") button.textContent = "填入 FD Work";
            clearLocalProjectGateStatus(status);
            return;
        }
        if (!button.disabled) button.disabled = true;
        if (button.textContent !== "非 FD Work 项目") button.textContent = "非 FD Work 项目";
        status.textContent = "";
        status.hidden = true;
        status.className = "inline-status";
    }

    function installTimelineProjectGate() {
        if (App.fdWorkProjectGateInstalled === true) return;
        var select = document.getElementById("edit-project-select");
        var list = document.getElementById("timeline-sessions-list");
        var button = document.getElementById("fd-work-entry-btn");
        var status = document.getElementById("fd-work-status");
        if (!select || !list || !button || !status) return;
        App.fdWorkProjectGateInstalled = true;

        select.addEventListener("change", enforceTimelineProjectGate);
        list.addEventListener("click", function () {
            window.setTimeout(enforceTimelineProjectGate, 0);
        });
        button.addEventListener("click", function (event) {
            var project = selectedTimelineProject();
            if (!project || project.fd_work_bound === true) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            enforceTimelineProjectGate();
        }, true);
        if (window.MutationObserver) {
            var observer = new MutationObserver(function () {
                enforceTimelineProjectGate();
            });
            observer.observe(button, { attributes: true, attributeFilter: ["disabled"] });
            observer.observe(status, { childList: true });
        }
        enforceTimelineProjectGate();
    }

    App.projectIdentity = Object.freeze({
        bindEvents: bindIdentityEvents,
        bindHost: bindIdentityHost,
        buildSavePayload: buildIdentitySave,
        enabled: identityEnabled,
        prepareEditor: prepareIdentityEditor,
        reset: resetIdentityEditor,
        syncStatus: syncIdentityStatus,
        updateControls: updateIdentityControls,
        verifyPersistence: verifyIdentityPersistence
    });
    App.receiveFDWorkCasePickerResult = receiveIdentityPickerResult;
    App.fdWork = Object.freeze({
        bindStatusHost: bindStatusHost,
        ensureSession: ensureSession,
        resetGeneration: resetIdentityEditor
    });
})();