# WorkTrace v0.1 Release Validation

This checklist is the release-candidate validation baseline for WorkTrace v0.1 Lite.

## Scope

- Current validation target: WorkTrace v0.1 Lite.
- This document does not cover v0.2 AI, server features, payments, licensing, database encryption, automatic updates, or frontend migration.
- The goal is to confirm that Windows users can install, start, collect active-window metadata, classify activity, export, clear local data, and exit without crossing the documented privacy boundary.
- The local affected-test runner (`scripts/run_affected_tests.py`) and marker
  shard commands are **development accelerators only**. They select focused
  feedback based on changed paths or registered pytest markers and never invoke
  PyInstaller or the installer. They do **not** replace this release
  validation: a release still requires the full `pytest` suite to pass plus the
  PyInstaller exe and the per-user installer builds validated below.
- `scripts/test_inventory.py --check` is a governance gate for marker
  registration and static-test hygiene. It is not a substitute for pytest
  execution.
- This phase does not enable parallel pytest execution. `parallel_safe` and
  `serial` are planning markers only.

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
python scripts/test_inventory.py --check
pytest
```

Focused development feedback may use:

```powershell
python scripts/run_affected_tests.py
python scripts/test_inventory.py
pytest -m "webview_static and contract"
pytest -m "live_display and contract"
pytest -m "security_privacy"
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

### B. Responsive UI And Windows Scaling

Before functional collection checks, validate the redesigned WebView on a real
Windows 10/11 desktop. These scaling checks cannot be substituted by browser
viewport emulation.

- [ ] At 100% scaling, verify 1080×720 and 800×540 with no page-level horizontal scrolling.
- [ ] At 125% scaling, verify navigation rail, Timeline project/duration row, Drawer, and two-step delete Dialog are not clipped.
- [ ] At 150% scaling, verify long Chinese project names, long descriptions, Statistics filters, and Settings danger controls remain keyboard reachable.
- [ ] At 1366×768 and 1920×1080, verify page balance and local table scrolling.
- [ ] Verify focus rings, Escape close, focus trapping, and focus restoration for Drawer and Dialog.
- [ ] Verify current activity and LiveClock update once per second without screen-reader announcements.

### C. Normal Collection

- [ ] Open Notepad, Word, WPS, browser, or similar windows.
- [ ] Activity records appear in Time Details.
- [ ] App name, process name, window title, and duration look correct.
- [ ] Current activity timer increases in `hh:mm:ss`.
- [ ] Activities below 30 seconds do not immediately pollute history.
- [ ] Activities enter history normally after reaching the threshold.

### D. Projects And Rules

- [ ] Create a normal project.
- [ ] Add a keyword rule.
- [ ] Add a folder rule.
- [ ] Activity is classified automatically.
- [ ] Manual classification is not overwritten by automatic rules.
- [ ] Disabled projects no longer participate in automatic classification.
- [ ] The exclusion-rule project is disabled by default and has no default rules.

### E. File Paths And Resource Recognition

- [ ] A full local path in a window title can be used as an anchor.
- [ ] A full local file path with any extension can be used as an anchor.
- [ ] Folder rules can match non-Office and non-PDF files.
- [ ] Files with the same name but non-unique paths are not classified incorrectly.
- [ ] WPS, Office, PDF, IDE, browser, and email resource types are represented reasonably in the UI.
- [ ] File body, email body, and webpage body are not read.

### F. Exclusion Rules And Privacy

- [ ] Enable the `排除规则` project.
- [ ] Add a keyword or folder exclusion rule.
- [ ] Matching activity saves only anonymous information.
- [ ] Real app name, process name, window title, and path are not saved.
- [ ] Excluded records are not included in normal exports by default.
- [ ] Logs do not record the real title or path of excluded windows.

### G. Pause And Resume

- [ ] Clicking pause stops recording real window titles.
- [ ] Paused state displays correctly.
- [ ] Resuming records the current window again.
- [ ] UI state and collector state are consistent.

### H. Idle

- [ ] Reaching the idle threshold enters idle state.
- [ ] Idle does not continuously generate many short history records.
- [ ] User activity restores normal state.
- [ ] Idle records are handled in statistics and export according to README and architecture documentation.

### I. Abnormal Recovery

