const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function harness() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        hidden: false,
        disabled: false,
        value: "",
        textContent: "",
        innerHTML: "",
        className: "",
        classList: { add() {}, remove() {}, contains() { return false; } },
        setAttribute() {}, removeAttribute() {}, getAttribute() { return ""; },
        querySelectorAll() { return []; },
        addEventListener() {},
      });
    }
    return elements.get(id);
  }
  const context = {
    Promise,
    Error,
    Uint8Array,
    setTimeout,
    clearTimeout,
    window: { WorkTraceApp: {}, crypto: { randomUUID: (() => { let n = 0; return () => `request-${++n}`; })() } },
    document: {
      getElementById: element,
      querySelectorAll() { return []; },
      querySelector() { return null; },
      createElement() { return element(`created-${elements.size}`); },
    },
  };
  vm.createContext(context);
  const bridgeCall = (method) => (...args) => {
    const handler = context.window.WorkTraceApp.callBridge;
    if (typeof handler !== "function") return Promise.reject(new Error(`missing bridge handler: ${method}`));
    return handler(method, ...args);
  };
  context.window.WorkTraceApp.bridge = {
    getTimeline: bridgeCall("get_timeline"),
    getTimelineSessionActivitySummary: bridgeCall("get_timeline_session_activity_summary"),
    listProjectsForTimeline: bridgeCall("list_projects_for_timeline"),
    saveTimelineSessionEdit: bridgeCall("save_timeline_session_edit"),
    hideTimelineSession: bridgeCall("hide_timeline_session"),
    hideTimelineSessionActivity: bridgeCall("hide_timeline_session_activity"),
    mergeTimelineSession: bridgeCall("merge_timeline_session"),
    splitTimelineSession: bridgeCall("split_timeline_session"),
    copyTimelineSession: bridgeCall("copy_timeline_session"),
    openFDWorkEntry: bridgeCall("open_fd_work_entry"),
  };
  for (const file of ["timeline_request_state.js", "timeline.js"]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
      context,
      { filename: file }
    );
  }
  const App = context.window.WorkTraceApp;
  App.timelineDate = "2026-07-12";
  App.selectedProjectionInstanceKey = "base:a";
  App.selectedProjectionRevision = "rev-a";
  App.currentSessions = [{ projection_instance_key: "base:a", projection_revision: "rev-a" }];
  App.detailsInFlight = {};
  App.handleResult = (result, onError) => {
    if (result && result.ok === false) { onError(result.message || "操作失败", result.error); return null; }
    return result;
  };
  App.runtimeReportDateForPage = () => "";
  App.payloadReportDate = () => "";
  App.isPagePayloadCompatibleWithRuntime = () => true;
  App.escapeHtml = (s) => String(s || "");
  App.formatDuration = (s) => {
    const value = Math.max(0, Number.parseInt(s, 10) || 0);
    const pad = (part) => String(part).padStart(2, "0");
    return `${pad(Math.floor(value / 3600))}:${pad(Math.floor((value % 3600) / 60))}:${pad(value % 60)}`;
  };
  App.formatCompactHours = (s) => `${(Number(s || 0) / 3600).toFixed(1)} h`;
  App.formatStartTimeOnly = (s) => String(s || "");
  App.formatProjectLabel = () => "";
  App.validateLiveClock = () => null;
  App.recordLiveClockContractViolation = () => {};
  App.renderDurationProjected = (target, seconds) => {
    if (target) target.textContent = App.formatDuration(seconds);
  };
  App.renderCurrentActivityElement = () => {};
  App.setLiveClockTarget = () => {};
  App.clearLiveClockTarget = () => {};
  App.acceptLiveRuntimePayload = () => true;
  return { App, element };
}

