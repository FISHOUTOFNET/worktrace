const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadApp() {
  let intervalCreates = 0;
  let intervalClears = 0;
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
    setInterval: () => {
      intervalCreates += 1;
      return { timer: intervalCreates };
    },
    clearInterval: () => {
      intervalClears += 1;
    },
  };
  vm.createContext(context);
  const source = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/init_fd_work_v5.js"),
    "utf8"
  );
  vm.runInContext(source, context);
  return {
    App: context.window.WorkTraceApp,
    counts: () => ({ intervalCreates, intervalClears }),
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

test("hiding does not discard a queued timeline edit", () => {
  const { App } = loadApp();
  App.editingSession = { projection_instance_key: "session-1" };
  App.timelineSaveQueued = true;

  App.setShellVisibility(false);

  assert.equal(App.editingSession.projection_instance_key, "session-1");
  assert.equal(App.timelineSaveQueued, true);
});
