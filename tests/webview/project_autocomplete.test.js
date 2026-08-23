const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadApp() {
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
      body: { hidden: false, getAttribute: () => null, parentNode: null },
      getElementById,
      querySelectorAll: () => [],
      addEventListener: () => {},
    },
  };
  vm.createContext(context);
  const source = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/project_autocomplete.js"),
    "utf8"
  );
  vm.runInContext(source, context);
  return context.window.WorkTraceApp;
}

function project(id, name, description, lastUsedAt) {
  return {
    id,
    name,
    description: description || "",
    last_used_at: lastUsedAt || null,
  };
}

test("empty query returns at most ten most recently used projects", () => {
  const App = loadApp();
  const projects = [];
  for (let i = 1; i <= 12; i += 1) {
    projects.push(project(i, `Project ${String(i).padStart(2, "0")}`, "", `2026-08-${String(i).padStart(2, "0")} 09:00:00`));
  }
  projects.push(project(99, "Never used", "", null));

  const result = App.projectAutocompleteCandidates(projects, "");

  assert.equal(result.length, 10);
  assert.deepEqual(
    Array.from(result, (item) => item.name),
    ["Project 12", "Project 11", "Project 10", "Project 09", "Project 08", "Project 07", "Project 06", "Project 05", "Project 04", "Project 03"]
  );
  assert.equal(result.some((item) => item.name === "Never used"), false);
});

test("search matches project name and description and sorts only by project name", () => {
  const App = loadApp();
  const projects = [
    project(1, "Zulu Matter", "client one", "2026-08-12 12:00:00"),
    project(2, "Alpha Matter", "client one", "2026-01-01 12:00:00"),
    project(3, "Beta One", "other", "2026-08-11 12:00:00"),
    project(4, "Gamma", "CLIENT ONE diligence", "2026-08-10 12:00:00"),
  ];

  const result = App.projectAutocompleteCandidates(projects, "one");

  assert.deepEqual(
    Array.from(result, (item) => item.name),
    ["Alpha Matter", "Beta One", "Gamma", "Zulu Matter"]
  );
});

test("search results are capped at ten", () => {
  const App = loadApp();
  const projects = [];
  for (let i = 15; i >= 1; i -= 1) {
    projects.push(project(i, `Case ${String(i).padStart(2, "0")}`, "shared description", null));
  }

  const result = App.projectAutocompleteCandidates(projects, "shared");

  assert.equal(result.length, 10);
  assert.deepEqual(
    Array.from(result, (item) => item.name),
    ["Case 01", "Case 02", "Case 03", "Case 04", "Case 05", "Case 06", "Case 07", "Case 08", "Case 09", "Case 10"]
  );
});