test("bridge rejection becomes unknown and retry reuses the exact request id", async () => {
  const { App } = harness();
  const calls = [];
  const first = deferred();
  App.callBridge = (...args) => { calls.push(args); return calls.length === 1 ? first.promise : Promise.resolve({
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: "snapshot-2",
    selection_hint: { projection_instance_key: "copy:7", projection_revision: "copy-rev" },
  }); };
  App.loadTimelineReport = () => Promise.resolve();

  const pending = App.runTimelineSessionOperation("copy");
  first.reject(new Error("bridge disconnected"));
  await pending;
  assert.equal(App.mutationOwner.state, "unknown");
  const requestId = calls[0][4];

  await App.runTimelineSessionOperation("copy");
  assert.equal(calls[1][4], requestId);
  assert.equal(App.mutationOwner, null);
  assert.equal(App.selectedProjectionInstanceKey, "copy:7");
  assert.equal(App.selectedProjectionRevision, "copy-rev");
});

test("different intent is explicitly blocked while pending", async () => {
  const { App, element } = harness();
  const request = deferred();
  App.callBridge = () => request.promise;
  const pending = App.runTimelineSessionOperation("copy");
  await App.runTimelineSessionOperation("hide");
  assert.match(element("edit-status").textContent, /已有操作结果尚未确认/);
  assert.equal(App.mutationOwner.method, "copy_timeline_session");
  request.resolve({ ok: false, error: "operation_not_allowed", message: "不允许执行该操作" });
  await pending;
  assert.equal(App.mutationOwner, null);
});

test("confirmed failure releases mutation owner and displays message, not code", async () => {
  const { App, element } = harness();
  App.callBridge = () => Promise.resolve({
    ok: false,
    error: "revision_conflict",
    message: "活动时段已变化",
  });
  await App.runTimelineSessionOperation("hide");
  assert.equal(App.mutationOwner, null);
  assert.equal(element("edit-status").textContent, "活动时段已变化");
});

test("confirmed success consumes selection hint before authoritative refresh", async () => {
  const { App } = harness();
  let selectionAtRefresh = null;
  App.callBridge = () => Promise.resolve({
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: "snapshot-merge",
    selection_hint: { projection_instance_key: "merge:9", projection_revision: "merge-rev" },
  });
  App.loadTimelineReport = () => {
    selectionAtRefresh = [App.selectedProjectionInstanceKey, App.selectedProjectionRevision];
    return Promise.resolve();
  };
  await App.runTimelineSessionOperation("copy");
  assert.deepEqual(selectionAtRefresh, ["merge:9", "merge-rev"]);
  assert.equal(App.lastMutationSnapshotRevision, "snapshot-merge");
  assert.equal(App.lastMutationOutcomeType, "operation_committed");
});

test("confirmed mutation plus refresh failure is not reported as operation failure", async () => {
  const { App, element } = harness();
  App.callBridge = () => Promise.resolve({
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: "snapshot-copy",
    selection_hint: { projection_instance_key: "copy:5", projection_revision: "copy-rev" },
  });
  App.loadTimelineReport = () => Promise.reject(new Error("refresh unavailable"));
  await App.runTimelineSessionOperation("copy");
  assert.equal(App.mutationOwner, null);
  assert.equal(element("edit-status").textContent, "操作已保存，但刷新失败");
});

test("copy and merge bind the authoritative returned entry", async () => {
  for (const scenario of [
    ["copy", {}, "copy:12"],
    ["merge", { direction: "next" }, "merge:13"],
  ]) {
    const { App } = harness();
    App.currentSessions.push({ projection_instance_key: "base:b", projection_revision: "rev-b" });
    App.callBridge = () => Promise.resolve({
      ok: true,
      outcome_type: "operation_committed",
      snapshot_revision: "snapshot-new",
      selection_hint: { projection_instance_key: scenario[2], projection_revision: "actual-revision" },
    });
    App.loadTimelineReport = () => Promise.resolve();
    await App.runTimelineSessionOperation(scenario[0], scenario[1]);
    assert.equal(App.selectedProjectionInstanceKey, scenario[2]);
    assert.equal(App.selectedProjectionRevision, "actual-revision");
  }
});

