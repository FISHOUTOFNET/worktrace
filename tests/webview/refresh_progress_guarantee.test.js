const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const initSource = fs.readFileSync(
  path.join(__dirname, "../../worktrace/webview_ui/js/init_fd_work_v5.js"),
  "utf8"
);

function schedulerHarness() {
  let now = 1000;
  let nextTimerId = 1;
  const timers = [];
  const App = {
    currentPage: "overview",
    heartbeatTimer: null,
    shellVisible: true,
    localTodayStr: () => "2026-08-22",
    runtimeReportDateForPage: (_page, date) => date || "2026-08-22",
    handleResult: (result) => result,
    requestCoordinator: {
      beginLatest: () => ({}),
      isCurrent: () => true,
      bumpDataEpoch() {},
    },
    validateLiveClock: () => null,
    recordLiveClockContractViolation() {},
    readLiveClockTarget: () => null,
    clearLiveClockTarget() {},
    liveTargetCompatibleWithRuntime: () => true,
    renderLiveDurationTarget() {},
    showStatus() {},
    showError() {},
    clearError() {},
    showGlobalAlert() {},
    clearGlobalAlert() {},
  };
  let rejectRefresh = false;
  App.overview = {
    refreshPolicy: {
      entryGenerations: ["report_structure"],
      automaticGenerations: ["report_structure"],
      deferred: true,
    },
    hasLoadedData: () => true,
    refreshEvidence: () => null,
    automaticRefreshAllowed: () => true,
    refreshScopeKey: () => "overview|scope",
    applyLocalTick: () => ({ refreshRequired: true }),
    onRefreshRequested: () => rejectRefresh
      ? Promise.reject(new Error("refresh failed"))
      : Promise.resolve(null),
    resetGeneration() {},
  };
  for (const page of ["timeline", "statistics", "rules", "settings"]) {
    App[page] = { resetGeneration() {} };
  }
  const pageRoot = { querySelectorAll: () => [] };
  const context = {
    Promise, Error, String, Number, Boolean, Array, Object, Math, JSON, parseInt,
    Date: { now() { return now; } },
    document: {
      readyState: "loading",
      addEventListener() {},
      getElementById: (id) => id === "page-overview" ? pageRoot : null,
      querySelectorAll: () => [],
    },
    setTimeout(fn, ms) {
      const timer = { id: nextTimerId++, fn, ms, cancelled: false };
      timers.push(timer);
      return timer.id;
    },
    clearTimeout(id) {
      const timer = timers.find((item) => item.id === id);
      if (timer) timer.cancelled = true;
    },
    setInterval: () => 1,
    clearInterval() {},
  };
  context.window = context;
  context.WorkTraceApp = App;
  context.pywebview = { api: {
    get_refresh_state: () => Promise.resolve(null),
    get_status: () => Promise.resolve({ ok: true, status: "running", paused: false }),
  } };
  context.addEventListener = () => {};
  context.removeEventListener = () => {};
  vm.createContext(context);
  for (const file of ["page_lifecycle.js", "init_fd_work_v5.js"]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
      context,
      { filename: file }
    );
  }
  return {
    App,
    timers,
    schedule: () => App.applyLocalTicker(),
    scheduleRetry: async () => {
      rejectRefresh = true;
      await App.refreshCurrentPageData(null, { automatic: true });
      rejectRefresh = false;
    },
    setNow(value) { now = value; },
  };
}

function pendingTimers(timers) {
  return timers.filter((timer) => !timer.cancelled);
}

test("same-scope deferred changes cannot postpone the first refresh deadline", () => {
  const { timers, schedule, setNow } = schedulerHarness();

  schedule();
  assert.equal(pendingTimers(timers).length, 1);
  assert.equal(pendingTimers(timers)[0].ms, 1500);

  setNow(1300);
  schedule();
  setNow(1800);
  schedule();

  assert.equal(timers.length, 1);
  assert.equal(pendingTimers(timers).length, 1);
  assert.equal(pendingTimers(timers)[0].ms, 1500);
});

test("an earlier normal refresh preempts a later failure retry", async () => {
  const { timers, schedule, scheduleRetry, setNow } = schedulerHarness();

  await scheduleRetry();
  assert.equal(pendingTimers(timers)[0].ms, 5000);

  setNow(2000);
  schedule(1500);

  assert.equal(timers.length, 2);
  assert.equal(timers[0].cancelled, true);
  assert.equal(pendingTimers(timers).length, 1);
  assert.equal(pendingTimers(timers)[0].ms, 1500);
});

test("an already-earlier retry is not delayed by a later normal request", async () => {
  const { timers, schedule, scheduleRetry, setNow } = schedulerHarness();

  await scheduleRetry();
  setNow(5000);
  schedule(1500);

  assert.equal(timers.length, 1);
  assert.equal(pendingTimers(timers).length, 1);
  assert.equal(pendingTimers(timers)[0].ms, 5000);
});

test("page-local self-heal requests are consumed only by the central coordinator", () => {
  assert.match(initSource, /result\.refreshRequired\s*!==\s*true/);
  assert.match(initSource, /markPageDirty\(page\)/);
  assert.match(initSource, /scheduleAutomaticPageRefresh\(\)/);
});
