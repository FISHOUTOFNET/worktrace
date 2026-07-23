const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Behavior tests for the privacy-gated startup orchestration in init.js.
// Loads the REAL core.js, settings.js, and init.js; stubs only Bridge, DOM, timers.

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

function makeElement(id) {
  return {
    id,
    hidden: false,
    disabled: false,
    checked: false,
    value: "",
    textContent: "",
    innerHTML: "",
    className: "",
    dataset: {},
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
    setAttribute() {}, removeAttribute() {}, getAttribute() { return null; },
    appendChild() {}, removeChild() {},
    firstChild: null,
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
}

function makeBaseContext() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  }
  const context = {
    Promise, Error, String, Number, Array, Date, Math, JSON, RegExp,
    setTimeout, clearTimeout, setImmediate, setInterval, clearInterval,
    window: {
      WorkTraceApp: {},
      matchMedia: () => ({ matches: false }),
      setTimeout, clearTimeout, setInterval, clearInterval,
      addEventListener() {}, removeEventListener() {},
    },
    document: {
      // "loading" prevents init.js from auto-calling init() during eval.
      readyState: "loading",
      getElementById: element,
      querySelector() { return null; },
      querySelectorAll() { return []; },
      createElement() { return makeElement(`created-${elements.size}`); },
      addEventListener() {}, removeEventListener() {},
    },
  };
  vm.createContext(context);
  return { context, element, elements };
}

function loadJs(context, file) {
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
    context,
    { filename: file }
  );
}

// Full startup harness: loads core.js, settings.js, AND init.js with a
// stubbed pywebview.api bridge and DOM. The only stubs are the bridge API
// methods and timers (setInterval is captured so we can assert heartbeat
// creation without real timers running).
function startupHarness() {
  const { context, element, elements } = makeBaseContext();
  const App = context.window.WorkTraceApp;

  // Capture setInterval to detect heartbeat creation without real timers.
  let intervalsCreated = 0;
  let clearedIntervals = 0;
  context.setInterval = function (fn, ms) {
    intervalsCreated += 1;
    return Symbol("interval");
  };
  context.clearInterval = function () { clearedIntervals += 1; };
  context.window.setInterval = context.setInterval;
  context.window.clearInterval = context.clearInterval;

  const bridgeCalls = {
    getFirstRunNotice: 0,
    acceptFirstRunNotice: 0,
    getRefreshState: 0,
    getOverview: 0,
    getStatus: 0,
    getSettingsPrivacyStatus: 0,
    listProjectsForTimeline: 0,
  };

  // Configurable bridge responses (snake_case keys match what init.js's
  // invokeBridge calls: window.pywebview.api[method]).
  let firstRunNoticeResponse = { ok: true, notice: { accepted: false, title: "T", text: "x", highlights: [] } };
  let acceptResponse = { ok: true, accepted: true, collector_started: true, collector_status: { status: "running" } };
  let refreshStateResponse = { ok: true, runtime: { schema_version: 2, clock: null, snapshot: {}, revisions: {}, current_activity: {} } };
  let overviewResponse = { ok: true, overview: {}, date: "2026-07-24", runtime: { schema_version: 2, clock: null, snapshot: {}, revisions: {} } };
  let statusResponse = { ok: true, status: "running", paused: false, display: "记录中" };
  let settingsStatusResponse = { ok: true, status: { recovery_blocked: false, maintenance_in_progress: false, collector_running: true, first_run_notice: { accepted: true } } };
  let projectsResponse = { ok: true, projects: [], editing_projects: [], filter_projects: [] };

  const pywebviewApi = {
    get_first_run_notice: () => { bridgeCalls.getFirstRunNotice += 1; return Promise.resolve(firstRunNoticeResponse); },
    accept_first_run_notice: () => { bridgeCalls.acceptFirstRunNotice += 1; return Promise.resolve(acceptResponse); },
    get_refresh_state: () => { bridgeCalls.getRefreshState += 1; return Promise.resolve(refreshStateResponse); },
    get_overview: () => { bridgeCalls.getOverview += 1; return Promise.resolve(overviewResponse); },
    get_status: () => { bridgeCalls.getStatus += 1; return Promise.resolve(statusResponse); },
    get_settings_privacy_status: () => { bridgeCalls.getSettingsPrivacyStatus += 1; return Promise.resolve(settingsStatusResponse); },
    list_projects_for_timeline: () => { bridgeCalls.listProjectsForTimeline += 1; return Promise.resolve(projectsResponse); },
  };
  context.window.pywebview = { api: pywebviewApi };

  // loadProjects is defined in rules.js; stub it since we only load core/settings/init.
  App.loadProjects = () => { return Promise.resolve(); };
  // requestCoordinator is defined in a separate module; stub its interface
  // so init.js refresh helpers (refreshOverview, refreshStatus) work.
  App.requestCoordinator = {
    beginLatest() { return {}; },
    isCurrent() { return true; },
    bumpDataEpoch() {},
  };

  loadJs(context, "core.js");
  loadJs(context, "settings.js");
  loadJs(context, "init.js");

  // Set the default page after loading so continueStartupAfterPrivacyGate
  // routes through refreshOverview for the "overview" page.
  App.currentPage = "overview";

  return {
    App, element, elements, bridgeCalls, pywebviewApi,
    intervalsCreated: () => intervalsCreated,
    clearedIntervals: () => clearedIntervals,
    setFirstRunNoticeResponse: (r) => { firstRunNoticeResponse = r; },
    setAcceptResponse: (r) => { acceptResponse = r; },
    setRefreshStateResponse: (r) => { refreshStateResponse = r; },
  };
}