test("hide and split clear selection when the authoritative hint is null", async () => {
  for (const method of ["hide", "split"]) {
    const { App } = harness();
    App.callBridge = () => Promise.resolve({
      ok: true,
      outcome_type: "operation_committed",
      snapshot_revision: "snapshot-new",
      selection_hint: null,
    });
    App.loadTimelineReport = () => Promise.resolve();
    await App.runTimelineSessionOperation(method);
    assert.equal(App.selectedProjectionInstanceKey, null);
    assert.equal(App.selectedProjectionRevision, null);
  }
});

test("an out-of-order Details response cannot write after selection changes", async () => {
  const { App, element } = harness();
  App.timelineRequestState.nextTimelineOwner("2026-07-12");
  const ownerA = App.timelineRequestState.nextSelectionOwner("2026-07-12", "base:a", "rev-a");
  const oldRequest = deferred();
  App.callBridge = () => oldRequest.promise;
  const pending = App.loadSessionDetails("base:a", "2026-07-12", "rev-a", false, ownerA);

  App.selectedProjectionInstanceKey = "base:b";
  App.selectedProjectionRevision = "rev-b";
  App.timelineRequestState.nextSelectionOwner("2026-07-12", "base:b", "rev-b");
  const before = element("timeline-details-list").innerHTML;
  oldRequest.resolve({ ok: true, summary_rows: [{ activity_name: "stale" }] });
  await pending;
  assert.equal(element("timeline-details-list").innerHTML, before);
});

test("in-progress selection resolves uniquely by first_activity_id after key changes", () => {
  const { App } = harness();
  App.selectedProjectionInstanceKey = "base:old";
  App.selectedProjectionRevision = "rev-old";
  App.selectedTimelineAnchorActivityId = 42;
  App.selectedTimelineWasInProgress = true;
  const replacement = {
    projection_instance_key: "base:new",
    projection_revision: "rev-new",
    first_activity_id: 42,
    is_in_progress: true,
  };

  const resolved = App.resolveTimelineSelection([replacement]);

  assert.equal(resolved, replacement);
  assert.equal(App.selectedProjectionInstanceKey, "base:new");
  assert.equal(App.selectedProjectionRevision, "rev-new");
  assert.equal(App.selectedTimelineAnchorActivityId, 42);
  assert.equal(App.selectedTimelineWasInProgress, true);
});

test("replacement selection requests details with the new key and revision", async () => {
  const { App } = harness();
  App.currentPage = "timeline";
  App.timelineRequestState.nextTimelineOwner("2026-07-12");
  App.selectedProjectionInstanceKey = "base:old";
  App.selectedProjectionRevision = "rev-old";
  App.selectedTimelineAnchorActivityId = 42;
  App.selectedTimelineWasInProgress = true;
  const calls = [];
  App.callBridge = (method, ...args) => {
    if (method === "get_timeline_session_activity_summary") calls.push(args);
    if (method === "list_projects_for_timeline") {
      return Promise.resolve({ ok: true, projects: [], filter_projects: [] });
    }
    return Promise.resolve({ ok: true, summary_rows: [] });
  };

  App.showTimeline({
    ok: true,
    date: "2026-07-12",
    today: "2026-07-12",
    entries: [{
      projection_instance_key: "base:new",
      projection_revision: "rev-new",
      first_activity_id: 42,
      is_in_progress: true,
      edit_disabled: true,
      duration_seconds: 1800,
      start_time: "2026-07-12T09:00:00",
    }],
    today_total_seconds: 1800,
  });
  await Promise.resolve();
  await Promise.resolve();

  assert.deepEqual(calls[0].slice(0, 3), ["base:new", "2026-07-12", "rev-new"]);
});

