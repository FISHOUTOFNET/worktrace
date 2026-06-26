# WorkTrace v0.1 Release Validation

This checklist is the release-candidate validation baseline for WorkTrace v0.1 Lite.

## Scope

- Current validation target: WorkTrace v0.1 Lite.
- This document does not cover v0.2 AI, server features, payments, licensing, database encryption, automatic updates, or frontend migration.
- The goal is to confirm that Windows users can install, start, collect active-window metadata, classify activity, export, clear local data, and exit without crossing the documented privacy boundary.

## Validation Environment

- Windows 10 or Windows 11 with a normal user account.
- Do not use administrator privileges.
- Prefer a clean or temporary Windows user profile.
- Validate the Python development run.
- Validate the PyInstaller single-file exe.
- Validate the current-user installer.
- Before validation, these paths may be deleted:
  - `%LOCALAPPDATA%\WorkTrace`
  - `%LOCALAPPDATA%\Programs\WorkTrace`
  - `Documents\WorkTrace Exports`

## Basic Commands

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run tests:

```powershell
pytest
```

Start from source:

```powershell
python -m worktrace.main
```

Build the single-file exe:

```powershell
python -m PyInstaller --noconfirm --clean WorkTrace.spec
```

Build the installer:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1
```

## Automated Validation Checklist

- [ ] `pytest` passes.
- [ ] GitHub Actions Windows tests pass.
- [ ] PyInstaller build smoke test passes.
- [ ] `dist\WorkTrace.exe` is generated.
- [ ] `dist\WorkTrace-Setup.exe` is generated.
- [ ] No new network dependency is introduced.
- [ ] No new administrator-permission requirement is introduced.

## Manual Validation Checklist

### A. First Launch And Privacy Notice

- [ ] Start after deleting old data.
- [ ] Privacy notice appears.
- [ ] Collection does not start before acceptance.
- [ ] Collection starts after acceptance.
- [ ] Database is created at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`.
- [ ] Log file is created at `%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`.

### B. Normal Collection

- [ ] Open Notepad, Word, WPS, browser, or similar windows.
- [ ] Activity records appear in Time Details.
- [ ] App name, process name, window title, and duration look correct.
- [ ] Current activity timer increases in `hh:mm:ss`.
- [ ] Activities below 30 seconds do not immediately pollute history.
- [ ] Activities enter history normally after reaching the threshold.

### C. Projects And Rules

- [ ] Create a normal project.
- [ ] Add a keyword rule.
- [ ] Add a folder rule.
- [ ] Activity is classified automatically.
- [ ] Manual classification is not overwritten by automatic rules.
- [ ] Disabled projects no longer participate in automatic classification.
- [ ] The exclusion-rule project is disabled by default and has no default rules.

### D. File Paths And Resource Recognition

- [ ] A full local path in a window title can be used as an anchor.
- [ ] A full local file path with any extension can be used as an anchor.
- [ ] Folder rules can match non-Office and non-PDF files.
- [ ] Files with the same name but non-unique paths are not classified incorrectly.
- [ ] WPS, Office, PDF, IDE, browser, and email resource types are represented reasonably in the UI.
- [ ] File body, email body, and webpage body are not read.

### E. Exclusion Rules And Privacy

- [ ] Enable the `排除规则` project.
- [ ] Add a keyword or folder exclusion rule.
- [ ] Matching activity saves only anonymous information.
- [ ] Real app name, process name, window title, and path are not saved.
- [ ] Excluded records are not included in normal exports by default.
- [ ] Logs do not record the real title or path of excluded windows.

### F. Pause And Resume

- [ ] Clicking pause stops recording real window titles.
- [ ] Paused state displays correctly.
- [ ] Resuming records the current window again.
- [ ] Tray state and UI state are consistent.

### G. Idle

- [ ] Reaching the idle threshold enters idle state.
- [ ] Idle does not continuously generate many short history records.
- [ ] User activity restores normal state.
- [ ] Idle records are handled in statistics and export according to README and architecture documentation.

### H. Abnormal Recovery

- [ ] Startup closes the previous abnormal-exit open record.
- [ ] Recovered record duration is not negative.
- [ ] Records that cannot be confirmed are marked as `error`.
- [ ] Records crossing midnight are handled under the correct report date.

### I. Basic UI Usability

- [ ] Overview shows total time, classified time, unclassified time, current activity, and recent projects.
- [ ] Clicking unclassified activity opens Time Details with the expected filter.
- [ ] Clicking a recent project locates the corresponding session.
- [ ] Time Details column widths, selection, copy, notes, and project correction work.
- [ ] Statistics/Export page statistics are reasonable.
- [ ] Settings/Privacy can show the privacy notice, toggle clipboard recording, and clear data.
- [ ] UI refresh does not visibly clear and rebuild the whole page.
- [ ] Minimize, restore, and resize do not crash the app.

### J. Excel Export

- [ ] A selected date range can be exported.
- [ ] Output is generated in `Documents\WorkTrace Exports` or a user-selected path.
- [ ] `Summary` sheet exists.
- [ ] `Activity Logs` sheet exists.
- [ ] Duration uses `hh:mm:ss`.
- [ ] Default filtering for `excluded`, `idle`, `paused`, `is_deleted`, and `is_hidden` matches the documentation.
- [ ] Exported file opens in Excel.

### K. Packaged Exe

- [ ] `dist\WorkTrace.exe` starts.
- [ ] First-run privacy notice works.
- [ ] `schema.sql` is bundled correctly.
- [ ] `open_files_helper` packaged path works.
- [ ] Tray exit works.
- [ ] Administrator privileges are not required.

### L. Installer

- [ ] `dist\WorkTrace-Setup.exe` runs.
- [ ] App installs to `%LOCALAPPDATA%\Programs\WorkTrace`.
- [ ] Current-user Start Menu shortcut is created.
- [ ] Administrator privileges are not required.
- [ ] App starts from the shortcut.
- [ ] Installation directory and local data can be deleted for cleanup.

## Release Blockers

- `pytest` fails.
- GitHub Actions fails.
- The app cannot start.
- Collection starts before the first-run privacy notice is accepted.
- Administrator privileges are required.
- Network, login, or cloud-sync dependencies appear.
- The app records screenshots, keyboard input, body content, browser history, cookies, or passwords.
- Exclusion rules leak real window titles or paths.
- Excel export is unusable.
- PyInstaller exe cannot start.
- Installer cannot install under normal user permissions.
- Database contains negative durations or duplicate open records.
- Tray exit fails and leaves a collector running.

## Release Record Template

- Date:
- Commit SHA:
- Windows version:
- Python version:
- Test result:
- Build result:
- Manual validation result:
- Known issues:
- Release decision: pass / blocked

## v0.2 Phase 1B Local Security Validation

This section validates the encrypted `.wtbackup` export/import introduced in Phase 1B of the v0.2 local security work. It is scoped to local encrypted backup only: no runtime field-level encryption, no SQLCipher, no network, no AI, no server, no payment, no license, no token, no subscription.

### Validation Environment

- Windows 10 or Windows 11 with a normal user account.
- Do not use administrator privileges.
- Prefer a clean or temporary Windows user profile.
- Validate the Python development run, the PyInstaller single-file exe, and the current-user installer.
- Before validation, these paths may be deleted:
  - `%LOCALAPPDATA%\WorkTrace`
  - `%LOCALAPPDATA%\Programs\WorkTrace`
  - `Documents\WorkTrace Exports`

### Automated Checklist

- [ ] `pytest` passes, including the Phase 1B encrypted backup tests.
- [ ] No new runtime dependency beyond the existing `cryptography` package.
- [ ] No new network dependency.
- [ ] No new administrator-permission requirement.

### Manual Validation Checklist

#### M. Encrypted Backup Export

- [ ] Start WorkTrace with a real local database that contains at least one project, one activity, one resource, one note, and one clipboard event.
- [ ] Open Settings/Privacy and find the Encrypted Backup section.
- [ ] Click "导出加密备份".
- [ ] Enter and confirm a backup passphrase.
- [ ] Choose an output path ending in `.wtbackup`.
- [ ] The `.wtbackup` file is created.
- [ ] The `.wtbackup` file does not contain the test project name in plaintext.
- [ ] The `.wtbackup` file does not contain the test window title in plaintext.
- [ ] The `.wtbackup` file does not contain the test file path in plaintext.
- [ ] The `.wtbackup` file does not contain the test note in plaintext.
- [ ] The `.wtbackup` file does not contain the test copied text in plaintext.
- [ ] The UI warns that the backup may include copied text.

#### N. Encrypted Backup Import

- [ ] Start WorkTrace on a clean profile.
- [ ] Open Settings/Privacy and click "导入加密备份".
- [ ] Enter the correct passphrase for the backup from section M.
- [ ] Confirm the replace-import warning.
- [ ] Import succeeds.
- [ ] Projects, activities, resources, notes, and clipboard events are restored.
- [ ] `folder_rule_file_index` is not imported and `folder_rule_index_state` is left in a rebuildable state.
- [ ] Enter a wrong passphrase for the same backup.
- [ ] Import fails with a generic "could not decrypt backup or wrong passphrase" message.
- [ ] The current database is unchanged.
- [ ] Corrupt the `.wtbackup` file (flip a byte in the ciphertext region).
- [ ] Import fails with a "backup file is invalid or corrupted" message.
- [ ] The current database is unchanged.
- [ ] Attempt to import a backup with an unsupported version.
- [ ] Import fails with a "backup version is not supported" message.
- [ ] The current database is unchanged.

#### O. Packaged Builds

- [ ] `dist\WorkTrace.exe` can export a `.wtbackup` file.
- [ ] `dist\WorkTrace.exe` can import a `.wtbackup` file with the correct passphrase.
- [ ] `dist\WorkTrace.exe` does not require administrator privileges for export or import.
- [ ] `dist\WorkTrace.exe` does not require network access for export or import.
- [ ] The installer-installed WorkTrace (`dist\WorkTrace-Setup.exe`) can export a `.wtbackup` file.
- [ ] The installer-installed WorkTrace can import a `.wtbackup` file with the correct passphrase.
- [ ] The installer-installed WorkTrace does not require administrator privileges for export or import.
- [ ] The installer-installed WorkTrace does not require network access for export or import.

#### P. Logging Hygiene

- [ ] Logs record only operation type, result, and exception type for encrypted backup operations.
- [ ] Logs do not contain the passphrase.
- [ ] Logs do not contain decrypted payload content.
- [ ] Logs do not contain window titles, paths, notes, or copied text from the backup.
- [ ] Logs do not contain the full ciphertext.

### Phase 1B Release Blockers

- `pytest` fails.
- A `.wtbackup` file contains plaintext project name, window title, file path, note, or copied text.
- A wrong passphrase damages the current database.
- A corrupted backup damages the current database.
- An unsupported version damages the current database.
- Replace import does not restore projects, activities, resources, notes, or clipboard events.
- `folder_rule_file_index` is imported instead of being left in a rebuildable state.
- The UI imports `worktrace.security.crypto`, `worktrace.security.kdf`, or `worktrace.security.backup_format` directly.
- PyInstaller exe cannot export or import a `.wtbackup` file.
- Installer-installed WorkTrace cannot export or import a `.wtbackup` file.
- Administrator privileges are required for export or import.
- Network access is required for export or import.
- Logs contain passphrase, decrypted payload, window title, path, note, copied text, or full ciphertext.

## v0.2 Phase 1B.1 Encrypted Import Safety Hardening

This section validates the Phase 1B.1 hardening of the encrypted backup import path. It ensures imports cannot conflict with concurrent collector writes and that logs do not record sensitive local paths.

### Automated Checklist

- [ ] `pytest` passes, including the Phase 1B.1 guard and logging tests.
- [ ] No new runtime dependency is introduced.
- [ ] No new network dependency.
- [ ] No new administrator-permission requirement.

### Manual Validation Checklist

#### Q. Import Guard During Active Recording

- [ ] Start WorkTrace with the collector actively recording.
- [ ] Open Settings/Privacy and start an encrypted backup import.
- [ ] During the import, no new `activity_log`, `activity_resource`, or `activity_clipboard_event` rows are created.
- [ ] No real window title or file path is stored during the import.
- [ ] After a successful import, `collector_status` is `paused` and `user_paused` is `true`.
- [ ] The user can manually resume recording from the tray or Settings after verifying the imported data.
- [ ] After resuming, the collector records normally.

#### R. Import Failure State Restoration

- [ ] Start an import with a wrong passphrase.
- [ ] The import fails with a generic "could not decrypt backup or wrong passphrase" message.
- [ ] `user_paused`, `collector_status`, and `current_activity_snapshot` are restored to their pre-import values.
- [ ] Database row counts are unchanged.
- [ ] `secure_import_in_progress` is `false` after the failure.
- [ ] Repeat with a corrupted backup; same restoration behavior.
- [ ] Repeat with an unsupported-version backup; same restoration behavior.

#### S. Concurrent Import Rejection

- [ ] While an import is in progress, attempt to start a second import.
- [ ] The second import is rejected with a clear error message.
- [ ] The first import is not interrupted.

#### T. Logging Hygiene

- [ ] Export success log does not contain the backup file path.
- [ ] Import success log does not contain the input file path.
- [ ] Failure logs do not contain the passphrase.
- [ ] Failure logs do not contain sensitive test marker strings (project name, window title, file path, note, copied text).
- [ ] Logs contain only operation name, result, exception type, table count, or boolean flags.

#### U. Packaged Builds

- [ ] `dist\WorkTrace.exe` exhibits the same guard behavior.
- [ ] The installer-installed WorkTrace exhibits the same guard behavior.
- [ ] Neither requires administrator privileges or network access for the guard behavior.

### Phase 1B.1 Release Blockers

- An import does not set `secure_import_in_progress` during DB replacement.
- An import does not clear `secure_import_in_progress` after success or failure.
- A successful import does not leave the app paused.
- A failed import does not restore the prior pause/status state.
- A failed import alters database row counts.
- An existing `secure_import_in_progress=true` does not reject a new import.
- The collector writes real activity rows while the guard is active.
- Export/import logs contain the backup path or sensitive content.
- The UI allows concurrent imports.
- PyInstaller exe or installer-installed WorkTrace does not exhibit the guard behavior.

## WebView Phase 1 Validation

This section is the validation framework for the WebView UI migration documented in [`docs/ui-webview-migration.md`](ui-webview-migration.md). Phase 1 is a destructive migration: the WebView UI is the default and only shipping UI. The legacy Tkinter / CustomTkinter UI under `worktrace/ui` is retained only as legacy code pending per-page migration and removal; it is not a supported runtime path and is not started by the default entry point.

