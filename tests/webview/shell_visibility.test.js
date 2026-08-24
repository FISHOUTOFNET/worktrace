const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadApp() {
  let intervalCreates = 0;
  let intervalClears = 0;
  let intervalCallback = null;
  const App = {
    heartbeatTimer: null,
    HEARTBEAT_INTERVAL_MS: 1000,
    requestCoordinator: {
      beginLatest: () => ({}),
      isCurrent: () => true,
    },
    bridge: {
      getRefreshState: () => Promise.resolve({ ok: false }),
    },
    handleResult: () => null,
    applyLocalTicker: () => {},
    validateLiveClock: () => null,
  };
  const context = {
    window: {
      WorkTraceApp: App,
      addEventListener: () => {},
      removeEventListener: () => {},
      pywebview: { api: {} },
    },
    document: {
      readyState: "loading",
      addEventListener: () => {},
      getElementById: () => null,
      querySelectorAll: () => [],
    },
    console,
    Promise,
    Date,
    setInterval: (callback) => {
      intervalCreates += 1;
      intervalCallback = callback;
      return { timer: intervalCreates };
    },
    clearInterval: () => {
      intervalClears += 1;
    },
  };
  vm.createContext(context);
  for (const file of ["init_fd_work_v5.js", "shell_lifecycle.js"]) {
    const source = fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js", file),
      "utf8"
    );
    vm.runInContext(source, context, { filename: file });
  }
  return {
    App: context.window.WorkTraceApp,
    counts: () => ({ intervalCreates, intervalClears }),
    fireHeartbeat: () => intervalCallback && intervalCallback(),
  };
}

test("shell visibility stops heartbeat and restores it once", async () => {
  const { App, counts } = loadApp();
  let revisionChecks = 0;
  App.runRevisionCheck = () => {
    revisionChecks += 1;
    return Promise.resolve();
  };

  App.startHeartbeat();
  await App.setShellVisibility(false);
  assert.equal(App.heartbeatTimer, null);
  App.startHeartbeat();
  assert.equal(App.heartbeatTimer, null, "hidden startup must not recreate heartbeat");
  await App.setShellVisibility(true);
  await App.setShellVisibility(true);

  assert.equal(revisionChecks, 1);
  assert.deepEqual(counts(), { intervalCreates: 2, intervalClears: 1 });
});

test("shell restore restarts heartbeat even when revision recovery rejects", async () => {
  const { App, counts } = loadApp();
  App.startHeartbeat();
  await App.setShellVisibility(false);
  App.runRevisionCheck = () => Promise.reject(new Error("bridge unavailable"));

  await App.setShellVisibility(true);

  assert.equal(App.shellVisible, true);
  assert.notEqual(App.heartbeatTimer, null, "visible shell must retain its recovery heartbeat");
  assert.deepEqual(counts(), { intervalCreates: 2, intervalClears: 1 });
});

test("repeated visible notification repairs a missing heartbeat", async () => {
  const { App, counts } = loadApp();
  App.heartbeatTimer = null;
  App.shellVisible = true;

  await App.setShellVisibility(true);

  assert.notEqual(App.heartbeatTimer, null);
  assert.deepEqual(counts(), { intervalCreates: 1, intervalClears: 0 });
});

test("heartbeat absorbs asynchronous revision-check rejection", async () => {
  const { App, fireHeartbeat } = loadApp();
  App.bridge.getRefreshState = () => Promise.reject(new Error("bridge unavailable"));
  App.startHeartbeat();

  fireHeartbeat();
  await Promise.resolve();
  await Promise.resolve();

  assert.notEqual(App.heartbeatTimer, null, "bridge rejection must not tear down heartbeat");
});

test("shell visibility dispatches presentation lifecycle exactly once", async () => {
  const { App } = loadApp();
  const calls = [];
  App.uiPrimitives = {
    onShellHidden: () => calls.push("ui:hidden"),
    onShellVisible: () => calls.push("ui:visible"),
  };
  App.projectAutocomplete = {
    onShellHidden: () => calls.push("autocomplete:hidden"),
    onShellVisible: () => calls.push("autocomplete:visible"),
  };
  App.timelineTransientUi = {
    onShellHidden: () => calls.push("timeline:hidden"),
    onShellVisible: () => calls.push("timeline:visible"),
  };
  App.privacyNotice = {
    closeView: (options) => calls.push(`privacy:${options.restoreFocus}`),
  };
  App.runRevisionCheck = () => Promise.resolve();

  await App.setShellVisibility(false);
  await App.setShellVisibility(false);
  await App.setShellVisibility(true);
  await App.setShellVisibility(true);

  assert.deepEqual(calls, [
    "ui:hidden",
    "autocomplete:hidden",
    "timeline:hidden",
    "privacy:false",
    "ui:visible",
    "autocomplete:visible",
    "timeline:visible",
  ]);
});

test("hiding does not discard a queued timeline edit", () => {
  const { App } = loadApp();
  const editor = {
    currentSession: () => ({ projection_instance_key: "session-1" }),
    hasQueuedAutosave: () => true,
  };
  App.timelineEditorState = editor;

  App.setShellVisibility(false);

  assert.equal(App.timelineEditorState, editor);
  assert.equal(App.timelineEditorState.currentSession().projection_instance_key, "session-1");
  assert.equal(App.timelineEditorState.hasQueuedAutosave(), true);
});
