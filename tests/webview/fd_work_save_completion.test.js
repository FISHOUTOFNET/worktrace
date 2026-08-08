const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../worktrace/integrations/fd_work/fd_work_adapter.js"),
  "utf8"
);

function saveHarness({ initiallyDisabled = false, loadingAfterClick = true } = {}) {
  let clicks = 0;
  let loading = false;
  const fields = new Map();

  class Input {
    constructor(value = "value") { this._value = value; }
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
    getClientRects() { return [{}]; }
  }
  class Textarea extends Input {}

  const button = {
    textContent: "保存",
    disabled: initiallyDisabled,
    isConnected: true,
    classList: { contains(name) { return name === "ant-btn-loading" && loading; } },
    getAttribute(name) {
      if (name === "aria-busy") return loading ? "true" : null;
      if (name === "aria-disabled") return this.disabled ? "true" : null;
      return null;
    },
    getClientRects() { return [{}]; },
    querySelector() { return null; },
    click() {
      clicks += 1;
      if (!loadingAfterClick) return;
      loading = true;
      this.disabled = true;
      setTimeout(() => {
        loading = false;
        this.disabled = false;
      }, 8);
    },
  };
  const form = {
    isConnected: true,
    getClientRects() { return [{}]; },
    querySelectorAll() { return [button]; },
    contains() { return false; },
  };
  fields.set("form#basic", form);
  fields.set("#duration", new Input("1.0"));
  fields.set("#narrative", new Textarea("Narrative"));

  const listeners = new Map();
  const context = {
    Promise, Object, String, Array,
    Event: class Event { constructor(type) { this.type = type; } },
    MouseEvent: class MouseEvent { constructor(type) { this.type = type; } },
    PointerEvent: class PointerEvent { constructor(type) { this.type = type; } },
    HTMLInputElement: Input,
    HTMLTextAreaElement: Textarea,
    MutationObserver: class { observe() {} disconnect() {} },
    setTimeout, clearTimeout,
    requestAnimationFrame(callback) { return setTimeout(callback, 1); },
    document: {
      visibilityState: "visible",
      documentElement: { setAttribute() {}, removeAttribute() {} },
      body: { firstElementChild: {}, appendChild() {}, insertBefore() {} },
      querySelector(selector) { return fields.get(selector) || null; },
      querySelectorAll() { return []; },
      getElementById() { return null; },
      createElement() {
        return { setAttribute() {}, appendChild() {}, addEventListener() {} };
      },
    },
    window: {
      innerWidth: 980,
      innerHeight: 760,
      location: {
        href: "https://work.fangdalaw.com/Works/WorkHourList?picker=day",
        origin: "https://work.fangdalaw.com",
      },
      getComputedStyle() { return { display: "block", visibility: "visible" }; },
      addEventListener(name, callback) { listeners.set(name, callback); },
      removeEventListener() {},
    },
  };
  context.window.top = context.window;
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "fd_work_adapter.js" });

  return {
    adapter: context.window.WorkTraceFDWorkAdapter,
    button,
    clicks: () => clicks,
    setDisabled(value) { button.disabled = value; },
    contract() {
      return {
        version: 5,
        operation_generation: 0,
        operation_deadline_ms: Date.now() + 300,
        save_timeout_ms: 150,
        form_selector: "form#basic",
        save_action_label: "保存",
        save_success_selector: ".ant-message-success",
        save_loading_selector: ".ant-btn-loading",
        entry_fields: {
          duration_hours: { selector: "#duration" },
          narrative: { selector: "#narrative" },
          case_number: { selector: "#case" },
        },
      };
    },
  };
}

test("post-click loading to idle is strong save completion evidence", async () => {
  const h = saveHarness({ loadingAfterClick: true });

  const result = await h.adapter._test.saveEntry(h.contract(), 0);

  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(result.stage, "save_completed");
  assert.equal(result.save_loading_observed, true);
  assert.equal(h.clicks(), 1);
});

test("save action waits for transient disabled state before clicking", async () => {
  const h = saveHarness({ initiallyDisabled: true, loadingAfterClick: true });
  setTimeout(() => h.setDisabled(false), 8);

  const result = await h.adapter._test.saveEntry(h.contract(), 0);

  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(result.stage, "save_completed");
  assert.equal(h.clicks(), 1);
});

test("save without toast reset close or post-click loading remains unconfirmed", async () => {
  const h = saveHarness({ loadingAfterClick: false });

  const result = await h.adapter._test.saveEntry(h.contract(), 0);

  assert.equal(result.ok, false);
  assert.equal(result.error, "save_completion_failed");
  assert.equal(result.stage, "save_completed");
  assert.equal(result.save_loading_observed, false);
  assert.equal(h.clicks(), 1);
});