test("S1. first launch unaccepted: no project load, no refresh state, no heartbeat", async () => {
  const { App, element, bridgeCalls, intervalsCreated, setFirstRunNoticeResponse } = startupHarness();
  setFirstRunNoticeResponse({
    ok: true,
    notice: { accepted: false, title: "WorkTrace 隐私说明", text: "...", highlights: ["a"] },
  });

  App.init();
  await flush();
  await flush();

  assert.equal(App.privacyGateState, "acceptance_required");
  assert.equal(element("first-run-notice-overlay").hidden, false, "gate overlay must be visible");
  // No startup work may happen while unaccepted.
  assert.equal(bridgeCalls.getFirstRunNotice, 1, "notice loaded once");
  assert.equal(bridgeCalls.listProjectsForTimeline, 0, "project catalog must NOT load");
  assert.equal(bridgeCalls.getRefreshState, 0, "refresh state must NOT be requested");
  assert.equal(bridgeCalls.getOverview, 0, "page must NOT refresh");
  assert.equal(intervalsCreated(), 0, "heartbeat interval must NOT be created");
  assert.equal(App.heartbeatTimer, null, "heartbeat timer must remain null");
  assert.equal(App.startupAfterPrivacyState, "idle", "startup state must remain idle");
});

test("S2. accepted cold start: catalog + refresh state + page refresh + single heartbeat", async () => {
  const { App, bridgeCalls, intervalsCreated, setFirstRunNoticeResponse } = startupHarness();
  setFirstRunNoticeResponse({
    ok: true,
    notice: { accepted: true, title: "T", text: "x", highlights: [] },
  });

  App.init();
  await flush();
  await flush();
  await flush();
  await flush();

  assert.equal(App.privacyGateState, "accepted_ready");
  assert.equal(bridgeCalls.listProjectsForTimeline, 0, "loadProjects stubbed (no bridge call)");
  assert.equal(bridgeCalls.getRefreshState, 1, "refresh state requested once");
  assert.ok(bridgeCalls.getOverview >= 1, "page refreshed at least once");
  assert.equal(intervalsCreated(), 1, "heartbeat interval created exactly once");
  assert.equal(App.startupAfterPrivacyState, "ready");
});

test("S3. user confirm success: single continueStartup, single heartbeat", async () => {
  const { App, element, bridgeCalls, intervalsCreated, setFirstRunNoticeResponse, setAcceptResponse } = startupHarness();
  setFirstRunNoticeResponse({
    ok: true,
    notice: { accepted: false, title: "T", text: "x", highlights: [] },
  });
  setAcceptResponse({
    ok: true,
    accepted: true,
    collector_started: true,
    collector_status: { status: "running", paused: false, display: "记录中" },
  });

  App.init();
  await flush();
  await flush();
  assert.equal(App.privacyGateState, "acceptance_required");

  App.acceptFirstRunNotice();
  await flush();
  await flush();
  await flush();
  await flush();

  assert.equal(App.privacyGateState, "accepted_ready");
  assert.equal(element("first-run-notice-overlay").hidden, true);
  assert.equal(bridgeCalls.getRefreshState, 1, "refresh state once after confirm");
  assert.equal(intervalsCreated(), 1, "heartbeat created once after confirm");
  assert.equal(App.startupAfterPrivacyState, "ready");
});

test("S4. partial success: accepted + collector failed, UI enters app", async () => {
  const { App, element, bridgeCalls, intervalsCreated, setFirstRunNoticeResponse, setAcceptResponse } = startupHarness();
  setFirstRunNoticeResponse({
    ok: true,
    notice: { accepted: false, title: "T", text: "x", highlights: [] },
  });
  setAcceptResponse({
    ok: false,
    accepted: true,
    collector_started: false,
    error_code: "database_maintenance_recovery_required",
    message: "维护状态尚未恢复，暂不能开始记录",
    collector_status: { status: "paused", paused: true, display: "已暂停" },
  });

  App.init();
  await flush();
  await flush();

  App.acceptFirstRunNotice();
  await flush();
  await flush();
  await flush();
  await flush();

  assert.equal(App.privacyGateState, "accepted_start_failed");
  assert.equal(element("first-run-notice-overlay").hidden, true, "gate must close");
  assert.equal(element("global-alert").hidden, false, "global error visible");
  assert.match(element("global-alert").textContent, /维护状态尚未恢复/);
  // UI must still enter the app so the user can perform recovery.
  assert.equal(bridgeCalls.getRefreshState, 1, "refresh state loaded for app entry");
  assert.equal(intervalsCreated(), 1, "heartbeat created for app entry");
  assert.equal(App.startupAfterPrivacyState, "ready");
});

