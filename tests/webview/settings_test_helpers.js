const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SETTINGS_MODULES = Object.freeze([
  "settings_presentation.js",
  "settings_transient_ui.js",
  "settings_data_operations.js",
  "settings_backup_recovery.js",
  "settings.js",
]);

function loadSettingsModules(context) {
  for (const name of SETTINGS_MODULES) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", name), "utf8"),
      context,
      { filename: name },
    );
  }
}

module.exports = { SETTINGS_MODULES, loadSettingsModules };
