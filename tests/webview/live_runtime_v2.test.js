const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function runtimePayload(overrides = {}) {
  const runtime = {
    schema_version: 2,
    surface: "refresh",
    scope_report_date: "2026-07-19",
    live_report_date: "2026-07-19",
    snapshot: {
      id: "sample-1",
      timestamp_epoch_ms: 8000,
      revision: "live-1",
    },
    current_activity: {
      active: true,
      activity_id: 41,
      persisted_activity_id: 41,
      is_in_progress: true,
      live_state: "persisted_open",
      current_activity_display_span_id: "current-span-1",
      current_resource_identity_hash: "resource-1",
      stable_live_key_hash: "stable-1",
    },
    recent_first_row: {
      active: true,
      activity_id: 41,
      persisted_activity_id: 41,
      is_in_progress: true,
      stable_live_key_hash: "stable-1",
    },
    clock: {
      live_state: "persisted_open",
      is_live: true,
      duration_seconds_at_sample: 5,
      current_live_duration_seconds: 5,
      persisted_duration_seconds: 5,
      sample_epoch_ms: 8000,
      live_started_at_epoch_ms: 3000,
      display_span_id: "display-1",
      stable_live_key_hash: "stable-1",
      current_duration_live: true,
      project_duration_live: true,
      is_project_duration_live: true,
    },
    current_project: { id: 7, name: "Matter" },
    collector: { status: "running", paused: false, display: "记录中" },
    runtime_phase: "running",
    worker_health: {},
    degraded_workers: [],
    generations: { database_replacement: 1 },
    database_replacement_epoch: 1,
    error_codes: [],
    identity: {
      display_span_id: "display-1",
      stable_live_key_hash: "stable-1",
      current_activity_display_span_id: "current-span-1",
      current_resource_identity_hash: "resource-1",
    },
    revisions: { structure: "structure-1", page: "page-1" },
  };
  Object.assign(runtime, overrides);
  return { ok: true, runtime };
}

function harness() {
  let now = 10000;
  let nextTimerId = 1;
  const activeTimers = new Set();
  const listeners = new Map();
  const elements = new Map();

  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        classList: { add() {}, remove() {}, contains() { return false; } },
        addEventListener() {},
        getAttribute() { return ""; },
        setAttribute() {},
        removeAttribute() {},
        querySelectorAll() { return []; },
        querySelector() { return null; },
      });
    }
    return elements.get(id);
  }

  const context = {
    Promise,
    Error,
    String,
    Number,
    Array,
    Object,
    Math,
    parseInt,
    isNaN,
    Date: { now: () => now },
    setInterval(callback) {
      const id = nextTimerId++;
      activeTimers.add(id);
      return id;
    },
    clearInterval(id) { activeTimers.delete(id); },
    window: {
      WorkTraceApp: {},
      addEventListener(name, callback) { listeners.set(name, callback); },
      removeEventListener(name) { listeners.delete(name); },
    },
    document: {
      readyState: "loading",
      addEventListener(name, callback) { listeners.set(name, callback); },
      getElementById: element,
      querySelectorAll() { return []; },
      querySelector() { return null; },
    },
  };
  vm.createContext(context);

  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    HEARTBEAT_INTERVAL_MS: 1000,
    heartbeatTimer: null,
    currentPage: "overview",
    timelineDate: null,
    timelineLoaded: false,
    timelineLoading: false,
    statisticsLoaded: true,
    rulesLoaded: true,
    settingsLoaded: true,
    _monotonicRenderState: {},
    requestCoordinator: {
      bumpDataEpoch() {},
      beginLatest() { return {}; },
      isCurrent() { return true; },
    },
    runtimeReportDateForPage(page, fallback) {
      return fallback || "2026-07-19";
    },
    localTodayStr() { return "2026-07-19"; },
    normalizeLiveClock(clock) { return clock ? Object.assign({}, clock) : null; },
    liveTargetCompatibleWithRuntime() { return true; },
    recordLiveClockContractViolation() {},
    renderLiveDurationTarget() {},
    loadTimelineReport() {},
    initStatisticsDefaults() {},
    loadStatisticsExportSummary() {},
    loadProjectRules() {},
    loadSettingsPrivacyStatus() {},
  });

  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/init.js"), "utf8"),
    context,
    { filename: "init.js" }
  );

  return {
    App,
    activeTimers,
    setNow(value) { now = value; },
  };
}

