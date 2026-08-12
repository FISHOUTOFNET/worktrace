const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const JS_ROOT = path.join(__dirname, "../../worktrace/webview_ui/js");

function source(name) {
  return fs.readFileSync(path.join(JS_ROOT, name), "utf8");
}

function functionBody(text, name) {
  const marker = `function ${name}(`;
  const start = text.indexOf(marker);
  assert.notEqual(start, -1, `${name} must exist`);
  const open = text.indexOf("{", start);
  let depth = 0;
  for (let index = open; index < text.length; index += 1) {
    if (text[index] === "{") depth += 1;
    else if (text[index] === "}") {
      depth -= 1;
      if (depth === 0) return text.slice(open + 1, index);
    }
  }
  throw new Error(`unterminated function ${name}`);
}

test("project rules mutations use a fresh authoritative readback", () => {
  const core = source("rules.js");
  const panel = source("rules_create_panel_v5.js");
  const deletion = source("rules_delete_actions.js");

  const load = functionBody(core, "loadProjectRules");
  assert.match(load, /forceFresh/);
  assert.match(load, /App\.rulesLoadPromise && !forceFresh/);
  assert.match(core, /App\.reloadProjectRules = function/);

  assert.match(functionBody(panel, "savePanelProject"), /App\.reloadProjectRules/);
  assert.match(functionBody(panel, "savePanelRule"), /App\.reloadProjectRules/);
  assert.match(functionBody(panel, "deleteProject"), /App\.reloadProjectRules/);
  assert.match(functionBody(deletion, "deleteRule"), /App\.reloadProjectRules/);
});

test("successful rule creation closes the current drawer while failures stay editable", () => {
  const body = functionBody(source("rules_create_panel_v5.js"), "savePanelRule");

  assert.match(body, /if \(!outcome \|\| outcome\.created !== true\) return false/);
  assert.match(body, /if \(currentSession\) closeRulesPanel\(\)/);
  assert.match(body, /规则已新增，但列表刷新失败，请刷新后检查/);
  assert.match(body, /规则已新增，但应用到历史记录失败/);

  const createFailure = body.indexOf('showPanelStatus(result.error || "新增规则失败", true)');
  const confirmedOutcome = body.indexOf("outcome.created !== true");
  const close = body.indexOf("closeRulesPanel()");
  assert.ok(createFailure >= 0 && createFailure < confirmedOutcome && confirmedOutcome < close);
});