Phase 1 makes `python -m worktrace.main` (and the packaged `WorkTrace.exe`) start the WebView UI directly. The legacy `--webview` flag is accepted as a no-op compatibility flag. When the WebView2 Runtime is missing on Windows, WorkTrace prints a clear install prompt and exits with a non-zero code; it does not auto-download the runtime and does not fall back to Tkinter.

This section is scoped to the default WebView entry point, the Overview page, the bridge, the runtime, and the packaging. It does not validate Timeline, Statistics/Export, Rules, or Settings pages (those remain on the legacy Tkinter code pending later phases). It does not introduce field-level encryption, SQLCipher, AI, server, payment, license, token, or subscription features.

### Automated Checklist

- [ ] `pytest` passes, including the `test_ui_backend_boundary.py` WebView boundary tests, `test_webview_bridge.py`, `test_webview_resources.py`, `test_webview_packaging.py`, and `test_webview_phase1_entry.py`.
- [ ] `pywebview>=5.0` is declared in `requirements.txt`.
- [ ] `worktrace/main.py` delegates to `worktrace.webview_main.main()` by default and does not import or instantiate `worktrace.ui.app.WorkTraceApp`.
- [ ] `worktrace/webview_ui/runtime_check.py` `missing_runtime_message()` does not contain the words `Tkinter`, `fallback`, or `继续使用默认`.
- [ ] No new network dependency.
- [ ] No new administrator-permission requirement.

### Validation Items

1. [ ] `python -m worktrace.main` starts the WebView UI (no `--webview` flag required).
2. [ ] `python -m worktrace.main --webview` behaves identically to `python -m worktrace.main` (no-op compatibility flag).
3. [ ] WebView frontend resources do not contain `http://` or `https://` external links.
4. [ ] The WebView bridge does not import `worktrace.services`, `worktrace.db`, `worktrace.collector`, `worktrace.security`, `worktrace.runtime`, or `worktrace.config`.
5. [ ] Closing the WebView window triggers `AppRuntime.shutdown` and leaves no collector thread, folder-index worker, or database lock resident.
6. [ ] The PyInstaller build passes with the WebView entry point and resources bundled.
7. [ ] The per-user installer build passes and installs without administrator privileges.
8. [ ] The packaged `dist\WorkTrace.exe` defaults to the WebView UI and starts normally.
9. [ ] When WebView2 Runtime is missing, WorkTrace shows a clear install prompt and exits with a non-zero code; it does not fall back to Tkinter.
10. [ ] When `pywebview` is missing, WorkTrace shows a clear install prompt and exits with a non-zero code; it does not fall back to Tkinter.

### Manual Validation Checklist

#### V. WebView Shell Startup (Phase 1)

- [ ] Run `python -m worktrace.main` from the source tree.
- [ ] A WorkTrace window opens showing the Overview page.
- [ ] The sidebar shows collector status (记录中 / 已暂停 / 采集器未运行 / 状态异常).
- [ ] The pause/resume button toggles the status label.
- [ ] The Overview page shows today's date.
- [ ] The Overview page shows today's total duration.
- [ ] The Overview page shows today's classified duration.
- [ ] The Overview page shows today's uncategorized duration.
- [ ] The Overview page shows today's project count.
- [ ] The Overview page shows the current activity summary or "当前活动：无".
- [ ] The Overview page shows up to 20 recent sessions with project name, time range, status, and duration.
- [ ] The Overview page shows an in-page error banner when a bridge call fails, without exposing a Python traceback.
- [ ] The page auto-refreshes every 8 seconds without manual interaction.
- [ ] Clicking 时间详情, 统计与导出, 项目规则, 设置与隐私 shows the migration placeholder.
- [ ] Clicking 概览 returns to the Overview page.

#### W. WebView Window Close And Runtime Shutdown (Phase 1)

- [ ] Start `python -m worktrace.main` and let the collector run for a few seconds.
- [ ] Close the WebView window.
- [ ] The process exits cleanly (no lingering Python process in Task Manager).
- [ ] The collector thread is joined (no `WorkTraceCollector` thread resident).
- [ ] The single-instance lock is released (a second launch can acquire it).
- [ ] The `collector_status` setting is `stopped` after exit.
- [ ] No `activity_log` row has `end_time IS NULL` after a clean exit.

#### X. Phase 1 Source Run Validation

- [ ] `python -m worktrace.main` starts the WebView UI (default, no flag).
- [ ] `python -m worktrace.main --webview` also starts the WebView UI (no-op compat flag).
- [ ] On a machine without WebView2 Runtime, `python -m worktrace.main` prints the clear missing-runtime message and exits with code 2; no Tkinter UI is started.

#### Y. Phase 1 PyInstaller Build Validation

- [ ] `python -m PyInstaller --noconfirm --clean WorkTrace.spec` completes without error.
- [ ] `dist\WorkTrace.exe` exists.
- [ ] `dist\WorkTrace.exe` (no args) starts the WebView UI.
- [ ] `dist\WorkTrace.exe --webview` also starts the WebView UI (no-op compat flag).
- [ ] The bundle includes `worktrace/webview_ui/index.html`, `app.js`, `styles.css` (verified by build success and runtime resource resolution).

#### Z. Phase 1 Installer Build Validation

- [ ] `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1` completes without error.
- [ ] The standard installer command above passes directly, without bypassing the script or running an equivalent PyInstaller command by hand.
- [ ] `dist\WorkTrace-Setup.exe` exists.
- [ ] Installing with `WorkTrace-Setup.exe` does not prompt for administrator privileges (per-user install to `%LOCALAPPDATA%\Programs\WorkTrace`).
- [ ] The Start Menu shortcut launches the WebView UI by default.
- [ ] The installer does not download the WebView2 Runtime.

> Phase 0C.1 fixed the installer script's stderr handling. Under
> `$ErrorActionPreference = "Stop"`, PyInstaller's stderr INFO logs were
> previously wrapped as `NativeCommandError`, which falsely terminated the
> script even when PyInstaller exited 0. The script now locally relaxes the
> preference around the native call, still checks `$LASTEXITCODE`, and still
> throws on non-zero exit codes. The standard command must now pass directly.

#### AA. Phase 1 WebView2 Runtime Missing Handling

- [ ] On a Windows machine without the WebView2 Runtime, `python -m worktrace.main` shows the message: "WorkTrace 需要 Microsoft Edge WebView2 Runtime 才能启动，但未检测到该运行时。请从 Microsoft 官方渠道下载并安装 Microsoft Edge WebView2 Runtime，然后重新启动 WorkTrace。"
- [ ] The process exits with a non-zero code.
- [ ] No Python traceback is shown to the user.
- [ ] No Tkinter UI is started. WorkTrace does not fall back to the legacy UI.
- [ ] The same behavior holds for `dist\WorkTrace.exe` (no args).

#### AB. Phase 1 Post-Close Residual Validation

- [ ] After closing `WorkTrace.exe`, no `WorkTrace.exe` process remains in Task Manager.
- [ ] No database lock file remains.
- [ ] A second launch of `WorkTrace.exe` succeeds (single-instance lock released).

### Phase 1 Release Blockers

- `python -m worktrace.main` does not start the WebView UI by default.
- `python -m worktrace.main` imports or instantiates `worktrace.ui.app.WorkTraceApp` on the default path.
- `--webview` changes behavior (e.g. only `--webview` starts the WebView UI).
- WorkTrace falls back to the Tkinter UI when the WebView2 Runtime is missing or when `pywebview` is missing.
- The missing-runtime message contains the words `Tkinter`, `fallback`, or `继续使用默认`.
- The WebView bridge imports `worktrace.services`, `worktrace.db`, `worktrace.collector`, `worktrace.security`, `worktrace.runtime`, or `worktrace.config`.
- WebView frontend resources contain `http://`, `https://`, CDN, or Google Fonts references.
- The frontend stores sensitive data in `localStorage` or `sessionStorage`.
- The bridge returns tracebacks to JS.
- The bridge logs window titles, file paths, notes, or copied text.
- Closing the WebView window leaves the collector thread or database lock resident.
- PyInstaller cannot bundle the WebView entry point and resources.
- The per-user installer requires administrator privileges.
- WebView2 Runtime is missing and WorkTrace fails with no clear error, or auto-downloads the runtime.
- A new network dependency or administrator-permission requirement is introduced.

## WebView Phase 2 Validation

This section is the validation framework for the Timeline read-only migration.
Phase 2 migrates the Timeline / Time Details page as a read-only page: date
navigation, session list, per-session activity details, current activity
summary, daily total duration, empty/loading/error states, and auto-refresh.
No editing, correction, reclassification, note modification, or deletion is
exposed. The WebView-only / no Tkinter fallback principles from Phase 1
remain in effect.

### Automated Checklist

- [ ] `pytest` passes, including the Timeline bridge tests in
  `test_webview_bridge.py` and the Timeline frontend tests in
  `test_webview_resources.py`.
- [ ] `worktrace.webview_ui.bridge` still does not import
  `worktrace.services`, `worktrace.db`, `worktrace.collector`,
  `worktrace.security`, `worktrace.runtime`, or `worktrace.config`.
- [ ] `get_timeline` and `get_timeline_session_details` return
  JSON-serializable dicts.
- [ ] Bridge errors return `{"ok": false, "error": "操作失败"}` without
  tracebacks.
- [ ] The Timeline page in `index.html` is not a placeholder.
- [ ] `app.js` contains no edit/correction/delete/reclassify/note handlers.
- [ ] Frontend resources contain no `http://`, `https://`, CDN, Google
  Fonts, or `localStorage`/`sessionStorage` references.

### Validation Items

1. [ ] `bridge.get_timeline(date)` returns `ok`, `date`, `total_duration`,
   `current_activity`, and `sessions`.
2. [ ] Each session in the `sessions` list has `session_id`, `project_name`,
   `start_time`, `end_time`, `duration`, `status`, `event_count`,
   `is_uncategorized`, and `activity_ids`.
3. [ ] `bridge.get_timeline_session_details(activity_ids, date)` returns
   `ok` and `activities`.
4. [ ] Each activity in the `activities` list has `start_time`, `end_time`,
   `duration`, `app_name`, `resource_type`, `resource_name`, `project_name`,
   and `status`.
5. [ ] Neither bridge method returns `window_title`, `file_path_hint`,
   `note`, or `traceback` in its output.
6. [ ] `python -m worktrace.main` still defaults to the WebView UI (Phase 1
   invariant preserved).
7. [ ] The Timeline page in `index.html` has date navigation buttons, a
   sessions list container, a details list container, an error banner, a
   loading indicator, and an empty-state element.
8. [ ] The Statistics, Rules, and Settings pages still show the migration
   placeholder.

### Manual Validation Checklist

#### AC. Timeline Page Navigation And Display (Phase 2)

- [ ] Run `python -m worktrace.main` and click 时间详情 in the sidebar.
- [ ] The Timeline page loads and shows today's date.
- [ ] The Timeline page shows the daily total duration.
- [ ] The Timeline page shows the current activity summary or `当前活动：无`.
- [ ] The session list shows project sessions with project name, time range,
  duration, status, and event count.
- [ ] Clicking a session loads its activity details in the detail panel.
- [ ] Activity details show time range, resource name, resource type, app
  name, project name, and duration.
- [ ] Clicking the `今日` button returns to today's data.
- [ ] Clicking `<` loads the previous day; clicking `>` loads the next day.
- [ ] A day with no sessions shows the empty-state message.
- [ ] No edit, correction, reclassify, note, or delete buttons are present.

#### AD. Timeline Auto-Refresh (Phase 2)

- [ ] Stay on the Timeline page and wait 8 seconds.
- [ ] The Timeline data refreshes without full-page flicker.
- [ ] The selected session remains selected after auto-refresh.
- [ ] If the selected session's details are displayed, they also refresh.

#### AE. Timeline Error Handling (Phase 2)

- [ ] If a bridge call fails, the Timeline error banner shows a clear Chinese
  message.
- [ ] No Python traceback is shown in the UI.
- [ ] The error banner clears on the next successful refresh.

### Phase 2 Release Blockers

- The Timeline page in `index.html` is still a placeholder.
- `app.js` does not load or render Timeline data.
- `get_timeline` or `get_timeline_session_details` returns tracebacks or
  sensitive fields (`window_title`, `file_path_hint`, `note`).
- The Timeline page exposes any edit, correction, reclassify, note, or
  delete action.
- Auto-refresh does not refresh the Timeline when it is the active page.
- The selected session is lost after auto-refresh.
- The session list flickers visibly (full clear then rebuild) during refresh.
- The default entry point no longer starts the WebView UI.
- Any new network dependency, CDN reference, or browser storage usage is
  introduced.

## WebView Phase 2.1 Validation

This section is the validation framework for the Timeline read-only
validation hardening. Phase 2.1 does **not** introduce editing, correction,
reclassification, note modification, or deletion. It hardens the Phase 2
read-only page so that it is reliable, readable, secure, and maintainable
under real user use. The WebView-only / no Tkinter fallback principles from
Phase 1 remain in effect.

Phase 2.1 specifically:

- The bridge `resource_name` no longer falls back to the raw `window_title`
  column (which can contain file paths, URLs, or email subjects). It uses a
  safe chain: `resource_display_name` → `activity_display_name` →
  `app_name` → `process_name` → `"未知"`.
- The bridge passes through an explicit `is_in_progress` flag for
  sessions/activities. The timeline service sets this flag before
  projecting a display `end_time` for open activities, so the flag
  reflects the original open-activity state rather than the displayed
  (possibly projected) `end_time`. The frontend consumes this flag to
  mark open records distinctly.
- The frontend uses request tokens to prevent stale bridge responses from
  overwriting newer data when the user rapidly switches dates or sessions.
- The frontend preserves the selected session across auto-refresh and
  clears the selection gracefully if the session disappears.
- The frontend keeps the previously loaded data visible when a refresh
  fails, instead of clearing the page.
- Long resource/project names are truncated with safe tooltips; the layout
  remains usable on narrow viewports.
- Empty state, error state, and loading state are clearly differentiated.

### Automated Checklist

- [ ] `pytest` passes, including the Phase 2.1 tests in
  `test_webview_bridge.py` and `test_webview_resources.py`.
- [ ] `worktrace.webview_ui.bridge` still does not import
  `worktrace.services`, `worktrace.db`, `worktrace.collector`,
  `worktrace.security`, `worktrace.runtime`, or `worktrace.config`.
- [ ] `bridge.py` does not import `format_activity_display_name` (it falls
  back to the raw `window_title` column).