test("in-progress replacement keeps details open but hides the edit form", () => {
  const { App, element } = harness();
  App.callBridge = () => new Promise(() => {});
  App.selectedProjectionInstanceKey = "base:old";
  App.selectedProjectionRevision = "rev-old";
  App.selectedTimelineAnchorActivityId = 42;
  App.selectedTimelineWasInProgress = true;

  App.showTimeline({
    ok: true,
    date: "2026-07-11",
    today: "2026-07-12",
    today_total_seconds: 600,
    entries: [{
      projection_instance_key: "base:new",
      projection_revision: "rev-new",
      first_activity_id: 42,
      is_in_progress: true,
      edit_disabled: true,
      start_time: "2026-07-11T10:00:00",
      duration_seconds: 600,
    }],
  });

  assert.equal(element("timeline-edit-panel").hidden, true);
  assert.equal(element("timeline-readonly-notice").hidden, false);
  assert.equal(element("timeline-total-label").textContent, "当日总时长");
});

test("missing or ambiguous in-progress anchor clears the selection", () => {
  for (const sessions of [
    [],
    [
      { projection_instance_key: "base:b", projection_revision: "r2", first_activity_id: 42, is_in_progress: true },
      { projection_instance_key: "base:c", projection_revision: "r3", first_activity_id: 42, is_in_progress: true },
    ],
  ]) {
    const { App } = harness();
    App.selectedProjectionInstanceKey = "base:old";
    App.selectedProjectionRevision = "rev-old";
    App.selectedTimelineAnchorActivityId = 42;
    App.selectedTimelineWasInProgress = true;

    assert.equal(App.resolveTimelineSelection(sessions), null);
    assert.equal(App.selectedProjectionInstanceKey, null);
    assert.equal(App.selectedProjectionRevision, null);
    assert.equal(App.selectedTimelineAnchorActivityId, null);
    assert.equal(App.selectedTimelineWasInProgress, false);
  }
});

test("timeline selection reset clears the UI-only in-progress anchor", () => {
  const { App } = harness();
  App.selectedTimelineAnchorActivityId = 42;
  App.selectedTimelineWasInProgress = true;

  App.resetTimelineReportSelection();

  assert.equal(App.selectedTimelineAnchorActivityId, null);
  assert.equal(App.selectedTimelineWasInProgress, false);
});

test("date switch uses the existing reset path and clears the anchor", async () => {
  const { App } = harness();
  App.selectedTimelineAnchorActivityId = 42;
  App.selectedTimelineWasInProgress = true;
  App.setTimelineLoading = () => {};
  App.clearTimelineError = () => {};
  App.callBridge = () => new Promise(() => {});

  await App.goToDate("2026-07-13");

  assert.equal(App.selectedProjectionInstanceKey, null);
  assert.equal(App.selectedProjectionRevision, null);
  assert.equal(App.selectedTimelineAnchorActivityId, null);
  assert.equal(App.selectedTimelineWasInProgress, false);
});

test("timeline presentation sorts newest first with deterministic ties and exact clocks", () => {
  const { App, element } = harness();
  App.selectedProjectionInstanceKey = null;
  App.selectedProjectionRevision = null;
  App.callBridge = () => Promise.resolve({
    ok: true,
    projects: [],
    filter_projects: [],
  });

  App.showTimeline({
    ok: true,
    date: "2026-07-12",
    today: "2026-07-12",
    today_total_seconds: 5400,
    entries: [
      {
        projection_instance_key: "base:a",
        projection_revision: "r1",
        first_activity_id: 1,
        start_time: "2026-07-12T09:00:00",
        duration_seconds: 1800,
        project_name: "A",
      },
      {
        projection_instance_key: "base:b",
        projection_revision: "r2",
        first_activity_id: 2,
        start_time: "2026-07-12T10:00:00",
        duration_seconds: 3600,
        project_name: "B",
        is_in_progress: true,
      },
      {
        projection_instance_key: "base:c",
        projection_revision: "r3",
        first_activity_id: 3,
        start_time: "2026-07-12T10:00:00",
        duration_seconds: 4200,
        project_name: "C",
      },
    ],
  });

  const html = element("timeline-sessions-list").innerHTML;
  const c = html.indexOf('data-projection-instance-key="base:c"');
  const b = html.indexOf('data-projection-instance-key="base:b"');
  const a = html.indexOf('data-projection-instance-key="base:a"');
  assert.ok(c < b && b < a, "start_time desc, then key desc");
  assert.doesNotMatch(html, /data-duration-format="compact-hours"/);
  assert.match(html, />10:00:00<\/div>/);
  assert.match(html, />01:10:00<\/div>/);
  assert.doesNotMatch(html, />进行中<\/span>/);
  assert.equal(element("timeline-total-label").textContent, "今日总时长");
});

