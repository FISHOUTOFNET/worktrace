const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        hidden: false,
        disabled: false,
        readOnly: false,
        value: "",
        textContent: "",
        innerHTML: "",
        className: "",
        options: null,
        selectedIndex: 0,
        classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
        setAttribute() {}, removeAttribute() {}, getAttribute() { return ""; },
        querySelectorAll() { return []; },
        querySelector() { return null; },
        addEventListener() {},
      });
    }
    return elements.get(id);
  }
  const context = {
    Promise,
    Error,
    Uint8Array,
    setTimeout,
    clearTimeout,
    window: {
      WorkTraceApp: {},
      crypto: { randomUUID: (() => { let n = 0; return () => `request-${++n}`; })() },
    },
    document: {
      getElementById: element,
      querySelectorAll() { return []; },
      querySelector() { return null; },
      createElement() { return element(`created-${elements.size}`); },
    },
  };
  vm.createContext(context);
  const App = context.window.WorkTraceApp;
  const bridgeCall = (method) => (...args) => {
    if (typeof App.callBridge !== "function") {
      return Promise.reject(new Error(`missing bridge handler: ${method}`));
    }
    return App.callBridge(method, ...args);
  };
  App.bridge = {
    openFDWorkEntry: bridgeCall("open_fd_work_entry"),
    listProjectsForTimeline: bridgeCall("list_projects_for_timeline"),
    getTimelineSessionActivitySummary: bridgeCall("get_timeline_session_activity_summary"),
    saveTimelineSessionEdit: bridgeCall("save_timeline_session_edit"),
  };
  App.timelineRequestState = {
    nextMutationOwner() { return null; },
    nextSelectionOwner() { return null; },
    releaseMutationOwner() {},
    transitionMutation() {},
    isCurrentMutationOwner() { return false; },
    markMutationUnknown() {},
  };
  App.normalizeTimelineDurationInput = undefined;
  App.formatDuration = () => "";
  App.escapeHtml = (value) => String(value || "");
  App.validateLiveClock = () => null;
  App.recordLiveClockContractViolation = () => {};
  App.renderDurationProjected = () => {};
  App.renderCurrentActivityElement = () => {};
  App.clearLiveClockTarget = () => {};
  App.setLiveClockTarget = () => {};
  App.acceptLiveRuntimePayload = () => true;

  for (const file of ["fd_work_v5.js", "timeline.js", "ui_composition.js"]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
      context,
      { filename: file }
    );
  }
  return { App, element };
}

function configureReadySession(App, element) {
  const session = {
    row_kind: "project_session",
    projection_instance_key: "base:a",
    projection_revision: "rev-a",
    project_id: 17,
    project_name: "CASE-001",
    is_report_project: true,
    is_report_uncategorized: false,
    is_uncategorized: false,
    project_is_deleted: false,
    is_in_progress: false,
    end_time: "2026-08-08 10:00:00",
    session_note: "Narrative",
    duration_seconds: 3600,
    can_edit_project: true,
    can_edit_note: true,
    can_edit_duration: true,
  };
  App.editingSession = session;
  App.currentSessions = [session];
  App.timelineLastSaveFailed = false;
  App.editSaving = false;
  App.timelineCompositionActive = false;
  App.mutationState = "idle";
  App.fdWorkOpenPromise = null;
  App.lastSettingsStatus = { fd_work: { supported: true, enabled: true } };
  const project = element("edit-project-select");
  project.value = "17";
  project.options = [{ textContent: "CASE-001" }];
  project.selectedIndex = 0;
  element("edit-note-text").value = "Narrative";
  element("edit-duration-input").value = "1.0";
  App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "none",
    interaction_owner: "none",
    ready: true,
    login_required: false,
    error_code: null,
    operation_generation: 1,
    navigation_generation: 7,
  });
}

function terminalStatus(errorCode, generation) {
  return {
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "none",
    interaction_owner: "none",
    ready: true,
    login_required: false,
    error_code: errorCode,
    operation_status: "failed",
    operation_result_owner: "automation_fill",
    operation_generation: generation,
    navigation_generation: 7,
  };
}

test("ordinary fill failure remains retryable when capability is otherwise ready", () => {
  const { App, element } = harness();
  configureReadySession(App, element);

  assert.equal(App.receiveFDWorkStatus(terminalStatus("entry_editor_not_rendered", 2)), true);

  assert.match(element("fd-work-status").textContent, /失败.*重试/);
  assert.equal(element("fd-work-entry-btn").disabled, false);
});

test("uncertain save outcome blocks blind retry and tells user to verify FD Work", () => {
  const { App, element } = harness();
  configureReadySession(App, element);

  assert.equal(App.receiveFDWorkStatus(terminalStatus("save_outcome_unknown", 2)), true);

  assert.match(element("fd-work-status").textContent, /结果未确认/);
  assert.match(element("fd-work-status").textContent, /不要重复填入/);
  assert.equal(element("fd-work-entry-btn").disabled, true);
});

test("same-navigation older operation status cannot overwrite a newer fill", () => {
  const { App, element } = harness();
  configureReadySession(App, element);
  assert.equal(App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "automation_fill",
    interaction_owner: "automation_fill",
    ready: true,
    login_required: false,
    error_code: null,
    operation_status: "pending",
    operation_result_owner: "automation_fill",
    operation_generation: 5,
    navigation_generation: 7,
  }), true);

  assert.equal(App.receiveFDWorkStatus(terminalStatus("entry_editor_not_rendered", 4)), false);
  assert.equal(App.fdWorkStatus.operation, "automation_fill");
  assert.equal(App.fdWorkStatus.operation_generation, 5);
  assert.doesNotMatch(element("fd-work-status").textContent, /失败.*重试/);
});
