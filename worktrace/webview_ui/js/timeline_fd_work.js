// WorkTrace WebView frontend — timeline FD Work interaction owner.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    var fdWorkFillTransactionSequence = 0;
    var activeFDWorkFillTransaction = null;
    var fdWorkStatusOverrides = {};

    function fdWorkOperationGeneration() {
        var value = App.fdWorkStatus && App.fdWorkStatus.operation_generation;
        return Number.isInteger(value) ? value : null;
    }

    function fdWorkScope(session) {
        if (!session) return null;
        var key = String(session.projection_instance_key || "");
        var revision = String(session.projection_revision || "");
        if (!key || !revision) return null;
        return Object.freeze({ key: key, revision: revision });
    }

    function currentFDWorkScope() {
        return fdWorkScope(App.timelineEditorState.currentSession());
    }

    function fdWorkScopeId(scope) {
        return scope ? scope.key + "|" + scope.revision : "";
    }

    function sameFDWorkScope(left, right) {
        return !!left && !!right
            && left.key === right.key
            && left.revision === right.revision;
    }

    function getFDWorkStatusOverride(session) {
        var scope = fdWorkScope(session);
        var id = fdWorkScopeId(scope);
        return id ? fdWorkStatusOverrides[id] || null : null;
    }

    function clearFDWorkStatusOverride(scope) {
        var id = fdWorkScopeId(scope);
        if (id) delete fdWorkStatusOverrides[id];
    }

    function clearFDWorkSessionOverrides() {
        Object.keys(fdWorkStatusOverrides).forEach(function (id) {
            if (fdWorkStatusOverrides[id].kind === "session") {
                delete fdWorkStatusOverrides[id];
            }
        });
    }

    function beginFDWorkFillTransaction() {
        var transaction = {
            id: ++fdWorkFillTransactionSequence,
            state: "pending",
            terminalKind: null,
            baselineOperationGeneration: fdWorkOperationGeneration(),
            scope: currentFDWorkScope()
        };
        activeFDWorkFillTransaction = transaction;
        return transaction;
    }

    function currentFDWorkTerminalKind(transaction) {
        if (!transaction || activeFDWorkFillTransaction !== transaction) return null;
        var status = App.fdWorkStatus || {};
        if (
            status.operation !== "none"
            || status.operation_result_owner !== "automation_fill"
            || ["save_completed", "operation_canceled", "failed"]
                .indexOf(status.operation_status) < 0
        ) return null;
        var generation = Number.isInteger(status.operation_generation)
            ? status.operation_generation : null;
        if (
            generation !== null
            && transaction.baselineOperationGeneration !== null
            && generation <= transaction.baselineOperationGeneration
        ) return null;
        return status.operation_status;
    }

    function settleFDWorkFillTransaction(transaction, terminalKind) {
        if (
            !transaction
            || activeFDWorkFillTransaction !== transaction
            || transaction.state !== "pending"
        ) return false;
        transaction.state = "terminal";
        transaction.terminalKind = terminalKind;
        return true;
    }

    function syncFDWorkFillTransactionFromStatus(transaction) {
        var terminalKind = currentFDWorkTerminalKind(transaction);
        if (!terminalKind) return null;
        if (transaction.state === "pending") {
            settleFDWorkFillTransaction(transaction, terminalKind);
        }
        return terminalKind;
    }

    function canFDWorkFillTransactionWrite(transaction) {
        if (!transaction || activeFDWorkFillTransaction !== transaction) return false;
        syncFDWorkFillTransactionFromStatus(transaction);
        return transaction.state === "pending";
    }

    function fdWorkTerminalResult(transaction) {
        return !!(transaction && transaction.terminalKind === "save_completed");
    }

    function fdWorkEnabled() {
        var status = App.fdWorkStatus;
        return !!status
            && status.supported === true
            && status.enabled === true;
    }

    function getFDWorkAvailability(session, options) {
        options = options || {};
        if (!fdWorkEnabled()) {
            return { enabled: false, state: "hidden", reason: "" };
        }
        var capability = App.fdWorkStatus || {};
        var sessionView = typeof App.fdWorkSessionPresentation === "function"
            ? App.fdWorkSessionPresentation(capability)
            : null;
        if (sessionView) {
            if (sessionView.state === "busy") {
                return { enabled: true, state: "busy", reason: sessionView.statusText };
            }
            if (sessionView.state === "unavailable") {
                return { enabled: true, state: "error", reason: sessionView.statusText };
            }
            if (sessionView.state === "blocked") {
                return { enabled: true, state: "disabled", reason: sessionView.statusText };
            }
            if (sessionView.state !== "ready" && sessionView.canStartSession !== true) {
                return { enabled: true, state: "disabled", reason: "FD Work 尚未准备完成" };
            }
        } else {
            if (capability.session_state === "probing") {
                return { enabled: true, state: "busy", reason: "正在连接 FD Work…" };
            }
            if (capability.session_state === "error") {
                return { enabled: true, state: "error", reason: App.fdWorkStatusText(capability) };
            }
            if (capability.interaction_owner && capability.interaction_owner !== "none") {
                return { enabled: true, state: "busy", reason: App.fdWorkStatusText(capability) };
            }
            if (
                capability.ready !== true
                && capability.session_state !== "idle"
                && capability.session_state !== "login_required"
            ) {
                return { enabled: true, state: "disabled", reason: "FD Work 尚未准备完成" };
            }
        }
        if (!session) {
            return { enabled: true, state: "disabled", reason: "请选择一个已结束的时间段" };
        }
        if (session.is_in_progress === true || !session.end_time) {
            return { enabled: true, state: "disabled", reason: "进行中的时间段无法填入 FD Work" };
        }
        if (
            session.row_kind !== "project_session"
            || session.is_report_project !== true
            || session.is_report_uncategorized === true
            || session.is_uncategorized === true
            || session.project_is_deleted === true
        ) return { enabled: true, state: "disabled", reason: "请先为时间段选择项目" };
        var projectName = String(session.project_name || "").trim();
        var narrative = String(session.session_note || "").trim();
        var durationSeconds = Math.max(0, parseInt(session.duration_seconds, 10) || 0);
        if (options.authoritative !== true) {
            var preview = App.timelineEditorState.preview();
            if (
                preview
                && preview.session
                && preview.session.projection_instance_key === session.projection_instance_key
            ) {
                if (!preview.valid) {
                    return { enabled: true, state: "disabled", reason: preview.reason };
                }
                projectName = preview.projectName;
                narrative = preview.narrative;
                durationSeconds = preview.durationSeconds;
            }
        }
        if (!projectName) {
            return { enabled: true, state: "disabled", reason: "请先为时间段选择项目" };
        }
        if (!narrative) {
            return { enabled: true, state: "disabled", reason: "请先填写描述" };
        }
        if (durationSeconds < 360) {
            return { enabled: true, state: "disabled", reason: "时长至少为 0.1 小时" };
        }
        if (durationSeconds > 86040) {
            return { enabled: true, state: "disabled", reason: "该时间段超过 FD Work 允许的 23.9 小时" };
        }
        if (App.timelineEditMutation.lastFailed()) {
            return { enabled: true, state: "error", reason: "上次更改保存失败，请重试" };
        }
        if (!options.ignoreBusy && (
            App.timelineEditMutation.isSaving()
            || App.timelineEditorState.isComposing()
        )) {
            return { enabled: true, state: "busy", reason: "正在保存时间段" };
        }
        if (!options.ignoreBusy && App.mutationState === "unknown") {
            return { enabled: true, state: "error", reason: "上次更改保存失败，请重试" };
        }
        if (!options.ignoreBusy && App.fdWorkOpenPromise) {
            return { enabled: true, state: "busy", reason: "正在打开 FD Work…" };
        }
        var transientOverride = !options.ignoreTransient
            ? getFDWorkStatusOverride(session)
            : null;
        if (transientOverride) return transientOverride;
        var connectionReason = "填入前将先打开 FD Work。";
        if (sessionView && sessionView.state === "auth_required") {
            connectionReason = "填入前将先登录 FD Work。";
        } else if (sessionView && sessionView.state === "retryable") {
            connectionReason = "填入前将先重新连接 FD Work。";
        }
        return {
            enabled: true,
            state: "ready",
            reason: capability.ready === true
                ? "将项目、日期、时长和描述填入并保存到 FD Work。"
                : connectionReason
        };
    }
    App.getFDWorkAvailability = getFDWorkAvailability;

    function showFDWorkStatus(message, isError, options) {
        options = options || {};
        syncFDWorkFillTransactionFromStatus(activeFDWorkFillTransaction);
        var currentScope = currentFDWorkScope();
        if (activeFDWorkFillTransaction
            && activeFDWorkFillTransaction.state === "terminal"
            && currentScope
            && !sameFDWorkScope(activeFDWorkFillTransaction.scope, currentScope)) {
            activeFDWorkFillTransaction = null;
        }
        var scope = options.scope || (
            activeFDWorkFillTransaction && activeFDWorkFillTransaction.state === "pending"
                ? activeFDWorkFillTransaction.scope
                : currentScope
        );
        if (activeFDWorkFillTransaction
            && activeFDWorkFillTransaction.state === "terminal"
            && currentFDWorkTerminalKind(activeFDWorkFillTransaction)) {
            scope = activeFDWorkFillTransaction.scope || scope;
        }
        if (!scope) {
            updateFDWorkEntryButton();
            return;
        }
        if (!message) {
            clearFDWorkStatusOverride(scope);
        } else {
            fdWorkStatusOverrides[fdWorkScopeId(scope)] = Object.freeze({
                enabled: true,
                state: isError ? "error" : "ready",
                reason: message,
                kind: String(options.kind || "selection")
            });
        }
        updateFDWorkEntryButton();
    }
    App.showFDWorkStatus = showFDWorkStatus;

    function onFDWorkStatusChanged(status) {
        if (!status || status.operation !== "none") return;
        var sessionView = typeof App.fdWorkSessionPresentation === "function"
            ? App.fdWorkSessionPresentation(status)
            : null;
        if (!sessionView || ["ready", "connectable", "retryable", "disabled", "unavailable"]
            .indexOf(sessionView.state) < 0) return;
        clearFDWorkSessionOverrides();
    }

    function updateFDWorkEntryButton() {
        var button = document.getElementById("fd-work-entry-btn");
        var area = document.getElementById("fd-work-entry-area");
        var status = document.getElementById("fd-work-status");
        var availability = getFDWorkAvailability(App.timelineEditorState.currentSession());
        if (area) area.hidden = availability.state === "hidden";
        if (button) button.disabled = availability.state !== "ready";
        if (status) {
            status.hidden = availability.state === "hidden";
            status.textContent = availability.reason || "";
            status.className = "inline-status" + (
                availability.state === "error" || availability.state === "disabled"
                    ? " edit-status-error" : ""
            );
        }
    }
    App.updateFDWorkEntryButton = updateFDWorkEntryButton;

    function flushTimelineEditsForFDWork() {
        App.timelineEditorState.cancelAutosave();
        if (App.timelineEditorState.isComposing()) {
            showFDWorkStatus("请先完成当前文字输入", true);
            return Promise.resolve(false);
        }
        if (App.timelineEditMutation.isSaving()) {
            showFDWorkStatus("正在保存时间段…", false);
            return (App.timelineEditMutation.pendingPromise() || Promise.resolve(false)).then(function (ok) {
                if (!ok) return false;
                return flushTimelineEditsForFDWork();
            });
        }
        if (App.timelineEditorState.hasQueuedAutosave() || App.timelineEditorState.isDirty()) {
            App.timelineEditorState.consumeQueuedAutosave();
            showFDWorkStatus("正在保存时间段…", false);
            return App.timelineEditMutation.save().then(function (ok) {
                if (!ok) return false;
                return flushTimelineEditsForFDWork();
            });
        }
        return Promise.resolve(!App.timelineEditMutation.lastFailed());
    }
    App.flushTimelineEditsForFDWork = flushTimelineEditsForFDWork;

    function openFDWorkEntryForSelection() {
        if (App.fdWorkOpenPromise) return App.fdWorkOpenPromise;
        var currentScope = currentFDWorkScope();
        if (activeFDWorkFillTransaction
            && activeFDWorkFillTransaction.state === "terminal"
            && currentScope
            && !sameFDWorkScope(activeFDWorkFillTransaction.scope, currentScope)) {
            activeFDWorkFillTransaction = null;
        }
        clearFDWorkStatusOverride(currentScope);
        var availability = getFDWorkAvailability(App.timelineEditorState.currentSession());
        if (availability.state !== "ready") {
            updateFDWorkEntryButton();
            if (availability.state !== "hidden") showFDWorkStatus(availability.reason, true);
            updateFDWorkEntryButton();
            return Promise.resolve(false);
        }
        var capability = App.fdWorkStatus || {};
        if (capability.ready !== true) {
            if (!App.fdWork || typeof App.fdWork.ensureSession !== "function") {
                showFDWorkStatus("打开 FD Work 失败", true, { kind: "session" });
                return Promise.resolve(false);
            }
            var sessionView = typeof App.fdWorkSessionPresentation === "function"
                ? App.fdWorkSessionPresentation(capability)
                : null;
            var connectingMessage = sessionView && sessionView.state === "auth_required"
                ? "请登录 FD Work"
                : (sessionView && sessionView.state === "retryable"
                    ? "正在重新连接 FD Work…"
                    : "正在连接 FD Work…");
            showFDWorkStatus(connectingMessage, false, { kind: "session" });
            var sessionOperation = App.fdWork.ensureSession().then(function (result) {
                if (!result || result.ok !== true) {
                    showFDWorkStatus(
                        result && result.message || "打开 FD Work 失败",
                        true,
                        { kind: "session" }
                    );
                    return false;
                }
                var latest = App.fdWorkStatus || {};
                if (latest.ready === true) {
                    showFDWorkStatus(
                        "FD Work 已连接，请再次点击填入",
                        false,
                        { kind: "session" }
                    );
                } else if (latest.operation === "user_auth") {
                    showFDWorkStatus(
                        latest.page_phase === "login_confirmation"
                            ? "请确认登录"
                            : "请登录 FD Work",
                        false,
                        { kind: "session" }
                    );
                } else {
                    showFDWorkStatus("正在连接 FD Work…", false, { kind: "session" });
                }
                return false;
            }).finally(function () {
                if (App.fdWorkOpenPromise === sessionOperation) App.fdWorkOpenPromise = null;
                updateFDWorkEntryButton();
            });
            App.fdWorkOpenPromise = sessionOperation;
            updateFDWorkEntryButton();
            return sessionOperation;
        }
        var transaction = beginFDWorkFillTransaction();
        showFDWorkStatus(
            App.timelineEditorState.isDirty() || App.timelineEditMutation.isSaving()
                ? "正在保存时间段…" : "正在填入 FD Work…",
            false
        );
        var operation = flushTimelineEditsForFDWork().then(function (saved) {
            if (!canFDWorkFillTransactionWrite(transaction)) {
                return fdWorkTerminalResult(transaction);
            }
            if (!saved) {
                settleFDWorkFillTransaction(transaction, "failed");
                showFDWorkStatus("保存失败，未打开 FD Work", true);
                return false;
            }
            var selectionKey = String(App.selectedProjectionInstanceKey || "");
            return openResolvedFDWorkSelection(selectionKey, true, transaction);
        }).finally(function () {
            if (App.fdWorkOpenPromise === operation) App.fdWorkOpenPromise = null;
            updateFDWorkEntryButton();
        });
        App.fdWorkOpenPromise = operation;
        updateFDWorkEntryButton();
        return operation;
    }
    App.openFDWorkEntryForSelection = openFDWorkEntryForSelection;

    function resolveSelectedFDWorkSession(selectionKey) {
        var matches = (App.currentSessions || []).filter(function (session) {
            return String(session.projection_instance_key || "") === selectionKey;
        });
        if (matches.length !== 1) return null;
        var availability = getFDWorkAvailability(matches[0], {
            authoritative: true,
            ignoreBusy: true,
            ignoreTransient: true
        });
        if (availability.state !== "ready") {
            showFDWorkStatus(availability.reason || "当前时间段已变化，请重新选择", true);
            return null;
        }
        return matches[0];
    }
    App.resolveSelectedFDWorkSession = resolveSelectedFDWorkSession;

    function openResolvedFDWorkSelection(selectionKey, allowStaleRecovery, transaction) {
        if (!canFDWorkFillTransactionWrite(transaction)) {
            return Promise.resolve(fdWorkTerminalResult(transaction));
        }
        var session = resolveSelectedFDWorkSession(selectionKey);
        var reportDate = App.currentTimelineReportDate();
        var revision = String(session ? session.projection_revision || "" : "");
        if (!session || !reportDate || !selectionKey || !revision) {
            if (canFDWorkFillTransactionWrite(transaction)) {
                settleFDWorkFillTransaction(transaction, "failed");
                showFDWorkStatus("当前时间段已变化，请重新选择", true);
            }
            return Promise.resolve(false);
        }
        showFDWorkStatus("正在填入 FD Work…", false);
        return App.bridge.openFDWorkEntry(reportDate, selectionKey, revision).then(function (result) {
            if (!canFDWorkFillTransactionWrite(transaction)) {
                return fdWorkTerminalResult(transaction);
            }
            if (result && result.ok === true) {
                if (result.operation_status === "save_completed") {
                    settleFDWorkFillTransaction(transaction, "save_completed");
                    showFDWorkStatus("已保存到 FD Work", false);
                    return true;
                }
                settleFDWorkFillTransaction(transaction, "failed");
                showFDWorkStatus("FD Work 操作结果未确认，请重试", true);
                return false;
            }
            if (result && result.error === "stale_selection" && allowStaleRecovery) {
                showFDWorkStatus("时间段已更新，正在刷新…", false);
                return App.loadTimelineReport(reportDate, {
                    showLoading: false,
                    resetSelection: false,
                    rejectOnError: true,
                    errorMessage: "刷新失败，未打开 FD Work"
                }).then(function () {
                    if (!canFDWorkFillTransactionWrite(transaction)) {
                        return fdWorkTerminalResult(transaction);
                    }
                    return openResolvedFDWorkSelection(selectionKey, false, transaction);
                }).catch(function () {
                    if (!canFDWorkFillTransactionWrite(transaction)) {
                        return fdWorkTerminalResult(transaction);
                    }
                    settleFDWorkFillTransaction(transaction, "failed");
                    showFDWorkStatus("刷新失败，未打开 FD Work", true);
                    return false;
                });
            }
            settleFDWorkFillTransaction(transaction, "failed");
            showFDWorkStatus(
                result && result.message ? result.message : "打开 FD Work 失败",
                true
            );
            return false;
        }).catch(function () {
            if (!canFDWorkFillTransactionWrite(transaction)) {
                return fdWorkTerminalResult(transaction);
            }
            settleFDWorkFillTransaction(transaction, "failed");
            showFDWorkStatus("打开 FD Work 失败", true);
            return false;
        });
    }

    App.resetTimelineFDWorkState = function () {
        activeFDWorkFillTransaction = null;
        fdWorkStatusOverrides = {};
        App.fdWorkOpenPromise = null;
    };
    App.timelineFDWork = Object.freeze({
        onStatusChanged: onFDWorkStatusChanged
    });
})();