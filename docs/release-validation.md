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
