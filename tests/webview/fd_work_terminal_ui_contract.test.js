const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { TIMELINE_MODULES, loadTimelineModules } = require("./timeline_test_modules");

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
        appendChild() {},
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

  for (const file of ["fd_work_v5.js", ...TIMELINE_MODULES, "ui_composition.js"]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
      context,
      { filename: file }
    );
  }
  return { App, element };
}

function readySession(overrides = {}) {
  return {
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
    ...overrides,
  };
}

function selectSession(App, element, session) {
  App.timelineEditorState.populate(session);
  App.currentSessions = [session];
  App.mutationState = "idle";
  App.fdWorkOpenPromise = null;
  const project = element("edit-project-select");
  project.value = String(session.project_id || 17);
  project.options = [{ textContent: session.project_name || "CASE-001" }];
  project.selectedIndex = 0;
  element("edit-note-text").value = session.session_note || "Narrative";
  element("edit-duration-input").value = "1.0";
  App.updateFDWorkEntryButton();
}

function configureReadySession(App, element) {
  const session = readySession();
  selectSession(App, element, session);
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
  return session;
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

test("uncertain save outcome is scoped to the exact Timeline selection revision", () => {
  const { App, element } = harness();
  const sessionA = configureReadySession(App, element);
  assert.equal(App.receiveFDWorkStatus(terminalStatus("save_outcome_unknown", 2)), true);
  assert.equal(App.getFDWorkAvailability(sessionA).state, "error");

  const sessionB = readySession({
    projection_instance_key: "base:b",
    projection_revision: "rev-b",
    project_id: 18,
    project_name: "CASE-002",
  });
  selectSession(App, element, sessionB);
  assert.equal(App.getFDWorkAvailability(sessionB).state, "ready");
  assert.equal(element("fd-work-entry-btn").disabled, false);

  selectSession(App, element, sessionA);
  assert.equal(App.getFDWorkAvailability(sessionA).state, "error");
  assert.equal(element("fd-work-entry-btn").disabled, true);

  const rebasedA = readySession({ projection_revision: "rev-a-2" });
  selectSession(App, element, rebasedA);
  assert.equal(App.getFDWorkAvailability(rebasedA).state, "ready");
  assert.equal(element("fd-work-entry-btn").disabled, false);
});

test("recoverable session error keeps Timeline entry actionable", () => {
  const { App, element } = harness();
  const session = configureReadySession(App, element);

  assert.equal(App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "error",
    operation: "none",
    interaction_owner: "none",
    ready: false,
    login_required: false,
    error_code: "session_start_timeout",
    operation_generation: 2,
    navigation_generation: 8,
  }), true);

  const availability = App.getFDWorkAvailability(session);
  assert.equal(availability.state, "ready");
  assert.match(availability.reason, /重新连接/);
  assert.equal(element("fd-work-entry-btn").disabled, false);
});

test("renderer unavailable remains a fatal Timeline session error", () => {
  const { App, element } = harness();
  const session = configureReadySession(App, element);

  assert.equal(App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "error",
    operation: "none",
    interaction_owner: "none",
    ready: false,
    login_required: false,
    error_code: "renderer_unavailable",
    operation_generation: 2,
    navigation_generation: 8,
  }), true);

  const availability = App.getFDWorkAvailability(session);
  assert.equal(availability.state, "error");
  assert.match(availability.reason, /WebView2/);
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