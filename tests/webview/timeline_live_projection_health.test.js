const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const REPORT_DATE = "2026-08-29";

function aggregateClock() {
  return {
    sampled_at_epoch_ms: 100000,
    started_at_epoch_ms: 90000,
    elapsed_seconds_at_sample: 10,
    aggregate_base_seconds: 100,
    duration_semantic: "aggregate_live",
    is_live: true,
    live_state: "persisted_open",
    display_span_id: "span-1",
    stable_live_key_hash: "key-1",
  };
}

function runtimeClock() {
  return {
    ...aggregateClock(),
    aggregate_base_seconds: 0,
    duration_semantic: "current_live",
  };
}

function harness() {
  const totalTarget = { compatible: true };
  let sessionTargets = [{ compatible: true }];
  let detailTargets = [{ compatible: true }];
  let editing = false;
  let baseTickResult = false;
  const projectFilter = { value: "" };

  const document = {
    getElementById(id) {
      if (id === "timeline-total") return totalTarget;
      if (id === "timeline-project-filter") return projectFilter;
      return null;
    },
    querySelectorAll(selector) {
      if (selector.includes('data-live-role="timeline-session"')) return sessionTargets;
      if (selector.includes('data-live-role="timeline-detail"')) return detailTargets;
      return [];
    },
  };

  const runtime = {
    liveReportDate: REPORT_DATE,
    liveClock: runtimeClock(),
    currentActivity: {
      active: true,
      status: "normal",
      activity_id: 42,
      persisted_activity_id: 42,
    },
    runtimeConsistent: true,
    needsFullRefresh: false,
  };

  const liveOwner = {
    row_kind: "project_session",
    projection_instance_key: "session-1",
    activity_ids: [42],
    live_clock: aggregateClock(),
  };

  const App = {
    currentPage: "timeline",
    timelineDate: REPORT_DATE,
    timelineLoaded: true,
    selectedProjectionInstanceKey: null,
    lastSessionActivitySummaryViewModel: null,
    lastTimelineData: {
      date: REPORT_DATE,
      today: REPORT_DATE,
      total_live_clock: aggregateClock(),
      entries: [liveOwner],
    },
    localTodayStr() { return REPORT_DATE; },
    validateLiveClock(value) {
      return value && typeof value === "object" ? value : null;
    },
    liveTargetCompatibleWithRuntime(target) {
      return !!target && target.compatible !== false;
    },
    formatDuration(value) { return String(value); },
    formatProjectLabel(value) { return String(value || ""); },
    projectLiveClockDurationNow() { return 0; },
    recordLiveClockContractViolation() {},
    setLiveClockTarget() {},
    clearLiveClockTarget() {},
    renderDurationProjected() {},
    liveContinuityKey() { return "live"; },
    liveClockDataAttributes() { return ""; },
    escapeHtml(value) { return String(value || ""); },
    iconMarkup() { return ""; },
    liveRuntimeStore: {
      get() { return runtime; },
    },
  };

  const window = { WorkTraceApp: App };
  const context = {
    window,
    document,
    console,
    Promise,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    JSON,
    parseInt,
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/timeline_presentation.js"),
      "utf8"
    ),
    context,
    { filename: "timeline_presentation.js" }
  );

  App.timeline = Object.freeze({
    applyLocalTick() { return Promise.resolve(baseTickResult); },
    isEditingActive() { return editing; },
  });
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/ui_composition.js"),
      "utf8"
    ),
    context,
    { filename: "ui_composition.js" }
  );

  return {
    App,
    runtime,
    liveOwner,
    totalTarget,
    setSessionTargets(value) { sessionTargets = value; },
    setDetailTargets(value) { detailTargets = value; },
    setEditing(value) { editing = value; },
    setBaseTickResult(value) { baseTickResult = value; },
  };
}

test("healthy live timeline reports no recovery requirement", () => {
  const { App, runtime } = harness();

  const health = App.timelinePresentation.liveProjectionHealth(runtime);

  assert.equal(health.healthy, true);
  assert.equal(health.refreshRequired, false);
  assert.equal(health.reason, "healthy");
});

test("live timeline requires total clock and total target", () => {
  const { App, runtime, totalTarget } = harness();
  App.lastTimelineData.total_live_clock = null;

  let health = App.timelinePresentation.liveProjectionHealth(runtime);
  assert.equal(health.refreshRequired, true);
  assert.equal(health.reason, "timeline_total_live_clock_missing");

  App.lastTimelineData.total_live_clock = aggregateClock();
  totalTarget.compatible = false;
  health = App.timelinePresentation.liveProjectionHealth(runtime);
  assert.equal(health.refreshRequired, true);
  assert.equal(health.reason, "timeline_total_live_target_missing");
});

test("live owner requires aggregate clock and visible session target", () => {
  const { App, runtime, liveOwner, setSessionTargets } = harness();
  liveOwner.live_clock = null;

  let health = App.timelinePresentation.liveProjectionHealth(runtime);
  assert.equal(health.refreshRequired, true);
  assert.equal(health.reason, "timeline_session_live_clock_missing");

  liveOwner.live_clock = aggregateClock();
  setSessionTargets([]);
  health = App.timelinePresentation.liveProjectionHealth(runtime);
  assert.equal(health.refreshRequired, true);
  assert.equal(health.reason, "timeline_session_live_target_missing");
});

test("selected live details require a detail live target", () => {
  const { App, runtime, setDetailTargets } = harness();
  App.selectedProjectionInstanceKey = "session-1";
  App.lastSessionActivitySummaryViewModel = {
    projection_instance_key: "session-1",
    summary_rows: [{ summary_activity_ids: [42], live_clock: aggregateClock() }],
  };
  setDetailTargets([]);

  const health = App.timelinePresentation.liveProjectionHealth(runtime);

  assert.equal(health.refreshRequired, true);
  assert.equal(health.reason, "timeline_detail_live_target_missing");
});

test("historical and editing timeline states do not request live recovery", () => {
  const { App, runtime, setEditing } = harness();
  App.lastTimelineData.date = "2026-08-28";

  let health = App.timelinePresentation.liveProjectionHealth(runtime);
  assert.equal(health.refreshRequired, false);
  assert.equal(health.reason, "historical");

  App.lastTimelineData.date = REPORT_DATE;
  setEditing(true);
  health = App.timelinePresentation.liveProjectionHealth(runtime);
  assert.equal(health.refreshRequired, false);
  assert.equal(health.reason, "editing_deferred");
});

test("composition routes health recovery through the existing local tick contract", async () => {
  const { App, liveOwner, setSessionTargets, setBaseTickResult } = harness();
  liveOwner.live_clock = aggregateClock();
  setSessionTargets([]);

  const health = await App.timeline.applyLocalTick();
  assert.equal(health.refreshRequired, true);
  assert.equal(health.reason, "timeline_session_live_target_missing");

  setBaseTickResult(true);
  const structuralDrain = await App.timeline.applyLocalTick();
  assert.equal(structuralDrain, true, "existing structural refresh must retain priority");
});
