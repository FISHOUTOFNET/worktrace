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

## WebView Phase 0A/0B/0C Validation

This section is the validation framework for the optional WebView UI spike documented in [`docs/ui-webview-migration.md`](ui-webview-migration.md). It is scoped to the shell, bridge, runtime, and packaging only. It does not validate any feature page, does not migrate the Tkinter UI, and does not introduce field-level encryption, SQLCipher, AI, server, payment, license, token, or subscription features.

The Tkinter UI remains the default. The WebView entry point is an opt-in spike. Items marked Phase 0B or 0C are listed here as pending and are validated when those phases are implemented.

### Automated Checklist

- [ ] `pytest` passes, including the `test_ui_backend_boundary.py` WebView boundary tests, `test_webview_bridge.py`, `test_webview_resources.py`, and `test_webview_packaging.py`.
- [ ] `pywebview>=5.0` is declared in `requirements.txt` (added in Phase 0B).
- [ ] No new network dependency.
- [ ] No new administrator-permission requirement.

### Validation Items

1. [ ] (0A) `python -m worktrace.main` still starts the existing Tkinter UI.
2. [ ] (0B) `python -m worktrace.main --webview` starts the WebView UI.
3. [ ] (0A) WebView frontend resources do not contain `http://` or `https://` external links.
4. [ ] (0A) The WebView bridge does not import `worktrace.services`, `worktrace.db`, `worktrace.collector`, or `worktrace.security`.
5. [ ] (0B) Closing the WebView window triggers `AppRuntime.shutdown` and leaves no collector thread, folder-index worker, or database lock resident.
6. [ ] (0C) The PyInstaller build passes with the WebView entry point and resources bundled.
7. [ ] (0C) The per-user installer build passes and installs without administrator privileges.
8. [ ] (0C) The packaged `dist\WorkTrace.exe` defaults to the Tkinter UI and starts normally.
9. [ ] (0C) The packaged exe's WebView entry point (`WorkTrace.exe --webview`) can start.
10. [ ] (0C) When WebView2 Runtime is missing, WorkTrace shows a clear error or falls back to the Tkinter UI.

### Manual Validation Checklist

#### V. WebView Shell Startup (Phase 0B)

- [ ] Run `python -m worktrace.main --webview` from the source tree.
- [ ] A WorkTrace window opens showing the Overview page.
- [ ] The sidebar shows collector status (记录中 / 已暂停 / 采集器未运行).
- [ ] The pause/resume button toggles the status label.
- [ ] The Overview page shows today's date, total duration, and project count.
- [ ] The Overview page shows the current activity summary or "当前活动：无".
- [ ] The Overview page shows up to 20 recent sessions.
- [ ] The page auto-refreshes every 8 seconds without manual interaction.
- [ ] Clicking 时间详情, 统计与导出, 项目规则, 设置与隐私 shows the migration placeholder.
- [ ] Clicking 概览 returns to the Overview page.

#### W. WebView Window Close And Runtime Shutdown (Phase 0B)

- [ ] Start `python -m worktrace.main --webview` and let the collector run for a few seconds.
- [ ] Close the WebView window.
- [ ] The process exits cleanly (no lingering Python process in Task Manager).
- [ ] The collector thread is joined (no `WorkTraceCollector` thread resident).
- [ ] The single-instance lock is released (a second launch can acquire it).
- [ ] The `collector_status` setting is `stopped` after exit.
- [ ] No `activity_log` row has `end_time IS NULL` after a clean exit.

#### X. Phase 0C Source Run Validation

- [ ] `python -m worktrace.main` starts the Tkinter UI (default unchanged).
- [ ] `python -m worktrace.main --webview` starts the WebView UI.
- [ ] On a machine without WebView2 Runtime, `--webview` prints the clear missing-runtime message and exits with code 2.

#### Y. Phase 0C PyInstaller Build Validation

- [ ] `python -m PyInstaller --noconfirm --clean WorkTrace.spec` completes without error.
- [ ] `dist\WorkTrace.exe` exists.
- [ ] `dist\WorkTrace.exe` (no args) starts the Tkinter UI.
- [ ] `dist\WorkTrace.exe --webview` starts the WebView UI.
- [ ] The bundle includes `worktrace/webview_ui/index.html`, `app.js`, `styles.css` (verified by build success and runtime resource resolution).

#### Z. Phase 0C Installer Build Validation

- [ ] `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1` completes without error.
- [ ] `dist\WorkTrace-Setup.exe` exists.
- [ ] Installing with `WorkTrace-Setup.exe` does not prompt for administrator privileges (per-user install to `%LOCALAPPDATA%\Programs\WorkTrace`).
- [ ] The Start Menu shortcut launches the Tkinter UI by default.
- [ ] Running the installed `WorkTrace.exe --webview` launches the WebView UI.
- [ ] The installer does not download the WebView2 Runtime.

#### AA. Phase 0C WebView2 Runtime Missing Fallback

- [ ] On a Windows machine without the WebView2 Runtime, `WorkTrace.exe --webview` shows the message: "此功能需要 Microsoft Edge WebView2 Runtime。请安装 WebView2 Runtime，或继续使用默认 Tkinter UI。"
- [ ] No Python traceback is shown to the user.
- [ ] `WorkTrace.exe` (default Tkinter) still works on that machine.

#### AB. Phase 0C Post-Close Residual Validation

- [ ] After closing `WorkTrace.exe --webview`, no `WorkTrace.exe` process remains in Task Manager.
- [ ] No database lock file remains.
- [ ] A second launch of `WorkTrace.exe --webview` succeeds (single-instance lock released).

### Phase 0A/0B/0C Release Blockers

- `python -m worktrace.main` no longer starts the Tkinter UI.
- The WebView bridge imports `worktrace.services`, `worktrace.db`, `worktrace.collector`, or `worktrace.security`.
- WebView frontend resources contain `http://`, `https://`, CDN, or Google Fonts references.
- The frontend stores sensitive data in `localStorage` or `sessionStorage`.
- The bridge returns tracebacks to JS.
- The bridge logs window titles, file paths, notes, or copied text.
- Closing the WebView window leaves the collector thread or database lock resident.
- PyInstaller cannot bundle the WebView entry point and resources.
- The per-user installer requires administrator privileges.
- WebView2 Runtime is missing and WorkTrace fails with no clear error or fallback.
- A new network dependency or administrator-permission requirement is introduced.