test("timeline filter exclusion clears selection, while same-date page return can re-anchor", () => {
  const { App, element } = harness();
  App.callBridge = () => Promise.resolve({
    ok: true,
    projects: [],
    filter_projects: [],
  });
  App.selectedProjectionInstanceKey = "base:old";
  App.selectedProjectionRevision = "rev-old";
  App.selectedTimelineAnchorActivityId = 42;
  App.selectedTimelineWasInProgress = true;
  const replacement = {
    projection_instance_key: "base:new",
    projection_revision: "rev-new",
    first_activity_id: 42,
    is_in_progress: true,
    project_id: 7,
    start_time: "2026-07-12T10:00:00",
    duration_seconds: 600,
    edit_disabled: true,
  };

  App.showTimeline({
    ok: true,
    date: "2026-07-12",
    today: "2026-07-12",
    today_total_seconds: 600,
    entries: [replacement],
  });
  assert.equal(App.selectedProjectionInstanceKey, "base:new");
  assert.equal(App.selectedProjectionRevision, "rev-new");

  element("timeline-project-filter").value = "8";
  App.showTimeline({
    ok: true,
    date: "2026-07-12",
    today: "2026-07-12",
    today_total_seconds: 600,
    entries: [replacement],
  });
  assert.equal(App.selectedProjectionInstanceKey, null);
  assert.equal(App.selectedTimelineAnchorActivityId, null);
});

test("stale_selection triggers one timeline refresh and retry", async () => {
  const { App, element } = harness();
  App.lastTimelineData = {
    date: "2026-07-12",
    structure_revision: "sv-1",
    entries: [{ projection_instance_key: "base:a", projection_revision: "rev-a" }],
  };
  App.currentSessions = App.lastTimelineData.entries;
  let detailCalls = 0;
  const firstDetail = deferred();
  App.callBridge = (method) => {
    if (method === "get_timeline_session_activity_summary") {
      detailCalls++;
      if (detailCalls === 1) return firstDetail.promise;
      return Promise.resolve({ ok: true, summary_rows: [{ activity_name: "Doc1" }] });
    }
    return Promise.resolve({ ok: true });
  };
  App.loadTimelineReport = () => {
    App.timelineRequestState.nextTimelineOwner("2026-07-12");
    App.lastTimelineData = {
      date: "2026-07-12",
      structure_revision: "sv-2",
      entries: [{ projection_instance_key: "base:a", projection_revision: "rev-a" }],
    };
    App.currentSessions = App.lastTimelineData.entries;
    return Promise.resolve();
  };

  const pending = App.loadSessionDetails("base:a", "2026-07-12", "rev-a", false);
  firstDetail.resolve({ ok: false, error: "stale_selection", message: "活动时段已更新，请重新确认。" });
  await pending;

  assert.equal(detailCalls, 2, "exactly one retry after stale_selection");
  assert.ok(element("timeline-details-list").innerHTML.length > 0,
    "retry result should render");
});

