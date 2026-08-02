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
  function visibleNode(text, popup) {
    return {
      textContent: text,
      innerText: text,
      _popup: popup,
      getAttribute(name) { return name === "title" ? text : null; },
      getClientRects() { return [{}]; },
    };
  }
  const popup = {
    labels: initialLabels.slice(), empty: false, loading: false,
    getAttribute(name) { return name === "role" ? "listbox" : null; },
    getClientRects() { return [{}]; },
    contains(target) { return !!target && target._popup === popup; },
    querySelectorAll(selector) {
      if (selector === "[role='option']") {
        return this.labels.map((label) => visibleNode(label, popup));
      }
      if (selector === "div,span,p") {
        return this.empty ? [visibleNode("暂无数据", popup)] : [];
      }
      if (selector.includes("aria-busy")) {
        return this.loading ? [visibleNode("loading", popup)] : [];
      }
      return [];
    },
  };
  class Input {
    constructor() { this._value = ""; this.onInput = null; }
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
    getAttribute(name) { return name === "aria-controls" ? "case-list" : null; }
    getClientRects() { return [{}]; }
    focus() {}
    click() {}
    blur() {}
    dispatchEvent(event) {
      if (event.type === "input" && this._value && this.onInput) this.onInput(this._value);
    }
  }
  class Textarea extends Input {}
  const input = new Input();
  function emit(type = "childList", target = popup) {
    observers.filter((observer) => observer.active).forEach((observer) => {
      observer.callback([{ type, target }]);
    });
  }
  function setResults(labels, options = {}) {
    popup.labels = labels.slice();
    popup.empty = options.empty === true;
    popup.loading = options.loading === true;
    const target = typeTarget(options.mutationType);
    emit(options.mutationType || "childList", target);
  }
  function typeTarget(type) {
    return type === "characterData" && popup.labels.length
      ? visibleNode(popup.labels[0], popup) : popup;
  }
  const document = {
    documentElement: {},
    querySelector(selector) { return selector === "#case" ? input : null; },
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
    window: {
      location: { href: "https://work.fangdalaw.com/Works/WorkHourList?picker=day" },
      getComputedStyle() { return { display: "block", visibility: "visible" }; },
      close() {},
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "fd_work_adapter.js" });
  return {
    adapter: context.window.WorkTraceFDWorkAdapter,
    input, popup, setResults,
    contract: {
      version: 3,
      field: { selector: "#case" },
      empty_text: "暂无数据",
      max_options: 20,
      max_label_length: 100,
    },
  };
}

test("adapter contract is version 3 and observes text-only lookup changes", () => {
  const { adapter } = harness();
  assert.equal(adapter.version, 3);
  const body = source.slice(source.indexOf("function waitForLookupResult"), source.indexOf("async function fillEntry"));
  assert.match(body, /characterData\s*:\s*true/);
  assert.match(body, /childList\s*:\s*true/);
  assert.match(body, /subtree\s*:\s*true/);
  assert.match(body, /attributes\s*:\s*true/);
});

test("keyword search snapshots old options before observer and requires post-input evidence", () => {
  const body = source.slice(source.indexOf("function waitForLookupResult"), source.indexOf("async function fillEntry"));
  assert.match(body, /beforeSignature/);
  assert.match(body, /beforeCount/);
  assert.match(body, /beforeEmpty/);
  assert.match(body, /lookupGeneration/);
  assert.match(body, /lookup_superseded/);
  assert.ok(body.indexOf("new MutationObserver") < body.indexOf("setSearchValue(input, query)"));
  assert.match(body, /await delay\((?:150|180|200|220|250)\)/);
});

test("empty lookup opens native recent cases without writing query text", () => {
  const body = source.slice(source.indexOf("function waitForLookupResult"), source.indexOf("async function fillEntry"));
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
  assert.deepEqual(nativeSetCalls, ["element", "input", "input"]);
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
  const body = source.slice(source.indexOf("function waitForLookupResult"), source.indexOf("async function fillEntry"));
  assert.match(body, /stableEmpty/);
  assert.match(body, /await delay\((?:150|180|200|220|250)\)/);
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
