const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const REPORT_DATE = "2026-08-24";

function runtimeState(page, live, revision) {
  return {
    ok: true,
    runtime: {
      schema_version: 2,
      surface: page,
      scope_report_date: REPORT_DATE,
      live_report_date: REPORT_DATE,
      snapshot: { id: revision, revision },
      revisions: { structure: "structure-1", page: "page-1" },
      collector: {
        status: live ? "running" : "stopped",
        paused: false,
        display: live ? "记录中" : "未运行",
        live_eligible: live,
      },
      clock: {
        sampled_at_epoch_ms: 100000,
        started_at_epoch_ms: 90000,
        elapsed_seconds_at_sample: 10,
        aggregate_base_seconds: 100,
        duration_semantic: "aggregate_live",
        is_live: live,
        live_state: live ? "live" : "static",
        display_span_id: live ? "span-1" : "",
        stable_live_key_hash: live ? "key-1" : "",
      },
      current_activity: { active: live },
      current_project: null,
      runtime_phase: live ? "active" : "stopped",
      workers: {},
      generations: {
        report_structure: 1,
        classification_catalog: 1,
        settings: 1,
        privacy_catalog: 1,
      },
      database_replacement_epoch: 0,
      error_codes: [],
      runtime_consistent: true,
      needs_full_refresh: false,
    },
  };
}

function harness(initialPage = "overview") {
  let now = 100000;
  let renderCalls = 0;
  let statisticsTicks = 0;
  let timelineTicks = 0;
  const target = { clock: null };

  const capabilities = {
    overview: {
      hasLoadedData: () => true,
      refreshEvidence: () => ({ page: "overview" }),
      reportDate: () => REPORT_DATE,
      refreshPolicy: {},
    },
    timeline: {
      hasLoadedData: () => true,
      refreshEvidence: () => ({ page: "timeline" }),
      reportDate: () => REPORT_DATE,
      refreshPolicy: {},
      applyLocalTick() {
        timelineTicks += 1;
        return false;
      },
    },
    statistics: {
      hasLoadedData: () => true,
      refreshEvidence: () => ({ page: "statistics" }),
      reportDate: () => REPORT_DATE,
      refreshPolicy: {},
      applyLocalTick() {
        statisticsTicks += 1;
        return false;
      },
    },
  };

  const pageRoot = {
    querySelectorAll() {
      return target.clock ? [target] : [];
    },
  };

  const App = {
    currentPage: initialPage,
    heartbeatTimer: null,
    HEARTBEAT_INTERVAL_MS: 1000,
    liveClockContractRefreshRequested: false,
    pageLifecycle: {
      names: Object.freeze(["overview", "timeline", "statistics"]),
      capability(name) { return capabilities[name] || null; },
      bindEvents() {},
      onPageLeft() {},
      resetGeneration() {},
    },
    requestCoordinator: {
      beginLatest() { return {}; },
      isCurrent() { return true; },
      bumpDataEpoch() {},
    },
    privacyNotice: {
      bindEvents() {},
      loadGate() { return Promise.resolve(false); },
    },
    localTodayStr() { return REPORT_DATE; },
    runtimeReportDateForPage() { return REPORT_DATE; },
    validateLiveClock(value) {
      return value && typeof value === "object" ? value : null;
    },
    recordLiveClockContractViolation() { App.liveClockContractViolation = {}; },
    readLiveClockTarget(node) { return node.clock; },
    liveTargetCompatibleWithRuntime() { return true; },
    clearLiveClockTarget(node) { node.clock = null; },
    renderLiveDurationTarget() { renderCalls += 1; },
    clearError() {},
    showError() {},
    showStatus() {},
    showGlobalAlert() {},
    clearGlobalAlert() {},
    handleResult(value) { return value; },
  };

  const document = {
    readyState: "loading",
    addEventListener() {},
    getElementById(id) {
      return id === `page-${App.currentPage}` ? pageRoot : null;
    },
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
    target,
    acceptRefresh(live, revision) {
      return App.acceptRefreshStateRuntime(runtimeState(App.currentPage, live, revision));
    },
    acceptPage(live, revision, reportDate = REPORT_DATE) {
      const payload = runtimeState(App.currentPage, live, revision);
      payload.runtime.scope_report_date = reportDate;
      return App.acceptPagePayloadRuntime(payload, App.currentPage, reportDate);
    },
    advance(milliseconds) { now += milliseconds; },
    counts() { return { renderCalls, statisticsTicks, timelineTicks }; },
  };
}

test("stale live runtime freezes generic clocks until an authoritative page model rebases them", () => {
  const { App, target, acceptRefresh, acceptPage, advance, counts } = harness("overview");

  assert.equal(acceptRefresh(true, "live-1"), true);
  target.clock = App.liveRuntimeStore.get().liveClock;
  App.applyLocalTicker();
  assert.equal(counts().renderCalls, 1);
  assert.ok(App.getActiveLiveClock());

  advance(10001);
  App.applyLocalTicker();
  assert.equal(counts().renderCalls, 1, "expired runtime must freeze the last displayed value");
  assert.equal(App.getActiveLiveClock(), null);

  assert.equal(acceptRefresh(true, "live-2"), true);
  assert.equal(App.liveClockContractRefreshRequested, true);
  App.applyLocalTicker();
  assert.equal(counts().renderCalls, 1, "refresh-state alone must not release old DOM clocks");

  assert.equal(acceptPage(true, "page-live"), true);
  target.clock = App.liveRuntimeStore.get().liveClock;
  App.applyLocalTicker();
  assert.equal(counts().renderCalls, 2, "authoritative page model resumes local projection");
  assert.ok(App.getActiveLiveClock());
});

test("failed page rebase remains fail-closed after bridge recovery", () => {
  const { App, target, acceptRefresh, acceptPage, advance, counts } = harness("overview");

  acceptRefresh(true, "live-1");
  target.clock = App.liveRuntimeStore.get().liveClock;
  advance(10001);
  App.applyLocalTicker();
  acceptRefresh(true, "live-2");

  assert.equal(acceptPage(true, "wrong-date", "2026-08-23"), false);
  App.applyLocalTicker();
  assert.equal(counts().renderCalls, 0);
  assert.equal(App.getActiveLiveClock(), null);

  acceptRefresh(true, "live-3");
  assert.equal(App.liveClockContractRefreshRequested, true);
  App.applyLocalTicker();
  assert.equal(counts().renderCalls, 0, "later heartbeat cannot bypass pending page rebase");
});

test("statistics freezes on stale or non-live runtime and requires page rebase before resuming", () => {
  const { App, acceptRefresh, acceptPage, advance, counts } = harness("statistics");

  acceptRefresh(true, "live-1");
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 1);

  advance(10001);
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 1, "stale statistics snapshot must stop extrapolating");

  acceptRefresh(true, "live-2");
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 1, "fresh refresh-state still requires statistics page rebase");

  acceptPage(true, "page-live");
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 2);

  acceptRefresh(false, "stopped");
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 2, "live_eligible=false must freeze statistics immediately");

  acceptRefresh(true, "resumed");
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 2, "resume cannot reuse the pre-stop statistics target");

  acceptPage(true, "resumed-page");
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 3);
});

test("timeline structural local tick still runs while live projection is stale", () => {
  const { App, acceptRefresh, advance, counts } = harness("timeline");

  acceptRefresh(true, "live-1");
  advance(10001);
  App.applyLocalTicker();

  assert.equal(counts().timelineTicks, 1, "freshness safety must not block timeline structural draining");
});
