// Shared frontend owner for the optional FD Work capability.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    App.fdWorkStatus = null;
    App.FD_WORK_CASE_LABEL_MAX_LENGTH = 100;

    var sessionStates = ["disabled", "deferred_by_privacy", "idle", "probing", "login_required", "ready", "error", "shutdown"];
    var operations = ["none", "user_auth", "user_picker", "automation_fill"];
    var pagePhases = ["none", "login_credentials", "login_confirmation", "work_shell", "unauthorized", "error", "unknown"];

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
            && (status.navigation_generation === undefined
                || (Number.isInteger(status.navigation_generation)
                    && status.navigation_generation >= 0));
    }

    App.receiveFDWorkStatus = function (status) {
        if (!validStatus(status)) return false;
        var previousOperation = App.fdWorkStatus && App.fdWorkStatus.operation;
        var incomingGeneration = Number.isInteger(status.navigation_generation)
            ? status.navigation_generation : null;
        var currentGeneration = App.fdWorkStatus
            && Number.isInteger(App.fdWorkStatus.navigation_generation)
            ? App.fdWorkStatus.navigation_generation : null;
        if (incomingGeneration !== null
            && currentGeneration !== null
            && incomingGeneration < currentGeneration) return false;
        var terminalStates = ["login_required", "ready", "error"];
        if (incomingGeneration !== null
            && incomingGeneration === currentGeneration
            && App.fdWorkStatus
            && terminalStates.indexOf(App.fdWorkStatus.session_state) >= 0
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
            navigation_generation: incomingGeneration
        });
        if (App.lastSettingsStatus) App.lastSettingsStatus.fd_work = App.fdWorkStatus;
        if (typeof App.renderFDWorkToggle === "function") App.renderFDWorkToggle(App.lastSettingsStatus);
        if (typeof App.updateFDWorkEntryButton === "function") App.updateFDWorkEntryButton();
        if (App.projectIdentity) App.projectIdentity.syncStatus();
        if (previousOperation === "automation_fill" && status.operation === "none") {
            if (typeof App.showFDWorkStatus === "function") {
                App.showFDWorkStatus(
                    status.error_code ? "保存到 FD Work 失败，请重试" : "已保存到 FD Work",
                    !!status.error_code
                );
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

    var identityState = {
        selectionProof: null,
        selectedLabel: "",
        originalName: "",
        originalBound: false,
        pickerRequestId: null,
        pickerDrawerSession: null,
        pickerPending: false,
        pickerCounter: 0
    };

    function identityEnabled() {
        return (App.fdWorkStatus || {}).enabled === true;
    }

    function refreshRulesWriteState() {
        if (typeof App.refreshRulesPanelWriteState === "function") {
            App.refreshRulesPanelWriteState();
        }
    }

    function showIdentityStatus(message, isError) {
        var target = document.getElementById("rules-panel-fd-work-status");
        if (!target) return;
        target.hidden = !message;
        target.textContent = message || "";
        target.className = "inline-status" + (isError ? " edit-status-error" : "");
    }

    function resetIdentityEditor() {
        identityState.selectionProof = null;
        identityState.selectedLabel = "";
        identityState.originalName = "";
        identityState.originalBound = false;
        identityState.pickerRequestId = null;
        identityState.pickerDrawerSession = null;
        identityState.pickerPending = false;
        var selected = document.getElementById("rules-panel-fd-work-selected-label");
        if (selected) selected.value = "";
        showIdentityStatus("", false);
    }

    function prepareIdentityEditor(project) {
        resetIdentityEditor();
        identityState.originalName = project ? App.safeText(project.name, "") : "";
        identityState.originalBound = !!(project && project.fd_work_bound === true);
        var selected = document.getElementById("rules-panel-fd-work-selected-label");
        if (selected) selected.value = project ? identityState.originalName : "";
        if (project && identityState.originalBound) {
            showIdentityStatus("已关联 FD Work", false);
        } else if (project) {
            showIdentityStatus("历史本地项目：名称不变时可继续维护其他信息", false);
        }
        var pick = document.getElementById("rules-panel-fd-work-pick");
        if (pick) pick.textContent = project ? "更换案件" : "选择案件";
    }

    function isCurrentPickerRequest(requestId, drawerSession) {
        return requestId === identityState.pickerRequestId
            && drawerSession === identityState.pickerDrawerSession
            && drawerSession === App.rulesPanelSessionToken;
    }

    function openIdentityPicker() {
        if (identityState.pickerPending || App.rulesCreatingPanelProject) return;
        if (!identityEnabled()) return;
        var drawerSession = App.rulesPanelSessionToken;
        var requestId = "rules-picker-" + drawerSession + "-" + (++identityState.pickerCounter);
        identityState.pickerPending = true;
        identityState.pickerRequestId = requestId;
        identityState.pickerDrawerSession = drawerSession;
        showIdentityStatus("正在打开 FD Work 案件选择器……", false);
        refreshRulesWriteState();
        App.bridge.openFDWorkCasePicker(requestId).then(function (result) {
            if (!isCurrentPickerRequest(requestId, drawerSession)) return;
            if (!result || result.ok === false) {
                identityState.pickerPending = false;
                identityState.pickerRequestId = null;
                showIdentityStatus(result && result.message || "打开案件选择器失败", true);
                refreshRulesWriteState();
                return;
            }
            showIdentityStatus(
                result.operation_status === "authentication_required"
                    ? "请在 FD Work 窗口完成登录并选择案件"
                    : "请在 FD Work 原生案件框中选择并确认",
                false
            );
        }).catch(function () {
            if (!isCurrentPickerRequest(requestId, drawerSession)) return;
            identityState.pickerPending = false;
            identityState.pickerRequestId = null;
            showIdentityStatus("打开案件选择器失败", true);
            refreshRulesWriteState();
        });
    }

    function clearIdentitySelection() {
        if (identityState.pickerPending) return;
        if (identityState.originalBound && App.rulesPanelEditingProjectId) {
            var drawerSession = App.rulesPanelSessionToken;
            identityState.pickerPending = true;
            refreshRulesWriteState();
            App.bridge.clearFDWorkBindingForRules(
                App.rulesPanelEditingProjectId
            ).then(function (result) {
                if (drawerSession !== App.rulesPanelSessionToken) return;
                identityState.pickerPending = false;
                if (!result || result.ok === false) {
                    showIdentityStatus(result && result.error || "取消关联失败", true);
                    refreshRulesWriteState();
                    return;
                }
                identityState.originalBound = false;
                showIdentityStatus("已取消 FD Work 关联", false);
                if (App.loadProjectRules) App.loadProjectRules();
                refreshRulesWriteState();
            }).catch(function () {
                if (drawerSession !== App.rulesPanelSessionToken) return;
                identityState.pickerPending = false;
                showIdentityStatus("取消关联失败", true);
                refreshRulesWriteState();
            });
            return;
        }
        identityState.selectionProof = null;
        identityState.selectedLabel = "";
        var selected = document.getElementById("rules-panel-fd-work-selected-label");
        if (selected) selected.value = "";
        showIdentityStatus("尚未选择 FD Work 案件", false);
        refreshRulesWriteState();
    }

    function receiveIdentityPickerResult(result) {
        if (!result || typeof result !== "object") return false;
        var drawerSession = identityState.pickerDrawerSession;
        if (!isCurrentPickerRequest(result.request_id, drawerSession)) return false;
        identityState.pickerPending = false;
        identityState.pickerRequestId = null;
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
        identityState.selectedLabel = result.selected_label;
        identityState.selectionProof = result.selection_token;
        var selected = document.getElementById("rules-panel-fd-work-selected-label");
        if (selected) selected.value = result.selected_label;
        showIdentityStatus("已选择 FD Work 案件", false);
        refreshRulesWriteState();
        return true;
    }

    function buildIdentitySave(localName, editing) {
        if (!identityEnabled()) {
            var local = String(localName || "").trim();
            return local
                ? { ok: true, name: local, proof: null, verifyBinding: false }
                : { ok: false, error: "请输入项目名称" };
        }
        var selected = document.getElementById("rules-panel-fd-work-selected-label");
        var displayedLabel = String(selected && selected.value || "").trim();
        if (identityState.selectionProof
            && displayedLabel !== String(identityState.selectedLabel || "").trim()) {
            return { ok: false, error: "案件选择结果已被修改，请重新选择" };
        }
        if (!editing && !identityState.selectionProof) {
            return { ok: false, error: "请先选择 FD Work 案件" };
        }
        var name = identityState.selectionProof
            ? String(identityState.selectedLabel || "").trim()
            : identityState.originalName;
        return name
            ? {
                ok: true,
                name: name,
                proof: identityState.selectionProof,
                verifyBinding: !!identityState.selectionProof
            }
            : { ok: false, error: "请先选择 FD Work 案件" };
    }

    function verifyIdentityPersistence(result, saved, project) {
        if (!identityState.selectionProof) return true;
        var binding = (result && result.fd_work_binding) || {};
        return binding.bound === true
            && binding.verified === true
            && !!saved
            && String(saved.name || "") === String(project && project.name || "")
            && saved.fd_work_bound === true;
    }

    function syncIdentityStatus() {
        var enabled = identityEnabled();
        var label = document.getElementById("rules-panel-project-name-label");
        var help = document.getElementById("rules-panel-fd-work-help");
        var input = document.getElementById("rules-panel-project-name");
        if (label) label.textContent = enabled ? "FD Work 案件" : "项目名称";
        if (help) help.hidden = !enabled;
        if (input) {
            input.hidden = enabled;
            input.readOnly = enabled;
        }
        var picker = document.getElementById("rules-panel-fd-work-picker");
        if (picker) picker.hidden = !enabled;
        if (!enabled) resetIdentityEditor();
        refreshRulesWriteState();
    }

    function updateIdentityControls(projectBusy) {
        var pending = identityState.pickerPending;
        var pick = document.getElementById("rules-panel-fd-work-pick");
        var clear = document.getElementById("rules-panel-fd-work-clear");
        if (pick) {
            pick.disabled = projectBusy || pending;
            pick.textContent = pending
                ? "正在打开……"
                : (identityState.originalName || identityState.selectedLabel ? "更换案件" : "选择案件");
        }
        if (clear) {
            clear.disabled = projectBusy || pending;
            clear.hidden = !(identityState.selectionProof || identityState.originalBound);
        }
        return {
            pending: pending,
            hasName: identityEnabled()
                ? !!(identityState.selectionProof
                    || (App.rulesPanelEditingProjectId && identityState.originalName))
                : true
        };
    }

    function bindIdentityEvents() {
        var pick = document.getElementById("rules-panel-fd-work-pick");
        var clear = document.getElementById("rules-panel-fd-work-clear");
        if (pick && pick.getAttribute("data-bound") !== "1") {
            pick.setAttribute("data-bound", "1");
            pick.addEventListener("click", openIdentityPicker);
        }
        if (clear && clear.getAttribute("data-bound") !== "1") {
            clear.setAttribute("data-bound", "1");
            clear.addEventListener("click", clearIdentitySelection);
        }
    }

    App.projectIdentity = Object.freeze({
        bindEvents: bindIdentityEvents,
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
        resetGeneration: resetIdentityEditor
    });
})();