- [ ] `get_timeline` and `get_timeline_session_details` outputs do not
  contain `window_title`, `file_path_hint`, `note`, `clipboard`,
  `traceback`, `exception`, `stack`, or `full_path` at any level.
- [ ] `get_timeline` and `get_timeline_session_details` expose
  `is_in_progress` as an explicit flag passed through from the timeline
  service (not inferred from the displayed `end_time`, which may be
  projected for open activities).
- [ ] `app.js` defines `timelineRequestToken` and `detailsRequestToken`
  guards against stale responses.
- [ ] `app.js` preserves the selected session across auto-refresh and
  clears it gracefully when the session disappears.
- [ ] `app.js` keeps the previously loaded data visible when a refresh
  fails (the `lastTimelineData` cache).
- [ ] `app.js` shows `进行中` for in-progress time ranges.
- [ ] `app.js` does not use `localStorage` or `sessionStorage`.
- [ ] Frontend resources contain no `http://`, `https://`, CDN, Google
  Fonts, or traceback display logic.

### Manual Validation Checklist

#### AF. Phase 2.1 Real-Run Acceptance

- [ ] Run `python -m worktrace.main` from the source tree.
- [ ] Run the packaged `dist\WorkTrace.exe` separately.
- [ ] Open the Overview page, confirm collector status, pause/resume, and
  today's total duration render normally.
- [ ] Open the Timeline page, confirm today's sessions render with project
  name, time range, duration, status, and event count.
- [ ] Wait 3–5 minutes with the collector running. Confirm the current
  activity and the in-progress session duration keep growing.
- [ ] Confirm the in-progress session is visually marked (blue tint) and
  its time range shows `HH:MM-进行中`.
- [ ] Click `<`, `今日`, `>` in sequence. Confirm each date loads the
  correct data; rapid clicking does not let an older response overwrite a
  newer date.
- [ ] Navigate to a date with no activity. Confirm the empty-state message
  `当日暂无活动记录` appears, with no JS error in the dev console.
- [ ] Navigate to a long resource name (e.g. a long browser title or long
  file name). Confirm the name is truncated with an ellipsis, the layout
  is not stretched, and hovering shows the safe display name tooltip
  (never a full file path or raw window title).
- [ ] Click a session, wait for auto-refresh. Confirm the selected session
  remains selected and its details refresh in place without flicker.
- [ ] While a session is selected, force a bridge error (e.g. temporarily
  rename the database file). Confirm the error banner appears, the prior
  data remains visible, and no traceback is shown. Restore the database
  file and confirm the next refresh succeeds.
- [ ] Close WorkTrace and restart. Confirm historical sessions from the
  previous run still appear on the Timeline page.
- [ ] On a machine without WebView2 Runtime, confirm `python -m
  worktrace.main` still only prints the install prompt and exits with a
  non-zero code; no Tkinter UI is started.
- [ ] Inspect `%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`. Confirm the
  log does not contain window titles, full file paths, notes, clipboard
  text, or tracebacks.

#### AG. Phase 2.1 Privacy Boundary

- [ ] Inspect the JSON returned by `bridge.get_timeline_session_details`
  for an activity whose raw row has `window_title`, `file_path_hint`,
  and `note` populated. Confirm none of those fields appear in the
  bridge output at any level.
- [ ] Confirm `resource_name` is the sanitized basename / display name,
  not the raw window title.
- [ ] Confirm `index.html`, `app.js`, and `styles.css` contain no
  `http://`, `https://`, CDN, Google Fonts, or `localStorage` /
  `sessionStorage` references.
- [ ] Confirm `app.js` contains no code that parses or displays a Python
  traceback.

### Phase 2.1 Release Blockers

- The bridge `resource_name` falls back to the raw `window_title` column
  for any activity.
- `get_timeline` or `get_timeline_session_details` output contains
  `window_title`, `file_path_hint`, `note`, `clipboard`, `traceback`,
  `exception`, `stack`, or `full_path` at any level.
- `bridge.py` imports `format_activity_display_name` (the unsafe helper).
- `bridge.py` imports `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.security`, `worktrace.runtime`, or
  `worktrace.config` directly.
- `app.js` lacks request token guards, so rapid date switching lets a
  stale response overwrite newer data.
- `app.js` clears the page on refresh failure instead of keeping the
  prior data visible.
- `app.js` loses the selected session on every auto-refresh.
- `app.js` shows `HH:MM-` (empty end) for in-progress sessions instead
  of a clear `进行中` label.
- The Timeline page exposes any edit, correction, reclassify, note, or
  delete action.
- The default entry point no longer starts the WebView UI, or a Tkinter
  fallback is restored.
- Any new network dependency, CDN reference, Google Fonts reference, or
  browser storage usage is introduced.
- The frontend displays a Python traceback anywhere.

## WebView Phase 3A Validation

Phase 3A adds minimal write capability to the Timeline page: project
reclassification and session-note editing. It does **not** implement time
editing, session split/merge, deletion, batch editing, auto-rule creation,
or a complex correction page.

Phase 3A specifically:

- Adds `reclassify_timeline_session_project` and
  `update_timeline_session_note` to `worktrace.api.timeline_api` with
  explicit input validation (non-empty activity_ids, existence checks,
  project_id existence, date format, note length ≤ 2000).
- Adds `list_projects_for_timeline`, `update_timeline_project`, and
  `update_timeline_note` to `worktrace.webview_ui.bridge.WebViewBridge`.
  The bridge validates input, calls the API, and returns generic errors
  without tracebacks or sensitive raw fields.
- Adds an edit panel to the Timeline details area with a project
  `<select>`, a note `<textarea>` with character counter, and save/cancel
  buttons with saving/error/success states.
- On save success, the Timeline refreshes locally (preserving the current
  date and selected session if possible). On save failure, the original
  data is preserved and a Chinese error is shown.
- The bridge still imports only `worktrace.api` and `worktrace.formatters`.
- The frontend still uses no CDN, no external links, no Google Fonts, no
  `localStorage`/`sessionStorage`, and no traceback display.

### Automated Checklist

- [ ] `pytest` passes, including the Phase 3A tests in
      `tests/test_timeline_api_editing.py`,
      `tests/test_webview_bridge_editing.py`, and the updated
      `tests/test_webview_resources.py`.
- [ ] No new runtime dependency is introduced.
- [ ] No new network dependency.
- [ ] No new administrator-permission requirement.
- [ ] No new DB schema (Phase 3A reuses `activity_project_assignment`,
      `activity_log`, and `project_session_note`).

### Validation Items

- [ ] `reclassify_timeline_session_project` validates `activity_ids`
      (non-empty, positive ints, existence, deduplication) and
      `project_id` (positive int, existence).
- [ ] `update_timeline_session_note` validates `report_date`
      (`YYYY-MM-DD`), `first_activity_id` (positive int, existence), and
      `note` (string, length ≤ 2000).
- [ ] `list_projects_for_timeline` returns a JSON-serializable list
      including the "未归类" system project, with only `id`/`name`/
      `description` fields.
- [ ] `update_timeline_project` and `update_timeline_note` return
      `{"ok": true}` on success and `{"ok": false, "error": "..."}`
      on failure.
- [ ] Bridge errors never include tracebacks, exception class names, SQL
      errors, file paths, window titles, clipboard content, or the note's
      old value.
- [ ] The edit panel has a project `<select>`, a note `<textarea>` with
      character counter, and save/cancel buttons.
- [ ] The edit panel does not contain time editing, split, merge, delete,
      batch edit, or auto-rule UI.
- [ ] `app.js` tracks a saving state (`editSaving`, `setEditSaving`,
      `保存中…`).
- [ ] `app.js` preserves original data on save failure and shows a
      Chinese error.
- [ ] `app.js` refreshes the Timeline on save success.
- [ ] Frontend resources still contain no CDN, external links, Google
      Fonts, `localStorage`/`sessionStorage`, or traceback display logic.

### Manual Validation Checklist

#### AH. Phase 3A Project Reclassification

- [ ] Start WorkTrace with a database that contains at least two projects
      and several activities on the current day.
- [ ] Open the Timeline page.
- [ ] Select a session in the session list.
- [ ] The edit panel appears below the activity details.
- [ ] The project `<select>` shows the current project and all selectable
      projects including "未归类".
- [ ] Change the project to a different project.
- [ ] Click "保存".
- [ ] The button shows "保存中…" then the Timeline refreshes.
- [ ] The session list shows the new project name.
- [ ] The session may have regrouped (merged with another session for the
      same project) or the `session_id` may have disappeared; the selection
      clears gracefully if so.
- [ ] Change the project to "未归类".
- [ ] Click "保存".
- [ ] The session now shows "未归类" as the project name.

#### AI. Phase 3A Session Note Editing

- [ ] Select a session in the Timeline.
- [ ] The note `<textarea>` shows the existing note (empty if none).
- [ ] The character counter shows `0 / 2000` (or the current length).
- [ ] Type a note with multiple lines.
- [ ] The character counter updates as you type.
- [ ] Click "保存".
- [ ] The button shows "保存中…" then a success message appears.
- [ ] The Timeline refreshes and the note is persisted.
- [ ] Select the same session again; the note `<textarea>` shows the saved
      note with newlines preserved.
- [ ] Clear the note (or enter whitespace only) and save.
- [ ] The note is deleted (the `<textarea>` is empty on reload).

#### AJ. Phase 3A Save Failure Handling

- [ ] Select a session and modify the note.
- [ ] Simulate a bridge error (e.g. by stopping the collector or corrupting
      the database connection if possible in a test env).
- [ ] Click "保存".
- [ ] An error message appears in the edit status area.
- [ ] The original data is still in the form (not cleared).
- [ ] The UI is not stuck in "保存中…" state.
- [ ] No traceback, SQL error, file path, or window title is shown.

#### AK. Phase 3A Privacy Boundary

- [ ] The edit panel only shows the project select and note textarea.
- [ ] No raw `window_title`, `file_path_hint`, `clipboard`, or `full_path`
      appears in the edit panel or any bridge return value.
- [ ] The note `<textarea>` only shows the user-authored session note, not
      captured activity notes or other metadata.
- [ ] Logs do not contain the note content, resource names, full paths, or
      window titles.

### Phase 3A Release Blockers

- `pytest` fails.
- The bridge `update_timeline_project` or `update_timeline_note` returns
  a traceback, exception class name, SQL error, file path, window title,
  clipboard content, or the note's old value on any error path.
- `bridge.py` imports `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.security`, `worktrace.runtime`, or
  `worktrace.config` directly.
- The API layer performs a partial write (some activities reclassified,
  others not) when one activity_id is invalid.
- The API layer accepts a nonexistent `project_id` or `activity_id`.
- The API layer accepts a note longer than 2000 characters.
- The edit panel exposes time editing, split, merge, delete, batch edit,
  or auto-rule creation UI.
- The frontend allows free-form `project_id` input instead of selecting
  from the bridge-returned project list.
- `app.js` clears the form on save failure instead of preserving the
  original data.
- `app.js` gets stuck in the "保存中…" state after a save failure.
- The frontend introduces any new network dependency, CDN reference,
  Google Fonts reference, or browser storage usage.
- The default entry point no longer starts the WebView UI, or a Tkinter
  fallback is restored.
- Any new DB schema is introduced without justification, idempotent
  migration, and tests.

## WebView Phase 3A.1 Validation

Phase 3A.1 is a hardening phase. It adds **no new features**. It
validates that the Phase 3A basic editing path is more stable, safer,
and clearer under real use after the hardening changes.

### Automated Checklist

- [ ] `pytest` passes, including the Phase 3A.1 hardening tests.
- [ ] No new runtime dependency is introduced.
- [ ] No new network dependency.
- [ ] No new administrator-permission requirement.
- [ ] No new DB schema.

### Validation Items

#### AL. API Input Validation Hardening

- [ ] `reclassify_timeline_session_project` rejects `bool` inputs for
  `activity_ids` (the list itself), `project_id`, and individual
  activity id elements.
- [ ] `update_timeline_session_note` rejects `bool` for
  `first_activity_id`.
- [ ] The API never performs a partial write when one activity_id is
  missing or deleted.
- [ ] The API still rejects nonexistent `project_id`, nonexistent
  `activity_id`, notes longer than 2000 characters, and malformed
  `report_date`.

#### AM. Bridge Input Validation Hardening

- [ ] `_coerce_activity_ids` rejects `bool` elements.
- [ ] `update_timeline_project` rejects `bool` for `project_id`.
- [ ] `update_timeline_note` returns `"日期无效"` for a malformed
  `report_date` (not the generic `"操作失败"`).
- [ ] Bridge errors still never include tracebacks, exception class
  names, SQL errors, file paths, window titles, clipboard content, or
  the note's old value.
- [ ] `bridge.py` still imports only `worktrace.api` and
  `worktrace.formatters`.

#### AN. Frontend Save-State Hardening

- [ ] On save success, `editingSession.project_id` and
  `editingSession.session_note` are updated to the saved values so the
  dirty state clears.
- [ ] After save success, Cancel reverts to the saved values (not the
  pre-save values).
- [ ] After save success, an auto-refresh repopulates the edit panel
  with the new server-returned baseline.
- [ ] `updateNoteCount` disables the save button when the note exceeds
  2000 characters.
- [ ] `updateNoteCount` applies a red `edit-note-count-over` class when
  the note exceeds 2000 characters.
- [ ] `setEditSaving(false)` re-applies the note-length guard.
- [ ] `populateEditPanel` calls `updateNoteCount` after enabling the
  save button so the length check has the final say.

#### AO. Frontend Privacy And Boundary Regression

- [ ] `app.js` still uses no `localStorage` or `sessionStorage`.
- [ ] `app.js` still contains no `http://` or `https://` links.
- [ ] `app.js` still references no CDN or Google Fonts.
- [ ] `app.js` still exposes no traceback display logic.
- [ ] The edit panel still exposes no time editing, split, merge,
  delete, batch edit, or auto-rule UI.
- [ ] The default entry point still starts the WebView UI with no
  Tkinter fallback.

### Phase 3A.1 Release Blockers

- `pytest` fails.
- The API accepts `bool` for `activity_ids`, `project_id`, or
  `first_activity_id` (silently coercing `True` to `1`).
- The bridge accepts `bool` for `project_id` or `activity_ids` elements.
- `update_timeline_note` returns the generic `"操作失败"` for a malformed
  `report_date` instead of the clearer `"日期无效"`.
- `app.js` does not update the `editingSession` baseline on save
  success, causing Cancel to revert to pre-save values.
- `updateNoteCount` does not disable the save button when the note
  exceeds the 2000-character limit.
- The frontend introduces any new network dependency, CDN reference,
  Google Fonts reference, or browser storage usage.
