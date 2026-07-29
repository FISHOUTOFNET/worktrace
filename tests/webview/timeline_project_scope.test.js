const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function classList() {
  const values = new Set();
  return {
    add(...names) { names.forEach((name) => values.add(name)); },
    remove(...names) { names.forEach((name) => values.delete(name)); },
    contains(name) { return values.has(name); },
    toggle(name, force) {
      if (force === true) values.add(name);
      else if (force === false) values.delete(name);
      else if (values.has(name)) values.delete(name);
      else values.add(name);
    },
  };
}

function harness() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        value: "",
        hidden: false,
        disabled: false,
        textContent: "",
        innerHTML: "",
        classList: classList(),
        setAttribute() {},
        getAttribute() { return null; },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
        focus() {},
      });
    }
    return elements.get(id);
  }

  const context = {
    Promise, Error, String, Number, Array, Date, Math, JSON,
    performance: { now: () => 0 },
    window: {
      WorkTraceApp: {},
      matchMedia: () => ({ matches: false }),
      setTimeout,
      clearTimeout,
      console: { debug() {} },
    },
    document: {
      activeElement: null,
      getElementById: element,
      createElement(tag) { return element(`created-${tag}-${elements.size}`); },
      querySelectorAll() { return []; },
      documentElement: {
        getAttribute() { return null; },
        setAttribute() {},
      },
    },
  };
  vm.createContext(context);
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    selectedProjectionInstanceKey: null,
    selectedProjectionRevision: null,
    selectedTimelineAnchorActivityId: null,
    selectedTimelineWasInProgress: false,
    currentSessions: [],
    detailsInFlight: {},
    timelineDate: "2026-07-30",
    timelineRequestState: {
      nextSelectionOwner() { return {}; },
      detailRequestKey() { return "details"; },
      isCurrentDetailsOwner() { return true; },
    },
    bridge: {
      getTimelineSessionActivitySummary() {
        return new Promise(() => {});
      },
    },
    loadProjects() { return Promise.resolve([]); },
    renderCurrentActivityElement() {},
    formatDuration(seconds) { return String(seconds); },
    formatProjectLabel(name) { return String(name || "未归类"); },
    escapeHtml(value) { return String(value); },
    validateLiveClock() { return null; },
    recordLiveClockContractViolation() {},
    clearLiveClockTarget() {},
    setLiveClockTarget() {},
    renderDurationProjected() {},
    liveContinuityKey() { return ""; },
    liveClockDataAttributes() { return ""; },
    handleResult(result) { return result; },
    acceptLiveRuntimePayload() { return true; },
    isPagePayloadCompatibleWithRuntime() { return true; },
    runtimeReportDateForPage() { return "2026-07-30"; },
    payloadReportDate() { return "2026-07-30"; },
  });

  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/timeline.js"),
      "utf8"
    ),
    context,
    { filename: "timeline.js" }
  );
  return { App, element };
}

function row(overrides = {}) {
  return {
    row_kind: "project_session",
    projection_instance_key: "base:1",
    projection_revision: "rev-1",
    start_time: "2026-07-30T09:00:00",
    duration_seconds: 600,
    project_id: 7,
    project_name: "正式项目",
    is_report_project: true,
    is_report_classified: true,
    is_report_uncategorized: false,
    privacy_redacted: false,
    project_is_deleted: false,
    ...overrides,
  };
}

test("timeline project scope uses the authoritative matrix for every row kind", () => {
  const { App } = harness();
  const matrix = [
    [row(), "project", "ordinary official project"],
    [row({
      project_id: 1,
      project_name: "未归类",
      is_report_project: false,
      is_report_classified: false,
      is_report_uncategorized: true,
    }), "unclassified", "ordinary unclassified"],
    [row({
      project_id: 1,
      project_name: "未归类",
      is_report_project: false,
      is_report_classified: false,
      is_report_uncategorized: true,
      has_project_override: true,
    }), "unclassified", "manual project removal"],
    [row({
      row_kind: "standalone_status",
      project_id: 0,
      project_name: "已排除",
      status: "excluded",
      privacy_redacted: true,
      is_report_project: false,
      is_report_classified: false,
      is_report_uncategorized: true,
    }), "status", "standalone excluded"],
    [row({
      row_kind: "standalone_status",
      project_id: 0,
      status: "idle",
      is_report_project: false,
      is_report_classified: false,
      is_report_uncategorized: true,
    }), "status", "standalone idle"],
    [row({
      row_kind: "standalone_status",
      project_id: 0,
      status: "error",
      is_report_project: false,
      is_report_classified: false,
      is_report_uncategorized: true,
    }), "status", "standalone error"],
    [row({
      project_id: 0,
      privacy_redacted: true,
      is_report_project: false,
      is_report_classified: false,
      is_report_uncategorized: true,
    }), "status", "privacy redacted"],
    [row({ project_is_deleted: true }), "other", "deleted project history"],
    [row({ projection_kind: "merge" }), "project", "merged session"],
    [row({
      projection_kind: "split",
      project_id: 9,
      has_project_override: true,
    }), "project", "split and project override"],
  ];

  for (const [session, expected, label] of matrix) {
    assert.equal(App.timelineProjectScope(session), expected, label);
  }
});

test("unclassified and concrete project filters reuse the same scope decision", () => {
  const { App, element } = harness();
  const project = row();
  const unclassified = row({
    projection_instance_key: "base:unclassified",
    project_id: 1,
    project_name: "未归类",
    is_report_project: false,
    is_report_classified: false,
    is_report_uncategorized: true,
  });
  const status = row({
    projection_instance_key: "status:excluded",
    row_kind: "standalone_status",
    project_id: 0,
    project_name: "",
    display_status: "已排除",
    status: "excluded",
    privacy_redacted: true,
    is_report_project: false,
    is_report_classified: false,
    is_report_uncategorized: true,
  });

  element("timeline-project-filter").value = "unclassified";
  assert.deepEqual(
    Array.from(App.filteredTimelineSessions([project, unclassified, status])),
    [unclassified]
  );
  element("timeline-project-filter").value = "7";
  assert.deepEqual(
    Array.from(App.filteredTimelineSessions([project, unclassified, status])),
    [project]
  );
});

test("special status display never falls back to the unclassified project label", () => {
  const { App } = harness();
  const status = row({
    row_kind: "standalone_status",
    project_id: 0,
    project_name: "",
    display_status: "已排除",
    status: "excluded",
    is_report_project: false,
    is_report_uncategorized: true,
  });
  assert.equal(App.timelineProjectLabel(status), "已排除");
  assert.notEqual(App.timelineProjectLabel(status), "未归类");
});

test("details pane selection class is added, cleared, and removed when filtered out", () => {
  const { App, element } = harness();
  const project = row();
  const pane = element("timeline-details-pane");

  App.selectTimelineSession(project.projection_instance_key, [project]);
  assert.equal(pane.classList.contains("has-selection"), true);

  App.resetTimelineReportSelection();
  assert.equal(pane.classList.contains("has-selection"), false);

  App.selectTimelineSession(project.projection_instance_key, [project]);
  element("timeline-project-filter").value = "unclassified";
  App.showTimeline({
    date: "2026-07-30",
    today: "2026-07-30",
    today_total_seconds: 600,
    entries: [project],
    current_activity: {},
  });
  assert.equal(pane.classList.contains("has-selection"), false);
  assert.equal(App.selectedProjectionInstanceKey, null);
});
