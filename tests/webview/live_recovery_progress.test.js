const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const jsDir = path.join(__dirname, "../../worktrace/webview_ui/js");

function loadStatisticsProjection() {
  let now = 1000;
  const total = { textContent: "" };
  const emptyBody = { querySelectorAll: () => [] };
  const App = {
    currentPage: "statistics",
    statisticsLiveTickerSuspended: false,
    statisticsLastLiveRenderKey: "",
    statisticsAcceptedPayload: {
      summary: {
        snapshot_revision: "snapshot-1",
        total_duration_seconds: 100,
        by_project: [],
        by_file: [],
        by_app: [],
      },
      exportTicket: {
        revision: "snapshot-1",
        live_target: {
          enabled: true,
          ticking: true,
          sampled_at_epoch_ms: 1000,
          elapsed_seconds_at_sample: 10,
          project_key: "",
          file_key: "",
          app_key: "",
        },
      },
      filters: { allTime: true },
    },
    statisticsLoaded: true,
    handleResult: (value) => value,
    liveSampleFresh: (sampledAt, value) => value - sampledAt <= 10000,
    liveSampleRebaseDue: (sampledAt, value) => {
      const age = value - sampledAt;
      return age >= 7500 && age <= 10000;
    },
    liveRuntimeStore: {
      get: () => ({ collector: { live_eligible: true } }),
    },
    formatDuration: (seconds) => String(seconds),
  };
  const context = {
    Promise, Error, String, Number, Boolean, Array, Object, Math, JSON, parseInt,
    Date: { now: () => now },
    document: {
      getElementById(id) {
        if (id === "stats-total") return total;
        if (["stats-by-project", "stats-by-file", "stats-by-app"].includes(id)) return emptyBody;
        return null;
      },
    },
  };
  context.window = context;
  context.WorkTraceApp = App;
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(jsDir, "statistics.js"), "utf8"),
    context,
    { filename: "statistics.js" }
  );
  return {
    App,
    total,
    setNow(value) { now = value; },
  };
}

test("Statistics soft-rebases before the hard lease and keeps its recovery watchdog alive", () => {
  const { App, total, setNow } = loadStatisticsProjection();

  setNow(8500);
  const soft = App.statistics.applyLocalTick();
  assert.equal(total.textContent, "107", "fresh projection must continue rendering before rebase");
  assert.equal(soft.refreshRequired, true);
  assert.equal(soft.reason, "statistics_live_target_rebase_due");
  assert.equal(App.statisticsLiveTickerSuspended, false);

  setNow(11500);
  const stale = App.statistics.applyLocalTick();
  assert.equal(stale.refreshRequired, true);
  assert.equal(stale.reason, "statistics_live_target_stale");
  assert.equal(App.statisticsLiveTickerSuspended, true);
  assert.equal(total.textContent, "107", "hard-stale target must fail closed");

  setNow(12500);
  const watchdog = App.statistics.applyLocalTick();
  assert.equal(watchdog.refreshRequired, true, "blocked projection must keep requesting recovery");
  assert.equal(watchdog.reason, "statistics_projection_blocked");
  assert.equal(total.textContent, "107");
});

function runtimeState(databaseReplacementEpoch) {
  return {
    ok: true,
    runtime: {
      schema_version: 2,
      surface: "overview",
      scope_report_date: "2026-08-22",
      live_report_date: "2026-08-22",
      snapshot: { revision: `live-${databaseReplacementEpoch}`, id: `sample-${databaseReplacementEpoch}` },
      revisions: { structure: "structure-1", page: "page-1" },
      collector: {
        live_eligible: false,
        status: "running",
        paused: false,
        display: "running",
      },
      clock: {
        is_live: false,
        duration_semantic: "static_closed",
        display_span_id: "",
        stable_live_key_hash: "",
        sampled_at_epoch_ms: 1000,
      },
      current_activity: { active: false, status: "idle" },
      current_project: null,
      workers: {},
      generations: {
        report_structure: 1,
        classification_catalog: 1,
        settings: 1,
        privacy_catalog: 1,
      },
      database_replacement_epoch: databaseReplacementEpoch,
      error_codes: [],
      runtime_consistent: true,
      needs_full_refresh: false,
    },
  };
}

