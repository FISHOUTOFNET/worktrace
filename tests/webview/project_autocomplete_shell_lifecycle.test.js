const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function createHarness() {
  const listenersByWindow = new Map();
  const timers = [];
  let activeElement = null;
  let modality = "none";

  function makeClassList() {
    const values = new Set();
    return {
      add(...names) { names.forEach((name) => values.add(name)); },
      remove(...names) { names.forEach((name) => values.delete(name)); },
      toggle(name, force) {
        const enabled = force === undefined ? !values.has(name) : !!force;
        if (enabled) values.add(name);
        else values.delete(name);
        return enabled;
      },
      contains(name) { return values.has(name); },
    };
  }

  function makeNode(tagName = "DIV", id = "") {
    const attrs = new Map();
    const listeners = new Map();
    const node = {
      tagName,
      id,
      hidden: false,
      disabled: false,
      value: "",
      textContent: "",
      text: "",
      innerHTML: "",
      className: "",
      tabIndex: 0,
      parentNode: null,
      children: [],
      classList: makeClassList(),
      setAttribute(name, value) { attrs.set(name, String(value)); },
      getAttribute(name) { return attrs.has(name) ? attrs.get(name) : null; },
      removeAttribute(name) { attrs.delete(name); },
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
            stopPropagation() {},
            ...event,
          });
        }
      },
      appendChild(child) {
        child.parentNode = node;
        node.children.push(child);
      },
      insertBefore(child) {
        child.parentNode = node;
        node.children.push(child);
      },
      contains(target) {
        let current = target;
        while (current) {
          if (current === node) return true;
          current = current.parentNode;
        }
        return false;
      },
      querySelectorAll(selector) {
        if (selector === '[role="option"]') {
          return node.children.filter((child) => child.getAttribute("role") === "option");
        }
        return [];
      },
      closest() { return null; },
      focus() {
        activeElement = node;
        node.dispatch("focus");
      },
      blur() {
        activeElement = null;
        node.dispatch("blur");
      },
      select() {},
    };
    return node;
  }

  function option(value, label) {
    const item = makeNode("OPTION");
    item.value = value;
    item.textContent = label;
    item.text = label;
    return item;
  }

  const parent = makeNode("LABEL", "timeline-project-parent");
  const select = makeNode("SELECT", "timeline-project-filter");
  select.parentNode = parent;
  select.options = [option("", "全部项目"), option("unclassified", "未归类")];
  select.selectedIndex = 0;
  select.value = "";
  const originalAppendChild = select.appendChild;
  select.appendChild = function (child) {
    originalAppendChild.call(select, child);
    select.options.push(child);
  };

  const document = {
    get activeElement() { return activeElement; },
    getElementById(id) {
      return id === "timeline-project-filter" ? select : null;
    },
    createElement(tag) { return makeNode(String(tag || "div").toUpperCase()); },
    querySelectorAll() { return []; },
  };

  const App = {
    shellVisible: true,
    transientInputModality: () => modality,
    isTransientFocusSuppressed: () => false,
    projectCatalog: {
      getFilter: () => [{
        id: 1,
        name: "Alpha Project",
        description: "Client",
        last_used_at: "2026-08-23 10:00:00",
      }],
    },
  };
  const window = {
    WorkTraceApp: App,
    addEventListener(name, handler) {
      if (!listenersByWindow.has(name)) listenersByWindow.set(name, []);
      listenersByWindow.get(name).push(handler);
    },
  };
  const context = {
    window,
    document,
    Promise,
    Error,
    String,
    Number,
    Array,
    Object,
    Math,
    Date,
    setTimeout(fn, ms) {
      timers.push({ fn, ms, cleared: false });
      return timers.length;
    },
    clearTimeout(id) {
      if (timers[id - 1]) timers[id - 1].cleared = true;
    },
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/project_autocomplete.js"),
      "utf8"
    ),
    context,
    { filename: "project_autocomplete.js" }
  );

  return {
    App,
    select,
    state: select._projectAutocomplete,
    setModality(value) { modality = value; },
    runTimers() {
      for (const timer of timers) {
        if (!timer.cleared) {
          timer.cleared = true;
          timer.fn();
        }
      }
    },
    dispatchWindow(name) {
      for (const handler of listenersByWindow.get(name) || []) handler({});
    },
  };
}

test("restored focus does not open project suggestions", () => {
  const h = createHarness();
  assert.ok(h.state);
  h.setModality("none");

  h.state.input.focus();

  assert.equal(h.state.menu.hidden, true);
  assert.equal(h.state.input.getAttribute("aria-expanded"), "false");
});

test("real keyboard focus still opens project suggestions", () => {
  const h = createHarness();
  h.setModality("keyboard");

  h.state.input.focus();

  assert.equal(h.state.menu.hidden, false);
  assert.equal(h.state.input.getAttribute("aria-expanded"), "true");
});

test("shell hide closes suggestions without discarding a search draft", () => {
  const h = createHarness();
  h.setModality("keyboard");
  h.state.input.focus();
  h.state.input.value = "Alpha";
  h.state.input.dispatch("input");
  assert.equal(h.state.menu.hidden, false);

  h.App.shellVisible = false;
  h.App.projectAutocomplete.onShellHidden();
  h.state.input.blur();
  h.runTimers();

  assert.equal(h.state.menu.hidden, true);
  assert.equal(h.state.input.value, "Alpha");
  assert.equal(h.state.dirty, true);

  h.App.shellVisible = true;
  h.setModality("none");
  h.state.input.focus();
  assert.equal(h.state.menu.hidden, true);
  assert.equal(h.state.input.value, "Alpha");
});

test("window blur also closes suggestions while preserving the draft", () => {
  const h = createHarness();
  h.setModality("keyboard");
  h.state.input.focus();
  h.state.input.value = "Alpha";
  h.state.input.dispatch("input");

  h.dispatchWindow("blur");
  h.state.input.blur();
  h.runTimers();

  assert.equal(h.state.menu.hidden, true);
  assert.equal(h.state.input.value, "Alpha");
  assert.equal(h.state.dirty, true);
});
