const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function classList() {
  const values = new Set();
  return {
    add(...names) { names.forEach((name) => values.add(name)); },
    remove(...names) { names.forEach((name) => values.delete(name)); },
    contains(name) { return values.has(name); },
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : !!force;
      if (enabled) values.add(name);
      else values.delete(name);
      return enabled;
    },
  };
}

function harness() {
  const elements = new Map();
  const toggles = [];

  function element(id) {
    if (!elements.has(id)) {
      const attributes = new Map();
      elements.set(id, {
        id,
        hidden: false,
        disabled: false,
        checked: false,
        value: "",
        textContent: "",
        className: "",
        classList: classList(),
        setAttribute(name, value) { attributes.set(name, String(value)); },
        getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
        removeAttribute(name) { attributes.delete(name); },
        addEventListener() {},
      });
    }
    return elements.get(id);
  }

  const document = {
    activeElement: null,
    getElementById: element,
    querySelectorAll(selector) {
      return selector === ".rules-project-toggle" ? toggles : [];
    },
  };
  const window = { WorkTraceApp: {} };
  const context = {
    window,
    document,
    Promise,
    Array,
    Object,
    String,
    Number,
    parseInt,
  };
  vm.createContext(context);

  window.WorkTraceApp.projectIdentity = {
    prepareEditor() {},
    updateControls() { return { pending: false, hasName: false }; },
    enabled() { return false; },
    reset() {},
    bindHost() {},
    bindEvents() {},
    syncStatus() {},
  };

  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/rules_create_panel_v5.js"),
      "utf8"
    ),
    context,
    { filename: "rules_create_panel_v5.js" }
  );

  function expandedProject(id) {
    const rows = element(`rows-${id}`);
    rows.hidden = false;
    const card = element(`card-${id}`);
    card.querySelector = (selector) => selector === ".rules-row-list" ? rows : null;
    const button = element(`toggle-${id}`);
    button.closest = (selector) => selector === ".rules-project-card" ? card : null;
    button.setAttribute("aria-expanded", "true");
    button.setAttribute("aria-label", "收起项目规则");
    button.setAttribute("data-tooltip", "收起规则");
    button.classList.add("is-expanded");
    toggles.push(button);
    return { rows, button };
  }

  return { App: window.WorkTraceApp, element, expandedProject };
}

test("leaving Project Rules collapses every expanded project without clearing page context", () => {
  const h = harness();
  const first = h.expandedProject(1);
  const second = h.expandedProject(2);
  h.element("rules-search-input").value = "keep search";
  h.element("rules-sort-select").value = "alpha";
  h.App.rulesSortMode = "alpha";

  h.App.resetRulesTransientUi({ restoreFocus: false });

  for (const project of [first, second]) {
    assert.equal(project.rows.hidden, true);
    assert.equal(project.button.getAttribute("aria-expanded"), "false");
    assert.equal(project.button.classList.contains("is-expanded"), false);
    assert.equal(project.button.getAttribute("aria-label"), "展开项目规则");
    assert.equal(project.button.getAttribute("data-tooltip"), "展开规则");
  }
  assert.equal(h.element("rules-search-input").value, "keep search");
  assert.equal(h.element("rules-sort-select").value, "alpha");
  assert.equal(h.App.rulesSortMode, "alpha");
});
