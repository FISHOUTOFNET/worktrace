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

test("project Drawer keeps one editable name field with optional FD Work picker", () => {
  assert.match(html, /id="rules-panel-project-name"[^>]*type="text"/);
  assert.doesNotMatch(html, /id="rules-panel-fd-work-selected-label"/);
  assert.match(html, /id="rules-panel-fd-work-pick"/);
  assert.match(html, /id="rules-panel-fd-work-clear"/);
  assert.match(fdWorkSource, /label\.textContent = "项目名称"/);
  assert.match(fdWorkSource, /input\.hidden = false/);
  assert.match(fdWorkSource, /input\.readOnly = false/);
});

test("picker writes canonical case label into the shared project name field", () => {
  const receiver = fdWorkSource.slice(
    fdWorkSource.indexOf("function receiveIdentityPickerResult"),
    fdWorkSource.indexOf("function handleIdentityNameInput")
  );
  assert.match(receiver, /identityState\.selectedLabel = result\.selected_label\.trim\(\)/);
  assert.match(receiver, /identityState\.selectionProof = result\.selection_token/);
  assert.match(receiver, /projectNameInput\(\)/);
  assert.match(receiver, /input\.value = identityState\.selectedLabel/);
});

test("manual name input discards picker proof and saves as a local project", () => {
  const inputHandler = fdWorkSource.slice(
    fdWorkSource.indexOf("function handleIdentityNameInput"),
    fdWorkSource.indexOf("function buildIdentitySave")
  );
  const saveBuilder = fdWorkSource.slice(
    fdWorkSource.indexOf("function buildIdentitySave"),
    fdWorkSource.indexOf("function verifyIdentityPersistence")
  );
  assert.match(inputHandler, /identityState\.selectionProof = null/);
  assert.match(inputHandler, /identityState\.selectedLabel = ""/);
  assert.match(saveBuilder, /proof: null/);
  assert.match(saveBuilder, /identityState\.saveIntent = "local"/);
  assert.doesNotMatch(saveBuilder, /请先选择 FD Work 案件/);
});

test("bound project preserves unchanged identity but manual rename becomes local", () => {
  const saveBuilder = fdWorkSource.slice(
    fdWorkSource.indexOf("function buildIdentitySave"),
    fdWorkSource.indexOf("function verifyIdentityPersistence")
  );
  assert.match(saveBuilder, /editing && identityState\.originalBound && name === identityState\.originalName/);
  assert.match(saveBuilder, /identityState\.saveIntent = "preserve"/);
  assert.match(fdWorkSource, /名称已修改，保存后将取消 FD Work 关联/);
});

test("timeline gate disables unbound projects before opening FD Work", () => {
  assert.match(fdWorkSource, /project\.fd_work_bound === true/);
  assert.match(fdWorkSource, /非 FD Work 项目/);
  assert.match(fdWorkSource, /此项目未关联 FD Work/);
  assert.match(fdWorkSource, /var originalOpen = App\.openFDWorkEntryForSelection/);
  assert.match(fdWorkSource, /project && project\.fd_work_bound !== true/);
});

test("main bridge exports picker open and removes inline case search", () => {
  assert.match(initSource, /openFDWorkCasePicker:\s*fixedBridgeMethod\("open_fd_work_case_picker"\)/);
  assert.doesNotMatch(initSource, /searchFDWorkCases/);
  assert.match(fdWorkSource, /receiveFDWorkCasePickerResult/);
  assert.match(fdWorkSource, /openFDWorkCasePicker/);
  assert.match(rulesSource, /App\.projectIdentity/);
});

test("picker UI consumes operation status and never the ambiguous status field", () => {
  assert.match(fdWorkSource, /result\.operation_status\s*===\s*["']authentication_required["']/);
  assert.doesNotMatch(fdWorkSource, /result\.status\s*===\s*["']authentication_required["']/);
});

test("project name input never invokes FD Work helper operations while typing", () => {
  for (const retired of [
    "requestRecentFDWorkCases",
    "searchFDWorkCases",
    "rulesFDWorkSearchOptions",
    "rulesFDWorkActiveOption",
    "rulesFDWorkLastQuery",
    "rulesFDWorkLoginRetryPending",
  ]) {
    assert.doesNotMatch(rulesSource, new RegExp(retired));
  }
  const inputHandler = fdWorkSource.slice(
    fdWorkSource.indexOf("function handleIdentityNameInput"),
    fdWorkSource.indexOf("function buildIdentitySave")
  );
  assert.doesNotMatch(inputHandler, /openFDWorkCasePicker|showFDWorkLogin/);
});

test("picker state remains private and generation-bound", () => {
  assert.doesNotMatch(rulesSource, /rulesFDWorkPickerRequestId|rulesFDWorkPickerPending/);
  assert.match(fdWorkSource, /pickerRequestId/);
  assert.match(fdWorkSource, /pickerPending/);
  assert.match(fdWorkSource, /editorGeneration/);
  assert.match(fdWorkSource, /pickerEditorGeneration/);
  assert.doesNotMatch(fdWorkSource, /rulesPanelSessionToken|pickerDrawerSession/);
  const receiver = fdWorkSource.slice(
    fdWorkSource.indexOf("receiveIdentityPickerResult"),
    fdWorkSource.indexOf("receiveIdentityPickerResult") + 2200
  );
  assert.match(receiver, /request_id/);
  assert.match(receiver, /pickerRequestId/);
  assert.match(receiver, /pickerEditorGeneration|editorGeneration/);
});
