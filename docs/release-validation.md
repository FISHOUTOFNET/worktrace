# 有迹 (Trace) v0.1 Release Validation

This checklist is the release-candidate validation baseline for 有迹 (Trace) v0.1.

## Scope

- Current validation target: 有迹 (Trace) v0.1.
- The goal is to confirm that Windows users can install, start, collect active-window metadata, classify activity, export, clear local data, and exit without crossing the documented privacy boundary.
- A release requires the full Python non-benchmark suite, WebView tests, the PyInstaller executable build, and the per-user installer lifecycle validation. Local marker shards are development aids only.
- The internal Python package remains `worktrace`; this is not a user-facing product name.
- Legacy compatibility identifiers are intentionally retained where changing them would break upgrades: `%LOCALAPPDATA%\WorkTrace`, `AppId=WorkTrace`, the legacy HKCU Run value name, and the existing single-instance IPC identity.

## Validation Environment

- Windows 10 or Windows 11 with a normal user account.
- Do not use administrator privileges.
- Prefer a clean or temporary Windows user profile.
- Validate the Python development run, PyInstaller single-file executable, and current-user installer.
- For a clean application-state test, `%LOCALAPPDATA%\WorkTrace` may be deleted. This remains the compatibility data root after the rename.
- A fresh installed build uses `%LOCALAPPDATA%\Programs\Trace`.
- New exports default to `Documents\有迹`.

## Basic Commands

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run the release Python suite:

```powershell
python -m pytest -m "not benchmark"
```

Start from source:

```powershell
python -m worktrace.main
```

Build the single-file executable:

```powershell
python -m PyInstaller --noconfirm --clean WorkTrace.spec
```

Build the installer:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1
```

## Automated Validation Checklist

- [ ] `python -m pytest -m "not benchmark"` passes.
- [ ] GitHub Actions Windows tests pass.
- [ ] WebView Node behavior tests pass.
- [ ] PyInstaller build smoke passes.
- [ ] `dist\Trace.exe` is generated.
- [ ] `dist\Trace-Setup.exe` is generated.
- [ ] Installer upgrade smoke passes with both the current executable name and the legacy `WorkTrace.exe` compatibility path.
- [ ] Upgrade removes a stale legacy executable and rewrites the enabled startup command to `Trace.exe`.
- [ ] No administrator-permission requirement is introduced.

## Manual Validation Checklist

### A. First Launch And Privacy Notice

- [ ] Start after deleting old local application data when a clean-state test is intended.
- [ ] Privacy notice appears under the 有迹 brand.
- [ ] Collection does not start before acceptance.
- [ ] Collection starts after acceptance.
- [ ] Database remains at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db` for upgrade continuity.
- [ ] Log remains at `%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`.

### B. Branding And Windows Shell

- [ ] Main WebView title is `有迹 · Trace`.
- [ ] Navigation brand displays `迹 / 有迹` and no user-facing `WorkTrace` label remains.
- [ ] Main executable is `Trace.exe`.
- [ ] Installer is `Trace-Setup.exe`.
- [ ] Start Menu and optional desktop shortcut are named `有迹`.
- [ ] Installer and application use the white `迹` icon on the product blue background.
- [ ] Settings says `登录 Windows 时自动启动有迹`.
- [ ] Tray tooltip/menu/notifications use 有迹 / Trace branding.

### C. Responsive UI And Windows Scaling

- [ ] At 100% scaling, verify 1080×720 and 800×540 with no page-level horizontal scrolling.
- [ ] At 125% scaling, verify navigation rail, Timeline project/duration row, Drawer, and two-step delete Dialog are not clipped.
- [ ] At 150% scaling, verify long Chinese project names, descriptions, Statistics filters, and Settings controls remain keyboard reachable.
- [ ] At 1366×768 and 1920×1080, verify page balance and local table scrolling.
- [ ] Verify focus rings, Escape close, focus trapping, and focus restoration for Drawer and Dialog.

### D. Normal Collection

- [ ] Open Notepad, Word, WPS, browser, or similar windows.
- [ ] Activity records appear in Time Details.
- [ ] App name, process name, window title, and duration look correct.
- [ ] Current activity timer increases in `hh:mm:ss`.
- [ ] Short fragments are consolidated according to the current session rules rather than polluting Timeline with avoidable slices.

### E. Projects And Rules

- [ ] Create a normal project.
- [ ] Add keyword and folder rules.
- [ ] Activity is classified automatically.
- [ ] Manual classification is not overwritten by automatic rules.
- [ ] Disabled projects no longer participate in automatic classification.
- [ ] The exclusion-rule project remains disabled by default and has no default rules.

### F. File Paths And Resource Recognition

