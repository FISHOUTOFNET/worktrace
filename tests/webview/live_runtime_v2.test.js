const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function liveClock(overrides = {}) {
  return Object.assign({
    sampled_at_epoch_ms: 8000,
    started_at_epoch_ms: 3000,
    elapsed_seconds_at_sample: 5,
    aggregate_base_seconds: 0,
    duration_semantic: "current_live",
    is_live: true,
    live_state: "persisted_open",
    display_span_id: "display-1",
    stable_live_key_hash: "stable-1",
  }, overrides);
}

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
    },
    recent_first_row: {
      activity_id: 41,
      persisted_activity_id: 41,
      is_in_progress: true,
    },
    clock: liveClock(),
    current_project: { id: 7, name: "Matter" },
    collector: { status: "running", paused: false, display: "记录中" },
    runtime_phase: "running",
    workers: {},
    generations: { database_replacement: 1 },
    database_replacement_epoch: 1,
    error_codes: [],
    revisions: { structure: "structure-1", page: "page-1" },
    runtime_consistent: true,
    needs_full_refresh: false,
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

  class FakeDate extends Date {
    constructor(...args) {
      super(...(args.length ? args : [now]));
    }
    static now() { return now; }
  }

  function element(id) {
    if (!elements.has(id)) {
      const attributes = new Map();
      elements.set(id, {
        id,
        hidden: false,
        textContent: "",
        innerHTML: "",
        className: "",
        classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
        addEventListener() {},
        getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
        setAttribute(name, value) { attributes.set(name, String(value)); },
        removeAttribute(name) { attributes.delete(name); },
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
    Date: FakeDate,
    setInterval() {
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
  for (const file of ["core.js", "init.js"]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
      context,
      { filename: file }
    );
  }
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    requestCoordinator: {
      bumpDataEpoch() {},
      beginLatest() { return {}; },
      isCurrent() { return true; },
    },
    initStatisticsDefaults() {},
    loadStatisticsExportSummary() {},
    loadProjectRules() {},
    loadSettingsPrivacyStatus() {},
  });
  return {
    App,
    activeTimers,
    element,
    setNow(value) { now = value; },
  };
}

test("v2 exact clock is accepted and v1 is rejected", () => {
  const { App } = harness();
  assert.equal(
    App.liveRuntimeStore.acceptEnvelope(
      { ok: true, runtime: { schema_version: 1 } },
      "overview",
      "2026-07-19"
    ),
    null
  );
  const accepted = App.liveRuntimeStore.acceptEnvelope(
    runtimePayload(),
    "overview",
    "2026-07-19"
  );
  assert.equal(accepted.schemaVersion, 2);
  assert.equal(accepted.liveClock.duration_semantic, "current_live");
  assert.equal(accepted.liveClock.elapsed_seconds_at_sample, 5);
  assert.equal(accepted.displaySpanId, "display-1");
  assert.equal(accepted.currentActivity.activity_id, 41);
});

test("clock validator rejects missing, extra, negative, and invalid live states", () => {
  const { App } = harness();
  const missing = liveClock();
  delete missing.started_at_epoch_ms;
  assert.equal(App.validateLiveClock(missing), null);
  assert.equal(App.validateLiveClock(Object.assign(liveClock(), { extra: 1 })), null);
  assert.equal(App.validateLiveClock(liveClock({ elapsed_seconds_at_sample: -1 })), null);
  assert.equal(App.validateLiveClock(liveClock({ live_state: "none" })), null);
  assert.equal(
    App.validateLiveClock(liveClock({ duration_semantic: "static_closed", is_live: true })),
    null
  );
});

test("current and aggregate formulas use sampled elapsed exactly", () => {
  const { App } = harness();
  assert.equal(App.computeClockDurationNow(liveClock(), 12000), 9);
  assert.equal(
    App.computeClockDurationNow(
      liveClock({ duration_semantic: "aggregate_live", aggregate_base_seconds: 100 }),
      12000
    ),
    109
  );
  const staticClock = liveClock({
    sampled_at_epoch_ms: 8000,
    started_at_epoch_ms: 0,
    elapsed_seconds_at_sample: 22,
    aggregate_base_seconds: 0,
    duration_semantic: "static_closed",
    is_live: false,
    live_state: "none",
    display_span_id: "",
    stable_live_key_hash: "",
  });
  assert.equal(App.computeClockDurationNow(staticClock, 12000), null);
});

test("malformed clock fails static, deduplicates diagnostics, and requests low-frequency refresh", () => {
  const { App } = harness();
  const badPayload = runtimePayload({ clock: Object.assign(liveClock(), { unexpected: 1 }) });
  const accepted = App.liveRuntimeStore.acceptEnvelope(
    badPayload,
    "overview",
    "2026-07-19"
  );
  assert.equal(accepted.liveClock, null);
  assert.equal(accepted.needsFullRefresh, true);
  assert.equal(App.liveClockContractRefreshRequested, true);
  App.recordLiveClockContractViolation("display-1", "overview", "runtime_clock_invalid", 2);
  App.recordLiveClockContractViolation("display-1", "overview", "runtime_clock_invalid", 2);
  assert.equal(Object.keys(App.liveClockViolationKeys).length, 2);
});

test("render continuity never changes duration", () => {
  const { App, element } = harness();
  const target = element("duration");
  App.renderDurationProjected(target, 12, "same-key");
  App.renderDurationProjected(target, 8, "same-key");
  assert.equal(target.getAttribute("data-duration-seconds"), "8");
  assert.equal(target.textContent, "00:00:08");
});

test("database replacement resets stale client state before accepting new epoch", () => {
  const { App } = harness();
  assert.equal(App.acceptRefreshStateRuntime(runtimePayload()), true);
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

test("page switches keep one application timer", () => {
  const { App, activeTimers } = harness();
  App.startHeartbeat();
  assert.equal(activeTimers.size, 1);
  App.currentPage = "rules";
  App.startHeartbeat();
  assert.equal(activeTimers.size, 1);
});

test("shipping JavaScript has one clock contract and no retired aliases", () => {
  const directory = path.join(__dirname, "../../worktrace/webview_ui/js");
  const files = ["core.js", "init.js", "overview.js", "timeline.js"];
  const source = files.map((file) => fs.readFileSync(path.join(directory, file), "utf8")).join("\n");
  const forbidden = [
    "duration_seconds_at_sample",
    "carry_seconds",
    "live_started_at_epoch_ms",
    "sample_epoch_ms",
    "current_live_duration_seconds",
    "persisted_duration_seconds",
    "active_elapsed_at_sample",
    "current_elapsed_at_sample",
    "current_duration_live",
    "project_duration_live",
    "is_project_duration_live",
    "live_delta_eligible",
    "is_live_projected",
    "data-live-duration-target",
    "data-display-base-seconds",
    "data-live-base-seconds",
  ];
  for (const alias of forbidden) {
    assert.equal(source.includes(alias), false, `retired alias remains: ${alias}`);
  }
  const initSource = fs.readFileSync(path.join(directory, "init.js"), "utf8");
  assert.equal((initSource.match(/setInterval\s*\(/g) || []).length, 1);
});
