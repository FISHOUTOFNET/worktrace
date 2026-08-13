// Applies a newly created folder or keyword rule to eligible history.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function backfillCreatedRule(ruleType, ruleId) {
        if (ruleType !== "folder" && ruleType !== "keyword") return Promise.resolve(false);
        var parsedId = parseInt(ruleId, 10);
        if (!(parsedId > 0)) return Promise.resolve(false);
        App.rulesBackfillingRuleKey = ruleType + ":" + parsedId;
        return App.bridge.backfillProjectRule(ruleType, parsedId).then(function (result) {
            return !(result && result.ok === false);
        }).catch(function () {
            return false;
        }).then(function (ok) {
            App.rulesBackfillingRuleKey = null;
            return ok;
        });
    }
    App.backfillCreatedRule = backfillCreatedRule;
})();

// Owns the editable FD Work project-identity draft without changing the generic
// project-rules editor or the timeline FD Work gate.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var installed = false;
    var baseInitRulesPanelEvents = App.initRulesPanelEvents;

    function installFDWorkProjectIdentityLifecycle() {
        if (installed || !App.projectIdentity || !App.bridge) return false;
        installed = true;
        var baseIdentity = App.projectIdentity;
        var baseBridge = App.bridge;
        var baseFDWork = App.fdWork || {};
        var host = { onStateChanged: function () {}, onBindingChanged: function () {} };
        var state = {
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
            pickerCanceling: false,
            pickerCounter: 0,
            clearBindingOnSave: false,
            saveIntent: "local"
        };

        function projectNameInput() { return document.getElementById("rules-panel-project-name"); }
        function showStatus(message, error) {
            var target = document.getElementById("rules-panel-fd-work-status");
            if (!target) return;
            target.hidden = !message;
            target.textContent = message || "";
            target.className = "inline-status" + (error ? " edit-status-error" : "");
        }
        function refresh() { try { host.onStateChanged(); } catch (_error) {} }
        function clearPickerTransient() {
            state.pickerRequestId = null;
            state.pickerEditorGeneration = null;
            state.pickerPending = false;
            state.pickerCanceling = false;
        }
        function currentPicker(requestId, generation) {
            return requestId === state.pickerRequestId
                && generation === state.pickerEditorGeneration
                && generation === state.editorGeneration;
        }
        function callCancel(requestId) {
            if (!requestId || !App.bridge || typeof App.bridge.openFDWorkCasePicker !== "function") {
                return Promise.resolve({ ok: false, accepted: false });
            }
            return Promise.resolve(App.bridge.openFDWorkCasePicker(requestId, "cancel")).catch(function () {
                return { ok: false, accepted: false };
            });
        }
        function cancelPicker(detach) {
            if (!state.pickerPending || !state.pickerRequestId) return Promise.resolve(false);
            var requestId = state.pickerRequestId;
            var generation = state.pickerEditorGeneration;
            if (detach) {
                clearPickerTransient();
                refresh();
                void callCancel(requestId);
                return Promise.resolve(true);
            }
            if (state.pickerCanceling) return Promise.resolve(true);
            state.pickerCanceling = true;
            showStatus("正在取消案件选择…", false);
            refresh();
            return callCancel(requestId).then(function (result) {
                if (!currentPicker(requestId, generation)) return true;
                if (result && result.ok === true && result.accepted === true) return true;
                clearPickerTransient();
                showStatus("案件选择已取消", false);
                refresh();
                return true;
            });
        }
        function reset() {
            if (state.pickerPending) cancelPicker(true);
            state.editorGeneration += 1;
            state.selectionProof = null;
            state.selectedLabel = "";
            state.originalName = "";
            state.originalBound = false;
            state.editingProjectId = null;
            state.projectBusy = false;
            state.clearBindingOnSave = false;
            state.saveIntent = "local";
            clearPickerTransient();
            if (baseIdentity && typeof baseIdentity.reset === "function") baseIdentity.reset();
            showStatus("", false);
        }
        function prepareEditor(project) {
            reset();
            if (baseIdentity && typeof baseIdentity.prepareEditor === "function") baseIdentity.prepareEditor(project);
            var projectId = Number(project && project.id);
            state.editingProjectId = Number.isInteger(projectId) && projectId > 0 ? projectId : null;
            state.originalName = project ? App.safeText(project.name, "") : "";
            state.originalBound = !!(project && project.fd_work_bound === true);
            state.clearBindingOnSave = false;
            if (state.originalBound) showStatus("已关联 FD Work", false);
        }
        function enabled() { return (App.fdWorkStatus || {}).enabled === true; }
        function openPicker() {
            if (state.projectBusy || !enabled()) return;
            if (state.pickerPending) {
                void cancelPicker(false);
                return;
            }
            var generation = state.editorGeneration;
            var requestId = "rules-picker-" + generation + "-" + (++state.pickerCounter);
            state.pickerPending = true;
            state.pickerCanceling = false;
            state.pickerRequestId = requestId;
            state.pickerEditorGeneration = generation;
            showStatus("正在打开案件选择器…", false);
            refresh();
            Promise.resolve(baseBridge.openFDWorkCasePicker(requestId)).then(function (result) {
                if (!currentPicker(requestId, generation)) return;
                if (!result || result.ok === false) {
                    clearPickerTransient();
                    showStatus(result && result.message || "打开案件选择器失败", true);
                    refresh();
                    return;
                }
                showStatus(
                    result.operation_status === "authentication_required"
                        ? "请登录 FD Work"
                        : "请在 FD Work 中选择案件",
                    false
                );
                refresh();
            }).catch(function () {
                if (!currentPicker(requestId, generation)) return;
                clearPickerTransient();
                showStatus("打开案件选择器失败", true);
                refresh();
            });
        }
        function clearSelection() {
            if (state.pickerPending) return;
            if (state.selectionProof) {
                state.selectionProof = null;
                state.selectedLabel = "";
                state.clearBindingOnSave = false;
                if (state.originalBound) {
                    var input = projectNameInput();
                    if (input) input.value = state.originalName;
                    showStatus("已关联 FD Work", false);
                } else {
                    showStatus("", false);
                }
                refresh();
                return;
            }
            if (state.originalBound) {
                state.clearBindingOnSave = !state.clearBindingOnSave;
                showStatus(
                    state.clearBindingOnSave ? "保存后取消 FD Work 关联" : "已关联 FD Work",
                    false
                );
                refresh();
            }
        }
        function receivePickerResult(result) {
            if (!result || typeof result !== "object") return false;
            var generation = state.pickerEditorGeneration;
            if (!currentPicker(result.request_id, generation)) return false;
            clearPickerTransient();
            if (result.ok !== true) {
                showStatus(
                    result.error === "picker_canceled" ? "案件选择已取消" : "案件选择已失效",
                    result.error !== "picker_canceled"
                );
                refresh();
                return true;
            }
            if (typeof result.selected_label !== "string" || !result.selected_label
                || typeof result.selection_token !== "string" || !result.selection_token) {
                showStatus("案件选择结果无效", true);
                refresh();
                return false;
            }
            state.selectedLabel = result.selected_label.trim();
            state.selectionProof = result.selection_token;
            state.clearBindingOnSave = false;
            var input = projectNameInput();
            if (input) input.value = state.selectedLabel;
            showStatus("已选择 FD Work 案件", false);
            refresh();
            return true;
        }
        function handleNameInput() {
            var input = projectNameInput();
            var name = String(input && input.value || "").trim();
            if (state.selectionProof && name !== String(state.selectedLabel || "").trim()) {
                state.selectionProof = null;
                state.selectedLabel = "";
            }
            if (!enabled()) showStatus("", false);
            else if (state.selectionProof) showStatus("已选择 FD Work 案件", false);
            else if (state.clearBindingOnSave) showStatus("保存后取消 FD Work 关联", false);
            else if (state.originalBound && name === state.originalName) showStatus("已关联 FD Work", false);
            else if (state.originalBound && name !== state.originalName) showStatus("名称已修改，保存后将取消 FD Work 关联", false);
            else showStatus("", false);
            refresh();
        }
        function buildSavePayload(localName, editing) {
            var name = String(localName || "").trim();
            if (!name) {
                state.saveIntent = "local";
                return { ok: false, error: "请输入项目名称" };
            }
            if (!enabled()) {
                state.selectionProof = null;
                state.selectedLabel = "";
                state.clearBindingOnSave = false;
                state.saveIntent = "local";
                return { ok: true, name: name, proof: null, clearBinding: false, verifyBinding: false };
            }
            if (state.selectionProof) {
                var selected = String(state.selectedLabel || "").trim();
                if (name === selected) {
                    state.saveIntent = "external";
                    return {
                        ok: true,
                        name: selected,
                        proof: state.selectionProof,
                        clearBinding: false,
                        verifyBinding: true
                    };
                }
                state.selectionProof = null;
                state.selectedLabel = "";
            }
            if (editing && state.originalBound && state.clearBindingOnSave) {
                state.saveIntent = "clear";
                return { ok: true, name: name, proof: null, clearBinding: true, verifyBinding: true };
            }
            if (editing && state.originalBound && name === state.originalName) state.saveIntent = "preserve";
            else state.saveIntent = "local";
            return { ok: true, name: name, proof: null, clearBinding: false, verifyBinding: false };
        }
        function verifyPersistence(result, saved, project) {
            if (state.saveIntent === "external") {
                var binding = result && result.fd_work_binding || {};
                return !!saved
                    && String(saved.name || "") === String(project && project.name || "")
                    && binding.bound === true
                    && binding.verified === true
                    && saved.fd_work_bound === true;
            }
            if (state.saveIntent === "clear") {
                var cleared = result && result.fd_work_binding || {};
                return !!saved && saved.fd_work_bound !== true && cleared.bound !== true;
            }
            if (state.saveIntent === "preserve") return !!saved && saved.fd_work_bound === true;
            return true;
        }
        function syncStatus() {
            var capability = App.fdWorkStatus || {};
            var input = projectNameInput();
            var picker = document.getElementById("rules-panel-fd-work-picker");
            if (picker) picker.hidden = !enabled();
            if (!enabled() || capability.session_state === "shutdown") {
                state.selectionProof = null;
                state.selectedLabel = "";
                state.clearBindingOnSave = false;
                if (state.pickerPending) clearPickerTransient();
                showStatus("", false);
            } else if (state.pickerPending) {
                if (state.pickerCanceling) showStatus("正在取消案件选择…", false);
                else if (capability.operation === "user_auth") {
                    showStatus(
                        capability.page_phase === "login_confirmation" ? "请确认登录" : "请登录 FD Work",
                        false
                    );
                } else if (capability.operation === "user_picker") {
                    showStatus("请在 FD Work 中选择案件", false);
                } else if (capability.session_state === "error") {
                    clearPickerTransient();
                    showStatus(App.fdWorkStatusText(capability), true);
                }
            }
            if (input) input.readOnly = state.pickerPending;
            refresh();
        }
        function updateControls(projectBusy) {
            state.projectBusy = !!projectBusy;
            var pending = state.pickerPending;
            var pick = document.getElementById("rules-panel-fd-work-pick");
            var clear = document.getElementById("rules-panel-fd-work-clear");
            var input = projectNameInput();
            var name = String(input && input.value || "").trim();
            if (input) input.readOnly = pending;
            if (pick) {
                pick.disabled = state.projectBusy || state.pickerCanceling || !enabled();
                pick.textContent = pending
                    ? "取消选择"
                    : (state.selectionProof || state.originalBound ? "更换案件" : "选择案件");
            }
            if (clear) {
                clear.disabled = state.projectBusy || pending;
                clear.hidden = !(state.selectionProof || state.originalBound);
                clear.textContent = state.selectionProof
                    ? "取消选择"
                    : (state.clearBindingOnSave ? "保持关联" : "取消关联");
            }
            return { pending: pending, hasName: !!name };
        }
        function bindHost(nextHost) {
            nextHost = nextHost || {};
            host = {
                onStateChanged: typeof nextHost.onStateChanged === "function"
                    ? nextHost.onStateChanged
                    : function () {},
                onBindingChanged: typeof nextHost.onBindingChanged === "function"
                    ? nextHost.onBindingChanged
                    : function () {}
            };
            if (baseIdentity && typeof baseIdentity.bindHost === "function") baseIdentity.bindHost(nextHost);
        }
        function intercept(node, eventName, handler, marker) {
            if (!node || node.getAttribute(marker) === "1") return;
            node.setAttribute(marker, "1");
            node.addEventListener(eventName, function (event) {
                if (event.stopImmediatePropagation) event.stopImmediatePropagation();
                handler(event);
            }, true);
        }
        function bindEvents() {
            intercept(
                document.getElementById("rules-panel-fd-work-pick"),
                "click",
                openPicker,
                "data-fd-work-picker-lifecycle"
            );
            intercept(
                document.getElementById("rules-panel-fd-work-clear"),
                "click",
                clearSelection,
                "data-fd-work-clear-lifecycle"
            );
            intercept(
                projectNameInput(),
                "input",
                handleNameInput,
                "data-fd-work-name-lifecycle"
            );
            if (baseIdentity && typeof baseIdentity.bindEvents === "function") baseIdentity.bindEvents();
        }
        function updateProjectForRules(projectId, name, description, language, proof) {
            var explicitClear = state.clearBindingOnSave === true
                && Number(projectId) === Number(state.editingProjectId)
                && !proof;
            return Promise.resolve(
                baseBridge.updateProjectForRules(projectId, name, description, language, proof)
            ).then(function (result) {
                if (!explicitClear || !result || result.ok === false) return result;
                return Promise.resolve(baseBridge.clearFDWorkBindingForRules(projectId)).then(function (cleared) {
                    if (!cleared || cleared.ok === false) {
                        return { ok: false, error: "项目已保存，但取消 FD Work 关联失败" };
                    }
                    return Object.assign({}, result, {
                        fd_work_binding: cleared.fd_work_binding || { bound: false }
                    });
                }).catch(function () {
                    return { ok: false, error: "项目已保存，但取消 FD Work 关联失败" };
                });
            });
        }

        App.bridge = Object.freeze(Object.assign({}, baseBridge, {
            updateProjectForRules: updateProjectForRules
        }));
        App.projectIdentity = Object.freeze({
            enabled: enabled,
            bindHost: bindHost,
            bindEvents: bindEvents,
            prepareEditor: prepareEditor,
            reset: reset,
            syncStatus: syncStatus,
            updateControls: updateControls,
            buildSavePayload: buildSavePayload,
            verifyPersistence: verifyPersistence,
            openPicker: openPicker,
            clearSelection: clearSelection,
            cancelPicker: function () { return cancelPicker(false); },
            _testState: function () { return state; }
        });
        App.receiveFDWorkCasePickerResult = receivePickerResult;
        App.fdWork = Object.freeze(Object.assign({}, baseFDWork, { resetGeneration: reset }));
        return true;
    }

    App.installFDWorkProjectIdentityLifecycle = installFDWorkProjectIdentityLifecycle;
    App.initRulesPanelEvents = function () {
        installFDWorkProjectIdentityLifecycle();
        if (typeof baseInitRulesPanelEvents === "function") {
            return baseInitRulesPanelEvents.apply(this, arguments);
        }
    };
})();