- [ ] A full local path in a window title can be used as an anchor.
- [ ] Folder rules match supported local files and newly discovered descendants according to the current index policy.
- [ ] Files with the same name but non-unique paths are not classified incorrectly.
- [ ] WPS, Office, PDF, IDE, browser, and email resource types are represented reasonably in the UI.
- [ ] File body, email body, and webpage body are not read.

### G. Exclusion Rules And Privacy

- [ ] Enable the `排除规则` project and add a keyword or folder exclusion rule.
- [ ] Matching activity saves only anonymous information.
- [ ] Real app name, process name, window title, and path are not saved for excluded activity.
- [ ] Excluded records are not included in normal exports by default.
- [ ] Logs do not record the real title or path of excluded windows.

### H. Pause, Resume, Idle, And Recovery

- [ ] Pausing stops recording real window titles and resuming restores normal collection.
- [ ] Idle enters and exits correctly without generating excessive short records.
- [ ] Startup closes a previous abnormal-exit open record safely.
- [ ] Recovered duration is never negative.
- [ ] Records crossing midnight use the correct report date.

### I. Core UI Usability

- [ ] Overview shows today total, current activity, project/uncategorized distribution, and recent records.
- [ ] Current activity shows the actual resource rather than substituting the project name.
- [ ] Clicking current activity or a recent record locates the correct Timeline session.
- [ ] Timeline project correction, duration edit, notes, copy/split/merge, and deletion flows work.
- [ ] Statistics and CSV export remain consistent with the selected scope.
- [ ] Settings can toggle HKCU login startup and clipboard recording.
- [ ] UI refresh does not visibly clear and rebuild the whole page.
- [ ] Closing the main window hides it, keeps collection running, and tray/open-existing-instance activation restores it.
- [ ] Tray **退出有迹** shuts Runtime down cleanly.

### J. CSV Export

- [ ] A selected date range can be exported to CSV.
- [ ] New default export location is `Documents\有迹` unless the user selects another path.
- [ ] CSV is UTF-8 BOM so Excel opens Chinese headers correctly.
- [ ] Formula-injection escaping is preserved.
- [ ] Duration uses `hh:mm:ss`.
- [ ] Export does not expose raw paths, sensitive titles, notes, or clipboard text outside the documented boundary.

### K. Packaged Executable

- [ ] `dist\Trace.exe` starts.
- [ ] First-run privacy notice works.
- [ ] Bundled schemas and WebView resources load correctly.
- [ ] Closing the main window hides it while tray exit stops Runtime.
- [ ] Starting `Trace.exe` again activates the existing hidden instance.
- [ ] Administrator privileges are not required.

### L. Installer And Upgrade

- [ ] `dist\Trace-Setup.exe` runs.
- [ ] Fresh install defaults to `%LOCALAPPDATA%\Programs\Trace`.
- [ ] Current-user Start Menu shortcut is `有迹`; optional desktop shortcut is also `有迹`.
- [ ] Setup requests no UAC and uses `PrivilegesRequired=lowest`.
- [ ] Fresh install selects current-user login startup by default; disabling it leaves no startup value.
- [ ] Upgrade from an existing WorkTrace installation is recognized through the retained legacy AppId/uninstall identity.
- [ ] Upgrade can close either the old `WorkTrace.exe` or current `Trace.exe` cooperatively before replacement.
- [ ] Upgrade removes stale `WorkTrace.exe` and old `WorkTrace` shortcuts.
- [ ] If login startup was enabled before upgrade, its compatibility Run value points to `Trace.exe --background` afterward.
- [ ] Uninstall removes the startup value and stops a running Trace process.
- [ ] Existing `%LOCALAPPDATA%\WorkTrace` application data remains intact across the product rename.

## Privacy Boundary Acceptance

Explicitly verify:

- 不截屏。
- 不录屏。
- 不记录键盘。
- 不主动读取正文。
- 不上传数据。
- 剪贴板记录默认关闭。
- 命中排除规则的窗口只保存匿名时间块。
- 打包版和源码版在以上各项行为一致。

## Release Blockers

- Python, WebView, packaging, installer, or required GitHub Actions checks fail.
- The app cannot start or the installed executable is not `Trace.exe`.
- A fresh user-facing surface still presents the obsolete WorkTrace product name outside an explicitly documented compatibility identifier.
- Existing installations cannot upgrade in place or lose their local data.
- Collection starts before first-run privacy acceptance.
- Administrator privileges are required.
- Exclusion rules leak real window titles or paths.
- Installer cannot install under normal user permissions.
- Database contains negative durations or duplicate open records.
- Tray exit fails to stop Runtime, or window close hides without a recoverable tray/activation path.

## Release Record Template

- Date:
- Commit SHA:
- Windows version:
- Release decision: pass / blocked
