const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadState() {
  const context = { window: { WorkTraceApp: {} } };
  vm.createContext(context);
  const source = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/timeline_request_state.js"),
    "utf8"
  );
  vm.runInContext(source, context);
  return context.window.WorkTraceApp;
}

test("today null request becomes absolute-date owner after payload acceptance", () => {
  const App = loadState();
  App.timelineRequestState.nextTimelineOwner(null);
  App.timelineDate = "2026-07-12";
  const owner = App.timelineRequestState.nextSelectionOwner("2026-07-12", "base:a", "r1");
  App.selectedProjectionInstanceKey = "base:a";
  App.selectedSessionDetailRevision = "r1";
  assert.equal(owner.absoluteReportDate, "2026-07-12");
  assert.equal(App.timelineRequestState.isCurrentDetailsOwner(owner), true);
});

test("old detail owner cannot write after selection changes", () => {
  const App = loadState();
  App.timelineDate = "2026-06-25";
  App.timelineRequestState.nextTimelineOwner("2026-06-25");
  const ownerA = App.timelineRequestState.nextSelectionOwner("2026-06-25", "base:a", "rev-a");
  App.selectedProjectionInstanceKey = "base:a";
  App.selectedSessionDetailRevision = "rev-a";
  assert.equal(App.timelineRequestState.isCurrentDetailsOwner(ownerA), true);

  const ownerB = App.timelineRequestState.nextSelectionOwner("2026-06-25", "base:b", "rev-b");
  App.selectedProjectionInstanceKey = "base:b";
  App.selectedSessionDetailRevision = "rev-b";
  assert.equal(App.timelineRequestState.isCurrentDetailsOwner(ownerA), false);
  assert.equal(App.timelineRequestState.isCurrentDetailsOwner(ownerB), true);
});

test("request deduplication key includes date key revision and epochs", () => {
  const App = loadState();
  App.timelineRequestState.nextTimelineOwner("2026-06-25");
  const first = App.timelineRequestState.nextSelectionOwner("2026-06-25", "base:a", "rev-a");
  const second = App.timelineRequestState.nextSelectionOwner("2026-06-25", "base:a", "rev-b");
  assert.notEqual(
    App.timelineRequestState.detailRequestKey(first),
    App.timelineRequestState.detailRequestKey(second)
  );
});
