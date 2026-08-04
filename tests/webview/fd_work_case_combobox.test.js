const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function tick() {
  return Promise.resolve().then(() => Promise.resolve());
}

function harness({ enabled = true } = {}) {
  const elements = new Map();
  function element(id) {
    if (elements.has(id)) return elements.get(id);
    const attributes = new Map();
    const listeners = new Map();
    const node = {
      id, hidden: false, disabled: false, readOnly: false, value: "", checked: false,
      textContent: "", children: [], className: "", parentElement: null,
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      setAttribute(name, value) { attributes.set(name, String(value)); },
      getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
      removeAttribute(name) { attributes.delete(name); },
      addEventListener(name, handler) { listeners.set(name, handler); },
      appendChild(child) { child.parentElement = node; node.children.push(child); return child; },
      contains(target) { return target === node || node.children.includes(target); },
      closest() { return null; },
      fire(name, extra = {}) {
        const event = Object.assign({ target: node, preventDefault() {} }, extra);
        if (listeners.has(name)) return listeners.get(name).call(node, event);
      },
      focus() {},
    };
    Object.defineProperty(node, "innerHTML", {
      get() { return ""; },
      set() { node.children = []; },
    });
    elements.set(id, node);
    return node;
  }
  const context = {
    Promise, setTimeout, clearTimeout,
    window: { WorkTraceApp: {} },
    document: {
      activeElement: null,
      getElementById: element,
      createElement() { return element(`created-${elements.size}`); },
      addEventListener() {},
    },
  };
  vm.createContext(context);
  for (const file of ["fd_work.js", "rules_create_panel.js"]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
      context,
      { filename: file }
    );
  }
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    safeText: (value, fallback) => String(value || fallback || ""),
    rerenderProjectRulesList() {},
    openManagedDrawer(panel) { panel.hidden = false; },
    closeManagedDrawer(panel) { panel.hidden = true; },
    loadProjectRules: () => Promise.resolve(),
    showToast() {},
    lastProjectRulesData: { projects: [] },
  });
  const calls = { picker: [], create: [], update: [], clear: [], login: [] };
  App.bridge = {
    openFDWorkCasePicker(requestId) {
      calls.picker.push(requestId);
      return Promise.resolve({ ok: true, request_id: requestId, operation_status: "picker_ready", capability_status: {} });
    },
    createProjectForRules(...args) {
      calls.create.push(args);
      return Promise.resolve({ ok: true, project: { id: 9, name: args[0] }, fd_work_binding: { bound: !!args[3] } });
    },
    updateProjectForRules(...args) {
      calls.update.push(args);
      return Promise.resolve({ ok: true, project: { id: args[0], name: args[1] }, fd_work_binding: { bound: true } });
    },
    clearFDWorkBindingForRules(projectId) {
      calls.clear.push(projectId);
      return Promise.resolve({ ok: true, fd_work_binding: { bound: false } });
    },
    showFDWorkLogin() {
      calls.login.push(true);
      return Promise.resolve({ ok: true });
    },
  };
  App.initRulesPanelEvents();
  App.receiveFDWorkStatus({
    supported: true,
    enabled,
    session_state: enabled ? "ready" : "disabled",
    operation: "none",
    interaction_owner: "none",
    ready: enabled,
    login_required: false,
    error_code: null,
    page_phase: enabled ? "work_shell" : "none",
    navigation_generation: 1,
  });
  return { App, element, calls };
}

test("plugin disabled leaves ordinary editable project creation unchanged", async () => {
  const { App, element, calls } = harness({ enabled: false });
  App.openRulesPanel("project", {});
  const input = element("rules-panel-project-name");
  input.value = "Local project";
  App.savePanelProject();
  await tick();

  assert.equal(input.hidden, false);
  assert.equal(input.readOnly, false);
  assert.equal(calls.picker.length, 0);
  assert.deepEqual(calls.create[0], ["Local project", "", "中文", null]);
});

test("plugin enabled new project uses readonly picker and opening Drawer has no helper side effect", () => {
  const { App, element, calls } = harness();

  App.openRulesPanel("project", {});

  assert.equal(element("rules-panel-project-name").hidden, true);
  assert.equal(element("rules-panel-fd-work-selected-label").readOnly, false);
  assert.equal(element("rules-panel-save-project").disabled, true);
  assert.deepEqual(calls.picker, []);
  assert.deepEqual(calls.login, []);
});

