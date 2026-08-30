const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { loadTimelineModules } = require("./timeline_test_modules");

function harness() {
  let editing = false;
  let refreshes = 0;
  let refreshFailure = null;
  const document = {
    getElementById() { return null; },
    querySelectorAll() { return []; },
  };
  const App = {
    currentPage: "timeline",
    timelineDate: "2026-08-22",
    mutationState: "idle",
  };
  const window = {
    WorkTraceApp: App,
    document,
    clearTimeout,
    setTimeout,
  };
  const context = {
    window,
    document,
    Promise,
    Object,
    String,
    Array,
    Number,
    Math,
    Date,
    parseInt,
    setTimeout,
    clearTimeout,
  };
  vm.createContext(context);
  loadTimelineModules(context, __dirname);
  App.loadTimelineReport = () => {
    refreshes += 1;
    return refreshFailure ? Promise.reject(refreshFailure) : Promise.resolve();
  };
  return {
    App,
    refreshes: () => refreshes,
    setEditing(value) {
      editing = value;
      App.mutationState = editing ? "unknown" : "idle";
    },
    failRefresh(error) { refreshFailure = error; },
  };
}

test("Timeline live identity changes never suppress authoritative refresh", async () => {
  const { App, refreshes } = harness();
  App.timeline.onRuntimeTransition({ source: "refresh-state", liveChanged: true });

  await App.refreshTimeline();

  assert.equal(refreshes(), 1);
  assert.equal(App.suppressNextTimelineCollectionRefresh, undefined);
});

test("Timeline structural pending still drains through the authoritative refresh path", async () => {
  const { App, refreshes } = harness();
  App.timelineStructuralRefreshPending = true;

  assert.equal(await App.refreshTimeline(), true);
  assert.equal(refreshes(), 1);
  assert.equal(App.timelineStructuralRefreshPending, false);
});

test("Timeline holds structural refresh while editing and drains on a safe local tick", async () => {
  const { App, refreshes, setEditing } = harness();
  setEditing(true);
  App.timeline.onRuntimeTransition({
    source: "refresh-state",
    structureChanged: true,
    liveChanged: true,
  });

  assert.equal(App.timelineStructuralRefreshPending, true);
  assert.equal(await App.timeline.applyLocalTick(), false);
  assert.equal(refreshes(), 0);

  setEditing(false);
  assert.equal(await App.timeline.applyLocalTick(), true);
  assert.equal(refreshes(), 1);
  assert.equal(App.timelineStructuralRefreshPending, false);
});

test("Timeline restores structural pending when a drain refresh fails", async () => {
  const { App, failRefresh } = harness();
  App.timelineStructuralRefreshPending = true;
  failRefresh(new Error("refresh failed"));

  await assert.rejects(App.timeline.applyLocalTick(), /refresh failed/);
  assert.equal(App.timelineStructuralRefreshPending, true);
});

test("Timeline heartbeat overlay does not mutate the authoritative snapshot", () => {
  const { App } = harness();
  App.lastTimelineData = { current_activity: { marker: "A" } };

  App.timeline.updateCurrentActivity({ marker: "B" }, { render: false });

  assert.equal(App.lastTimelineData.current_activity.marker, "A");
});

test("Timeline runtime refresh identity is scoped to the live report date", () => {
  const { App } = harness();

  assert.equal(
    App.timeline.runtimeRefreshIdentity({
      liveReportDate: "2026-08-22",
      liveRevision: "rev-live",
    }),
    "rev-live"
  );
  assert.equal(
    App.timeline.runtimeRefreshIdentity({
      liveReportDate: "2026-08-23",
      liveRevision: "rev-other",
    }),
    ""
  );
});

test("Timeline automatic refresh is blocked while editing", () => {
  const { App, setEditing } = harness();
  setEditing(true);
  assert.equal(App.timeline.automaticRefreshAllowed("2026-08-22"), false);
  setEditing(false);
  assert.equal(App.timeline.automaticRefreshAllowed("2026-08-22"), true);
});
