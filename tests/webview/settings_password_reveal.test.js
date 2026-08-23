const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { loadSettingsModules } = require("./settings_test_helpers");

function harness() {
  const elements = new Map();
  const windowListeners = new Map();
  const revealIds = [
    ["settings-backup-passphrase-reveal", "settings-backup-passphrase"],
    ["settings-backup-passphrase-confirm-reveal", "settings-backup-passphrase-confirm"],
    ["settings-backup-import-passphrase-reveal", "settings-backup-import-passphrase"],
  ];

  function element(id) {
    if (!elements.has(id)) {
      const listeners = new Map();
      elements.set(id, {
        id,
        hidden: false,
        disabled: false,
        type: id.includes("passphrase") && !id.includes("reveal") ? "password" : "button",
        value: "",
        dataset: {},
        selectionStart: 1,
        selectionEnd: 3,
        selectionDirection: "forward",
        addEventListener(type, handler) { listeners.set(type, handler); },
        setAttribute(name, value) { this[name] = String(value); },
        setSelectionRange(start, end, direction) {
          this.selectionStart = start;
          this.selectionEnd = end;
          this.selectionDirection = direction;
        },
        setPointerCapture() {},
        dispatch(type, event = {}) {
          const handler = listeners.get(type);
          if (handler) {
            handler({
              target: this,
              currentTarget: this,
              key: "",
              pointerId: 1,
              preventDefault() {},
              ...event,
            });
          }
        },
      });
    }
    return elements.get(id);
  }

  const buttons = revealIds.map(([buttonId, inputId]) => {
    const button = element(buttonId);
    button.dataset.passwordInput = inputId;
    return button;
  });
  revealIds.forEach(([, inputId]) => element(inputId));

  const context = {
    Promise, Error, String, Number, Array, Math, Date,
    window: {
      WorkTraceApp: {},
      addEventListener(type, handler) { windowListeners.set(type, handler); },
    },
    document: {
      getElementById: element,
      querySelector() { return null; },
      querySelectorAll(selector) {
        return selector === ".password-reveal-button" ? buttons : [];
      },
      createElement(tag) { return element(`created-${tag}-${elements.size}`); },
    },
  };
  vm.createContext(context);
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    handleResult(result) { return result; },
  });
  loadSettingsModules(context);
  App.initPasswordRevealControls();
  return {
    App,
    element,
    windowDispatch(type) {
      const handler = windowListeners.get(type);
      if (handler) handler({});
    },
  };
}

test("all credential inputs default to hidden passwords", () => {
  const { element } = harness();
  for (const id of [
    "settings-backup-passphrase",
    "settings-backup-passphrase-confirm",
    "settings-backup-import-passphrase",
  ]) {
    assert.equal(element(id).type, "password");
  }
});

test("pointer reveal is momentary and preserves the input value and selection", () => {
  const { element } = harness();
  const input = element("settings-backup-passphrase");
  const button = element("settings-backup-passphrase-reveal");
  input.value = "secret";

  button.dispatch("pointerdown");
  assert.equal(input.type, "text");
  assert.equal(button["aria-pressed"], "true");
  button.dispatch("pointerup");

  assert.equal(input.type, "password");
  assert.equal(button["aria-pressed"], "false");
  assert.equal(input.value, "secret");
  assert.deepEqual(
    [input.selectionStart, input.selectionEnd, input.selectionDirection],
    [1, 3, "forward"]
  );
});

test("keyboard reveal lasts only for the Space or Enter key hold", () => {
  const { element } = harness();
  const input = element("settings-backup-passphrase-confirm");
  const button = element("settings-backup-passphrase-confirm-reveal");

  button.dispatch("keydown", { key: " " });
  assert.equal(input.type, "text");
  button.dispatch("keyup", { key: " " });
  assert.equal(input.type, "password");
  button.dispatch("keydown", { key: "Enter" });
  assert.equal(input.type, "text");
  button.dispatch("keyup", { key: "Enter" });
  assert.equal(input.type, "password");
});

test("cancel, leave, blur, page blur, and disabled state always hide passwords", () => {
  const { App, element, windowDispatch } = harness();
  const input = element("settings-backup-import-passphrase");
  const button = element("settings-backup-import-passphrase-reveal");

  for (const event of ["pointercancel", "pointerleave", "lostpointercapture", "blur"]) {
    button.dispatch("pointerdown");
    assert.equal(input.type, "text");
    button.dispatch(event);
    assert.equal(input.type, "password", event);
  }

  button.dispatch("pointerdown");
  windowDispatch("blur");
  assert.equal(input.type, "password");
  button.dispatch("pointerdown");
  windowDispatch("pagehide");
  assert.equal(input.type, "password");

  button.disabled = true;
  input.disabled = true;
  button.dispatch("pointerdown");
  assert.equal(input.type, "password");
  button.disabled = false;
  input.disabled = false;
  button.dispatch("pointerdown");
  assert.equal(input.type, "text");
  App.setSettingsBackupControlsDisabled(true);
  assert.equal(input.type, "password");
  App.hideAllPasswordFields();
  assert.equal(input.type, "password");
});
