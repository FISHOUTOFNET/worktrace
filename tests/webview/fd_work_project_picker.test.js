const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const rulesSource = fs.readFileSync(
  path.join(__dirname, "../../worktrace/webview_ui/js/rules_create_panel_v5.js"),
  "utf8"
);
const initSource = fs.readFileSync(
  path.join(__dirname, "../../worktrace/webview_ui/js/init_fd_work_v5.js"),
  "utf8"
);
const fdWorkSource = fs.readFileSync(
  path.join(__dirname, "../../worktrace/webview_ui/js/fd_work_v5.js"),
  "utf8"
);
const html = fs.readFileSync(
  path.join(__dirname, "../../worktrace/webview_ui/index_fd_work_v5.html"),
  "utf8"
);

test("project Drawer keeps one editable project-name surface with optional picker", () => {
  assert.match(html, /id="rules-panel-project-name"[^>]*type="text"/);
  assert.doesNotMatch(
    fdWorkSource,
    /label\.textContent\s*=\s*enabled\s*\?\s*"FD Work 案件"/
  );
  assert.match(fdWorkSource, /input\.hidden\s*=\s*false/);
  assert.match(fdWorkSource, /input\.readOnly\s*=\s*false/);
  assert.match(fdWorkSource, /rules-panel-fd-work-pick/);
});

test("picker result writes the canonical case into the shared project-name input", () => {
  const receiver = fdWorkSource.slice(
    fdWorkSource.indexOf("function receiveIdentityPickerResult"),
    fdWorkSource.indexOf("function handleIdentityNameInput")
  );
  assert.match(receiver, /projectNameInput\(\)/);
  assert.match(receiver, /input\.value\s*=\s*identityState\.selectedLabel/);
  assert.match(receiver, /selectionProof\s*=\s*result\.selection_token/);
});

test("manual name editing drops picker proof and saves a local project", () => {
  const inputHandler = fdWorkSource.slice(
    fdWorkSource.indexOf("function handleIdentityNameInput"),
    fdWorkSource.indexOf("function buildIdentitySave")
  );
  const saveBuilder = fdWorkSource.slice(
    fdWorkSource.indexOf("function buildIdentitySave"),
    fdWorkSource.indexOf("function verifyIdentityPersistence")
  );
  assert.match(inputHandler, /identityState\.selectionProof\s*=\s*null/);
  assert.match(inputHandler, /identityState\.selectedLabel\s*=\s*""/);
  assert.match(saveBuilder, /proof:\s*null/);
  assert.doesNotMatch(saveBuilder, /请先选择 FD Work 案件/);
});

test("bound project rename becomes local while unchanged name preserves binding", () => {
  const saveBuilder = fdWorkSource.slice(
    fdWorkSource.indexOf("function buildIdentitySave"),
    fdWorkSource.indexOf("function verifyIdentityPersistence")
  );
  assert.match(saveBuilder, /identityState\.saveIntent\s*=\s*"preserve"/);
  assert.match(saveBuilder, /identityState\.saveIntent\s*=\s*"local"/);
  assert.match(fdWorkSource, /名称已修改，保存后将取消 FD Work 关联/);
});

test("timeline gate disables local projects before backend fill is invoked", () => {
  assert.match(fdWorkSource, /project\.fd_work_bound\s*===\s*true/);
  assert.match(fdWorkSource, /非 FD Work 项目/);
  assert.match(fdWorkSource, /此项目未关联 FD Work/);
  assert.match(fdWorkSource, /event\.stopImmediatePropagation\(\)/);
  assert.match(fdWorkSource, /installTimelineProjectGate\(\)/);
});

test("main bridge still exports native picker and no inline case search", () => {
  assert.match(
    initSource,
    /openFDWorkCasePicker:\s*fixedBridgeMethod\("open_fd_work_case_picker"\)/
  );
  assert.doesNotMatch(initSource, /searchFDWorkCases/);
  assert.match(fdWorkSource, /receiveFDWorkCasePickerResult/);
  assert.match(rulesSource, /App\.projectIdentity/);
});

test("picker state remains private and generation-bound", () => {
  assert.doesNotMatch(
    rulesSource,
    /rulesFDWorkPickerRequestId|rulesFDWorkPickerPending/
  );
  assert.match(fdWorkSource, /pickerRequestId/);
  assert.match(fdWorkSource, /pickerPending/);
  assert.match(fdWorkSource, /editorGeneration/);
  assert.match(fdWorkSource, /pickerEditorGeneration/);
  assert.doesNotMatch(fdWorkSource, /rulesPanelSessionToken|pickerDrawerSession/);
});
