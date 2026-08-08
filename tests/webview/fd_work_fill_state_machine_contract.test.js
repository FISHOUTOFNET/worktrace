const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
  path.join(__dirname, "../../worktrace/integrations/fd_work/fd_work_adapter.js"),
  "utf8"
);

function bodyBetween(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start, `${startMarker} must precede ${endMarker}`);
  return source.slice(start, end);
}

test("target date is established before target-date editor preparation", () => {
  const body = bodyBetween("async function fillEntry", "function actionHandler");
  const date = body.indexOf("ensureEntryDate");
  const page = body.indexOf("awaitStableWorkPage", date);
  const editor = body.indexOf("ensureEntryEditor", page);
  const stable = body.indexOf("awaitStableEntryEditor", editor);
  const matter = body.indexOf("prepareCaseCombobox", stable);
  assert.ok(date >= 0 && page > date && editor > page && stable > editor && matter > stable);
});

test("entry readiness waiter never owns transaction blocker cleanup", () => {
  const body = bodyBetween(
    "async function awaitStableEntryEditor",
    "function createEntryActionText"
  );
  assert.doesNotMatch(body, /removeFillBlockingLayer/);
});

test("exact case freshness accelerates commit but is not the only valid path", () => {
  const body = bodyBetween("async function selectExactCase", "async function awaitInteractiveEntryField");
  assert.match(body, /freshEvidence/);
  assert.match(body, /stableExactFrames\s*>=\s*settleFrames/);
  assert.match(body, /freshEvidence\s*\|\|\s*stableExactFrames\s*>=\s*settleFrames/);
});

test("save completion rejects loading-only and form-identity-only evidence", () => {
  const reinit = bodyBetween("function formReinitializedAfterSave", "async function verifySaveCompletion");
  const verify = bodyBetween("async function verifySaveCompletion", "function clickSave");
  assert.doesNotMatch(reinit, /currentForm\s*!==\s*baseline\.form/);
  assert.doesNotMatch(verify, /loadingObserved\s*&&\s*!busy/);
  assert.match(verify, /successMessage\s*\|\|\s*reinitialized/);
});

test("controlled fields wait for interactive mounts instead of snapshot-failing", () => {
  const body = bodyBetween("async function awaitInteractiveEntryField", "function installFillBlockingLayer");
  assert.match(body, /await requestFrame\(\)/);
  assert.match(body, /fillDuration[\s\S]*await awaitInteractiveEntryField\("duration_hours"/);
  assert.match(body, /fillNarrative[\s\S]*await awaitInteractiveEntryField\("narrative"/);
});