test("stale_selection retry does not loop when session disappears", async () => {
  const { App } = harness();
  App.lastTimelineData = {
    date: "2026-07-12",
    structure_revision: "sv-1",
    entries: [{ projection_instance_key: "base:a", projection_revision: "rev-a" }],
  };
  App.currentSessions = App.lastTimelineData.entries;
  let detailCalls = 0;
  const firstDetail = deferred();
  App.callBridge = (method) => {
    if (method === "get_timeline_session_activity_summary") {
      detailCalls++;
      return firstDetail.promise;
    }
    return Promise.resolve({ ok: true });
  };
  App.loadTimelineReport = () => {
    App.timelineRequestState.nextTimelineOwner("2026-07-12");
    App.lastTimelineData = {
      date: "2026-07-12",
      structure_revision: "sv-2",
      entries: [],
    };
    App.currentSessions = [];
    return Promise.resolve();
  };

  const pending = App.loadSessionDetails("base:a", "2026-07-12", "rev-a", false);
  firstDetail.resolve({ ok: false, error: "stale_selection", message: "活动时段已更新，请重新确认。" });
  await pending;

  assert.equal(detailCalls, 1, "no retry when session disappears after refresh");
  assert.equal(App.selectedProjectionInstanceKey, null, "selection cleared");
  assert.equal(App.selectedProjectionRevision, null, "revision cleared");
});

test("stale_selection does not retry a second time", async () => {
  const { App } = harness();
  App.lastTimelineData = {
    date: "2026-07-12",
    structure_revision: "sv-1",
    entries: [{ projection_instance_key: "base:a", projection_revision: "rev-a" }],
  };
  App.currentSessions = App.lastTimelineData.entries;
  let detailCalls = 0;
  const firstDetail = deferred();
  const secondDetail = deferred();
  App.callBridge = (method) => {
    if (method === "get_timeline_session_activity_summary") {
      detailCalls++;
      if (detailCalls === 1) return firstDetail.promise;
      return secondDetail.promise;
    }
    return Promise.resolve({ ok: true });
  };
  App.loadTimelineReport = () => {
    App.timelineRequestState.nextTimelineOwner("2026-07-12");
    App.lastTimelineData = {
      date: "2026-07-12",
      structure_revision: "sv-2",
      entries: [{ projection_instance_key: "base:a", projection_revision: "rev-a" }],
    };
    App.currentSessions = App.lastTimelineData.entries;
    return Promise.resolve();
  };

  const pending = App.loadSessionDetails("base:a", "2026-07-12", "rev-a", false);
  firstDetail.resolve({ ok: false, error: "stale_selection", message: "活动时段已更新，请重新确认。" });
  secondDetail.resolve({ ok: false, error: "stale_selection", message: "活动时段已更新，请重新确认。" });
  await pending;

  assert.equal(detailCalls, 2, "exactly one retry, no infinite loop");
});

test("detail call passes source version from timeline payload", async () => {
  const { App } = harness();
  App.lastTimelineData = {
    date: "2026-07-12",
    structure_revision: "sv-from-timeline",
    entries: [{ projection_instance_key: "base:a", projection_revision: "rev-a" }],
  };
  App.currentSessions = App.lastTimelineData.entries;
  let capturedArgs = null;
  App.callBridge = (method, ...args) => {
    if (method === "get_timeline_session_activity_summary") {
      capturedArgs = args;
      return Promise.resolve({ ok: true, summary_rows: [] });
    }
    return Promise.resolve({ ok: true });
  };

  await App.loadSessionDetails("base:a", "2026-07-12", "rev-a", false);
  assert.ok(capturedArgs, "detail bridge call was made");
  assert.equal(capturedArgs[3], "sv-from-timeline",
    "4th argument should be structure_revision from timeline payload");
});

function configureFDWorkSession(App, element, overrides = {}) {
  const session = Object.assign({
    row_kind: "project_session",
    projection_instance_key: "base:a",
    projection_revision: "rev-a",
    project_id: 17,
    project_name: "CASE-001",
    is_report_project: true,
    is_report_uncategorized: false,
    is_uncategorized: false,
    project_is_deleted: false,
    is_in_progress: false,
    end_time: "2026-07-12 10:00:00",
    session_note: "Saved narrative",
    duration_seconds: 5040,
    adjusted_duration_seconds: null,
    has_duration_override: false,
    can_edit_project: true,
    can_edit_note: true,
    can_edit_duration: true,
  }, overrides);
  App.editingSession = session;
  App.selectedProjectionInstanceKey = session.projection_instance_key;
  App.selectedProjectionRevision = session.projection_revision;
  App.currentSessions = [session];
  App.lastTimelineData = {
    date: "2026-07-12",
    structure_revision: "source-a",
    entries: [session],
  };
  App.settingsLoaded = true;
  App.lastSettingsStatus = { fd_work: { supported: true, enabled: true } };
  App.projectsCache = [{ id: 17, name: "CASE-001" }];
  element("edit-project-select").value = "17";
  element("edit-note-text").value = session.session_note;
  element("edit-duration-input").value = "1.4";
  return session;
}

