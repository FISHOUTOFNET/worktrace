const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { TIMELINE_MODULES, loadTimelineModules } = require("./timeline_test_modules");

function source(name) {
  return fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js", name),
    "utf8"
  );
}

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
        options: [],
        selectedIndex: 0,
        classList: {
          add() {}, remove() {}, contains() { return false; }, toggle() {},
        },
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
    Number,
    String,
    Math,
    Date,
    parseInt,
    setTimeout,
    clearTimeout,
    performance: { now() { return 0; } },
    window: {
      WorkTraceApp: {},
      setTimeout,
      clearTimeout,
      console,
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
  const calls = { login: [], entry: [] };
  let loginResult = null;
  let entryResult = null;

  App.bridge = {
    showFDWorkLogin(...args) {
      calls.login.push(args);
      return Promise.resolve(loginResult);
    },
    openFDWorkEntry(...args) {
      calls.entry.push(args);
      return Promise.resolve(entryResult);
    },
  };

  vm.runInContext(source("fd_work_v5.js"), context, { filename: "fd_work_v5.js" });
  loadTimelineModules(context, __dirname);

  return {
    App,
    element,
    calls,
    setLoginResult(value) { loginResult = value; },
    setEntryResult(value) { entryResult = value; },
  };
}

function status(overrides = {}) {
  return Object.assign({
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "none",
    interaction_owner: "none",
    ready: true,
    login_required: false,
    error_code: null,
    page_phase: "work_shell",
    operation_generation: 0,
    navigation_generation: 1,
  }, overrides);
}

function configureValidSelection(App, element) {
  const session = {
    row_kind: "project_session",
    projection_instance_key: "base:a",
    projection_revision: "rev-old",
    project_id: 17,
    project_name: "CASE-001",
    is_report_project: true,
    is_report_uncategorized: false,
    is_uncategorized: false,
    project_is_deleted: false,
    is_in_progress: false,
    end_time: "2026-08-11 10:00:00",
    session_note: "Saved narrative",
    duration_seconds: 5040,
    adjusted_duration_seconds: null,
    has_duration_override: false,
    can_edit_project: true,
    can_edit_note: true,
    can_edit_duration: true,
  };
  App.timelineDate = "2026-08-11";
  App.editingSession = session;
  App.currentSessions = [session];
  App.selectedProjectionInstanceKey = session.projection_instance_key;
  App.selectedProjectionRevision = session.projection_revision;
  App.projectsCache = [{ id: 17, name: "CASE-001", fd_work_bound: true }];
  App.timelineLastSaveFailed = false;
  App.editSaving = false;
  App.timelineCompositionActive = false;
  App.timelineDurationDraftTouched = false;
  App.timelineDurationDraftInvalid = false;
  App.mutationState = "idle";

  const project = element("edit-project-select");
  project.value = "17";
  project.options = [{ textContent: "CASE-001" }];
  project.selectedIndex = 0;
  element("edit-note-text").value = session.session_note;
  element("edit-duration-input").value = "1.4";
  element("timeline-date-input").value = "2026-08-11";
  return session;
}

test("logged-out Timeline click prepares session but never opens an entry", async () => {
  const { App, element, calls, setLoginResult } = harness();
  configureValidSelection(App, element);
  App.receiveFDWorkStatus(status({
    session_state: "login_required",
    ready: false,
    login_required: true,
    error_code: "login_required",
    page_phase: "login_credentials",
  }));
  setLoginResult({
    ok: true,
    capability_status: status({
      session_state: "login_required",
      operation: "user_auth",
      interaction_owner: "user_auth",
      ready: false,
      login_required: true,
      error_code: "login_required",
      page_phase: "login_credentials",
      operation_generation: 1,
    }),
  });

  const result = await App.openFDWorkEntryForSelection();

  assert.equal(result, false);
  assert.equal(calls.login.length, 1);
  assert.equal(calls.entry.length, 0);
  assert.match(element("fd-work-status").textContent, /登录/);
});

test("after login the next click fills using the latest projection revision", async () => {
  const { App, element, calls, setLoginResult, setEntryResult } = harness();
  const session = configureValidSelection(App, element);
  App.receiveFDWorkStatus(status({
    session_state: "login_required",
    ready: false,
    login_required: true,
    error_code: "login_required",
    page_phase: "login_credentials",
  }));
  setLoginResult({
    ok: true,
    capability_status: status({
      session_state: "login_required",
      operation: "user_auth",
      interaction_owner: "user_auth",
      ready: false,
      login_required: true,
      error_code: "login_required",
      page_phase: "login_credentials",
      operation_generation: 1,
    }),
  });

  assert.equal(await App.openFDWorkEntryForSelection(), false);
  assert.equal(calls.entry.length, 0);

  App.receiveFDWorkStatus(status({
    session_state: "ready",
    ready: true,
    login_required: false,
    error_code: null,
    page_phase: "work_shell",
    operation_generation: 2,
    navigation_generation: 2,
  }));
  session.projection_revision = "rev-new";
  App.selectedProjectionRevision = "rev-new";
  setEntryResult({ ok: true, operation_status: "save_completed" });

  const result = await App.openFDWorkEntryForSelection();

  assert.equal(result, true);
  assert.equal(calls.login.length, 1);
  assert.equal(calls.entry.length, 1);
  assert.deepEqual(calls.entry[0], ["2026-08-11", "base:a", "rev-new"]);
});

test("Settings composition delegates reconnect to the shared FD Work session action", () => {
  const composition = source("ui_composition.js");
  const operations = source("settings_data_operations.js");
  assert.doesNotMatch(composition, /App\.reconnectFDWork\s*=/);
  assert.match(operations, /App\.fdWork\.ensureSession\(\)/);
  assert.doesNotMatch(operations, /App\.bridge\.showFDWorkLogin/);
});
