const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  const elements = new Map();
  let activeElement = null;

  function classList() {
    const values = new Set();
    return {
      add(...names) { names.forEach((name) => values.add(name)); },
      remove(...names) { names.forEach((name) => values.delete(name)); },
      contains(name) { return values.has(name); },
      toggle(name, force) {
        const next = force === undefined ? !values.has(name) : !!force;
        if (next) values.add(name); else values.delete(name);
        return next;
      },
    };
  }

  function element(id) {
    if (!elements.has(id)) {
      const attrs = new Map();
      const listeners = new Map();
      const node = {
        id,
        hidden: id === "rules-create-panel",
        disabled: false,
        checked: id === "rules-panel-folder-recursive" || id === "rules-panel-backfill",
        value: "",
        textContent: "",
        innerHTML: "",
        tabIndex: 0,
        className: "",
        classList: classList(),
        setAttribute(name, value) { attrs.set(name, String(value)); },
        getAttribute(name) { return attrs.has(name) ? attrs.get(name) : null; },
        addEventListener(name, handler) {
          if (!listeners.has(name)) listeners.set(name, []);
          listeners.get(name).push(handler);
        },
        dispatch(name, event = {}) {
          for (const handler of listeners.get(name) || []) {
            handler.call(node, {
              target: node,
              currentTarget: node,
              key: event.key || "",
              preventDefault() {},
              ...event,
            });
          }
        },
        appendChild() {},
        focus() { activeElement = node; },
      };
      elements.set(id, node);
    }
    return elements.get(id);
  }

  const document = {
    get activeElement() { return activeElement; },
    getElementById: element,
    createElement(tag) { return element(`created-${tag}-${elements.size}`); },
    querySelectorAll() { return []; },
  };
  const window = { WorkTraceApp: {}, document };
  const context = {
    window,
    document,
    Promise,
    String,
    Number,
    Array,
    Object,
    parseInt,
  };
  vm.createContext(context);

  const App = window.WorkTraceApp;
  App.safeText = (value, fallback) => value === undefined || value === null ? fallback : String(value);
  App.projectIdentity = {
    bindHost() {}, bindEvents() {}, syncStatus() {}, prepareEditor() {}, reset() {},
    enabled() { return false; },
    updateControls() { return { pending: false, hasName: false }; },
  };
  App.applyRulesSearch = () => {};
  App.rerenderProjectRulesList = () => {};
  App.lastProjectRulesData = { projects: [] };

  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/rules_create_panel_v5.js"),
      "utf8"
    ),
    context,
    { filename: "rules_create_panel_v5.js" }
  );
  App.initRulesPanelEvents();
  return { App, element, activeElement: () => activeElement };
}

test("rule type switching preserves the folder-recursive draft", () => {
  const h = harness();
  const recursive = h.element("rules-panel-folder-recursive");
  recursive.checked = false;
  recursive.dispatch("change");

  h.App.setRulesPanelRuleType("keyword");
  h.App.setRulesPanelRuleType("folder");

  assert.equal(recursive.checked, false);
  h.App.resetRulesTransientUi({ restoreFocus: false });
  assert.equal(recursive.checked, true);
});

test("rule type tabs support roving Arrow Home and End navigation", () => {
  const h = harness();
  const folder = h.element("rules-panel-folder-type");
  const keyword = h.element("rules-panel-keyword-type");
  h.App.setRulesPanelRuleType("folder");

  folder.dispatch("keydown", { key: "ArrowRight" });
  assert.equal(keyword.getAttribute("aria-selected"), "true");
  assert.equal(keyword.tabIndex, 0);
  assert.equal(folder.tabIndex, -1);
  assert.equal(h.activeElement(), keyword);

  keyword.dispatch("keydown", { key: "Home" });
  assert.equal(folder.getAttribute("aria-selected"), "true");
  assert.equal(h.activeElement(), folder);

  folder.dispatch("keydown", { key: "End" });
  assert.equal(keyword.getAttribute("aria-selected"), "true");
  assert.equal(h.activeElement(), keyword);

  keyword.dispatch("keydown", { key: "ArrowLeft" });
  assert.equal(folder.getAttribute("aria-selected"), "true");
  assert.equal(h.activeElement(), folder);
});