test("FD Work bridge receives only current timeline identity and versions", async () => {
  const { App, element } = harness();
  configureFDWorkSession(App, element);
  let captured = null;
  App.callBridge = (method, ...args) => {
    if (method === "open_fd_work_entry") captured = args;
    return Promise.resolve({ ok: true, status: "opening" });
  };

  assert.equal(await App.openFDWorkEntryForSelection(), true);
  assert.deepEqual(captured, ["2026-07-12", "base:a", "rev-a"]);
});

test("dirty Timeline waits for accepted autosave and uses refreshed revision", async () => {
  const { App, element } = harness();
  const original = configureFDWorkSession(App, element);
  element("edit-note-text").value = "New saved narrative";
  const order = [];
  let openArgs = null;
  App.callBridge = (method, ...args) => {
    if (method === "save_timeline_session_edit") {
      order.push("save");
      return Promise.resolve({
        ok: true,
        snapshot_revision: "snapshot-2",
        selection_hint: {
          projection_instance_key: "base:a",
          projection_revision: "rev-b",
        },
      });
    }
    if (method === "open_fd_work_entry") {
      order.push("open");
      openArgs = args;
    }
    return Promise.resolve({ ok: true });
  };
  App.loadTimelineReport = () => {
    const refreshed = Object.assign({}, original, {
      projection_revision: "rev-b",
      session_note: "New saved narrative",
    });
    App.currentSessions = [refreshed];
    App.lastTimelineData = {
      date: "2026-07-12",
      structure_revision: "source-b",
      entries: [refreshed],
    };
    return Promise.resolve();
  };

  assert.equal(await App.openFDWorkEntryForSelection(), true);
  assert.deepEqual(order, ["save", "open"]);
  assert.deepEqual(openArgs, ["2026-07-12", "base:a", "rev-b"]);
});

test("confirmed autosave failure prevents FD Work opening", async () => {
  const { App, element } = harness();
  configureFDWorkSession(App, element);
  element("edit-note-text").value = "Unsaved narrative";
  let openCalls = 0;
  App.callBridge = (method) => {
    if (method === "save_timeline_session_edit") {
      return Promise.resolve({ ok: false, error: "revision_conflict", message: "保存失败" });
    }
    if (method === "open_fd_work_entry") openCalls += 1;
    return Promise.resolve({ ok: true });
  };

  assert.equal(await App.openFDWorkEntryForSelection(), false);
  assert.equal(openCalls, 0);
  assert.match(element("fd-work-status").textContent, /保存失败/);
});

test("concurrent FD Work clicks reuse one opening request", async () => {
  const { App, element } = harness();
  configureFDWorkSession(App, element);
  const opening = deferred();
  let openCalls = 0;
  App.callBridge = (method) => {
    if (method === "open_fd_work_entry") {
      openCalls += 1;
      return opening.promise;
    }
    return Promise.resolve({ ok: true });
  };

  const first = App.openFDWorkEntryForSelection();
  const second = App.openFDWorkEntryForSelection();
  assert.equal(first, second);
  assert.equal(openCalls, 0);
  await Promise.resolve();
  assert.equal(openCalls, 1);
  opening.resolve({ ok: true, status: "opening" });
  assert.equal(await first, true);
});

