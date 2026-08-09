const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function actionsHarness() {
  const listeners = {};
  const toggles = [];
  const list = {
    attrs: {},
    getAttribute(name) { return this.attrs[name] || null; },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    addEventListener(type, handler) { listeners[type] = handler; },
  };
  const context = {
    Promise, Error, Array, String, parseInt,
    window: { WorkTraceApp: {} },
    document: {
      getElementById(id) { return id === "rules-list" ? list : null; },
      querySelectorAll(selector) {
        return selector === ".rules-rule-enabled-toggle" ? toggles : [];
      },
    },
  };
  vm.createContext(context);
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    rulesBackfillingRuleKey: null,
    clearRulesError() { App.lastRulesError = ""; },
    showRulesError(message) { App.lastRulesError = String(message || ""); },
    loadProjectRules() { App.loadCount = (App.loadCount || 0) + 1; return Promise.resolve(true); },
    showToast(message) { App.lastToast = String(message || ""); },
  });
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/rules_rule_actions.js"), "utf8"),
    context,
    { filename: "rules_rule_actions.js" },
  );
  return { App, listeners, toggles };
}

function renderHarness() {
  const context = {
    window: { WorkTraceApp: {} },
  };
  vm.createContext(context);
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    safeText(value, fallback) { return value === null || value === undefined || value === "" ? (fallback || "") : String(value); },
    escapeHtml(value) { return String(value || ""); },
    iconMarkup(name) { return `<svg data-icon="${name}"></svg>`; },
  });
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/rules_render.js"), "utf8"),
    context,
    { filename: "rules_render.js" },
  );
  return App;
}

test("rule row renders an enabled-state switch for both rule kinds", () => {
  const App = renderHarness();
  const enabled = App.renderProjectRuleRow({
    kind: "keyword", id: 7, kind_label: "关键词", target: "Spec", enabled: true, detail: "已启用",
  });
  const disabled = App.renderProjectRuleRow({
    kind: "folder", id: 3, kind_label: "文件夹", target: "D:/Client", enabled: false, detail: "仅直接文件 | 已禁用",
  });

  assert.match(enabled, /rules-rule-enabled-toggle/);
  assert.match(enabled, /data-rule-kind="keyword"/);
  assert.match(enabled, /data-rule-id="7"/);
  assert.match(enabled, /aria-label="停用规则"/);
  assert.match(enabled, / checked/);
  assert.match(disabled, /data-rule-kind="folder"/);
  assert.match(disabled, /aria-label="启用规则"/);
  assert.doesNotMatch(disabled, / checked/);
});

test("rule enabled control is bound to the rendered rules list", () => {
  const { listeners } = actionsHarness();
  assert.equal(typeof listeners.change, "function");
});

test("disabling a rule persists through the bridge without mutating history", async () => {
  const { App, toggles } = actionsHarness();
  const input = { checked: false, disabled: false };
  toggles.push(input);
  const calls = [];
  App.bridge = {
    setProjectRuleEnabled(ruleType, ruleId, enabled) {
      calls.push([ruleType, ruleId, enabled]);
      return Promise.resolve({ ok: true, enabled });
    },
  };

  const ok = await App.setProjectRuleEnabled("keyword", 7, false, input);

  assert.equal(ok, true);
  assert.deepEqual(calls, [["keyword", 7, false]]);
  assert.equal(App.loadCount, 1);
  assert.match(App.lastToast, /规则已停用/);
  assert.match(App.lastToast, /历史归类保持不变/);
  assert.equal(App.rulesTogglingRuleKey, null);
  assert.equal(input.disabled, false);
});

test("rule enabled write failure rolls the switch back", async () => {
  const { App, toggles } = actionsHarness();
  const input = { checked: false, disabled: false };
  toggles.push(input);
  App.bridge = {
    setProjectRuleEnabled() {
      return Promise.resolve({ ok: false, error: "write failed" });
    },
  };

  const ok = await App.setProjectRuleEnabled("folder", 3, false, input);

  assert.equal(ok, false);
  assert.equal(input.checked, true);
  assert.match(App.lastRulesError, /write failed/);
  assert.equal(App.loadCount || 0, 0);
  assert.equal(App.rulesTogglingRuleKey, null);
  assert.equal(input.disabled, false);
});
