const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { TIMELINE_MODULES, loadTimelineModules } = require("./timeline_test_modules");

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

test("Timeline consumes live-only suppression once", async () => {
  const { App, refreshes } = harness();
  App.timeline.onRuntimeTransition({ source: "refresh-state", liveChanged: true });

  await App.refreshTimeline();
  assert.equal(refreshes(), 0);
  assert.equal(App.suppressNextTimelineCollectionRefresh, false);

  await App.refreshTimeline();
  assert.equal(refreshes(), 1);
});

test("Timeline structural pending outranks one-shot suppression", async () => {
  const { App, refreshes } = harness();
  App.suppressNextTimelineCollectionRefresh = true;
  App.timelineStructuralRefreshPending = true;

  assert.equal(await App.refreshTimeline(), true);
  assert.equal(refreshes(), 1);
  assert.equal(App.timelineStructuralRefreshPending, false);
  assert.equal(App.suppressNextTimelineCollectionRefresh, false);
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

test("Timeline manual refresh bypasses passive live suppression", async () => {
  const { App, refreshes } = harness();
  App.timeline.onRuntimeTransition({ source: "refresh-state", liveChanged: true });

  await App.timeline.onRefreshRequested({ automatic: false });

  assert.equal(refreshes(), 1);
  assert.equal(App.suppressNextTimelineCollectionRefresh, false);
});