test("Timeline duration input uses deterministic one-decimal half-up normalization", () => {
  const { App } = harness();
  assert.deepEqual(JSON.parse(JSON.stringify(App.normalizeTimelineDurationInput(""))), {
    valid: true, cleared: true, text: "", seconds: null, reason: "",
  });
  assert.deepEqual(JSON.parse(JSON.stringify(App.normalizeTimelineDurationInput("0.05"))), {
    valid: true, cleared: false, text: "0.1", seconds: 360, reason: "",
  });
  assert.equal(App.normalizeTimelineDurationInput("0.001").valid, false);
  assert.equal(App.normalizeTimelineDurationInput("0.001").text, "0.0");
  assert.equal(App.normalizeTimelineDurationInput("1.234").seconds, 4320);
  assert.equal(App.normalizeTimelineDurationInput("1.234").text, "1.2");
  assert.equal(App.normalizeTimelineDurationInput("1.25").seconds, 4680);
  assert.equal(App.normalizeTimelineDurationInput("1.25").text, "1.3");
  for (const invalid of ["-1", "NaN", "Infinity"])
    assert.equal(App.normalizeTimelineDurationInput(invalid).valid, false);
});

test("invalid tiny duration is displayed as 0.0 and never autosaved", () => {
  const { App, element } = harness();
  configureFDWorkSession(App, element);
  let scheduled = 0;
  App.scheduleTimelineAutosave = () => { scheduled += 1; };
  element("edit-duration-input").value = "0.001";

  App.handleTimelineDurationChange();

  assert.equal(element("edit-duration-input").value, "0.0");
  assert.equal(scheduled, 0);
  assert.match(element("edit-status").textContent, /至少为 0.1/);
});

test("FD Work area is fail-closed and one availability model renders the reason", () => {
  const { App, element } = harness();
  configureFDWorkSession(App, element);
  App.settingsLoaded = false;
  App.updateFDWorkEntryButton();
  assert.equal(element("fd-work-entry-area").hidden, true);

  App.settingsLoaded = true;
  App.lastSettingsStatus.fd_work.enabled = true;
  element("edit-note-text").value = "";
  const availability = App.getFDWorkAvailability(App.editingSession);
  App.updateFDWorkEntryButton();
  assert.equal(availability.state, "disabled");
  assert.match(availability.reason, /请先填写描述/);
  assert.equal(element("fd-work-entry-area").hidden, false);
  assert.match(element("fd-work-status").textContent, /请先填写描述/);
});

test("FD Work stale response refreshes and retries exactly once with latest session", async () => {
  const { App, element } = harness();
  const original = configureFDWorkSession(App, element);
  const calls = [];
  let refreshes = 0;
  App.callBridge = (method, ...args) => {
    if (method !== "open_fd_work_entry") return Promise.resolve({ ok: true });
    calls.push(args);
    return Promise.resolve(calls.length === 1
      ? { ok: false, error: "stale_selection", message: "stale" }
      : { ok: true, status: "opening" });
  };
  App.loadTimelineReport = () => {
    refreshes += 1;
    const latest = Object.assign({}, original, { projection_revision: "rev-latest" });
    App.currentSessions = [latest];
    App.lastTimelineData = { date: "2026-07-12", entries: [latest] };
    return Promise.resolve();
  };

  assert.equal(await App.openFDWorkEntryForSelection(), true);
  assert.equal(refreshes, 1);
  assert.deepEqual(calls, [
    ["2026-07-12", "base:a", "rev-a"],
    ["2026-07-12", "base:a", "rev-latest"],
  ]);
});

test("FD Work second stale stops and refresh disappearance prevents retry", async () => {
  for (const disappears of [false, true]) {
    const { App, element } = harness();
    configureFDWorkSession(App, element);
    let opens = 0;
    App.callBridge = (method) => {
      if (method === "open_fd_work_entry") opens += 1;
      return Promise.resolve({ ok: false, error: "stale_selection", message: "stale" });
    };
    App.loadTimelineReport = () => {
      if (disappears) App.currentSessions = [];
      else App.currentSessions[0].projection_revision = "rev-new";
      return Promise.resolve();
    };

    assert.equal(await App.openFDWorkEntryForSelection(), false);
    assert.equal(opens, disappears ? 1 : 2);
  }
});