function loadCoordinator() {
  let dataEpoch = 0;
  let refreshCalls = 0;
  const responses = [runtimeState(2), runtimeState(2)];
  const requestCoordinator = {
    beginLatest: () => ({ dataEpoch }),
    isCurrent: (token) => token.dataEpoch === dataEpoch,
    bumpDataEpoch: () => { dataEpoch += 1; },
  };
  const App = {
    currentPage: "overview",
    heartbeatTimer: null,
    HEARTBEAT_INTERVAL_MS: 1000,
    requestCoordinator,
    localTodayStr: () => "2026-08-22",
    runtimeReportDateForPage: (_page, date) => date || "2026-08-22",
    handleResult: (value) => value,
    validateLiveClock: (clock) => clock && typeof clock === "object" ? clock : null,
    recordLiveClockContractViolation() {},
    readLiveClockTarget: () => null,
    clearLiveClockTarget() {},
    liveTargetCompatibleWithRuntime: () => true,
    renderLiveDurationTarget() {},
    computeClockDurationNow: () => 0,
    showStatus() {},
    showError() {},
    clearError() {},
    showGlobalAlert() {},
    clearGlobalAlert() {},
  };
  App.overview = {
    refreshPolicy: { entryGenerations: [], automaticGenerations: [], deferred: true },
    hasLoadedData: () => true,
    refreshEvidence: () => null,
    automaticRefreshAllowed: () => true,
    resetGeneration() {},
    updateCurrentActivity() {},
  };
  App.pageLifecycle = {
    names: ["overview"],
    capability: () => App.overview,
    resetGeneration: () => App.overview.resetGeneration(),
    bindEvents() {},
    onPageLeft() {},
  };
  const context = {
    Promise, Error, String, Number, Boolean, Array, Object, Math, JSON, parseInt,
    Date,
    document: {
      readyState: "loading",
      addEventListener() {},
      getElementById: () => null,
      querySelectorAll: () => [],
    },
    setTimeout: () => 1,
    clearTimeout() {},
    setInterval: () => 1,
    clearInterval() {},
    addEventListener() {},
    removeEventListener() {},
  };
  context.window = context;
  context.WorkTraceApp = App;
  context.pywebview = {
    api: {
      get_refresh_state: () => {
        const response = responses[Math.min(refreshCalls, responses.length - 1)];
        refreshCalls += 1;
        return Promise.resolve(response);
      },
      get_status: () => Promise.resolve({ ok: true, status: "running", paused: false }),
    },
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(jsDir, "init_fd_work_v5.js"), "utf8"),
    context,
    { filename: "init_fd_work_v5.js" }
  );
  return {
    App,
    refreshCalls: () => refreshCalls,
  };
}

test("database replacement invalidates payload ownership without permanently locking heartbeat single-flight", async () => {
  const { App, refreshCalls } = loadCoordinator();
  assert.equal(App.acceptRefreshStateRuntime(runtimeState(1)), true);

  await App.runRevisionCheck();
  assert.equal(refreshCalls(), 1);
  assert.equal(App.refreshCheckInFlight, false, "the owning flight must release after epoch invalidation");

  await App.runRevisionCheck();
  assert.equal(refreshCalls(), 2, "the next heartbeat must reach the bridge");
  assert.equal(App.refreshCheckInFlight, false);
});

test("freshness recovery contracts stay wired through the central coordinator", () => {
  const initSource = fs.readFileSync(path.join(jsDir, "init_fd_work_v5.js"), "utf8");
  const overviewSource = fs.readFileSync(path.join(jsDir, "overview.js"), "utf8");
  const statisticsSource = fs.readFileSync(path.join(jsDir, "statistics.js"), "utf8");
  const compatibilitySource = fs.readFileSync(path.join(jsDir, "statistics_live_projection.js"), "utf8");

  assert.match(initSource, /function liveSampleRebaseDue\(/);
  assert.match(initSource, /authoritativeRebase:\s*true/);
  assert.match(initSource, /ensureActivePageRecovery\(\)/);
  assert.doesNotMatch(initSource, /if \(App\.requestCoordinator\.isCurrent\(token\)\) App\.refreshCheckInFlight = false/);
  assert.doesNotMatch(overviewSource, /suppressCollectionCommit/);
  assert.doesNotMatch(overviewSource, /suppressNextOverviewCollectionRefresh/);
  assert.match(overviewSource, /runtimeRefreshIdentity/);
  assert.match(statisticsSource, /statistics_projection_blocked/);
  assert.match(statisticsSource, /statistics_live_target_rebase_due/);
  assert.doesNotMatch(compatibilitySource, /App\.statistics\s*=/);
  assert.doesNotMatch(compatibilitySource, /App\.handleResult\s*=/);
});
