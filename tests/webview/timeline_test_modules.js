const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const TIMELINE_MODULES = Object.freeze([
  "timeline_presentation.js",
  "timeline_transient_ui.js",
  "timeline_editor_state.js",
  "timeline_fd_work.js",
  "timeline.js",
]);

function sourcePath(testDir, file) {
  return path.join(testDir, "../../worktrace/webview_ui/js", file);
}

function readTimelineModules(testDir) {
  return TIMELINE_MODULES
    .map((file) => fs.readFileSync(sourcePath(testDir, file), "utf8"))
    .join("\n");
}

function loadTimelineModules(context, testDir) {
  for (const file of TIMELINE_MODULES) {
    vm.runInContext(
      fs.readFileSync(sourcePath(testDir, file), "utf8"),
      context,
      { filename: file }
    );
  }
}

module.exports = {
  TIMELINE_MODULES,
  loadTimelineModules,
  readTimelineModules,
};
