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
    rulesDeletingFolderKey: null,
    openDeleteDialog(options) {
      dialogOptions = options;
      return Promise.resolve(choice);
    },
    clearRulesError() {},
    showRulesError(message) { App.lastError = String(message || ""); },
    loadProjectRules() { return Promise.resolve(true); },
    showToast(message) { App.lastToast = String(message || ""); },
    setFolderDeleting() {},
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
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/rules_keyword_actions.js"), "utf8"),
    context,
    { filename: "rules_keyword_actions.js" },
  );
  return { App, getDialogOptions: () => dialogOptions, deleteCalls };
}

test("rule delete dialog offers only preserve history and restore original state", async () => {
  const { App, getDialogOptions } = harness(false);

  await App.openProjectRuleDeleteModal("keyword", 7, null);

  const options = getDialogOptions();
  assert.ok(options);
  assert.equal(options.choices.length, 2);
  assert.deepEqual(
    options.choices.map((item) => [item.value, item.label]),
    [["preserve", "保留已有归类"], ["restore", "恢复原状"]],
  );
  assert.match(options.choices[1].description, /视同这条规则从未存在/);
  assert.match(options.choices[1].description, /按其他现有规则重新归类/);
});

test("preserve history deletes the rule without historical reinference", async () => {
  const { App, deleteCalls } = harness("preserve");

  const ok = await App.openProjectRuleDeleteModal("keyword", 7, null);

  assert.equal(ok, true);
  assert.deepEqual(deleteCalls, [["keyword", 7, false]]);
  assert.match(App.lastToast, /已有历史归类保持不变/);
});

test("restore original state deletes the rule and requests normal historical reinference", async () => {
  const { App, deleteCalls } = harness("restore");

  const ok = await App.openProjectRuleDeleteModal("folder", 3, null);

  assert.equal(ok, true);
  assert.deepEqual(deleteCalls, [["folder", 3, true]]);
  assert.match(App.lastToast, /按其余规则恢复/);
});
