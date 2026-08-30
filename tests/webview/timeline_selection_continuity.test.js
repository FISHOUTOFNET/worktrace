const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function classList() {
  const values = new Set();
  return {
    add(name) { values.add(name); },
    remove(name) { values.delete(name); },
    contains(name) { return values.has(name); },
  };
}

function harness(options = {}) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        value: "",
        hidden: false,
        innerHTML: "",
        textContent: "",
        classList: classList(),
        addEventListener() {},
        setAttribute() {},
        getAttribute() { return null; },
        querySelectorAll() { return []; },
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
    Date,
    Math,
    JSON,
    performance: { now: () => 0 },
    window: {
      WorkTraceApp: {},
      console: { debug() {} },
      matchMedia: () => ({ matches: false }),
    },
    document: {
      activeElement: null,
      getElementById: element,
      querySelectorAll() { return []; },
    },
  };
  vm.createContext(context);
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    currentPage: "timeline",
    timelineDate: "2026-08-25",
    currentSessions: [],
    detailsInFlight: {},
    timelineEditorState: {
      clear() {},
      currentSession() { return null; },
      isDirty() { return false; },
      populate() {},
      setReadOnlyNotice() {},
      resetGeneration() {},
      bindEvents() {},
      syncMutationState() {},
    },
    projectCatalog: null,
    renderTimelineTotal() {},
    renderCurrentActivityElement() {},
    filteredTimelineSessions(entries) {
      const value = element("timeline-project-filter").value;
      if (!value) return entries.slice();
      return entries.filter((session) => String(session.project_id || "") === value);
    },
    timelinePresentation: {
      exactRowClock() { return null; },
      clockedSeconds(_clock, durable) { return durable; },
    },
    formatTimelineDuration(seconds) { return String(seconds); },
    formatTimelineStartTime() { return "09:00"; },
    timelineProjectScope() { return "project"; },
    timelineProjectLabel(session) { return session.project_name || "P"; },
    liveContinuityKey() { return ""; },
    liveClockDataAttributes() { return ""; },
    escapeHtml(value) { return String(value == null ? "" : value); },
    closeTimelineDrawer() {},
    dismissTimelineContextTransientUi() {},
    openTimelineDrawer() {},
    closeTimelineAdvancedMenu() {},
    resetTimelineTransientUi() {},
    updateFDWorkEntryButton() {},
    timelineRequestState: {
      nextSelectionOwner() { return {}; },
      detailRequestKey() { return "details"; },
      isCurrentDetailsOwner() { return true; },
    },
    bridge: {
      getTimelineSessionActivitySummary() { return new Promise(() => {}); },
    },
  });

  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/timeline.js"), "utf8"),
    context,
    { filename: "timeline.js" }
  );
  if (options.loadTimelineReport) App.loadTimelineReport = options.loadTimelineReport(App, element);
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/timeline_selection_continuity.js"),
      "utf8"
    ),
    context,
    { filename: "timeline_selection_continuity.js" }
  );
  return { App, element };
}

function baseSession(key, overrides = {}) {
  return {
    projection_kind: "base",
    projection_instance_key: key,
    projection_revision: "rev-new",
    anchor_activity_id: 42,
    first_activity_id: 42,
    activity_ids: [42],
    is_in_progress: false,
    project_id: 2,
    project_name: "B",
    duration_seconds: 600,
    start_time: "2026-08-25T09:00:00",
    ...overrides,
  };
}

test("closed base selection resolves after a projection-key change", () => {
  const { App } = harness();
  const replacement = baseSession("base:new");
  assert.equal(
    App.resolveTimelineSelectionContinuity("base:old", 42, [replacement]),
    replacement
  );
});

test("base continuity follows membership even when the anchor is no longer first", () => {
  const { App } = harness();
  const replacement = baseSession("base:new", {
    anchor_activity_id: 11,
    first_activity_id: 11,
    activity_ids: [11, 42, 43],
  });
  assert.equal(
    App.resolveTimelineSelectionContinuity("base:old", 42, [replacement]),
    replacement
  );
});

test("derived projection does not fall back to a base session sharing members", () => {
  const { App } = harness();
  assert.equal(
    App.resolveTimelineSelectionContinuity("copy:old", 42, [baseSession("base:new")]),
    null
  );
});

test("ambiguous base membership fails closed", () => {
  const { App } = harness();
  assert.equal(App.resolveTimelineSelectionContinuity("base:old", 42, [
    baseSession("base:a"),
    baseSession("base:b", { first_activity_id: 7, activity_ids: [7, 42] }),
  ]), null);
});

test("closed selection is restored after authoritative refresh without overriding user filter", async () => {
  const replacement = baseSession("base:new");
  const { App, element } = harness({
    loadTimelineReport: (app) => () => {
      app.selectedProjectionInstanceKey = null;
      app.selectedProjectionRevision = null;
      app.selectedTimelineAnchorActivityId = null;
      app.currentSessions = [replacement];
      app.lastTimelineData = {
        date: "2026-08-25",
        entries: [replacement],
        current_activity: {},
        today_total_seconds: 600,
      };
      return Promise.resolve();
    },
  });
  App.selectedProjectionInstanceKey = "base:old";
  App.selectedProjectionRevision = "rev-old";
  App.selectedTimelineAnchorActivityId = 42;
  App.lastTimelineData = { date: "2026-08-25", entries: [] };
  element("timeline-project-filter").value = "";

  await App.loadTimelineReport("2026-08-25", { showLoading: false });

  assert.equal(App.selectedProjectionInstanceKey, "base:new");
  assert.equal(App.selectedTimelineAnchorActivityId, 42);

  App.selectedProjectionInstanceKey = "base:old";
  App.selectedProjectionRevision = "rev-old";
  App.selectedTimelineAnchorActivityId = 42;
  element("timeline-project-filter").value = "1";

  await App.loadTimelineReport("2026-08-25", { showLoading: false });

  // A user filter that hides the target must remain authoritative; continuity
  // restoration is not allowed to clear it during an ordinary refresh.
  assert.equal(element("timeline-project-filter").value, "1");
  assert.equal(App.selectedProjectionInstanceKey, null);
});

test("explicit Overview intent clears a stale project filter and selects the rebased session", async () => {
  const { App, element } = harness();
  const replacement = baseSession("base:new");
  App.currentSessions = [replacement];
  App.lastTimelineData = {
    date: "2026-08-25",
    entries: [replacement],
    current_activity: {},
    today_total_seconds: 600,
  };
  App.timelineLoaded = true;
  App.currentPage = "overview";
  element("timeline-project-filter").value = "1";
  App.switchPage = (page) => { App.currentPage = page; };
  App.pageNeedsRefresh = () => false;
  let selectedKey = "";
  App.selectTimelineSession = (key) => {
    selectedKey = key;
    App.selectedProjectionInstanceKey = key;
  };

  await App.openTimelineSelectionIntent({
    projection_kind: "base",
    projection_instance_key: "base:old",
    anchor_activity_id: 42,
    first_activity_id: 42,
    activity_ids: [42],
    start_time: "2026-08-25T10:00:00",
  }, "");

  assert.equal(element("timeline-project-filter").value, "");
  assert.equal(selectedKey, "base:new");
  assert.equal(App.pendingTimelineSelectionIntent, null);
});
