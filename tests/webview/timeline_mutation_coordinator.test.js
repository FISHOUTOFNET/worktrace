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