- [ ] Startup closes the previous abnormal-exit open record.
- [ ] Recovered record duration is not negative.
- [ ] Records that cannot be confirmed are marked as `error`.
- [ ] Records crossing midnight are handled under the correct report date.

### J. Basic UI Usability

- [ ] Overview shows today summary bar (total/classified/unclassified/project count), current activity, recent records, and attention items.
- [ ] Current activity shows the real resource (file/webpage/window/app name), not the project name.
- [ ] Current activity and recent record durations are allowed to differ (current_live vs aggregate_live).
- [ ] Attention items also appear in recent records (subset relationship, not disjoint).
- [ ] In-progress report session appears as the first recent record.
- [ ] Excluded state does not leak real window titles, paths, files, webpages or projects.
- [ ] Paused and error states do not retain stale activity content.
- [ ] Clicking current activity, a recent record, or an attention item locates the correct Timeline session.
- [ ] Clicking unclassified activity opens Time Details with the expected filter.
- [ ] Clicking a recent record locates the corresponding session.
- [ ] Time Details column widths, selection, copy, notes, and project correction work.
- [ ] Statistics/Export page statistics are reasonable.
- [ ] Settings/Privacy can show the privacy notice, toggle clipboard recording, and clear data.
- [ ] UI refresh does not visibly clear and rebuild the whole page.
- [ ] Minimize, restore, and resize do not crash the app.
- [ ] Closing the WebView main window exits WorkTrace and shuts down runtime cleanly.

### K. CSV Export

CSV export is the current public export capability.

- [ ] A selected date range can be exported to CSV.
- [ ] Output path is user-selected through the native save dialog or the
      documented export flow.
- [ ] CSV is UTF-8 BOM so Excel opens Chinese headers correctly.
- [ ] CSV uses Chinese headers.
- [ ] Formula-injection escaping is preserved (cells starting with `=` /
      `+` / `-` / `@` / tab are escaped).
- [ ] Duration uses `hh:mm:ss`.
- [ ] Default filtering for `excluded`, `idle`, `paused`, `is_deleted`, and
      `is_hidden` matches the documentation.
- [ ] The exported result does not expose raw window title / file path /
      note / clipboard text beyond the documented display-safe CSV boundary.
- [ ] Excel / PDF / timesheet-template export remain unsupported.

### L. Packaged Exe

- [ ] `dist\WorkTrace.exe` starts.
- [ ] First-run privacy notice works.
- [ ] `schema.sql` is bundled correctly.
- [ ] `open_files_helper` packaged path works.
- [ ] Closing the WebView main window exits WorkTrace and shuts down runtime cleanly.
- [ ] Administrator privileges are not required.

### M. Installer

- [ ] `dist\WorkTrace-Setup.exe` runs.
- [ ] App installs to `%LOCALAPPDATA%\Programs\WorkTrace`.
- [ ] Current-user Start Menu shortcut is created.
- [ ] Administrator privileges are not required.
- [ ] App starts from the shortcut.
- [ ] Installation directory and local data can be deleted for cleanup.

### Privacy Boundary Acceptance

Explicitly verify (these guarantees mirror README.md and the exclusion-rule
boundary above):

- 不截屏。
- 不录屏。
- 不记录键盘。
- 不主动读取正文。
- 不上传数据。
- 剪贴板记录默认关闭。
- 命中排除规则 的窗口只保存匿名时间块（不保存真实标题/路径）。
- 打包版和源码版在以上各项行为一致。

In English, for reviewers: no screenshots, no screen recording, no keyboard
logging, no active body-content reading, no data upload, clipboard recording
off by default, exclusion-rule matches store only anonymous time blocks, and
the packaged build behaves identically to the source-run build.

## Release Blockers

- `pytest` fails.
- GitHub Actions fails.
- The app cannot start.
- Collection starts before the first-run privacy notice is accepted.
- Administrator privileges are required.
- Network, login, or cloud-sync dependencies appear.
- The app records screenshots, keyboard input, body content, browser history, cookies, or passwords.
- Exclusion rules leak real window titles or paths.
- PyInstaller exe cannot start.
- Installer cannot install under normal user permissions.
- Database contains negative durations or duplicate open records.
- Window close or app exit fails and leaves a collector running.

## Release Record Template

- Date:
- Commit SHA:
- Windows version:
- Release decision: pass / blocked
