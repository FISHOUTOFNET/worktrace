const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../worktrace/integrations/fd_work/fd_work_adapter.js"),
  "utf8"
);

function harness() {
  class Input {
    constructor() {
      this._value = "";
      this.events = [];
      this.parentElement = null;
    }
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
    dispatchEvent(event) { this.events.push(event.type); }
    getAttribute() { return null; }
    closest() { return null; }
  }
  class Textarea extends Input {
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
  }
  const fields = new Map();
  const documentElement = {
    attrs: new Map(),
    setAttribute(name, value) { this.attrs.set(name, value); },
    removeAttribute(name) { this.attrs.delete(name); },
  };
  const document = {
    documentElement,
    querySelector(selector) { return fields.get(selector) || null; },
    querySelectorAll() { return []; },
    getElementById() { return null; },
  };
  const context = {
    Promise,
    Object,
    String,
    Array,
    Event: class Event { constructor(type) { this.type = type; } },
    HTMLInputElement: Input,
    HTMLTextAreaElement: Textarea,
    MutationObserver: class {
      observe() {}
      disconnect() {}
    },
    clearTimeout,
    setTimeout,
    navigator: {},
    document,
    window: {
      location: { href: "https://work.fangdalaw.com/Works/WorkHourList?picker=day" },
      getComputedStyle() { return { display: "block", visibility: "visible" }; },
      close() {},
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "fd_work_adapter.js" });
  return { context, fields, Input, Textarea, adapter: context.window.WorkTraceFDWorkAdapter };
}

function lookupHarness(initialLabels = ["RECENT A", "RECENT B"]) {
  const observers = [];
  const windowListeners = new Map();
  let optionClicks = 0;
  let input;
  const selection = {
    textContent: "", title: "",
    getAttribute(name) { return name === "title" ? this.title : null; },
  };
  function visibleNode(text, popup) {
    return {
      textContent: text,
      innerText: text,
      _popup: popup,
      getAttribute(name) { return name === "title" ? text : null; },
      getClientRects() { return [{}]; },
      getBoundingClientRect() { return { width: 100, height: 24 }; },
      click() {
        optionClicks += 1;
        selection.textContent = text; selection.title = text; input.value = text;
      },
    };
  }
  function makePopup(labels) {
    const node = {
      labels: labels.slice(), empty: false, loading: false, rendered: true,
      getAttribute(name) { return name === "role" ? "listbox" : null; },
      getClientRects() { return this.rendered ? [{}] : []; },
      contains(target) { return !!target && target._popup === node; },
      querySelectorAll(selector) {
        if (selector === "[role='option']") {
          return this.labels.map((label) => visibleNode(label, node));
        }
        if (selector === "div,span,p") {
          return this.empty ? [visibleNode("暂无数据", node)] : [];
        }
        if (selector.includes("aria-busy")) {
          return this.loading ? [visibleNode("loading", node)] : [];
        }
        return [];
      },
    };
    return node;
  }
  let popup = makePopup(initialLabels);
  class Input {
    constructor() { this._value = ""; this.onInput = null; this.disabled = false; this.readOnly = false; }
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
    getAttribute(name) { return name === "aria-controls" ? "case-list" : null; }
    getClientRects() { return [{}]; }
    getBoundingClientRect() { return { width: 160, height: 30 }; }
    closest() { return { querySelector() { return selection.textContent ? selection : null; } }; }
    focus() {}
    click() {}
    blur() {}
    dispatchEvent(event) {
      if (event.type === "input" && this._value && this.onInput) this.onInput(this._value);
    }
  }
  class Textarea extends Input {}
  input = new Input();
  function emit(type = "childList", target = popup) {
    observers.filter((observer) => observer.active).forEach((observer) => {
      observer.callback([{ type, target }]);
    });
  }
  function setResults(labels, options = {}) {
    if (!popup) return;
    popup.labels = labels.slice();
    popup.empty = options.empty === true;
    popup.loading = options.loading === true;
    const target = typeTarget(options.mutationType);
    emit(options.mutationType || "childList", target);
  }
  function replacePopup(labels) {
    popup = makePopup(labels);
    emit("childList", {});
  }
  function removePopup() {
    popup = null;
    emit("childList", {});
  }
  function typeTarget(type) {
    return type === "characterData" && popup.labels.length
      ? visibleNode(popup.labels[0], popup) : popup;
  }
  const document = {
    documentElement: {}, body: { firstElementChild: {} }, visibilityState: "visible",
    querySelector(selector) {
      if (selector === "#case") return input;
      if (selector === "#case-list") return popup;
      return null;
    },
    querySelectorAll() { return []; },
    getElementById(id) { return id === "case-list" ? popup : null; },
  };
  const context = {
    Promise, Object, String, Array,
    Event: class Event { constructor(type) { this.type = type; } },
    KeyboardEvent: class KeyboardEvent { constructor(type) { this.type = type; } },
    HTMLInputElement: Input,
    HTMLTextAreaElement: Textarea,
    MutationObserver: class {
      constructor(callback) { this.callback = callback; this.active = true; observers.push(this); }
      observe() {}
      disconnect() { this.active = false; }
    },
    clearTimeout, setTimeout, navigator: {}, document,
    requestAnimationFrame(callback) { return setTimeout(callback, 0); },
    window: {
      location: { href: "https://work.fangdalaw.com/Works/WorkHourList?picker=day" },
      innerWidth: 980, innerHeight: 760,
      getComputedStyle() { return { display: "block", visibility: "visible" }; },
      addEventListener(name, handler) { windowListeners.set(name, handler); },
      close() {},
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "fd_work_adapter.js" });
  return {
    adapter: context.window.WorkTraceFDWorkAdapter,
    input, get popup() { return popup; }, setResults, replacePopup, removePopup,
    get optionClicks() { return optionClicks; },
    pagehide() { if (windowListeners.has("pagehide")) windowListeners.get("pagehide")(); },
    contract: {
      version: 4,
      field: { selector: "#case", listbox: "#case-list" },
      fields: { case_number: { selector: "#case", listbox: "#case-list" } },
      empty_text: "暂无数据",
      max_options: 20,
      max_label_length: 100,
      popup_timeout_ms: 100,
      lookup_timeout_ms: 800,
      stability_ms: 200,
    },
  };
}