- The edit panel exposes time editing, split, merge, delete, batch edit,
  or auto-rule creation UI.
- The default entry point no longer starts the WebView UI, or a Tkinter
  fallback is restored.
- Any new DB schema is introduced.

## WebView Phase 3B.1 Validation

Phase 3B.1 implements the **Timeline time correction foundation** — the
minimal usable time-correction capability for the WebView Timeline. It
adds single-activity `start_time` / `end_time` editing, single-activity
session-level time correction, strict time validation, post-save
Timeline refresh, and independent saving states. It does **not** add
multi-activity session whole-time correction, split, merge, deletion,
batch editing, auto-rule creation, or complex correction pages.

### Automated Checklist

| Check | Command |
|-------|---------|
| Full test suite | `python -m pytest` |
| PyInstaller build | `python -m PyInstaller --noconfirm --clean WorkTrace.spec` |

### Validation Items

#### AP. API Time Correction

- `update_timeline_activity_time` rejects non-positive `activity_id`,
  `bool` `activity_id`, nonexistent `activity_id`, deleted activity,
  non-string time, bad time format, `start_time >= end_time`, and
  in-progress activities.
- `update_timeline_activity_time` succeeds for valid inputs and
  recomputes `duration_seconds`.
- `update_timeline_session_time` succeeds for single-activity sessions
  and raises `TimelineTimeEditError("multi_activity")` for multi-activity
  sessions.
- Cross-day activity modification is correctly projected by
  `timeline_service` onto both `report_date`s.
- No partial writes occur on validation failure.

#### AQ. Bridge Time Correction

- `update_timeline_activity_time` and `update_timeline_session_time`
  return `{"ok": true}` on success.
- Invalid inputs return `{"ok": false, "error": "<chinese message>"}`.
- Multi-activity sessions return `"多活动 session 暂不支持整体时间修改"`.
- In-progress activities return `"进行中记录暂不支持时间修正"`.
- Malformed time returns `"时间无效"`.
- Error results do not contain tracebacks, SQL errors, file paths,
  window titles, or clipboard data.
- The bridge does not import `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.runtime`, `worktrace.security`, or
  `worktrace.config`.

#### AR. Frontend Time Correction

- `index.html` has a time-correction section with `datetime-local`
  inputs and a save button.
- `app.js` calls `update_timeline_activity_time` and
  `update_timeline_session_time` bridge methods.
- `app.js` has `backendToDatetimeLocal` / `datetimeLocalToBackend`
  conversion helpers using fixed-format string replacement.
- `app.js` has independent saving states (`timeSaving`,
  `activityTimeSaving`, `editSaving`).
- `app.js` refreshes the Timeline after a successful time save.
- `app.js` preserves user input on save failure.
- `app.js` disables / prompts in-progress activity time correction.
- `app.js` disables multi-activity session whole-time correction.
- `app.js` does not contain split / merge / delete / batch / auto-rule
  handlers.
- Frontend resources have no CDN, external links, Google Fonts, or
  browser storage usage.
- Frontend resources do not contain traceback display logic.

#### AS. Privacy And Boundary Regression

- Overview tests continue to pass.
- Timeline read-only tests continue to pass.
- Phase 2.1 privacy boundary tests continue to pass.
- Phase 3A / 3A.1 basic editing tests continue to pass.
- Default WebView entry tests continue to pass.
- PyInstaller resource path tests continue to pass.

### Phase 3B.1 Release Blockers

- `pytest` fails.
- The API accepts `bool` for `activity_id` (silently coercing `True` to
  `1`).
- The API allows editing a deleted or in-progress activity.
- `duration_seconds` is not recomputed after a time correction.
- Multi-activity session whole-time correction is performed instead of
  rejected.
- The bridge exposes tracebacks, SQL errors, file paths, window titles,
  or clipboard data in error results.
- The bridge imports `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.runtime`, `worktrace.security`, or
  `worktrace.config`.
- The frontend introduces split, merge, delete, batch edit, or
  auto-rule creation UI.
- The frontend uses browser storage, external links, CDN, or Google
  Fonts.
- The default entry point no longer starts the WebView UI, or a Tkinter
  fallback is restored.
- Any new DB schema is introduced.

## WebView Phase 3B.1.1 Validation

Phase 3B.1.1 is a **hardening phase** for the Phase 3B.1 time-correction
path. It adds no new features. It strengthens the service-layer write
(rowcount check), the API-layer error handling (race-condition mapping),
and the frontend saving-state lifecycle (session-time save button no
longer stuck disabled; save flows fully decoupled).

### Automated Checklist

| Check | Command |
|-------|---------|
| Full test suite | `python -m pytest` |
| PyInstaller build | `python -m PyInstaller --noconfirm --clean WorkTrace.spec` |

### Validation Items

#### AT. Service Layer Race-Condition Guard

- `activity_service.update_activity_time` raises `ValueError` when the
  UPDATE affects 0 rows (activity deleted or reopened between validation
  and write).
- The UPDATE still includes `WHERE is_deleted = 0 AND end_time IS NOT
  NULL` as a defensive guard.

#### AU. API Layer Race-Condition Mapping

- `update_timeline_activity_time` catches the service-layer `ValueError`
  and raises `TimelineTimeEditError("invalid_id")`.
- `update_timeline_session_time` does the same.
- No silent success when 0 rows are written.

#### AV. Frontend Saving-State Hardening

- `saveSessionTime` resets `timeSaving` on success (button re-enabled).
- `refreshTimelineAfterEdit` does not call `setEditSaving` (decoupled).
- `saveEdit` resets `editSaving` on success before refresh.
- `saveActivityTime` resets `activityTimeSaving` on success before
  refresh (unchanged from Phase 3B.1, verified).

#### AW. Regression

- Overview tests continue to pass.
- Timeline read-only tests continue to pass.
- Phase 2.1 privacy boundary tests continue to pass.
- Phase 3A / 3A.1 basic editing tests continue to pass.
- Phase 3B.1 time-correction tests continue to pass.
- Default WebView entry tests continue to pass.
- PyInstaller resource path tests continue to pass.

### Phase 3B.1.1 Release Blockers

- `pytest` fails.
- `update_activity_time` silently succeeds when 0 rows are updated.
- `saveSessionTime` leaves the save button disabled after success.
- `refreshTimelineAfterEdit` resets `editSaving` (coupling between save
  flows).
- Any new DB schema is introduced.
- Any new feature (split, merge, delete, batch, auto-rule, complex
  correction page, overlap detection) is introduced.

## WebView Phase 3B.2 Validation

Phase 3B.2 implements the **Timeline activity split foundation** — the
minimal usable single-activity split capability for the WebView Timeline.
It adds the ability to split a single closed activity at a user-supplied
split point into two closed activities, with precise `duration_seconds`
recomputation, project/resource inheritance, atomic transaction safety,
and post-save Timeline refresh. It does **not** add multi-activity
session whole-split, merge, delete/hide, batch editing, auto-rule
creation, complex correction pages, or overlap detection.

### Automated Checklist

| Check | Command |
|-------|---------|
| Full test suite | `python -m pytest` |
| PyInstaller build | `python -m PyInstaller --noconfirm --clean WorkTrace.spec` |

### Validation Items

#### AX. API / Service Split

- `split_timeline_activity` rejects non-positive `activity_id`, `bool`
  `activity_id`, nonexistent `activity_id`, deleted activity, and
  in-progress activities.
- `split_timeline_activity` rejects non-string `split_time`, missing
  seconds, `T` separator, timezone suffix, `split_time <= start_time`,
  and `split_time >= end_time`.
- `split_timeline_activity` succeeds for valid inputs: original activity
  keeps its id and becomes `[start, split_time)`; new activity becomes
  `[split_time, end)` with a new id.
- Both `duration_seconds` are precisely recomputed and sum to the
  original duration.
- The new activity inherits `app_name`, `process_name`, `window_title`,
  `file_path_hint`, `status`, `source`, `is_hidden`, `auto_classified`,
  `manual_override`, `project_id`. The `note` field is **not** copied.
- `activity_project_assignment` rows (manual and auto) are copied to
  the new activity id.
- `activity_resource` rows are copied to the new activity id.
- `project_session_note` is **not** auto-copied to the new back-half
  activity.
- `split_timeline_session` succeeds for single-activity sessions and
  raises `TimelineSplitError("multi_activity")` for multi-activity
  sessions.
- Cross-day activity split is correctly projected by `timeline_service`
  onto both `report_date`s.
- No partial writes occur on validation failure: if any step fails the
  transaction rolls back and the original activity is unchanged.
- Race-condition (0 rows updated) raises `ValueError` at the service
  layer and `TimelineSplitError("operation_failed")` at the API layer;
  no new activity is inserted.

#### AY. Bridge Split

- `split_timeline_activity` and `split_timeline_session` return
  `{"ok": true, "original_activity_id": int, "new_activity_id": int}`
  on success.
- Invalid `activity_id` (non-int, bool, nonexistent) returns
  `{"ok": false, "error": "操作失败"}`.
- Invalid `split_time` (non-string, empty, wrong shape, `T` separator)
  returns `{"ok": false, "error": "拆分时间无效"}`.
- `split_time` outside `[start_time, end_time)` returns
  `{"ok": false, "error": "拆分时间无效"}`.
- In-progress activities return
  `{"ok": false, "error": "进行中记录暂不支持拆分"}`.
- Multi-activity sessions return
  `{"ok": false, "error": "多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动"}`.
- Error results do not contain tracebacks, SQL errors, file paths,
  window titles, clipboard data, or notes.
- The bridge does not import `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.runtime`, `worktrace.security`, or
  `worktrace.config`.

#### AZ. Frontend Split

- `index.html` has a split section (`edit-split-section`) with a
  `datetime-local` input and a split button.
- `app.js` calls `split_timeline_activity` and `split_timeline_session`
  bridge methods.
- `app.js` has independent split saving states (`sessionSplitSaving`,
  `activitySplitSaving`).
- `app.js` refreshes the Timeline after a successful split save.
- `app.js` resets the saving state before refreshing.
- `app.js` preserves user input on split save failure.
- `app.js` disables multi-activity session whole-split with a clear
  Chinese hint.
- `app.js` disables or prompts in-progress activity split.
- `app.js` does not use JS `Date` string parsing for split-time
  conversion (uses fixed-format string replacement or `Date.UTC`).
- `app.js` does not contain merge / delete / batch / auto-rule
  handlers.
- `app.js` has no traceback display logic.
- `isEditDirty` covers split inputs so auto-refresh does not overwrite
  unsaved split edits.
- `styles.css` covers split UI and narrow-viewport responsive layout.
- Frontend resources have no CDN, external links, Google Fonts, or
  browser storage usage.

#### BA. Privacy And Boundary Regression

- Overview tests continue to pass.
- Timeline read-only tests continue to pass.
- Phase 2.1 privacy boundary tests continue to pass.
- Phase 3A / 3A.1 basic editing tests continue to pass.
- Phase 3B.1 / 3B.1.1 time-correction tests continue to pass.
- Default WebView entry tests continue to pass.
- PyInstaller resource path tests continue to pass.

### Phase 3B.2 Release Blockers

- `pytest` fails.
- The API accepts `bool` for `activity_id` (silently coercing `True` to
  `1`).
- The API allows splitting a deleted or in-progress activity.
- `duration_seconds` is not recomputed after a split.
- The two durations do not sum to the original duration.
- The new activity does not inherit the original project assignment or
  resource association.
- The split is not atomic: a failure leaves the original activity
  modified or a half-split new activity persisted.
- Multi-activity session whole-split is performed instead of rejected.
- The bridge exposes tracebacks, SQL errors, file paths, window titles,
  clipboard data, or notes in error results.
- The bridge imports `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.runtime`, `worktrace.security`, or
  `worktrace.config`.
- The frontend introduces merge, delete, batch edit, or auto-rule
  creation UI.
- The frontend uses browser storage, external links, CDN, or Google
  Fonts.
- The frontend uses `new Date(string)` parsing for split-time
  conversion.
- The default entry point no longer starts the WebView UI, or a Tkinter
  fallback is restored.
- Any new DB schema is introduced.

## WebView Phase 3B.2.1 Validation

Phase 3B.2.1 is a **hardening phase** for the Phase 3B.2 activity split.
It adds no new features. It strengthens the split write path with a
defensive ``lastrowid`` guard, clarifies the ``created_at`` /
``updated_at`` inheritance semantics, fixes a docstring mismatch, and adds
explicit rollback tests for every write step inside the transaction.

### Automated Checklist

| Check | Command |
|-------|---------|
| Full test suite | `python -m pytest` |
| PyInstaller build | `python -m PyInstaller --noconfirm --clean WorkTrace.spec` |

### Validation Items

#### BB. Service Layer Hardening

- The ``lastrowid <= 0`` guard fires when the INSERT does not return a
  valid row id: the service raises ``ValueError``, the transaction rolls
  back, and the original activity is unchanged.
- If the INSERT statement raises (e.g. constraint error), the transaction
  rolls back: no new activity is persisted, and the original activity's
  ``end_time`` / ``duration_seconds`` are restored.
- If the assignment-copy INSERT raises, the transaction rolls back: no new
  activity or half-created assignment is persisted.
- If the resource-copy INSERT raises, the transaction rolls back: no new
  activity or half-created resource is persisted.
- The new activity's ``created_at`` reflects the write time (not the
  original's creation time); the original's ``created_at`` is untouched.
- If the original activity has no ``activity_project_assignment`` row, the
  split does not create a spurious assignment for the new activity.
- An automatic (non-manual) assignment is copied with ``is_manual=0`` and
  the original ``source`` preserved.

#### BC. API Layer Hardening

- The ``_validate_activity_id_for_split`` docstring accurately reflects
  that it checks existence and deleted state only; the in-progress check
  is performed in the caller after fetching the activity for range
  validation.
- No change to the stable error codes (``invalid_id``, ``invalid_time``,
  ``outside_range``, ``in_progress``, ``multi_activity``,
  ``operation_failed``).
- No change to the bridge error mapping.

#### BD. Regression

- All Phase 3B.2 split tests continue to pass.
- All Phase 3B.1 / 3B.1.1 time-correction tests continue to pass.
- All Phase 3A / 3A.1 editing tests continue to pass.
- All Phase 2.1 privacy boundary tests continue to pass.
- Overview and Timeline read-only tests continue to pass.
- Default WebView entry tests continue to pass.
- PyInstaller resource path tests continue to pass.

### Phase 3B.2.1 Release Blockers

- The ``lastrowid <= 0`` guard is missing or does not raise.
- A write-step failure (INSERT, assignment copy, resource copy) does not
  roll back the transaction.
