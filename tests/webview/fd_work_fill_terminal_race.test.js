const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
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
    openFDWorkCasePicker: bridgeCall("open_fd_work_case_picker"),
  };

  for (const file of ["fd_work_v5.js", "timeline.js", "ui_composition.js"]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
      context,
      { filename: file }
    );
  }
  return { App, element };
}

function configureFDWorkSession(App, element) {
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
    end_time: "2026-07-12 10:00:00",
    session_note: "Saved narrative",
    duration_seconds: 5040,
    adjusted_duration_seconds: null,
    has_duration_override: false,
    can_edit_project: true,
    can_edit_note: true,
    can_edit_duration: true,
  };
  App.timelineDate = "2026-07-12";
  App.editingSession = session;
  App.selectedProjectionInstanceKey = session.projection_instance_key;
  App.selectedProjectionRevision = session.projection_revision;
  App.currentSessions = [session];
  App.lastTimelineData = {
    date: "2026-07-12",
    structure_revision: "source-a",
    entries: [session],
  };
  App.lastSettingsStatus = { fd_work: { supported: true, enabled: true } };
  App.projectsCache = [{ id: 17, name: "CASE-001", fd_work_bound: true }];
  App.timelineLastSaveFailed = false;
  App.editSaving = false;
  App.timelineCompositionActive = false;
  App.mutationState = "idle";
  element("edit-project-select").value = "17";
  element("edit-note-text").value = session.session_note;
  element("edit-duration-input").value = "1.4";
  App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "none",
    interaction_owner: "none",
    ready: true,
    login_required: false,
    error_code: null,
    operation_generation: 0,
    navigation_generation: 1,
  });
}

function closeFill(App, generation = 2, navigationGeneration = 2) {
  App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "idle",
    operation: "none",
    interaction_owner: "none",
    ready: false,
    login_required: false,
    error_code: "window_closed",
    operation_status: "operation_canceled",
    operation_result_owner: "automation_fill",
    operation_generation: generation,
    navigation_generation: navigationGeneration,
  });
}

async function flushBridgeDispatch() {
  await Promise.resolve();
  await Promise.resolve();
}

test("helper-close terminal cancellation wins over a late page-unavailable result", async () => {
  const { App, element } = harness();
  configureFDWorkSession(App, element);
  const opening = deferred();
  App.callBridge = (method) => method === "open_fd_work_entry"
    ? opening.promise : Promise.resolve({ ok: true });

  const pending = App.openFDWorkEntryForSelection();
  await flushBridgeDispatch();
  closeFill(App);
  const terminalText = element("fd-work-status").textContent;
  assert.match(terminalText, /关闭|取消/);

  opening.resolve({
    ok: false,
    error: "fd_work_page_unavailable",
    message: "FD Work 页面暂时不可用",
  });

  assert.equal(await pending, false);
  assert.equal(element("fd-work-status").textContent, terminalText);
  assert.doesNotMatch(element("fd-work-status").textContent, /页面暂时不可用/);
});

test("helper-close terminal cancellation wins over a late bridge rejection", async () => {
  const { App, element } = harness();
  configureFDWorkSession(App, element);
  const opening = deferred();
  App.callBridge = (method) => method === "open_fd_work_entry"
    ? opening.promise : Promise.resolve({ ok: true });

  const pending = App.openFDWorkEntryForSelection();
  await flushBridgeDispatch();
  closeFill(App);
  const terminalText = element("fd-work-status").textContent;

  opening.reject(new Error("window disappeared"));

  assert.equal(await pending, false);
  assert.equal(element("fd-work-status").textContent, terminalText);
  assert.doesNotMatch(element("fd-work-status").textContent, /打开 FD Work 失败/);
});

test("a stale transaction cannot overwrite a newer fill transaction", async () => {
  const { App, element } = harness();
  configureFDWorkSession(App, element);
  const firstOpening = deferred();
  const secondOpening = deferred();
  let openCount = 0;
  App.callBridge = (method) => {
    if (method !== "open_fd_work_entry") return Promise.resolve({ ok: true });
    openCount += 1;
    return openCount === 1 ? firstOpening.promise : secondOpening.promise;
  };

  const first = App.openFDWorkEntryForSelection();
  await flushBridgeDispatch();
  closeFill(App, 2, 2);
  assert.equal(App.fdWorkOpenPromise, null);

  App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "none",
    interaction_owner: "none",
    ready: true,
    login_required: false,
    error_code: null,
    operation_generation: 2,
    navigation_generation: 3,
  });
  const second = App.openFDWorkEntryForSelection();
  await flushBridgeDispatch();
  App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "automation_fill",
    interaction_owner: "automation_fill",
    ready: true,
    login_required: false,
    error_code: null,
    operation_status: "pending",
    operation_generation: 3,
    navigation_generation: 3,
  });
  assert.match(element("fd-work-status").textContent, /正在填入/);

  firstOpening.resolve({
    ok: false,
    error: "fd_work_page_unavailable",
    message: "FD Work 页面暂时不可用",
  });
  assert.equal(await first, false);
  assert.match(element("fd-work-status").textContent, /正在填入/);
  assert.doesNotMatch(element("fd-work-status").textContent, /页面暂时不可用/);

  App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "none",
    interaction_owner: "none",
    ready: true,
    login_required: false,
    error_code: null,
    operation_status: "save_completed",
    operation_result_owner: "automation_fill",
    operation_generation: 4,
    navigation_generation: 3,
  });
  assert.match(element("fd-work-status").textContent, /已保存到 FD Work/);

  secondOpening.resolve({
    ok: false,
    error: "fd_work_page_unavailable",
    message: "FD Work 页面暂时不可用",
  });
  assert.equal(await second, true);
  assert.match(element("fd-work-status").textContent, /已保存到 FD Work/);
  assert.doesNotMatch(element("fd-work-status").textContent, /页面暂时不可用/);
});

test("authoritative save-completed status wins over a late bridge failure", async () => {
  const { App, element } = harness();
  configureFDWorkSession(App, element);
  const opening = deferred();
  App.callBridge = (method) => method === "open_fd_work_entry"
    ? opening.promise : Promise.resolve({ ok: true });

  const pending = App.openFDWorkEntryForSelection();
  await flushBridgeDispatch();
  App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "none",
    interaction_owner: "none",
    ready: true,
    login_required: false,
    error_code: null,
    operation_status: "save_completed",
    operation_result_owner: "automation_fill",
    operation_generation: 2,
    navigation_generation: 2,
  });
  assert.match(element("fd-work-status").textContent, /已保存到 FD Work/);

  opening.resolve({
    ok: false,
    error: "fd_work_page_unavailable",
    message: "FD Work 页面暂时不可用",
  });

  assert.equal(await pending, true);
  assert.match(element("fd-work-status").textContent, /已保存到 FD Work/);
  assert.doesNotMatch(element("fd-work-status").textContent, /页面暂时不可用/);
});
