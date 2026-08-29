const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const REPORT_DATE = "2026-08-29";

function runtimePayload({
  sampleId,
  liveRevision,
  pageRevision,
  sampledAt = 100000,
  page = "overview",
  reportDate = REPORT_DATE,
  databaseEpoch = 0,
}) {
  return {
    ok: true,
    runtime: {
      schema_version: 2,
      surface: page,
      scope_report_date: reportDate,
      live_report_date: REPORT_DATE,
      snapshot: { id: sampleId, revision: liveRevision },
      revisions: { structure: "structure-1", page: pageRevision },
      collector: {
        status: "running",
        paused: false,
        display: "记录中",
        live_eligible: true,
      },
      clock: {
        sampled_at_epoch_ms: sampledAt,
        started_at_epoch_ms: 90000,
        elapsed_seconds_at_sample: 10,
        aggregate_base_seconds: 100,
        duration_semantic: "aggregate_live",
        is_live: true,
        live_state: "persisted_open",
        display_span_id: "span-1",
        stable_live_key_hash: "key-1",
      },
      current_activity: {
        active: true,
        status: "normal",
        activity_id: 42,
      },
      current_project: null,
      runtime_phase: "active",
      workers: {},
      generations: {
        report_structure: 1,
        classification_catalog: 1,
        settings: 1,
        privacy_catalog: 1,
      },
      database_replacement_epoch: databaseEpoch,
      error_codes: [],
      runtime_consistent: true,
      needs_full_refresh: false,
    },
  };
}

function harness() {
  let now = 100000;
  const App = {
    currentPage: "overview",
    heartbeatTimer: null,
    HEARTBEAT_INTERVAL_MS: 1000,
    liveClockContractRefreshRequested: false,
    localTodayStr() { return REPORT_DATE; },
    runtimeReportDateForPage(_page, date) { return String(date || REPORT_DATE); },
    validateLiveClock(value) {
      return value && typeof value === "object" ? value : null;
    },
    computeClockDurationNow() { return 0; },
    recordLiveClockContractViolation(_span, _page, reason) {
      App.liveClockContractViolation = { reason };
    },
    requestCoordinator: {
      beginLatest() { return {}; },
      isCurrent() { return true; },
      bumpDataEpoch() {},
    },
    pageLifecycle: {
      names: Object.freeze(["overview", "timeline"]),
      capability(name) {
        if (name === "overview") {
          return {
            hasLoadedData: () => true,
            refreshEvidence: () => null,
            refreshPolicy: {},
          };
        }
        if (name === "timeline") {
          return {
            hasLoadedData: () => true,
            refreshEvidence: () => null,
            reportDate: () => REPORT_DATE,
            refreshPolicy: {},
          };
        }
        return null;
      },
      bindEvents() {},
      onPageLeft() {},
      resetGeneration() {},
    },
    privacyNotice: {
      bindEvents() {},
      loadGate() { return Promise.resolve(false); },
    },
    readLiveClockTarget() { return null; },
    clearLiveClockTarget() {},
    liveTargetCompatibleWithRuntime() { return true; },
    renderLiveDurationTarget() {},
    showStatus() {},
    showError() {},
    clearError() {},
    showGlobalAlert() {},
    clearGlobalAlert() {},
    extractBridgeError(_value, fallback) { return fallback; },
    handleResult(value) { return value; },
  };

  const document = {
    readyState: "loading",
    addEventListener() {},
    getElementById() { return null; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
  };
  const context = {
    window: {
      WorkTraceApp: App,
      pywebview: { api: {} },
      addEventListener() {},
      removeEventListener() {},
      setTimeout,
      clearTimeout,
    },
    document,
    console,
    Promise,
    Date: { now: () => now },
    Math,
    Number,
    String,
    Array,
    Object,
    JSON,
    parseInt,
    setInterval() { return {}; },
    clearInterval() {},
    setTimeout,
    clearTimeout,
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/init_fd_work_v5.js"),
      "utf8"
    ),
    context,
    { filename: "init_fd_work_v5.js" }
  );

  return {
    App: context.window.WorkTraceApp,
    setNow(value) { now = value; },
  };
}