test("explicit picker click opens once and disables the button while pending", async () => {
  const { App, element, calls } = harness();
  App.openRulesPanel("project", {});

  element("rules-panel-fd-work-pick").fire("click");

  assert.equal(calls.picker.length, 1);
  assert.equal(App.rulesFDWorkPickerPending, true);
  assert.equal(element("rules-panel-fd-work-pick").disabled, true);
  await tick();
  assert.match(element("rules-panel-fd-work-status").textContent, /原生案件框/);
});

test("picker result must match the current Drawer request and session", async () => {
  const { App, element } = harness();
  App.openRulesPanel("project", {});
  element("rules-panel-fd-work-pick").fire("click");
  await tick();
  const requestId = App.rulesFDWorkPickerRequestId;

  assert.equal(App.receiveFDWorkCasePickerResult({
    ok: true, request_id: "stale", selected_label: "OLD", selection_token: "old-token",
  }), false);
  assert.equal(App.rulesFDWorkSelectionToken, null);
  assert.equal(App.receiveFDWorkCasePickerResult({
    ok: true, request_id: requestId, selected_label: "CASE A", selection_token: "token-a",
  }), true);
  assert.equal(element("rules-panel-fd-work-selected-label").value, "CASE A");
  assert.equal(App.rulesFDWorkSelectionToken, "token-a");
  assert.equal(element("rules-panel-save-project").disabled, false);
});

test("manual display-label tampering cannot be saved", async () => {
  const { App, element, calls } = harness();
  App.openRulesPanel("project", {});
  element("rules-panel-fd-work-pick").fire("click");
  await tick();
  App.receiveFDWorkCasePickerResult({
    ok: true,
    request_id: App.rulesFDWorkPickerRequestId,
    selected_label: "CASE A",
    selection_token: "token-a",
  });
  element("rules-panel-fd-work-selected-label").value = "TAMPERED";

  App.savePanelProject();

  assert.deepEqual(calls.create, []);
  assert.match(element("rules-panel-status").textContent, /重新选择/);
});

test("bound unchanged edit preserves binding without a transient token", async () => {
  const { App, calls } = harness();
  const project = { id: 7, name: "CASE A", description: "old", language: "中文", fd_work_bound: true };
  App.lastProjectRulesData.projects = [project];
  App.openRulesPanel("project", { project });
  App.savePanelProject();
  await tick();

  assert.deepEqual(calls.update[0], [7, "CASE A", "old", "中文", null]);
});

test("historical unbound unchanged project can edit non-name fields", async () => {
  const { App, element, calls } = harness();
  const project = { id: 8, name: "Legacy", description: "old", language: "English", fd_work_bound: false };
  App.lastProjectRulesData.projects = [project];
  App.openRulesPanel("project", { project });
  element("rules-panel-project-description").value = "new";
  App.savePanelProject();
  await tick();

  assert.deepEqual(calls.update[0], [8, "Legacy", "new", "English", null]);
});

test("picker cancel or close restores pending state without changing the project name", async () => {
  const { App, element } = harness();
  App.openRulesPanel("project", {});
  element("rules-panel-fd-work-pick").fire("click");
  await tick();
  const requestId = App.rulesFDWorkPickerRequestId;

  assert.equal(App.receiveFDWorkCasePickerResult({
    ok: false, request_id: requestId, error: "picker_canceled",
  }), true);
  assert.equal(App.rulesFDWorkPickerPending, false);
  assert.equal(App.rulesFDWorkSelectionToken, null);
  assert.equal(element("rules-panel-fd-work-selected-label").value, "");
  assert.match(element("rules-panel-fd-work-status").textContent, /已取消/);
});

test("explicit cancel association clears an existing durable binding", async () => {
  const { App, element, calls } = harness();
  const project = { id: 7, name: "CASE A", description: "", language: "中文", fd_work_bound: true };
  App.lastProjectRulesData.projects = [project];
  App.openRulesPanel("project", { project });

  element("rules-panel-fd-work-clear").fire("click");
  await tick();

  assert.deepEqual(calls.clear, [7]);
  assert.equal(App.rulesFDWorkOriginalBound, false);
});