test("rule target refresh preserves selection and fails closed when the project disappears", () => {
  const body = functionBody(source("rules_create_panel_v5.js"), "refreshRulesPanelTargets");

  assert.match(body, /currentProjectId = parsePositiveInt\(select\.value\)/);
  assert.match(body, /requestedProjectId = parsePositiveInt\(preferredProjectId\) \|\| currentProjectId/);
  assert.match(body, /App\.rulesPanelTargetMissing = true/);
  assert.match(body, /项目已不存在/);
  assert.match(body, /所选项目已不存在，请重新选择/);

  const writeState = functionBody(source("rules_create_panel_v5.js"), "refreshPanelWriteState");
  assert.match(writeState, /rules-panel-save-rule", ruleBusy \|\| App\.rulesPanelTargetMissing/);
  assert.match(writeState, /rules-panel-target-project", ruleBusy \|\| App\.rulesPanelTargetMissing/);
});

test("project deletion has an in-flight lock and distinguishes refresh failure", () => {
  const text = source("rules_create_panel_v5.js");
  const body = functionBody(text, "deleteProject");

  assert.match(text, /App\.rulesDeletingProjectId = null/);
  assert.match(body, /if \(App\.rulesDeletingProjectId\) return/);
  assert.match(body, /setProjectDeleting\(projectId\)/);
  assert.match(body, /项目已删除，但列表刷新失败，请刷新后检查/);
  assert.match(body, /finally\(function \(\) \{\s*setProjectDeleting\(null\)/);
});

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

function classList() {
  const values = new Set();
  return {
    add(...names) { names.forEach((name) => values.add(name)); },
    remove(...names) { names.forEach((name) => values.delete(name)); },
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : !!force;
      if (enabled) values.add(name); else values.delete(name);
      return enabled;
    },
    contains(name) { return values.has(name); },
  };
}

function autocompleteHarness() {
  let activeElement = null;
  const document = {
    get activeElement() { return activeElement; },
    getElementById() { return null; },
    querySelectorAll() { return []; },
    createElement(tag) { return makeNode(tag); },
  };

  function makeNode(tag, id = "") {
    const attrs = new Map();
    const listeners = new Map();
    const node = {
      tagName: String(tag || "div").toUpperCase(),
      id,
      hidden: false,
      disabled: false,
      tabIndex: 0,
      textContent: "",
      className: "",
      classList: classList(),
      children: [],
      parentNode: null,
      value: "",
      setAttribute(name, value) { attrs.set(name, String(value)); },
      getAttribute(name) { return attrs.has(name) ? attrs.get(name) : null; },
      removeAttribute(name) { attrs.delete(name); },
      addEventListener(name, handler) {
        if (!listeners.has(name)) listeners.set(name, []);
        listeners.get(name).push(handler);
      },
      dispatch(name, event = {}) {
        for (const handler of listeners.get(name) || []) {
          handler({ target: node, currentTarget: node, preventDefault() {}, ...event });
        }
      },
      dispatchEvent(event) { node.dispatch(event.type, event); return true; },
      appendChild(child) { child.parentNode = node; node.children.push(child); return child; },
      insertBefore(child, reference) {
        child.parentNode = node;
        const index = node.children.indexOf(reference);
        if (index < 0) node.children.push(child); else node.children.splice(index, 0, child);
        return child;
      },
      querySelectorAll(selector) {
        if (selector === '[role="option"]') {
          return node.children.filter((child) => child.getAttribute("role") === "option");
        }
        return [];
      },
      contains(target) {
        if (target === node) return true;
        return node.children.some((child) => child.contains && child.contains(target));
      },
      focus() { activeElement = node; node.dispatch("focus"); },
      select() {},
      closest() { return null; },
    };
    let html = "";
    Object.defineProperty(node, "innerHTML", {
      get() { return html; },
      set(value) { html = String(value); if (html === "") node.children = []; },
    });
    return node;
  }

  function makeSelect(id) {
    const select = makeNode("select", id);
    let selectedValue = "";
    Object.defineProperty(select, "options", { get() { return select.children; } });
    Object.defineProperty(select, "selectedIndex", {
      get() { return select.children.findIndex((option) => String(option.value || "") === selectedValue); },
    });
    Object.defineProperty(select, "value", {
      get() { return selectedValue; },
      set(value) {
        const wanted = String(value || "");
        selectedValue = select.children.some((option) => String(option.value || "") === wanted)
          ? wanted : "";
      },
    });
    return select;
  }

  const parent = makeNode("div", "parent");
  const select = makeSelect("timeline-project-filter");
  parent.appendChild(select);
  const all = makeNode("option"); all.value = ""; all.textContent = "全部项目"; select.appendChild(all);
  const uncategorized = makeNode("option"); uncategorized.value = "unclassified"; uncategorized.textContent = "未归类"; select.appendChild(uncategorized);
  select.value = "";

  const context = {
    Promise,
    Error,
    String,
    Number,
    Array,
    Object,
    Math,
    Date,
    RegExp,
    setTimeout,
    clearTimeout,
    setImmediate,
    Event: class Event { constructor(type, options = {}) { this.type = type; Object.assign(this, options); } },
    document,
    window: { WorkTraceApp: {}, document },
  };
  vm.createContext(context);
  vm.runInContext(source("project_autocomplete.js"), context, { filename: "project_autocomplete.js" });
  return { App: context.window.WorkTraceApp, select, document };
}

test("autocomplete refreshes the catalog and materializes a real source option before selection", async () => {
  const { App, select } = autocompleteHarness();
  let projects = [{ id: 7, name: "Old", description: "", last_used_at: "2026-08-01" }];
  let invalidations = 0;
  let loads = 0;
  App.projectCatalog = {
    getFilter: () => projects,
    getEditing: () => projects,
    invalidate() { invalidations += 1; projects = []; },
    load() {
      loads += 1;
      projects = [{ id: 42, name: "Fresh Matter", description: "new client", last_used_at: "2026-08-12" }];
      return Promise.resolve({ filterProjects: projects, editingProjects: projects });
    },
  };

  let changes = 0;
  select.addEventListener("change", () => { changes += 1; });
  const state = App.enhanceProjectSelect(select);
  assert.ok(state);

  state.input.focus();
  await flush();
  await flush();

  assert.equal(invalidations, 1);
  assert.equal(loads, 1);
  assert.ok(select.options.some((option) => String(option.value) === "42"));
  assert.ok(state.items.some((item) => item.value === "42"));

  state.input.value = "fresh";
  state.input.dispatch("input");
  state.input.dispatch("keydown", { key: "ArrowDown" });
  state.input.dispatch("keydown", { key: "Enter" });

  assert.equal(select.value, "42");
  assert.equal(changes, 1);
  assert.equal(state.input.value, "Fresh Matter");
});