- The new activity's ``created_at`` is copied from the original instead of
  using the write time.
- A spurious ``activity_project_assignment`` row is created for the new
  activity when the original had none.
- An auto assignment is copied with ``is_manual=1`` instead of
  ``is_manual=0``.
- Any Phase 3B.2 regression.
- Any new DB schema is introduced.

## WebView Phase 3B.3 Validation

Phase 3B.3 implements the **Timeline activity merge foundation** — the
minimal usable two-activity merge. Two closed, adjacent, same-project /
same-resource / same-status / same-source activities are merged into one.
The earlier activity keeps its id and start_time; its end_time is extended
to the later activity's end_time. The later activity is soft-deleted.

### Automated Checklist

| Check | Command |
|-------|---------|
| Full test suite | `python -m pytest` |
| PyInstaller build | `python -m PyInstaller --noconfirm --clean WorkTrace.spec` |

### Validation Items

#### BE. Service Layer

- ``merge_activities`` rejects the same id for both arguments.
- ``merge_activities`` rejects nonexistent or deleted activities.
- ``merge_activities`` rejects in-progress activities (raw DB
  ``end_time IS NULL``).
- The kept activity is the earlier one (by ``start_time``, then ``id``),
  regardless of argument order.
- The kept activity's ``start_time`` and ``created_at`` are unchanged.
- The kept activity's ``end_time`` is extended to the later activity's
  ``end_time``.
- The kept activity's ``duration_seconds`` is precisely recomputed as
  ``merged_end - kept_start`` in seconds.
- The kept activity's ``updated_at`` is refreshed.
- The later activity is soft-deleted (``is_deleted = 1``), not physically
  removed. Its row still exists in ``activity_log``.
- Different ``project_id`` is rejected.
- Different resource ``identity_key`` is rejected.
- Different ``status`` is rejected.
- Different ``source`` is rejected.
- Overlap is rejected.
- A gap larger than ``MERGE_GAP_TOLERANCE_SECONDS`` (2 seconds) is
  rejected.
- A gap within the tolerance (≤ 2 seconds) is allowed.
- Cross-day adjacent activities merge successfully and project via
  ``timeline_service``.
- The kept activity's ``note`` is preserved; the later activity's note is
  not copied or concatenated.