test("adapter contract is version 4 and observes text-only lookup changes", () => {
  const { adapter } = harness();
  assert.equal(adapter.version, 4);
  const body = source.slice(source.indexOf("async function prepareCaseCombobox"), source.indexOf("async function fillEntry"));
  assert.match(body, /characterData\s*:\s*true/);
  assert.match(body, /childList\s*:\s*true/);
  assert.match(body, /subtree\s*:\s*true/);
  assert.match(body, /attributes\s*:\s*true/);
});

test("keyword search snapshots old options before observer and requires post-input evidence", () => {
  const body = source.slice(source.indexOf("async function prepareCaseCombobox"), source.indexOf("async function fillEntry"));
  assert.match(body, /before\.signature/);
  assert.match(body, /before\.count/);
  assert.match(body, /before\.empty/);
  assert.match(body, /lookupGeneration/);
  assert.match(body, /lookup_superseded/);
  assert.ok(body.indexOf("new MutationObserver") < body.indexOf("setSearchValue(input, query)"));
  assert.match(body, /Math\.max\(150, Math\.min\(250,/);
  assert.match(body, /await delay\(stabilityMs\)/);
});

test("search and fill share lookupCaseOptions through unique exact selection", () => {
  const body = source.slice(source.indexOf("async function prepareCaseCombobox"), source.indexOf("function verifyEntry"));
  assert.match(body, /async function lookupCaseOptions/);
  assert.match(body, /async function selectExactCase/);
  const fillBody = body.slice(body.indexOf("async function fillCaseNumber"));
  assert.match(fillBody, /selectExactCase/);
  assert.doesNotMatch(fillBody, /querySelectorAll\("\[role='option'\]"\)/);
});

test("empty lookup opens native recent cases without writing query text", () => {
  const body = source.slice(source.indexOf("async function prepareCaseCombobox"), source.indexOf("async function fillEntry"));
  assert.match(body, /query === ""/);
  assert.match(body, /input\.click\(\)/);
  assert.match(body, /recent/);
});

test("case matching is unique exact matching after edge Unicode whitespace only", () => {
  const { adapter } = harness();
  assert.deepEqual(
    Array.from(adapter._test.exactMatches([" CASE-1 ", "CASE-10", "case-1"], "CASE-1")),
    [" CASE-1 "]
  );
  assert.deepEqual(
    Array.from(adapter._test.exactMatches(["CASE-1", "\u3000CASE-1\u00a0"], "CASE-1")),
    ["CASE-1", "\u3000CASE-1\u00a0"]
  );
  assert.equal(adapter._test.exactMatches(["CASE-10"], "CASE-1").length, 0);
});

test("date duration and narrative use native setter events and verify readback", () => {
  const { adapter, fields, Input, Textarea } = harness();
  const date = new Input();
  const duration = new Input();
  const narrative = new Textarea();
  fields.set("#date", date);
  fields.set("#duration", duration);
  fields.set("#narrative", narrative);
  const contract = { fields: {
    work_date: { selector: "#date" },
    duration_hours: { selector: "#duration" },
    narrative: { selector: "#narrative" },
  } };

  const dateResult = adapter.fillWorkDate("2026-07-31", contract);
  const durationResult = adapter.fillDuration("1.4", contract);
  const narrativeResult = adapter.fillNarrative("Line one.\nLine two.", contract);
  assert.equal(dateResult.ok, true, JSON.stringify(dateResult));
  assert.equal(durationResult.ok, true, JSON.stringify(durationResult));
  assert.equal(narrativeResult.ok, true, JSON.stringify(narrativeResult));
  assert.equal(date.value, "2026-07-31");
  assert.equal(duration.value, "1.4");
  assert.equal(narrative.value, "Line one.\nLine two.");
  assert.deepEqual(date.events, ["input", "change", "blur"]);
  assert.deepEqual(duration.events, ["input", "change", "blur"]);
  assert.deepEqual(narrative.events, ["input", "change", "blur"]);
});

test("adapter has reversible compact root and never saves submits or calls an internal API", () => {
  assert.match(source, /data-worktrace-fdwork-compact/);
  assert.match(source, /removeCompactMode/);
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /XMLHttpRequest|axios|token|cookie/i);
  assert.doesNotMatch(source, /querySelector\([^)]*css-dev-only-do-not-override/);
  assert.doesNotMatch(source, /nth-child|screenX|screenY/);
  assert.doesNotMatch(source, /\.click\(\).*["'](?:保存|提交)/s);
});

test("ignored FD Work fields are never passed to nativeSet", () => {
  const nativeSetCalls = Array.from(source.matchAll(/nativeSet\(([^,]+)/g), (match) => match[1].trim());
  assert.deepEqual(nativeSetCalls, ["element", "input"]);
  for (const id of ["basic_clientId", "basic_employeeId", "basic_nickName", "basic_writtenLanguage"]) {
    assert.doesNotMatch(source, new RegExp(`nativeSet\\([^\\n]*${id}`));
  }
});

test("search labels preserve order and only normalize Unicode edge spaces", () => {
  const { adapter } = harness();
  const normalized = adapter._test.normalizeCaseLabels([
    "  CASE A  ",
    "\u3000CASE B\u00a0",
    "case a",
  ], 20, 100);
  assert.equal(normalized.ok, true, JSON.stringify(normalized));
  assert.deepEqual(Array.from(normalized.labels), ["CASE A", "CASE B", "case a"]);
});

test("duplicate normalized case labels fail closed instead of becoming selectable", () => {
  const { adapter } = harness();
  const normalized = adapter._test.normalizeCaseLabels(
    ["CASE A", "\u3000CASE A\u00a0"], 20, 100
  );
  assert.deepEqual(
    { ok: normalized.ok, error: normalized.error },
    { ok: false, error: "duplicate_case_label" }
  );
});

test("case option visibility rejects nodes with no rendered client rectangle", () => {
  const { adapter } = harness();
  assert.equal(adapter._test.visible({ getClientRects() { return []; } }), false);
  assert.equal(adapter._test.visible({ getClientRects() { return [{}]; } }), true);
});

test("case search does not click an option or invoke native save actions", () => {
  assert.match(source, /async function searchCases/);
  const body = source.slice(
    source.indexOf("async function searchCases"),
    source.indexOf("async function fillEntry")
  );
  assert.doesNotMatch(body, /\[role=['"]option['"]\][\s\S]*\.click\s*\(/);
  assert.doesNotMatch(body, /保存|提交/);
});

test("case search confirms the empty result remains stable", () => {
  const body = source.slice(source.indexOf("async function prepareCaseCombobox"), source.indexOf("async function fillEntry"));
  assert.match(body, /stableEmpty/);
  assert.match(body, /await delay\(stabilityMs\)/);
});

test("native recent lookup preserves the popup order", async () => {
  const h = lookupHarness(["RECENT B", "RECENT A"]);
  const found = await h.adapter.searchCases("", h.contract);
  assert.equal(found.ok, true, JSON.stringify(found));
  assert.deepEqual(Array.from(found.labels), ["RECENT B", "RECENT A"]);
});

test("keyword lookup cannot immediately return the two pre-focus recent options", async () => {
  const h = lookupHarness(["RECENT A", "RECENT B"]);
  h.input.onInput = (query) => h.setResults(
    [`${query} RESULT`], { mutationType: "characterData" }
  );
  const found = await h.adapter.searchCases("ALPHA", h.contract);
  assert.equal(found.ok, true, JSON.stringify(found));
  assert.deepEqual(Array.from(found.labels), ["ALPHA RESULT"]);
});

test("fill waits past pre-focus recent options and selects the unique current result", async () => {
  const h = lookupHarness(["RECENT A", "RECENT B"]);
  h.input.onInput = () => setTimeout(
    () => h.setResults(["CASE Z"], { mutationType: "characterData" }), 25
  );

  const filled = await h.adapter.fillCaseNumber("CASE Z", h.contract);

  assert.equal(filled.ok, true, JSON.stringify(filled));
  assert.equal(h.input.value, "CASE Z");
});

test("pagehide supersedes an old fill lookup before it can click a late option", async () => {
  const h = lookupHarness(["RECENT A", "RECENT B"]);
  h.contract.lookup_timeout_ms = 300;
  h.input.onInput = () => setTimeout(
    () => h.setResults(["CASE Z"], { mutationType: "characterData" }), 100
  );
  const pending = h.adapter.fillCaseNumber("CASE Z", h.contract);
  setTimeout(() => h.pagehide(), 20);

  const filled = await pending;
  await new Promise((resolve) => setTimeout(resolve, 120));

  assert.equal(filled.error, "lookup_superseded");
  assert.equal(h.optionClicks, 0);
});

test("unrelated attribute mutation cannot prove stale recent options belong to query", async () => {
  const h = lookupHarness(["RECENT A", "RECENT B"]);
  h.input.onInput = () => {
    h.setResults(["RECENT A", "RECENT B"], { mutationType: "attributes" });
    setTimeout(() => h.setResults(["QUERY RESULT"], { mutationType: "characterData" }), 320);
  };

  const found = await h.adapter.searchCases("QUERY", h.contract);

  assert.equal(found.ok, true, JSON.stringify(found));
  assert.deepEqual(Array.from(found.labels), ["QUERY RESULT"]);
});

test("popup identity replacement is accepted as current-query evidence", async () => {
  const h = lookupHarness(["RECENT A", "RECENT B"]);
  h.input.onInput = () => setTimeout(() => h.replacePopup(["SWAPPED RESULT"]), 20);

  const found = await h.adapter.searchCases("SWAP", h.contract);

  assert.equal(found.ok, true, JSON.stringify(found));
  assert.deepEqual(Array.from(found.labels), ["SWAPPED RESULT"]);
});

test("combobox preparation returns granular input and popup failures", async () => {
  const disabled = lookupHarness();
  disabled.input.disabled = true;
  assert.equal((await disabled.adapter.searchCases("A", disabled.contract)).error, "case_input_not_interactive");

  const unrendered = lookupHarness();
  unrendered.input.getClientRects = () => [];
  assert.equal((await unrendered.adapter.searchCases("A", unrendered.contract)).error, "case_input_not_rendered");

  const noControls = lookupHarness();
  noControls.input.getAttribute = () => null;
  assert.equal((await noControls.adapter.searchCases("A", noControls.contract)).error, "case_aria_controls_missing");

  const missingPopup = lookupHarness();
  missingPopup.removePopup();
  assert.equal((await missingPopup.adapter.searchCases("A", missingPopup.contract)).error, "case_popup_not_created");

  const hiddenPopup = lookupHarness();
  hiddenPopup.popup.rendered = false;
  assert.equal((await hiddenPopup.adapter.searchCases("A", hiddenPopup.contract)).error, "case_popup_not_interactive");
});

test("loading cycle and stable empty result are accepted only after mutation", async () => {
  const loading = lookupHarness(["RECENT A", "RECENT B"]);
  loading.input.onInput = () => {
    loading.setResults([], { loading: true, mutationType: "attributes" });
    setTimeout(() => loading.setResults(["LOADED"], { mutationType: "childList" }), 10);
  };
  const loaded = await loading.adapter.searchCases("L", loading.contract);
  assert.deepEqual(Array.from(loaded.labels), ["LOADED"]);

  const empty = lookupHarness(["RECENT A", "RECENT B"]);
  empty.input.onInput = () => empty.setResults([], { empty: true, mutationType: "childList" });
  const none = await empty.adapter.searchCases("NONE", empty.contract);
  assert.equal(none.ok, true, JSON.stringify(none));
  assert.deepEqual(Array.from(none.labels), []);
});

test("late lookup A is superseded by lookup B without clearing B", async () => {
  const h = lookupHarness(["RECENT A", "RECENT B"]);
  h.input.onInput = (query) => {
    if (query === "B") h.setResults(["B RESULT"], { mutationType: "characterData" });
  };
  const first = h.adapter.searchCases("A", h.contract);
  await new Promise((resolve) => setTimeout(resolve, 10));
  const second = h.adapter.searchCases("B", h.contract);
  const [a, b] = await Promise.all([first, second]);
  assert.equal(a.error, "lookup_superseded");
  assert.deepEqual(Array.from(b.labels), ["B RESULT"]);
});
