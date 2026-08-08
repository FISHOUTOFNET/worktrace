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

test("project Drawer contains an explicit readonly FD Work picker and no local listbox", () => {
  assert.match(html, /id="rules-panel-fd-work-selected-label"[^>]*readonly/);
  assert.match(html, /id="rules-panel-fd-work-pick"/);
  assert.match(html, /id="rules-panel-fd-work-clear"/);
  assert.doesNotMatch(html, /id="rules-panel-fd-work-options"/);
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

test("project name focus click input never invoke FD Work helper operations", () => {
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
  assert.doesNotMatch(rulesSource, /project-name[\s\S]{0,500}showFDWorkLogin/);
});

test("picker state is private and bound to request id and current Drawer session", () => {
  assert.doesNotMatch(rulesSource, /rulesFDWorkPickerRequestId|rulesFDWorkPickerPending/);
  assert.match(fdWorkSource, /pickerRequestId/);
  assert.match(fdWorkSource, /pickerPending/);
  assert.match(fdWorkSource, /rulesPanelSessionToken/);
  const receiver = fdWorkSource.slice(
    fdWorkSource.indexOf("receiveIdentityPickerResult"),
    fdWorkSource.indexOf("receiveIdentityPickerResult") + 1800
  );
  assert.match(receiver, /request_id/);
  assert.match(receiver, /pickerRequestId/);
  assert.match(receiver, /pickerDrawerSession/);
});

test("save is fail closed without a picker proof and detects label tampering", () => {
  const saveBody = rulesSource.slice(
    rulesSource.indexOf("function savePanelProject"),
    rulesSource.indexOf("function savePanelRule")
  );
  assert.match(saveBody, /projectIdentity\.buildSavePayload/);
  assert.doesNotMatch(saveBody, /fdWorkEnabled|rulesFDWorkSelectionToken/);
  assert.match(fdWorkSource, /请先选择 FD Work 案件/);
  assert.match(fdWorkSource, /displayedLabel[^\n]*!==|!==[^\n]*displayedLabel/);
});

test("picker pending disables the explicit button and cancel restores local UI state", () => {
  assert.match(fdWorkSource, /pickerPending/);
  assert.match(fdWorkSource, /rules-panel-fd-work-pick/);
  assert.match(fdWorkSource, /picker_canceled/);
  assert.match(fdWorkSource, /取消关联/);
});