test("S5. accept write failure: gate stays open, no heartbeat, retryable", async () => {
  const { App, element, bridgeCalls, intervalsCreated, setFirstRunNoticeResponse, setAcceptResponse } = startupHarness();
  setFirstRunNoticeResponse({
    ok: true,
    notice: { accepted: false, title: "T", text: "x", highlights: [] },
  });
  setAcceptResponse({
    ok: false,
    accepted: false,
    collector_started: false,
    error_code: "privacy_accept_failed",
    message: "确认隐私说明失败",
  });

  App.init();
  await flush();
  await flush();

  App.acceptFirstRunNotice();
  await flush();
  await flush();

  assert.equal(App.privacyGateState, "acceptance_required");
  assert.equal(element("first-run-notice-overlay").hidden, false, "gate must stay open");
  assert.equal(bridgeCalls.getRefreshState, 0, "no startup on accept failure");
  assert.equal(intervalsCreated(), 0, "no heartbeat on accept failure");
  // User can click accept again (button re-enabled).
  assert.equal(element("first-run-notice-accept-btn").disabled, false);
});

test("S6. load failure then retry: fail-closed, retry succeeds, startup continues", async () => {
  const { App, element, bridgeCalls, intervalsCreated, pywebviewApi } = startupHarness();
  let loadAttempts = 0;
  pywebviewApi.get_first_run_notice = () => {
    loadAttempts += 1;
    if (loadAttempts === 1) return Promise.resolve({ ok: false, error: "load_failed" });
    return Promise.resolve({
      ok: true,
      notice: { accepted: true, title: "T", text: "x", highlights: [] },
    });
  };

  App.init();
  await flush();
  await flush();

  // First load failed — fail-closed.
  assert.equal(App.privacyGateState, "load_failed");
  assert.equal(element("first-run-notice-overlay").hidden, false);
  assert.equal(element("first-run-notice-retry-btn").hidden, false, "retry button visible");
  assert.equal(element("first-run-notice-accept-btn").hidden, true, "accept hidden on failure");
  assert.equal(intervalsCreated(), 0, "no heartbeat on load failure");
  assert.equal(bridgeCalls.getRefreshState, 0);

  // Retry succeeds.
  await App.retryFirstRunNotice();
  await flush();
  await flush();
  await flush();

  assert.equal(App.privacyGateState, "accepted_ready");
  assert.equal(loadAttempts, 2, "retry issued a new request");
  assert.equal(bridgeCalls.getRefreshState, 1, "startup continued after retry");
  assert.equal(intervalsCreated(), 1, "heartbeat created after retry");
});

test("S7. concurrent continueStartup: catalog loaded once, single heartbeat", async () => {
  const { App, bridgeCalls, intervalsCreated } = startupHarness();
  App.privacyGateState = "accepted_ready";
  App.firstRunNoticeLoaded = true;

  const results = await Promise.all([
    App.continueStartupAfterPrivacyGate(),
    App.continueStartupAfterPrivacyGate(),
    App.continueStartupAfterPrivacyGate(),
  ]);
  await flush();
  await flush();
  await flush();

  assert.deepEqual(results, [true, true, true]);
  assert.equal(bridgeCalls.getRefreshState, 1, "refresh state once despite 3 calls");
  assert.equal(intervalsCreated(), 1, "heartbeat once");
  assert.equal(App.startupAfterPrivacyState, "ready");
});

test("S8. repeat continueStartup after ready: no duplicate work", async () => {
  const { App, bridgeCalls, intervalsCreated } = startupHarness();
  App.privacyGateState = "accepted_ready";
  App.firstRunNoticeLoaded = true;

  await App.continueStartupAfterPrivacyGate();
  await flush();
  await flush();
  assert.equal(App.startupAfterPrivacyState, "ready");
  assert.equal(bridgeCalls.getRefreshState, 1);
  assert.equal(intervalsCreated(), 1);

  // Second call after ready — no new work.
  const result = await App.continueStartupAfterPrivacyGate();
  assert.equal(result, true);
  assert.equal(bridgeCalls.getRefreshState, 1, "no duplicate refresh state");
  assert.equal(intervalsCreated(), 1, "no duplicate heartbeat");
});

test("S9. startHeartbeat idempotent: two calls, one interval", async () => {
  const { App, intervalsCreated } = startupHarness();
  App.heartbeatTimer = null;
  App.startHeartbeat();
  assert.equal(intervalsCreated(), 1);
  App.startHeartbeat();
  assert.equal(intervalsCreated(), 1, "second call must not create a new interval");
});
