const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function harness(choice) {
  let dialogOptions = null;
  const deleteCalls = [];
  const context = {
    Promise, Error, Array, String, parseInt,
    window: { WorkTraceApp: {} },
    document: {
      getElementById() { return null; },
      querySelectorAll() { return []; },
    },
  };
  vm.createContext(context);
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    rulesDeletingRuleKey: null,
    openDeleteDialog(options) {
      dialogOptions = options;
      return Promise.resolve(choice);
    },
    clearRulesError() {},
    showRulesError(message) { App.lastError = String(message || ""); },
    loadProjectRules() { return Promise.resolve(true); },
    showToast(message) { App.lastToast = String(message || ""); },
    bridge: {
      deleteProjectKeywordRule(ruleId, restoreHistory) {
        deleteCalls.push(["keyword", ruleId, restoreHistory]);
        return Promise.resolve({ ok: true });
      },
      deleteProjectFolderRule(ruleId, restoreHistory) {
        deleteCalls.push(["folder", ruleId, restoreHistory]);
        return Promise.resolve({ ok: true });
      },
    },
  });
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/rules_delete_actions.js"), "utf8"),
    context,
    { filename: "rules_delete_actions.js" },
  );
  return { App, getDialogOptions: () => dialogOptions, deleteCalls };
}

test("rule delete dialog offers only preserve history and treat-rule-as-absent choices", async () => {
  const { App, getDialogOptions } = harness(false);

  await App.openProjectRuleDeleteModal("keyword", 7, null);

  const options = getDialogOptions();
  assert.ok(options);
  assert.equal(options.warning, "如何处理已有归类？");
  assert.equal(options.objectLabel, undefined);
  assert.equal(options.choices.length, 2);
  assert.equal(options.choices[0].value, "preserve");
  assert.equal(options.choices[0].label, "保留已有归类");
  assert.equal(options.choices[0].description, undefined);
  assert.equal(options.choices[1].value, "restore");
  assert.equal(options.choices[1].label, "视同规则不存在");
  assert.equal(options.choices[1].description, undefined);
});

test("preserve history deletes the rule without historical reinference", async () => {
  const { App, deleteCalls } = harness("preserve");

  const ok = await App.openProjectRuleDeleteModal("keyword", 7, null);

  assert.equal(ok, true);
  assert.deepEqual(deleteCalls, [["keyword", 7, false]]);
  assert.equal(App.lastToast, "规则已删除");
});

test("treat-rule-as-absent still requests normal historical reinference", async () => {
  const { App, deleteCalls } = harness("restore");

  const ok = await App.openProjectRuleDeleteModal("folder", 3, null);

  assert.equal(ok, true);
  assert.deepEqual(deleteCalls, [["folder", 3, true]]);
  assert.equal(App.lastToast, "规则已删除");
});
