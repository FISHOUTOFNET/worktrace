const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const REPORT_DATE = "2026-08-24";

function runtimeState(page, live, revision, sampledAt = 100000) {
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
        sampled_at_epoch_ms: sampledAt,
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
  let toggleCalls = 0;
  const toggleResolvers = [];
  const target = { clock: null };
  const toggleButton = { disabled: false, addEventListener() {} };

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
    computeClockDurationNow(clock, nowMs) {
      if (!clock || clock.is_live !== true) return null;
      const delta = Math.max(0, Math.floor((nowMs - clock.sampled_at_epoch_ms) / 1000));
      const elapsed = clock.elapsed_seconds_at_sample + delta;
      return clock.duration_semantic === "aggregate_live"
        ? clock.aggregate_base_seconds + elapsed
        : elapsed;
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
    extractBridgeError(_result, fallback) { return fallback; },
    handleResult(value) { return value; },
  };

  const document = {
    readyState: "loading",
    addEventListener() {},
    getElementById(id) {
      if (id === "toggle-pause-btn") return toggleButton;
      return id === `page-${App.currentPage}` ? pageRoot : null;
    },
    querySelectorAll() { return []; },
    querySelector() { return null; },
  };

  const context = {
    window: {
      WorkTraceApp: App,
      pywebview: {
        api: {
          toggle_pause() {
            toggleCalls += 1;
            return new Promise((resolve) => toggleResolvers.push(resolve));
          },
        },
      },
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
    toggleButton,
    acceptRefresh(live, revision, sampledAt = now) {
      return App.acceptRefreshStateRuntime(
        runtimeState(App.currentPage, live, revision, sampledAt)
      );
    },
    acceptPage(live, revision, reportDate = REPORT_DATE, sampledAt = now) {
      const payload = runtimeState(App.currentPage, live, revision, sampledAt);
      payload.runtime.scope_report_date = reportDate;
      return App.acceptPagePayloadRuntime(payload, App.currentPage, reportDate);
    },
    advance(milliseconds) { now += milliseconds; },
    nowValue() { return now; },
    resolveToggle(result) {
      const resolve = toggleResolvers.shift();
      assert.ok(resolve, "expected an in-flight toggle request");
      resolve(result);
    },
    counts() { return { renderCalls, statisticsTicks, timelineTicks, toggleCalls }; },
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

test("cached presentation projection cannot bypass an expired runtime lease", () => {
  const { App, acceptRefresh, acceptPage, advance, nowValue } = harness("timeline");

  assert.equal(acceptRefresh(true, "live-1"), true);
  const cachedClock = App.liveRuntimeStore.get().liveClock;
  assert.equal(App.projectLiveClockDurationNow(cachedClock, nowValue()), 110);

  advance(10001);
  assert.equal(
    App.computeClockDurationNow(cachedClock, nowValue()),
    120,
    "pure clock math must remain independent from runtime freshness"
  );
  assert.equal(
    App.projectLiveClockDurationNow(cachedClock, nowValue()),
    null,
    "cache rerender must not mint new seconds after freshness expiry"
  );

  assert.equal(acceptRefresh(true, "live-2"), true);
  assert.equal(
    App.projectLiveClockDurationNow(App.liveRuntimeStore.get().liveClock, nowValue()),
    null,
    "heartbeat refresh alone must not re-authorize presentation projection"
  );

  assert.equal(acceptPage(true, "page-live"), true);
  assert.equal(
    App.projectLiveClockDurationNow(App.liveRuntimeStore.get().liveClock, nowValue()),
    110,
    "fresh authoritative page model may re-authorize projection"
  );
});

test("shared live sample freshness uses the runtime lease and future-skew boundary", () => {
  const { App, nowValue } = harness("overview");
  const now = nowValue();

  assert.equal(App.liveSampleFresh(now - 10000, now), true);
  assert.equal(App.liveSampleFresh(now - 10001, now), false);
  assert.equal(App.liveSampleFresh(now + 2000, now), true);
  assert.equal(App.liveSampleFresh(now + 2001, now), false);
});

test("a live response stale before arrival cannot become or refresh runtime authority", () => {
  const { App, acceptRefresh, acceptPage, nowValue } = harness("overview");

  assert.equal(acceptRefresh(true, "delayed", nowValue() - 30000), true);
  assert.equal(App.getActiveLiveClock(), null);
  assert.equal(App.liveClockContractRefreshRequested, true);

  assert.equal(acceptPage(true, "delayed-page", REPORT_DATE, nowValue() - 30000), false);
  assert.equal(
    App.getActiveLiveClock(),
    null,
    "a stale page-model response must remain fail-closed"
  );

  assert.equal(
    acceptPage(true, "fresh-page"),
    false,
    "a page model cannot replace a stale canonical heartbeat on its own"
  );
  assert.equal(acceptRefresh(true, "fresh-heartbeat"), true);
  assert.equal(acceptPage(true, "fresh-page"), true);
  assert.ok(App.getActiveLiveClock());
  assert.equal(App.liveRuntimeStore.get().liveRevision, "fresh-heartbeat");
});

test("a materially future-dated live source clock fails closed", () => {
  const { App, acceptRefresh, nowValue } = harness("overview");

  assert.equal(acceptRefresh(true, "future", nowValue() + 2001), true);
  assert.equal(App.getActiveLiveClock(), null);
  assert.equal(App.liveClockContractRefreshRequested, true);
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

test("statistics freshness is page-owned rather than canonical runtime-rebase gated", () => {
  const { App, acceptRefresh, advance, counts } = harness("statistics");

  acceptRefresh(true, "live-1");
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 1);

  advance(10001);
  App.applyLocalTicker();
  assert.equal(
    counts().statisticsTicks,
    2,
    "the coordinator must delegate stale Statistics handling to its snapshot-owned live target"
  );

  acceptRefresh(true, "live-2");
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 3);

  acceptRefresh(false, "stopped");
  App.applyLocalTicker();
  assert.equal(counts().statisticsTicks, 4, "runtime liveness must not create a second Statistics gate");
});

test("timeline structural local tick still runs while live projection is stale", () => {
  const { App, acceptRefresh, advance, counts } = harness("timeline");

  acceptRefresh(true, "live-1");
  advance(10001);
  App.applyLocalTicker();

  assert.equal(counts().timelineTicks, 1, "freshness safety must not block timeline structural draining");
});

test("pause toggle is single-flight until the authoritative mutation settles", async () => {
  const h = harness("overview");

  const first = h.App.togglePause();
  const second = h.App.togglePause();

  assert.equal(first, second);
  assert.equal(h.toggleButton.disabled, true);
  await Promise.resolve();
  assert.equal(h.counts().toggleCalls, 1);

  h.resolveToggle({ ok: true, status: "paused", paused: true, display: "已暂停" });
  await first;

  assert.equal(h.toggleButton.disabled, false);

  const third = h.App.togglePause();
  await Promise.resolve();
  assert.equal(h.counts().toggleCalls, 2, "a later deliberate action must still be allowed");
  h.resolveToggle({ ok: true, status: "running", paused: false, display: "记录中" });
  await third;
  assert.equal(h.toggleButton.disabled, false);
});
