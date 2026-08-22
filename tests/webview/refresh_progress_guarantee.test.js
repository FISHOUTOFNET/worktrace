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
  const start = initSource.indexOf("    function clearScheduledAutomaticPageRefresh()");
  const end = initSource.indexOf("    function settingsRuntimeIdentity", start);
  assert.ok(start >= 0 && end > start, "scheduler source boundary");

  let now = 1000;
  let nextTimerId = 1;
  const timers = [];
  const App = { currentPage: "overview" };
  const context = {
    App,
    Date: { now() { return now; } },
    window: {
      setTimeout(fn, ms) {
        const timer = { id: nextTimerId++, fn, ms, cancelled: false };
        timers.push(timer);
        return timer.id;
      },
      clearTimeout(id) {
        const timer = timers.find((item) => item.id === id);
        if (timer) timer.cancelled = true;
      },
    },
    nonNegativeInt(value, fallback) {
      return typeof value === "number" && Number.isInteger(value) && value >= 0
        ? value
        : (fallback || 0);
    },
    automaticRefreshScopeKey(page) { return `${page}|scope`; },
    pageNeedsRefresh() { return true; },
    automaticRefreshAllowedForPage() { return true; },
    refreshCurrentPageData() {},
  };
  vm.createContext(context);
  vm.runInContext(
    [
      "var AUTOMATIC_PAGE_REFRESH_DELAY_MS = 1500;",
      "var automaticPageRefreshTimer = null;",
      "var automaticPageRefreshKey = '';",
      "var automaticPageRefreshDueAtEpochMs = 0;",
      initSource.slice(start, end),
      "this.scheduleForTest = scheduleAutomaticPageRefresh;",
    ].join("\n"),
    context,
    { filename: "refresh_scheduler_extract.js" }
  );
  return {
    App,
    timers,
    schedule: context.scheduleForTest,
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

test("an earlier normal refresh preempts a later failure retry", () => {
  const { timers, schedule, setNow } = schedulerHarness();

  schedule(5000);
  assert.equal(pendingTimers(timers)[0].ms, 5000);

  setNow(2000);
  schedule(1500);

  assert.equal(timers.length, 2);
  assert.equal(timers[0].cancelled, true);
  assert.equal(pendingTimers(timers).length, 1);
  assert.equal(pendingTimers(timers)[0].ms, 1500);
});

test("an already-earlier retry is not delayed by a later normal request", () => {
  const { timers, schedule, setNow } = schedulerHarness();

  schedule(5000);
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