test("v1 is rejected and v2 is the only accepted transport", () => {
  const { App } = harness();
  assert.equal(
    App.liveRuntimeStore.acceptEnvelope({ ok: true, runtime: { schema_version: 1 } }, "overview", "2026-07-19"),
    null
  );

  const accepted = App.liveRuntimeStore.acceptEnvelope(
    runtimePayload(),
    "overview",
    "2026-07-19"
  );

  assert.equal(accepted.schemaVersion, 2);
  assert.equal(accepted.liveRevision, "live-1");
  assert.equal(accepted.pageRevision, "page-1");
  assert.equal(accepted.currentActivity.activity_id, 41);
  assert.equal(accepted.recentFirstRow.activity_id, 41);
  assert.equal(accepted.liveClock.carry_seconds, 7);
});

test("repeated refresh rebases one clock without double counting", () => {
  const { App, setNow } = harness();
  App.liveRuntimeStore.acceptEnvelope(runtimePayload(), "overview", "2026-07-19");

  setNow(12000);
  const second = runtimePayload({
    snapshot: { id: "sample-2", timestamp_epoch_ms: 11000, revision: "live-2" },
    clock: {
      live_state: "persisted_open",
      is_live: true,
      duration_seconds_at_sample: 8,
      current_live_duration_seconds: 8,
      persisted_duration_seconds: 8,
      sample_epoch_ms: 11000,
      live_started_at_epoch_ms: 3000,
      display_span_id: "display-1",
      stable_live_key_hash: "stable-1",
      current_duration_live: true,
      project_duration_live: true,
      is_project_duration_live: true,
    },
  });
  const accepted = App.liveRuntimeStore.acceptEnvelope(second, "overview", "2026-07-19");

  assert.equal(accepted.liveClock.carry_seconds, 9);
  setNow(13000);
  assert.equal(App.computeActiveElapsedNow(accepted.liveClock, 13000), 10);
});

test("page switches do not create another application timer", () => {
  const { App, activeTimers } = harness();
  App.startHeartbeat();
  assert.equal(activeTimers.size, 1);

  App.switchPage("rules");
  assert.equal(activeTimers.size, 1);
});

test("database replacement resets stale client state before accepting the new epoch", () => {
  const { App } = harness();
  App.acceptRefreshStateRuntime(runtimePayload());
  App.timelineLoaded = true;

  const replacement = runtimePayload({
    generations: { database_replacement: 2 },
    database_replacement_epoch: 2,
  });
  assert.equal(App.acceptRefreshStateRuntime(replacement), true);

  assert.equal(App.lastClientGenerationResetReason, "database_replacement_epoch_changed");
  assert.equal(App.timelineLoaded, false);
  assert.equal(App.liveRuntime.databaseReplacementEpoch, 2);
});

test("paused runtime retains the sampled duration and does not advance locally", () => {
  const { App, setNow } = harness();
  const paused = runtimePayload({
    collector: { status: "running", paused: true, display: "已暂停" },
  });
  const accepted = App.liveRuntimeStore.acceptEnvelope(paused, "overview", "2026-07-19");
  assert.equal(accepted.liveClock.is_live, false);
  const sampled = accepted.liveClock.carry_seconds;

  setNow(20000);
  assert.equal(App.computeActiveElapsedNow(accepted.liveClock, 20000), sampled);
});

test("init source contains one timer and no retired v1 or top-level runtime reads", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/init.js"),
    "utf8"
  );
  assert.equal((source.match(/setInterval\s*\(/g) || []).length, 1);
  assert.equal(source.includes("schema_version || 0) !== 1"), false);
  assert.equal(source.includes("bundle.current_activity"), false);
  assert.equal(source.includes("bundle.live_clock"), false);
  assert.equal(source.includes("state.collector_status"), false);
});