- ``project_session_note`` is not migrated.
- Assignment and resource rows are not complex-merged (the later
  activity's rows are left in place).
- If the kept-activity UPDATE affects 0 rows (race condition), the service
  raises ``ValueError`` and the later activity is NOT soft-deleted.
- If the merged-activity soft-delete UPDATE affects 0 rows (race
  condition), the service raises ``ValueError`` and the kept activity's
  ``end_time`` is rolled back.
- No partial writes occur on validation failure.

#### BF. API Layer

- ``merge_timeline_activities`` accepts a list of exactly two positive
  integers (``bool`` rejected).
- Non-list, empty, single, three+, bool, non-positive, duplicate, and
  nonexistent ids are rejected with the appropriate stable error codes.
- Service-layer ``ValueError`` codes map to stable
  ``TimelineMergeError`` codes: ``invalid_selection``, ``invalid_id``,
  ``in_progress``, ``different_project``, ``different_resource``,
  ``incompatible_activity``, ``not_adjacent``, ``invalid_time``,
  ``operation_failed``.
- The API returns ``{"kept_activity_id": int, "merged_activity_id": int}``
  and does not leak raw rows, ``window_title``, ``file_path_hint``,
  ``note``, or internal fields.

#### BG. Bridge Layer

- ``merge_timeline_activities`` returns
  ``{"ok": true, "kept_activity_id": int, "merged_activity_id": int}``
  on success.
- Error results return ``{"ok": false, "error": "<chinese message>"}``
  with clear messages for each known failure mode.
- Unknown failures collapse to ``"操作失败"``.
- Error results do not contain tracebacks, SQL errors, ``window_title``,
  ``file_path_hint``, ``full_path``, ``clipboard``, or ``note``.
- The bridge does not import ``worktrace.services``, ``worktrace.db``,
  ``worktrace.collector``, ``worktrace.runtime``, ``worktrace.security``,
  or ``worktrace.config``.

#### BH. Frontend

- app.js calls ``merge_timeline_activities`` bridge method.
- app.js has a "与下一条合并" button per activity detail row.
- app.js has independent ``mergeSaving`` / ``mergingActivityId`` state.
- app.js resets the saving state BEFORE refreshing the Timeline on
  success.
- app.js preserves the detail list on failure and shows "合并失败".
- app.js disables the merge button for in-progress activities.
- app.js does not contain delete, batch, auto-rule, or
  multi-activity-session-merge handlers.
- app.js does not display tracebacks or raw sensitive fields.
- styles.css styles the merge button and status, with responsive layout
  for narrow viewports.
- No external links, CDN, Google Fonts, or browser storage introduced.

#### BI. Regression

- All Phase 3B.2 / 3B.2.1 split tests continue to pass.
- All Phase 3B.1 / 3B.1.1 time-correction tests continue to pass.
- All Phase 3A / 3A.1 editing tests continue to pass.
- All Phase 2.1 privacy boundary tests continue to pass.
- Overview and Timeline read-only tests continue to pass.
- Default WebView entry tests continue to pass.
- PyInstaller resource path tests continue to pass.

### Phase 3B.3 Release Blockers

- The merge is not atomic (a failure leaves one activity modified and the
  other not soft-deleted).
- The kept activity's ``start_time`` or ``created_at`` is modified.
- The kept activity's ``duration_seconds`` is not precisely recomputed.
- The later activity is physically deleted instead of soft-deleted.
- A race condition (UPDATE rowcount 0) does not roll back the transaction.
- In-progress or deleted activities can be merged.
- Different project / resource / status / source activities can be merged.
- Overlapping activities can be merged.
- A gap larger than the tolerance can be merged.
- The bridge exposes tracebacks, SQL errors, ``window_title``,
  ``file_path_hint``, ``full_path``, ``clipboard``, or ``note``.
- The bridge imports backend internals (services/db/collector/runtime/
  security/config).
- The frontend introduces delete, batch, auto-rule, or
  multi-activity-session-merge controls.
- The frontend uses browser storage or external resources.
- Any Phase 3B.2 / 3B.1 / 3A / 2.1 regression.
- Any new DB schema is introduced.

## WebView Phase 3B.3.1 Validation

Phase 3B.3.1 is a **hardening-only** phase for the Phase 3B.3 activity
merge. It introduces no new features, no new DB schema, and no new UI
controls. It confirms the merge write path is stable, safe, and
semantically clear, and adds explicit regression tests for edge cases the
foundation tests did not exercise.

### Automated Checklist

| Check | Command |
|-------|---------|
| Full test suite | `python -m pytest` |
| PyInstaller build | `python -m PyInstaller --noconfirm --clean WorkTrace.spec` |

### Validation Items

#### BJ. Transaction Boundary Hardening

- The kept-activity UPDATE and the later-activity soft-delete run inside
  the same ``with get_connection()`` transaction. The sqlite3 connection
  context manager commits on normal exit and rolls back on any exception.
- The kept-activity UPDATE guards its WHERE clause with
  ``id = ? AND is_deleted = 0 AND end_time IS NOT NULL``; a rowcount of 0
  raises ``ValueError("activity_merge_update_affected_zero_rows")`` and
  rolls back.
- The later-activity soft-delete UPDATE uses the same WHERE guard; a
  rowcount of 0 raises the same ``ValueError`` and rolls back (the kept
  UPDATE is also rolled back).
- An arbitrary exception raised by the soft-delete UPDATE (e.g.
  ``sqlite3.OperationalError``) propagates out of ``merge_activities`` and
  the ``with get_connection()`` context manager rolls back the
  transaction. The kept activity's ``end_time`` returns to its original
  value and the later activity is NOT soft-deleted. Verified by
  ``test_service_merge_soft_delete_exception_rolls_back``.

#### BK. Validation Order And Excluded Activities

- The service checks resource identity (``activity_resource.identity_key``)
  before status/source. Excluded activities are always anonymised to
  ``system:excluded``, which differs from a normal activity's file-based
  identity_key. An excluded-vs-non-excluded merge is therefore rejected
  with ``different_resource`` — a stronger and earlier guard. Verified by
  ``test_merge_excluded_vs_non_excluded_rejected``.
- The in-progress determination reads the raw DB ``end_time IS NULL``
  column, not the projected display value.

#### BL. No Partial Write On Rejection

- Different project: both activities' ``start_time`` / ``end_time`` /
  ``is_deleted`` unchanged. Verified by existing Phase 3B.3 tests and
  ``test_merge_kept_fields_unchanged_on_validation_failure``.
- Different resource: both activities unchanged. Verified by
  ``test_merge_no_partial_write_on_different_resource``.
- Different status: both activities unchanged. Verified by
  ``test_merge_no_partial_write_on_different_status``.
- Different source: both activities unchanged. Verified by
  ``test_merge_no_partial_write_on_different_source``.
- Gap too large: both activities unchanged. Verified by
  ``test_merge_no_partial_write_on_gap_too_large``.
- On any validation failure the kept activity's ``start_time`` /
  ``end_time`` / ``duration_seconds`` / ``updated_at`` are all unchanged.
  Verified by ``test_merge_kept_fields_unchanged_on_validation_failure``.

#### BM. Error Code Mapping

- Every service-layer ``ValueError`` code used by ``merge_activities``
  maps to a stable ``TimelineMergeError`` code. Verified by
  ``test_api_maps_all_service_value_error_codes`` (table-driven, covers
  all 9 known codes plus an unknown code that collapses to
  ``operation_failed``).

#### BN. Regression

- All Phase 3B.3 merge foundation tests continue to pass.
- All Phase 3B.2 / 3B.2.1 split tests continue to pass.
- All Phase 3B.1 / 3B.1.1 time-correction tests continue to pass.
- All Phase 3A / 3A.1 editing tests continue to pass.
- All Phase 2.1 privacy boundary tests continue to pass.
- Overview and Timeline read-only tests continue to pass.
- Default WebView entry tests continue to pass.
- PyInstaller resource path tests continue to pass.

### Phase 3B.3.1 Release Blockers

- A soft-delete UPDATE exception leaves a partial write (kept ``end_time``
  extended but later activity still live).
- A race-condition rowcount-0 does not roll back the transaction.
- An excluded-vs-non-excluded merge is allowed.
- A validation failure modifies either activity's ``start_time`` /
  ``end_time`` / ``is_deleted`` / ``duration_seconds`` / ``updated_at``.
- A service ``ValueError`` code does not map to the documented stable
  ``TimelineMergeError`` code.
- Any Phase 3B.3 / 3B.2 / 3B.1 / 3A / 2.1 regression.
- Any new feature (delete / hide, batch edit, auto-rule, complex
  correction page, overlap detection, arbitrary-length merge,
  multi-activity session whole-merge) is introduced.
- Any new DB schema is introduced.

## WebView Phase 3B.4 Validation

Phase 3B.4 implements the **Timeline hide / soft delete foundation** —
the minimal usable single-activity hide and soft delete. Hide sets
`activity_log.is_hidden = 1`; soft delete sets `is_deleted = 1`. Neither
physically deletes the row or touches assignment / resource / note /
session-note rows. Single-activity session-level hide / soft delete is
supported; multi-activity session whole-hide / whole-delete is rejected.

### Automated Checklist

| Check | Command |
|-------|---------|
| Full test suite | `python -m pytest` |
| PyInstaller build | `python -m PyInstaller --noconfirm --clean WorkTrace.spec` |

### Validation Items

#### BJ. Service Layer

- ``hide_activity`` sets ``is_hidden = 1`` and leaves ``is_deleted``
  unchanged.
- ``soft_delete_activity`` sets ``is_deleted = 1`` and leaves
  ``is_hidden`` unchanged.
- Neither operation physically deletes the row (the row still exists in
  ``activity_log``).
- Neither operation modifies ``start_time``, ``end_time``,
  ``duration_seconds``, ``project_id``, ``note``, ``status``, or
  ``source``.
- Neither operation deletes ``activity_project_assignment``,
  ``activity_resource``, or ``project_session_note`` rows.
- Neither operation migrates ``project_session_note``.
- ``hide_activity`` on a nonexistent / deleted / in-progress activity
  raises ``ValueError`` (the WHERE clause excludes ``is_deleted = 1``
  and ``end_time IS NULL``).
- ``soft_delete_activity`` on a nonexistent / deleted / in-progress
  activity raises ``ValueError``.
- ``hide_activity`` is idempotent: hiding an already-hidden activity
  succeeds (the UPDATE still matches the row).
- ``soft_delete_activity`` is NOT idempotent: deleting an already-deleted
  activity raises ``ValueError`` (the WHERE clause excludes it).
- A race-condition UPDATE (rowcount 0) raises ``ValueError`` and no
  write occurs.

#### BK. API Layer

- ``hide_timeline_activity`` and ``soft_delete_timeline_activity`` accept
  a single positive integer (``bool`` rejected).
- Non-int, non-positive, nonexistent, deleted, and in-progress ids are
  rejected with the appropriate stable error codes.
- ``hide_timeline_session`` and ``soft_delete_timeline_session`` accept a
  non-empty list of positive integers (``bool`` rejected). Duplicate ids
  are deduplicated.
- A multi-activity session (more than one id after dedup) raises
  ``multi_activity_hide`` / ``multi_activity_delete`` respectively.
- A single-activity session hide / soft delete is equivalent to the
  activity-level call.
- Service-layer ``ValueError`` codes map to stable
  ``TimelineVisibilityError`` codes: ``invalid_id``, ``in_progress``,
  ``multi_activity_hide``, ``multi_activity_delete``,
  ``operation_failed``.
- The API returns ``None`` on success and does not leak raw rows,
  ``window_title``, ``file_path_hint``, ``note``, or internal fields.
- In-progress is determined by the raw DB ``end_time IS NULL`` column,
  not the projected display value.

#### BL. Bridge Layer

- ``hide_timeline_activity``, ``soft_delete_timeline_activity``,
  ``hide_timeline_session``, and ``soft_delete_timeline_session`` return
  ``{"ok": true}`` on success.
- Error results return ``{"ok": false, "error": "<chinese message>"}``
  with clear messages for each known failure mode.
- Bridge error messages: ``操作失败`` (invalid_id / operation_failed /
  unknown), ``进行中记录暂不支持隐藏或删除`` (in_progress),
  ``多活动 session 暂不支持整体隐藏，请在活动详情中逐条处理``
  (multi_activity_hide),
  ``多活动 session 暂不支持整体删除，请在活动详情中逐条处理``
  (multi_activity_delete).
- Unknown failures and unknown error codes collapse to ``"操作失败"``.
- Error results do not contain tracebacks, SQL errors, ``window_title``,
  ``file_path_hint``, ``full_path``, ``clipboard``, or ``note``.
- The bridge does not import ``worktrace.services``, ``worktrace.db``,
  ``worktrace.collector``, ``worktrace.runtime``, ``worktrace.security``,
  or ``worktrace.config``.

#### BM. Frontend

- app.js calls ``hide_timeline_activity``, ``soft_delete_timeline_activity``,
  ``hide_timeline_session``, and ``soft_delete_timeline_session`` bridge
  methods.
- app.js has independent ``hideSaving`` / ``hidingActivityId`` and
  ``deleteSaving`` / ``deletingActivityId`` state, separate from the
  project/note/time/split/merge saving states.
- app.js resets the saving state on both success and failure paths.
- app.js refreshes the Timeline on success and preserves the detail list
  on failure.
- app.js disables the hide / delete buttons for in-progress activities.
- app.js shows the "多活动" hint for multi-activity session-level hide /
  delete.
- app.js refuses hide / delete when ``isEditDirty()`` returns true with
  "请先保存或取消当前编辑".
- app.js uses ``window.confirm`` for the delete flow with the soft-delete
  hint.
- app.js does not contain batch hide, batch delete, restore,
  permanent-delete, auto-rule, or complex-correction handlers.
- app.js does not display tracebacks or raw sensitive fields.
- index.html includes the ``edit-visibility-section`` with the single /
  multi / hide / delete / status elements.
- styles.css styles the hide / delete UI, with responsive layout for
  narrow viewports.
- No external links, CDN, Google Fonts, or browser storage introduced.

#### BN. Regression

- All Phase 3B.3 / 3B.3.1 merge tests continue to pass.
- All Phase 3B.2 / 3B.2.1 split tests continue to pass.
- All Phase 3B.1 / 3B.1.1 time-correction tests continue to pass.
- All Phase 3A / 3A.1 editing tests continue to pass.
- All Phase 2.1 privacy boundary tests continue to pass.
- Overview and Timeline read-only tests continue to pass.
- Default WebView entry tests continue to pass.
- PyInstaller resource path tests continue to pass.

### Phase 3B.4 Release Blockers

- Hide or soft delete physically removes the DB row.
- Hide or soft delete modifies ``start_time``, ``end_time``,
  ``duration_seconds``, ``project_id``, ``note``, ``status``, or
  ``source``.
- Hide or soft delete deletes ``activity_project_assignment``,
  ``activity_resource``, or ``project_session_note`` rows.
- A race condition (UPDATE rowcount 0) does not raise ``ValueError`` or
  leaves a partial write.
- An in-progress activity (raw ``end_time IS NULL``) can be hidden or
  deleted.
- A deleted activity can be hidden or soft-deleted.
- A multi-activity session whole-hide / whole-delete is allowed.
- The bridge exposes tracebacks, SQL errors, ``window_title``,
  ``file_path_hint``, ``full_path``, ``clipboard``, or ``note``.
- The bridge imports backend internals (services/db/collector/runtime/
  security/config).
- The frontend introduces batch hide, batch delete, restore,
  permanent-delete, auto-rule, or complex-correction controls.
- The frontend uses browser storage or external resources.
- The frontend wipes the detail list on a hide / delete failure.
- Any Phase 3B.3 / 3B.2 / 3B.1 / 3A / 2.1 regression.
- Any new DB schema is introduced.

## WebView Phase 3B.4.1 Validation

Phase 3B.4.1 is a **hardening-only** phase for the Phase 3B.4 Timeline
hide / soft delete foundation. It introduces **no new features** — no
batch hide, no batch delete, no undo / restore, no permanent delete, no
auto-rule, no complex correction page, no overlap detection, and no
multi-activity session whole-hide / whole-delete. It strengthens the
service, bridge, and documentation invariants so the hide / soft delete
write path is more predictable and semantically clearer.

### Automated Checklist

| Check | Command |
|-------|---------|
| Full test suite | `python -m pytest` |
| PyInstaller build | `python -m PyInstaller --noconfirm --clean WorkTrace.spec` |

### Validation Items

#### BO. Service-Layer Hardening

- ``hide_activity`` is idempotent at the service layer: calling it twice
  on the same closed activity succeeds both times (the WHERE clause
  matches an already-hidden row).
- ``soft_delete_activity`` is NOT idempotent at the service layer: the
  second call on an already-deleted activity raises ``ValueError`` (the
  WHERE clause excludes ``is_deleted = 1``).
- ``soft_delete_activity`` on an in-progress activity (raw
  ``end_time IS NULL``) raises ``ValueError``.
- ``hide_activity`` leaves ``is_deleted`` at 0; ``soft_delete_activity``
  leaves ``is_hidden`` unchanged (an already-hidden activity stays
  hidden after a soft delete).
- Neither operation modifies ``start_time``, ``end_time``,
  ``duration_seconds``, ``project_id``, ``note``, ``status``, or
  ``source`` at the service layer.
- Neither operation deletes ``activity_project_assignment`` or
  ``activity_resource`` rows at the service layer.
- Neither operation physically removes the row from ``activity_log``.

#### BP. Bridge-Layer Hardening

- A multi-activity session hide / soft delete returns the dedicated
  Chinese message **without** calling the API write path (the bridge
  short-circuits).
- An invalid activity id (non-positive, ``bool``, non-int) returns
  ``"操作失败"`` **without** calling the API write path.
- A non-list ``activity_ids`` argument returns ``"操作失败"``
  **without** calling the API write path.
- All bridge error payloads remain free of tracebacks, SQL errors,
  ``window_title``, ``file_path_hint``, ``full_path``, ``clipboard``,
  and ``note``.

#### BQ. Semantics Restated

- In-progress is determined by the **raw DB ``end_time IS NULL``
  column**, not the projected display value.
- The delete confirmation is a **soft-delete confirmation**, not a
  permanent-delete confirmation. The frontend uses
  ``window.confirm("确定从 Timeline 删除这条记录吗？本阶段不会物理删除数据。")``.
- Hide is idempotent; soft delete is non-idempotent.
- Hide sets ``is_hidden = 1``; soft delete sets ``is_deleted = 1``.
- Neither physically deletes the row or touches assignment / resource /
  note / session-note rows.

#### BR. Regression

- All Phase 3B.4 hide / soft delete foundation tests continue to pass.
- All Phase 3B.3 / 3B.3.1 merge tests continue to pass.
- All Phase 3B.2 / 3B.2.1 split tests continue to pass.
- All Phase 3B.1 / 3B.1.1 time-correction tests continue to pass.
- All Phase 3A / 3A.1 editing tests continue to pass.
- All Phase 2.1 privacy boundary tests continue to pass.
- Overview and Timeline read-only tests continue to pass.
- Default WebView entry tests continue to pass.
- PyInstaller resource path tests continue to pass.

### Phase 3B.4.1 Release Blockers

- Any new feature (batch hide, batch delete, undo / restore, permanent
  delete, auto-rule, complex correction page, overlap detection,
  multi-activity session whole-hide / whole-delete) is introduced.
- ``hide_activity`` is no longer idempotent at the service layer.
- ``soft_delete_activity`` becomes idempotent at the service layer.
- ``hide_activity`` modifies ``is_deleted``, or ``soft_delete_activity``
  modifies ``is_hidden``.
- Either operation modifies ``start_time``, ``end_time``,
  ``duration_seconds``, ``project_id``, ``note``, ``status``, or
  ``source`` at the service layer.
- Either operation deletes ``activity_project_assignment``,
  ``activity_resource``, or ``project_session_note`` rows.
- Either operation physically removes the row from ``activity_log``.
- The bridge calls the API write path for a multi-activity session or
  an invalid activity id instead of short-circuiting.
- In-progress is determined by anything other than the raw DB
  ``end_time IS NULL`` column.
- The delete confirmation wording claims permanent deletion.
- Any bridge error payload leaks tracebacks, SQL errors,
  ``window_title``, ``file_path_hint``, ``full_path``, ``clipboard``,
  or ``note``.
- Any Phase 3B.4 / 3B.3 / 3B.2 / 3B.1 / 3A / 2.1 regression.
- Any new DB schema is introduced.

## WebView Phase 3B.5A Validation

Phase 3B.5A is a **consolidation / polish / consistency** phase for the
Timeline correction actions already implemented in Phase 3B.1 /
3B.2 / 3B.3 / 3B.4. It adds **no new backend write capability**, **no
new DB schema**, and **no new correction action**. It only reorganizes
the existing per-activity correction buttons into action groups, unifies
dirty-state guards and refresh semantics, unifies destructive-action
copy, and unifies session-level edit-panel section labels.

### Phase 3B.5A Scope

- The five per-activity correction buttons (编辑时间, 拆分, 与下一条合并,
  隐藏, 删除) are wrapped in three action groups:
  `.detail-action-edit-group`, `.detail-action-merge-group`,
  `.detail-action-danger-group`.
- The action order is stable: `编辑时间 → 拆分 → 与下一条合并 → 隐藏 →
  删除`.
- The merge button carries an indigo accent; the danger group has a
  red-tinted left border.
- `saveActivityMerge` now carries the same `isEditDirty()` guard and
  row-id consistency check as hide / delete.
- Destructive-action copy is unified: hide `已隐藏` / `隐藏失败`; delete
  `已删除` / `删除失败`; dirty-state refusal `请先保存或取消当前编辑`;
  delete confirmation still says `本阶段不会物理删除数据`.
- Session-level edit-panel section labels are unified: `项目与备注`,
  `时间修正`, `拆分`, `可见性`.
- `clearEditPanel` resets all transient action state;
  `populateEditPanel` populates all correction sections.
- Auto-refresh preserves dirty inputs and re-applies in-flight saving
  state to refreshed buttons.

### Phase 3B.5A Verification

- `python -m pytest` passes (all Phase 3B.5A frontend resource / state
  consistency tests pass; all prior phase tests continue to pass).
- `python -m PyInstaller --noconfirm --clean WorkTrace.spec` succeeds.
- The bridge still imports only `worktrace.api` / `worktrace.formatters`
  (no `services` / `db` / `collector` / `security` / `runtime` /
  `config`).
- No frontend resource contains `localStorage`, `sessionStorage`, CDN,
  external links, or Google Fonts.
- No frontend resource contains traceback display logic.
- No frontend resource contains batch / restore / permanent-delete /
  auto-rule / complex-correction-page handlers.

### Phase 3B.5A Release Blockers

- Any new feature (batch edit, batch hide, batch delete, undo / restore,
  permanent delete, auto-rule, complex correction page, overlap
  detection, multi-activity session whole-hide / whole-delete,
  arbitrary-length merge) is introduced.
- The stable action order changes (编辑时间 → 拆分 → 与下一条合并 → 隐藏
  → 删除).
- Any destructive action loses its `isEditDirty()` guard or row-id
  consistency check.
- The delete confirmation wording claims permanent deletion.
- Any bridge error payload leaks tracebacks, SQL errors,
  ``window_title``, ``file_path_hint``, ``full_path``, ``clipboard``,
  or ``note``.
- Any Phase 3B.4 / 3B.3 / 3B.2 / 3B.1 / 3A / 2.1 regression.
- Any new DB schema is introduced.

## WebView Phase 3B.5B Validation

Phase 3B.5B is a **correction shell / advanced edit layout foundation**
phase for the Timeline page. It adds a hidden correction workspace *shell*
inside `#page-timeline` (inside `#timeline-details`, after
`#timeline-edit-panel`). The shell is a **read-only context + navigation
layout**: it summarizes the selected session and its activities using
display-safe fields only and guides the user back to the existing single
project / note / time / split / merge / hide / delete controls. It adds
**no new backend write capability**, **no new DB schema**, **no new
bridge / API / service method**, and **no new correction action**. It
does **not** implement batch editing.

### Phase 3B.5B Scope

- A `#timeline-correction-shell` container (class `correction-shell`,
  `hidden` by default) is added inside the Timeline details column,
  after the edit panel. It is **not** a new top-level sidebar nav item;
  the sidebar remains `概览 / 时间详情 / 统计与导出 / 项目规则 /
  设置与隐私`.
- The shell header has title `高级纠错`, a subtitle, and a close button
  `返回时间详情` (`#correction-shell-close-btn`).
- The shell has status / context / activities / actions areas
  (`#correction-shell-status`, `#correction-shell-context`,
  `#correction-shell-activities`, `#correction-shell-actions`).
- A session-level entry button `打开高级纠错`
  (`#open-correction-shell-btn`) opens the shell.
- Shell state (`correctionShellOpen`, `correctionShellSessionId`,
  `correctionShellActivityId`, `correctionShellMode`) is declared
  separately from the existing saving states.
- `openCorrectionShell` refuses to open while `isEditDirty()` is true
  (`请先保存或取消当前编辑`) and requires a selected session.
- `closeCorrectionShell` resets shell state but preserves
  `selectedSessionId`.
- `clearEditPanel` and date navigation (`goPrevDay` / `goNextDay` /
  `goToday`) reset shell state; `selectTimelineSession` closes the shell
  on session switch; `showTimeline` resets shell state when the selected
  session disappears.
- `renderCorrectionShell` uses only display-safe fields and reuses the
  existing `formatTimeRange` helper; it never reads `window_title`,
  `file_path_hint`, `full_path`, `clipboard`, or note internals, and
  does not parse backend times with `new Date(string)`.
- The shell activity rows are click-to-locate (scroll to / highlight the
  matching `.detail-item`); no write is performed from the shell.
- The shell action area renders guidance text only (no write buttons)
  and reiterates soft-delete semantics (`本阶段不会物理删除数据`).

### Phase 3B.5B Verification

- `python -m pytest` passes (all Phase 3B.5B frontend resource / state
  consistency tests pass; all prior phase tests continue to pass).
- `python -m PyInstaller --noconfirm --clean WorkTrace.spec` succeeds.
- The bridge still imports only `worktrace.api` / `worktrace.formatters`
  (no `services` / `db` / `collector` / `security` / `runtime` /
  `config`).
- No frontend resource contains `localStorage`, `sessionStorage`, CDN,
  external links, or Google Fonts.
- No frontend resource contains traceback display logic.
- No frontend resource contains batch / restore / permanent-delete /
  auto-rule / overlap-detection handlers.
- No new bridge / API / service method is added.

### Phase 3B.5B Release Blockers

- Any new feature (batch edit, batch hide, batch delete, undo / restore,
  permanent delete, auto-rule, complex correction page, overlap
  detection, multi-activity session whole-hide / whole-delete,
  arbitrary-length merge) is introduced.
- The shell is added as a new top-level sidebar nav item.
- The shell performs any write directly (instead of guiding back to the
  existing controls).
- The shell reads or displays raw `window_title`, `file_path_hint`,
  `full_path`, `clipboard`, or note internals.
- `openCorrectionShell` opens while `isEditDirty()` is true, or
  `closeCorrectionShell` clears `selectedSessionId`.
- `clearEditPanel` / date navigation / session disappear paths fail to
  reset shell state.
- Any bridge error payload leaks tracebacks, SQL errors,
  ``window_title``, ``file_path_hint``, ``full_path``, ``clipboard``,
  or ``note``.
- Any Phase 3B.5A / 3B.4 / 3B.3 / 3B.2 / 3B.1 / 3A / 2.1 regression.
- Any new DB schema is introduced.

## WebView Phase 3B.5B.1 Validation

Phase 3B.5B.1 is a **hardening-only** phase for the 3B.5B correction shell.
It stabilizes the shell on navigation, auto-refresh, dirty-state, selected
session disappearance, display-safe field boundaries, click-to-locate, and
the close / reset paths. It adds **no new backend write capability**, **no
new DB schema**, **no new bridge / API / service method**, and **no new
correction action**. It does **not** implement batch editing.

### Phase 3B.5B.1 Scope

- `openCorrectionShell` keeps its dirty-state open guard
  (`isEditDirty()` → `请先保存或取消当前编辑`). The refusal does not clear
  `selectedSessionId`, does not clear the edit panel / inputs, and does
  not change the selected session. It requires the selected session to
  still exist in `currentSessions`.
- `closeCorrectionShell` resets shell-only state and **preserves**
  `selectedSessionId`; it triggers no refresh and performs no write.
- `resetCorrectionShellState` clears shell-only state only (never the
  edit / time / split / merge / hide / delete saving states) and cancels
  any pending highlight timer.
- `clearEditPanel`, date navigation (`goPrevDay` / `goNextDay` /
  `goToday`), and `selectTimelineSession` (on switch) reset shell state;
  `showTimeline` resets shell state when the selected session disappears.
- Auto-refresh never overwrites a dirty shell: the shell context is
  re-rendered only when the shell is open, the selected session still
  exists, **and** the panel is not dirty.
- `renderCorrectionShell` uses only display-safe fields, escapes all
  dynamic values via `escapeHtml`, reuses `formatTimeRange`, and never
  reads `window_title` / `file_path_hint` / `full_path` / `clipboard` /
  note internals / traceback / SQL / exception text. Shell activity rows
  carry a distinct `data-correction-activity-id`; only numeric ids are
  click-to-locate targets, invalid ids render as non-clickable `.is-static`
  rows.
- `highlightDetailRow` (click-to-locate) only scrolls to / highlights the
  existing `.detail-item[data-activity-id=...]` row. It calls no bridge
  method, performs no write, does not switch date / session, and does not
  change `selectedSessionId`. A stale target shows a safe status message
  and never throws. A single tracked transient-highlight timer is cleared
  before each re-schedule so repeated clicks never accumulate timers.
- CSS: `.correction-shell[hidden]` stays `display: none`;
  `.detail-item.detail-item-highlight` is a noticeable-but-not-harsh
  transient flash; narrow-viewport rules keep the layout stable. No
  external fonts / icons / resources are used; Phase 3B.5A action-group
  styles are untouched.

### Phase 3B.5B.1 Verification

- `python -m pytest` passes (all Phase 3B.5B.1 shell state / display-safe
  / click-to-locate / boundary tests pass; all prior phase tests continue
  to pass).
- `python -m PyInstaller --noconfirm --clean WorkTrace.spec` succeeds.
- The bridge still imports only `worktrace.api` / `worktrace.formatters`
  (no `services` / `db` / `collector` / `security` / `runtime` /
  `config`).
- No frontend resource contains `localStorage`, `sessionStorage`, CDN,
  external links, or Google Fonts.
- No frontend resource contains batch / restore / permanent-delete /
  auto-rule / overlap-detection handlers.
- No new bridge / API / service method is added; no new DB schema is
  introduced.

### Phase 3B.5B.1 Release Blockers

- Any new feature (batch edit, batch hide, batch delete, undo / restore,
  permanent delete, auto-rule, complex correction page, overlap
  detection, multi-activity session whole-hide / whole-delete,
  arbitrary-length merge) is introduced.
- `openCorrectionShell` opens while `isEditDirty()` is true, or the dirty
  refusal clears `selectedSessionId` / the edit panel.
- `closeCorrectionShell` clears `selectedSessionId` or triggers a refresh
  / write.
- `resetCorrectionShellState` resets any edit / time / split / merge /
  hide / delete saving state, or leaves a dangling highlight timer.
- Auto-refresh overwrites a dirty shell, or fails to close the shell when
  the selected session disappears.
- The shell reads or displays raw `window_title`, `file_path_hint`,
  `full_path`, `clipboard`, note internals, traceback, SQL, or exception
  text.
- `highlightDetailRow` calls a bridge method, performs a write, switches
  date / session, changes `selectedSessionId`, throws on a stale target,
  or accumulates highlight timers.
- Any Phase 3B.5B / 3B.5A / 3B.4 / 3B.3 / 3B.2 / 3B.1 / 3A / 2.1
  regression.
- Any new DB schema or any new bridge / API / service method is
  introduced.

## WebView Phase 3B.6 Validation

Phase 3B.6 implements the **first batch write capability** in the WebView
Timeline: **batch project reassignment**. Multiple closed activities
selected in the Phase 3B.5B correction shell can be reassigned to a single
target project through an atomic transaction. It is the **only** batch
write capability introduced in this phase — it is **not** a general batch
editing phase. Hidden / in-progress / deleted activities are rejected.
No new DB schema is introduced; the write reuses the existing
`activity_project_assignment` and `activity_log.project_id` semantics.

### Phase 3B.6 Scope

- Service (`worktrace/services/activity_service.py`):
  `batch_update_activity_project(activity_ids, project_id) -> int`. Input
  validation: `activity_ids` must be a list; dedup to ≥ 2 ids; each id a
  positive int (bool rejected); count ≤
  `MAX_BATCH_PROJECT_EDIT_ACTIVITIES` (= 100). `project_id` a positive
  int (bool rejected); project must exist, not be archived, and be
  enabled. Each activity must exist, have `is_deleted = 0`,
  `is_hidden = 0`, and raw DB `end_time IS NOT NULL` (closed); in-progress
  activities are rejected. The write runs in a single transaction, updates
  each activity's effective project consistent with the existing
  `update_activity_project` / `update_activities_project` single-edit
  semantics (writes both `activity_log.project_id` and
  `activity_project_assignment` with `is_manual = 1` / `source = 'manual'`
  / `confidence = 100`), refreshes `updated_at`, applies a rowcount guard
  (any 0-row UPDATE raises and rolls back), and returns the updated count.
  Any validation or write failure rolls back the whole transaction.
- API (`worktrace/api/timeline_api.py`):
  `batch_update_timeline_activities_project(activity_ids, project_id) ->
  dict` returns `{"updated_count": n}`. `TimelineBatchProjectError(ValueError)`
  exposes stable codes: `invalid_selection`, `batch_too_large`,
  `invalid_project`, `in_progress`, `hidden_activity`, `operation_failed`.
  The API never returns raw rows, raw fields, tracebacks, SQL errors, or
  internal exception text.
- Bridge (`worktrace/webview_ui/bridge.py`):
  `batch_update_timeline_activities_project(activity_ids, project_id) ->
  dict` returns `{"ok": true, "updated_count": n}` on success and
  `{"ok": false, "error": "<中文错误>"}` on failure. Imports only
  `worktrace.api` / `worktrace.formatters`. Rejects bool ids / bool
  project_id at the boundary. `_BATCH_PROJECT_ERROR_MESSAGES` maps codes
  to Chinese user-facing messages. Never returns tracebacks / SQL /
  `window_title` / `file_path_hint` / `full_path` / `clipboard` / note
  values; falls back to `操作失败` on unexpected exceptions.
- Frontend (`worktrace/webview_ui/index.html` / `app.js` / `styles.css`):
  the Phase 3B.5B correction shell gains a dedicated `批量项目重分类`
  section with a hint stating that only batch project reassignment is
  supported. Eligible shell activity rows carry a
  `correction-shell-activity-checkbox` with `data-batch-activity-id`;
  in-progress / non-numeric rows render a disabled checkbox. Selection
  state (`selectedBatchActivityIds` / `batchProjectSaving` /
  `batchProjectTargetId`) is never written to browser storage.
  `全选当前可修改活动` / `清空选择` toggles, an `已选择 N 条` count, a
  target project `<select>` (reusing the project list cache), and a
  `批量设置项目` save button. Save disabled when < 2 selected or no
  target project. `saveBatchProject` refuses while `isEditDirty()` is
  true (`请先保存或取消当前编辑`). Stale ids are pruned on every render
  and re-checked against the rendered shell rows before the bridge call.
  Success clears the selection and refreshes the Timeline (preserving the
  selected session when possible). Failure preserves the selection and
  detail list and shows a Chinese error. `clearEditPanel` /
  `resetCorrectionShellState` / `closeCorrectionShell` /
  `selectTimelineSession` / date navigation all clear the selection and
  reset `batchProjectSaving`. Auto-refresh re-renders the batch rows only
  when the shell is open and not dirty, prunes stale ids, and never
  overwrites a save in flight.
- DB schema: **no new schema**.
- WebView-only: no Tkinter fallback, no new sidebar nav item, no React /
  Vue / Vite / Node, no local HTTP server, no CDN / external fonts /
  Google Fonts, no `localStorage` / `sessionStorage`.

### Phase 3B.6 Verification

- `python -m pytest` passes (all Phase 3B.6 service / API / bridge /
  frontend resource tests pass; all prior phase tests continue to pass).
- `python -m PyInstaller --noconfirm --clean WorkTrace.spec` succeeds.
- The bridge still imports only `worktrace.api` / `worktrace.formatters`
  (no `services` / `db` / `collector` / `security` / `runtime` /
  `config`).
- No frontend resource contains `localStorage`, `sessionStorage`, CDN,
  external links, or Google Fonts.
- No frontend resource contains batch hide / batch delete / batch time /
  batch split / batch merge / restore / permanent-delete / auto-rule /
  overlap-detection handlers (only batch project reassignment is present).
- No new DB schema is introduced (the batch write reuses
  `activity_project_assignment` / `activity_log.project_id`).

### Phase 3B.6 Release Blockers

- A partial batch write is left in the database after any validation or
  write failure (the transaction must roll back fully).
- Selected ids from a stale / disappeared session are sent to the bridge
  (stale ids must be pruned before the bridge call).
- Hidden / in-progress / deleted activities are accepted by the batch
  write (they must be rejected with a stable error code).
- The bridge leaks raw `window_title` / `file_path_hint` / `full_path` /
  clipboard / note / traceback / SQL / exception text in either success
  or error results.
- A new DB schema is introduced to support the batch write.
- The frontend introduces unintended batch delete / batch hide / batch
  time / batch split / batch merge controls.
- The bridge imports `services` / `db` / `collector` / `runtime` /
  `security` / `config` directly.
- Any Phase 3B.5B.1 / 3B.5B / 3B.5A / 3B.4 / 3B.3 / 3B.2 / 3B.1 / 3A /
  2.1 regression.
- Any Tkinter fallback, React / Vue / Vite / Node dependency, local HTTP
  server, CDN, external font, or `localStorage` / `sessionStorage`
  usage is introduced.

## WebView Phase 3B.6.1 Validation

Phase 3B.6.1 is a **hardening-only** phase for the Phase 3B.6 batch project
reassignment. It introduces **no new features** and **no new batch write
types**. The hardening stabilizes the batch project reassignment across
service transaction rollback, API error mapping, bridge error
convergence, and frontend stale selection / auto-refresh / dirty-state /
saving-state / selected-session-disappear paths.

### Phase 3B.6.1 Scope

- **Service layer hardening** (`worktrace/services/activity_service.py`):
  `batch_update_activity_project` already used a single atomic transaction
  with a rowcount guard. Phase 3B.6.1 verifies and tests:
  - Mixed invalid selection rejection: one valid + one deleted / hidden /
    in-progress / nonexistent activity rejects all activities; the valid
    activity is not modified (no partial write).
  - Duplicate id dedup: ids are deduped before validation; after dedup,
    fewer than 2 ids reject, more than 100 reject.
  - Exact max boundary: exactly 100 activities succeed.
  - Assignment semantics match single-edit: batch confidence / source /
    is_manual equal the values set by `update_activities_project(manual=True)`.
  - Resource rows (`activity_resource`) unchanged: no field is modified.
  - Session notes (`project_session_note`) unchanged: note text is not
    modified.
  - Mid-transaction exception rollback: assignment UPSERT failure,
    `activity_log` UPDATE failure, and pre-write SELECT failure all roll
    back the entire transaction so no activity's project changes.
  - No new DB schema: table/column layout is unchanged after a batch
    update.
- **API layer hardening** (`worktrace/api/timeline_api.py`):
  `batch_update_timeline_activities_project` now catches non-ValueError
  service exceptions (e.g. `sqlite3.OperationalError`, `RuntimeError`) and
  maps them to `operation_failed`. The error payload never contains the
  original exception text or traceback.
- **Bridge layer hardening** (`worktrace/webview_ui/bridge.py`): the
  bridge already collapsed unexpected exceptions to `操作失败`.
  Phase 3B.6.1 verifies the error payload contains no traceback / SQL /
  `window_title` / `file_path_hint` / `full_path` / clipboard / note
  values and that the import boundary (only `worktrace.api` /
  `worktrace.formatters`) is preserved.
- **Frontend hardening** (`worktrace/webview_ui/app.js` / `index.html` /
  `styles.css`):
  - `batchProjectSaving` is an independent state variable, separate from
    `editSaving` / `timeSaving` / `activityTimeSaving` /
    `sessionSplitSaving` / `activitySplitSaving` / `mergeSaving` /
    `hideSaving` / `deleteSaving`.
  - `setBatchProjectSaving(true)` disables the save button, select-all
    button, clear button, project select, and every batch checkbox; the
    save button text changes to `保存中…`.
  - `saveBatchProject` is guarded by `batchProjectSaving` (prevents
    double-submit), checks `isEditDirty()` before the bridge call (shows
    `请先保存或取消当前编辑`), validates the project selection (shows
    `请选择有效的项目`), and re-derives selected ids from the currently
    rendered shell rows so stale ids are pruned before the bridge call.
  - `pruneStaleBatchSelection` drops ids that disappeared from the
    rendered activity list, skips in-progress activities, and uses a
    `^[0-9]+` regex so invalid (non-numeric) ids are dropped. It is
    called from both `renderCorrectionShell` and
    `renderBatchProjectSection` so auto-refresh always prunes.
  - The `.then` handler calls `setBatchProjectSaving(false)` before
    branching; the failure branch does not clear the selection or call
    `resetBatchProjectState`. The `.catch` handler resets saving and shows
    `操作失败`.
  - The success path clears `selectedBatchActivityIds`, resets
    `batchProjectTargetId`, shows `已批量更新项目`, and refreshes the
    Timeline.
  - `selectTimelineSession` (on switch), `goPrevDay` / `goNextDay` /
    `goToday`, `clearEditPanel`, and `resetCorrectionShellState` all call
    `resetBatchProjectState` so the batch selection never carries over to
    a different session or date.
  - No `localStorage` / `sessionStorage` usage; no external links / CDN /
    Google Fonts; no traceback display; no batch hide / delete / time /
    split / merge UI; no restore / permanent delete / auto-rule / overlap
    handler.

### Phase 3B.6.1 Verification

- `python -m pytest` passes (all Phase 3B.6.1 service / API / frontend
  resource tests pass; all Phase 3B.6 and prior phase tests continue to
  pass).
- `python -m PyInstaller --noconfirm --clean WorkTrace.spec` succeeds.
- The bridge still imports only `worktrace.api` / `worktrace.formatters`.
- No frontend resource contains `localStorage`, `sessionStorage`, CDN,
  external links, or Google Fonts.
- No frontend resource contains batch hide / batch delete / batch time /
  batch split / batch merge / restore / permanent-delete / auto-rule /
  overlap-detection handlers.
- No new DB schema is introduced.

### Phase 3B.6.1 Release Blockers

- A partial batch write is left in the database after a mid-transaction
  exception (the transaction must roll back fully).
- Stale ids from a disappeared / auto-refreshed session are sent to the
  bridge (stale ids must be pruned before the bridge call).
- Hidden / in-progress / deleted activities are accepted by the batch
  write (they must be rejected with a stable error code).
- A non-ValueError service exception propagates uncaught through the API
  layer (it must collapse to `operation_failed`).
- The bridge leaks raw `window_title` / `file_path_hint` / `full_path` /
  clipboard / note / traceback / SQL / exception text in either success
  or error results.
- The frontend introduces a dirty-edit bypass (batch save while
  `isEditDirty()` is true).
- The saving state gets stuck (`.then` or `.catch` fails to reset
  `batchProjectSaving`).
- The batch selection carries over to a different session or date.
- A new DB schema is introduced.
- The frontend introduces unintended batch delete / batch hide / batch
  time / batch split / batch merge controls.
- The bridge imports `services` / `db` / `collector` / `runtime` /
  `security` / `config` directly.
- Any Phase 3B.6 / 3B.5B.1 / 3B.5B / 3B.5A / 3B.4 / 3B.3 / 3B.2 / 3B.1 /
  3A / 2.1 regression.
- Any Tkinter fallback, React / Vue / Vite / Node dependency, local HTTP
  server, CDN, external font, or `localStorage` / `sessionStorage`
  usage is introduced.

## WebView Phase 3B.7 Validation

Phase 3B.7 implements the **second batch write capability** in the WebView
Timeline: **batch note overwrite**. Multiple closed activities selected in
the Phase 3B.5B correction shell can have their `note` field overwritten to
the same value through an atomic transaction. It is the **only** batch
write capability introduced in this phase — it is **not** a general batch
editing phase. Batch note append and batch note merge are explicitly out of
scope. Hidden / in-progress / deleted activities are rejected. No new DB
schema is introduced; the write reuses the existing `activity_log.note`
and `activity_log.updated_at` columns only. Only `note` and `updated_at`
are modified — `source` is intentionally not changed (unlike the single
`update_activity_note`).

### Phase 3B.7 Scope

- Service (`worktrace/services/activity_service.py`):
  `batch_update_activity_note(activity_ids, note) -> int`. Input validation:
  `activity_ids` must be a list; dedup to ≥ 2 ids; each id a positive int
  (bool rejected); count ≤ `MAX_BATCH_NOTE_EDIT_ACTIVITIES` (= 100).
  `note` must be a `str` (not `None`); length ≤ `BATCH_NOTE_MAX_LENGTH`
  (= 2000); empty string is allowed and is used to batch-clear notes. Each
  activity must exist, have `is_deleted = 0`, `is_hidden = 0`, and raw DB
  `end_time IS NOT NULL` (closed); in-progress activities are rejected.
  The write runs in a single transaction, UPDATEs each activity's `note`
  to the new value, refreshes `updated_at`, applies a rowcount guard (any
  0-row UPDATE raises and rolls back), and returns the updated count. Only
  `activity_log.note` and `updated_at` are modified; `source`,
  `start_time`, `end_time`, `duration_seconds`, `project_id`, `status`,
  assignment rows, resource rows, and `project_session_note` are unchanged.
  Any validation or write failure rolls back the whole transaction. The
  service does not read, concatenate, or return old note values.
- API (`worktrace/api/timeline_api.py`):
  `batch_update_timeline_activities_note(activity_ids, note) -> dict`
  returns `{"updated_count": n}`. `TimelineBatchNoteError(ValueError)`
  exposes stable codes: `invalid_selection`, `batch_too_large`,
  `invalid_note`, `note_too_long`, `in_progress`, `hidden_activity`,
  `operation_failed`. The API never returns raw rows, raw fields, old note
  values, new note content, tracebacks, SQL errors, or internal exception
  text.
- Bridge (`worktrace/webview_ui/bridge.py`):
  `batch_update_timeline_activities_note(activity_ids, note) -> dict`
  returns `{"ok": true, "updated_count": n}` on success and
  `{"ok": false, "error": "<中文错误>"}` on failure. Imports only
  `worktrace.api` / `worktrace.formatters`. Rejects bool ids / non-list
  ids / `None` note / non-str note at the boundary.
  `_BATCH_NOTE_ERROR_MESSAGES` maps codes to Chinese user-facing messages
  (`请选择至少两个活动` / `一次最多修改 100 条活动` / `请输入有效备注` /
  `备注过长` / `进行中记录暂不支持批量修改` / `隐藏记录暂不支持批量修改` /
  `操作失败`). Never returns tracebacks / SQL / `window_title` /
  `file_path_hint` / `full_path` / clipboard / old note / new note content;
  falls back to `操作失败` on unexpected exceptions.
- Frontend (`worktrace/webview_ui/index.html` / `app.js` / `styles.css`):
  the Phase 3B.5B correction shell gains a dedicated `批量备注覆盖` section
  rendered after the `批量项目重分类` section, with a hint stating that
  only batch note overwrite is supported (no append / merge). The section
  **reuses** the same `selectedBatchActivityIds` selection state as the
  batch project section. Controls: a `<textarea>` with placeholder, a note
  count label `0 / 2000` (turns red when exceeded), and a `批量覆盖备注`
  save button. Save disabled when < 2 selected, note too long, or while a
  batch save is in flight. `saveBatchNote` refuses while `isEditDirty()`
  is true (`请先保存或取消当前编辑`) and while `batchProjectSaving` is true
  (cross-save guard). Stale ids are pruned on every render and re-checked
  against the rendered shell rows before the bridge call. Success clears
  the selection and note textarea and refreshes the Timeline (preserving
  the selected session when possible). Failure preserves the selection,
  note textarea, and detail list and shows a Chinese error. The `catch`
  path resets `batchNoteSaving` and shows `操作失败`.
  `clearEditPanel` / `resetCorrectionShellState` / `closeCorrectionShell`
  / `selectTimelineSession` / date navigation all clear the selection and
  note textarea and reset `batchNoteSaving`. Auto-refresh re-renders the
  batch rows only when the shell is open and not dirty, prunes stale ids,
  and never overwrites a save in flight.
- DB schema: **no new schema**.
- WebView-only: no Tkinter fallback, no new sidebar nav item, no React /
  Vue / Vite / Node, no local HTTP server, no CDN / external fonts /
  Google Fonts, no `localStorage` / `sessionStorage`.

### Phase 3B.7 Verification

- `python -m pytest` passes (all Phase 3B.7 service / API / bridge /
  frontend resource tests pass; all prior phase tests continue to pass).
- `python -m PyInstaller --noconfirm --clean WorkTrace.spec` succeeds.
- The bridge still imports only `worktrace.api` / `worktrace.formatters`
  (no `services` / `db` / `collector` / `security` / `runtime` /
  `config`).
- No frontend resource contains `localStorage`, `sessionStorage`, CDN,
  external links, or Google Fonts.
- No frontend resource contains batch note append / batch note merge /
  batch hide / batch delete / batch time / batch split / batch merge /
  restore / permanent-delete / auto-rule / overlap-detection handlers
  (only batch note overwrite is present).
- No new DB schema is introduced (the batch write reuses
  `activity_log.note` / `activity_log.updated_at`).

### Phase 3B.7 Release Blockers

- A partial batch note write is left in the database after any validation
  or write failure (the transaction must roll back fully).
- Selected ids from a stale / disappeared session are sent to the bridge
  (stale ids must be pruned before the bridge call).
- Hidden / in-progress / deleted activities are accepted by the batch
  write (they must be rejected with a stable error code).
- Old note values are leaked through the API / bridge / frontend (the
  service must not read or return old notes).
- New note content is echoed back in the bridge error payload.
- The bridge leaks raw `window_title` / `file_path_hint` / `full_path` /
  clipboard / note / traceback / SQL / exception text in either success
  or error results.
- A new DB schema is introduced to support the batch note write.
- The frontend introduces unintended batch note append / batch note merge
  / batch delete / batch hide / batch time / batch split / batch merge
  controls.
- The bridge imports `services` / `db` / `collector` / `runtime` /
  `security` / `config` directly.
- Any Phase 3B.6.1 / 3B.6 / 3B.5B.1 / 3B.5B / 3B.5A / 3B.4 / 3B.3 /
  3B.2 / 3B.1 / 3A / 2.1 regression.
- Any Tkinter fallback, React / Vue / Vite / Node dependency, local HTTP
  server, CDN, external font, or `localStorage` / `sessionStorage`
  usage is introduced.

## WebView Phase 3B.7.1 Validation

Phase 3B.7.1 is a **hardening-only** phase for the Phase 3B.7 batch note
overwrite. It introduces **no new features** and **no new batch write
types**. The hardening adds explicit tests that verify the service
transaction, API error mapping, bridge error convergence, and frontend
state-management invariants are stable and do not regress.

### Phase 3B.7.1 Scope

- Service (`worktrace/services/activity_service.py`): verified that
  `batch_update_activity_note` does NOT set `source = 'manual'` — the
  `source` column remains unchanged (the key semantic difference from the
  single `update_activity_note` path). Verified the `note_update_failed`
  error code on rowcount mismatch. Verified every selected activity's
  note equals the target exactly. Verified empty string clears all
  selected notes. Verified `updated_at` is refreshed on every selected
  activity.
- API (`worktrace/api/timeline_api.py`): verified the complete service →
  API error code mapping table (all 10 stable service codes map to the
  correct API codes). Verified non-`ValueError` exception collapse to
  `operation_failed` without leaking exception text. Verified the return
  payload contains only `{"updated_count": n}` — no note content, no
  old/new note keys.
- Bridge (`worktrace/webview_ui/bridge.py`): verified error payloads do
  not contain the note content sent to the bridge. Verified
  `updated_count` matches the deduplicated selection. Verified every
  stable error code produces its exact Chinese message. Verified unknown
  codes converge to `操作失败`. Verified success payload has exactly
  `{ok, updated_count}` and error payload has exactly `{ok, error}`.
  Verified the bridge rejects overly long notes before calling the API.
- Frontend (`worktrace/webview_ui/app.js`): verified the cross-save guard
  (`saveBatchNote` checks `batchProjectSaving` and vice versa). Verified
  `setBatchNoteSaving` disables batch project controls and
  `setBatchProjectSaving` disables the batch note textarea. Verified
  `selectTimelineSession` / `goPrevDay` / `goNextDay` / `goToday` /
  `closeCorrectionShell` all reset batch note state. Verified
  `resetBatchNoteState` clears the textarea, count, and saving flag.
  Verified the error handling code does not reference old/new note
  variables. Verified the failure path preserves the textarea and the
  success path clears both selection and textarea.
- DB schema: **no new schema**. No code changes to the implementation.
- WebView-only: no Tkinter fallback, no new sidebar nav item, no React /
  Vue / Vite / Node, no local HTTP server, no CDN / external fonts /
  Google Fonts, no `localStorage` / `sessionStorage`.

### Phase 3B.7.1 Verification

- `python -m pytest` passes (all Phase 3B.7.1 hardening tests pass; all
  prior phase tests continue to pass).
- `python -m PyInstaller --noconfirm --clean WorkTrace.spec` succeeds.
- No new DB schema is introduced.
- No code changes to the service / API / bridge / frontend implementation
  (hardening-only: tests + docs).

### Phase 3B.7.1 Release Blockers

- `source` is changed to `'manual'` by the batch note overwrite (it must
  remain unchanged — this is the key semantic difference from single
  note editing).
- The API return payload leaks the note content (old or new).
- The bridge error payload echoes back the note content that was sent.
- A non-`ValueError` service exception propagates uncaught through the
  API layer (it must collapse to `operation_failed`).
- The `updated_count` does not match the deduplicated selection count.
- An unknown error code surfaces internal details instead of converging
  to `操作失败`.
- The frontend cross-save guard is bypassed (two batch saves can
  compete).
- The note textarea carries over to a different session / date / shell
  state.
- The failure path clears the note textarea (it must be preserved for
  retry).
- The success path does not clear the selection and textarea.
- `source` / `project_id` / `status` / `start_time` / `end_time` /
  `duration_seconds` / assignment rows / resource rows / session notes
  are modified by the batch note overwrite.
- A new DB schema is introduced.
- The bridge imports `services` / `db` / `collector` / `runtime` /
  `security` / `config` directly.
- Any Phase 3B.7 / 3B.6.1 / 3B.6 / 3B.5B.1 / 3B.5B / 3B.5A / 3B.4 /
  3B.3 / 3B.2 / 3B.1 / 3A / 2.1 regression.
- Any Tkinter fallback, React / Vue / Vite / Node dependency, local HTTP
  server, CDN, external font, or `localStorage` / `sessionStorage`
  usage is introduced.
