const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadApp() {
  const body = {
    hidden: false,
    getAttribute: () => null,
    parentNode: null,
  };
  const elements = {};
  function getElementById(id) {
    if (!elements[id]) {
      elements[id] = {
        id,
        hidden: false,
        disabled: false,
        textContent: "",
        innerHTML: "",
        className: "",
        classList: { toggle: () => {}, add: () => {}, remove: () => {} },
        querySelector: () => null,
        querySelectorAll: () => [],
        addEventListener: () => {},
        focus: () => {},
        setAttribute: () => {},
        getAttribute: () => null,
        appendChild: () => {},
      };
    }
    return elements[id];
  }
  const context = {
    Promise, Error, String, Number, Array, Math, Date, setTimeout, clearTimeout,
    window: { WorkTraceApp: {} },
    document: {
      body,
      getElementById,
      querySelector: () => null,
      addEventListener: () => {},
    },
  };
  vm.createContext(context);
  const source = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/ui_components.js"),
    "utf8"
  );
  vm.runInContext(source, context);
  return { App: context.window.WorkTraceApp, body };
}

function makeElement(opts) {
  opts = opts || {};
  const el = {
    hidden: !!opts.hidden,
    disabled: !!opts.disabled,
    getAttribute: function (name) {
      if (name === "aria-hidden") return opts.ariaHidden ? "true" : null;
      if (name === "tabindex") return opts.tabindex !== undefined ? String(opts.tabindex) : null;
      return null;
    },
    getClientRects: opts.noLayout
      ? function () { return []; }
      : function () { return [{ width: 10, height: 10 }]; },
    offsetParent: opts.noOffsetParent ? null : { tagName: "BODY" },
    parentNode: opts.parent || null,
  };
  return el;
}

function containerFrom(elements) {
  return {
    querySelectorAll: function () { return elements.slice(); },
  };
}

test("focusable includes visible elements", () => {
  const { App, body } = loadApp();
  const input = makeElement({ parent: body });
  const button = makeElement({ parent: body });
  const container = containerFrom([input, button]);
  const result = App.focusableElements(container);
  assert.equal(result.length, 2);
});

test("focusable excludes elements inside hidden ancestor section", () => {
  const { App, body } = loadApp();
  const visibleInput = makeElement({ parent: body });
  const hiddenSection = { hidden: true, getAttribute: () => null, parentNode: body };
  const hiddenInput = makeElement({ parent: hiddenSection });
  const container = containerFrom([visibleInput, hiddenInput]);
  const result = App.focusableElements(container);
  assert.equal(result.length, 1);
  assert.equal(result[0], visibleInput);
});

test("focusable excludes elements inside aria-hidden ancestor", () => {
  const { App, body } = loadApp();
  const visibleButton = makeElement({ parent: body });
  const ariaHiddenPanel = {
    hidden: false,
    getAttribute: function (name) {
      return name === "aria-hidden" ? "true" : null;
    },
    parentNode: body,
  };
  const hiddenInput = makeElement({ parent: ariaHiddenPanel });
  const container = containerFrom([visibleButton, hiddenInput]);
  const result = App.focusableElements(container);
  assert.equal(result.length, 1);
  assert.equal(result[0], visibleButton);
});

test("focusable excludes elements with no layout box", () => {
  const { App, body } = loadApp();
  const visibleInput = makeElement({ parent: body });
  const noLayoutInput = makeElement({ parent: body, noLayout: true });
  const container = containerFrom([visibleInput, noLayoutInput]);
  const result = App.focusableElements(container);
  assert.equal(result.length, 1);
  assert.equal(result[0], visibleInput);
});

test("focusable returns empty array for null container", () => {
  const { App } = loadApp();
  const result = App.focusableElements(null);
  assert.equal(result.length, 0);
});

test("dialog visible first and last controls close the loop", () => {
  const { App, body } = loadApp();
  const first = makeElement({ parent: body });
  const last = makeElement({ parent: body });
  const container = containerFrom([first, last]);
  const result = App.focusableElements(container);
  assert.equal(result[0], first);
  assert.equal(result[result.length - 1], last);
});