test("late page response cannot overwrite newer heartbeat runtime", () => {
  const { App } = harness();
  const heartbeatB = runtimePayload({
    sampleId: "heartbeat-b",
    liveRevision: "live-b",
    pageRevision: "page-b",
  });
  const pageA = runtimePayload({
    sampleId: "page-a",
    liveRevision: "live-a",
    pageRevision: "page-a",
  });
  const pageB = runtimePayload({
    sampleId: "page-b",
    liveRevision: "live-b",
    pageRevision: "page-b",
  });

  assert.equal(App.acceptRefreshStateRuntime(heartbeatB), true);
  assert.equal(App.liveRuntimeStore.get().sampleId, "heartbeat-b");

  assert.equal(App.acceptPagePayloadRuntime(pageA, "overview", REPORT_DATE), false);
  assert.equal(App.liveRuntimeStore.get().sampleId, "heartbeat-b");
  assert.equal(App.liveRuntimeStore.get().pageRevision, "page-b");
  assert.equal(App.liveClockContractRefreshRequested, true);

  App.liveClockContractRefreshRequested = false;
  assert.equal(App.acceptPagePayloadRuntime(pageB, "overview", REPORT_DATE), true);
  assert.equal(
    App.liveRuntimeStore.get().sampleId,
    "heartbeat-b",
    "coherent page confirmation must not replace canonical heartbeat runtime"
  );
});

test("timeline details are coherence-only and never become runtime authority", () => {
  const { App } = harness();
  App.currentPage = "timeline";
  const heartbeat = runtimePayload({
    page: "timeline",
    sampleId: "heartbeat",
    liveRevision: "live-1",
    pageRevision: "page-1",
  });
  const matchingDetails = runtimePayload({
    page: "details",
    sampleId: "details",
    liveRevision: "live-1",
    pageRevision: "page-1",
  });
  const staleDetails = runtimePayload({
    page: "details",
    sampleId: "details-stale",
    liveRevision: "live-0",
    pageRevision: "page-0",
  });

  assert.equal(App.acceptRefreshStateRuntime(heartbeat), true);
  assert.equal(
    App.acceptLiveRuntimePayload(matchingDetails, "timeline", REPORT_DATE, {
      source: "details_model",
    }),
    true
  );
  assert.equal(App.liveRuntimeStore.get().sampleId, "heartbeat");

  assert.equal(
    App.acceptLiveRuntimePayload(staleDetails, "timeline", REPORT_DATE, {
      source: "details_model",
    }),
    false
  );
  assert.equal(App.liveRuntimeStore.get().sampleId, "heartbeat");
});

test("page model may bootstrap only before a same-scope heartbeat authority exists", () => {
  const { App } = harness();
  const initialPage = runtimePayload({
    sampleId: "bootstrap-page",
    liveRevision: "live-1",
    pageRevision: "page-1",
  });
  const heartbeat = runtimePayload({
    sampleId: "heartbeat",
    liveRevision: "live-1",
    pageRevision: "page-1",
  });
  const laterPage = runtimePayload({
    sampleId: "later-page",
    liveRevision: "live-1",
    pageRevision: "page-1",
  });

  assert.equal(App.acceptPagePayloadRuntime(initialPage, "overview", REPORT_DATE), true);
  assert.equal(App.liveRuntimeStore.get().sampleId, "bootstrap-page");

  assert.equal(App.acceptRefreshStateRuntime(heartbeat), true);
  assert.equal(App.liveRuntimeStore.get().sampleId, "heartbeat");

  assert.equal(App.acceptPagePayloadRuntime(laterPage, "overview", REPORT_DATE), true);
  assert.equal(App.liveRuntimeStore.get().sampleId, "heartbeat");
});
