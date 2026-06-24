# WorkTrace v0.1 Release Checklist

This checklist defines the minimum acceptance items for promoting the current v0.1 Lite development build to a release candidate. It is a manual acceptance document unless a section explicitly says a command is automated.

Items marked as **Release Blocker** in section 9 must all pass before tagging a release. Windows-only steps (sections 6 and 7) are skipped on non-Windows acceptance environments, but every other section must still pass.

## 1. Clean Environment

- Windows 10 or Windows 11.
- Python 3.11+.
- A fresh virtual environment created for the acceptance run.
- Runtime dependencies installed:
  ```powershell
  pip install -r requirements.txt
  ```
- Build dependencies installed only when exercising the packaging steps in sections 6 and 7:
  ```powershell
  pip install -r requirements-dev.txt
  ```

Acceptance:

- The environment contains no leftover `build/` or `dist/` directories from a previous run.
- No WorkTrace database exists at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db` (or it has been deleted via Settings → clear data) so the first-run privacy notice is exercised.

## 2. Automated Tests

Command:

```powershell
pytest
```

Acceptance:

- All tests pass.
- Tests do not require a real Windows foreground window.
- Non-Windows environments are allowed to use `worktrace.platforms.fake_adapter.FakeAdapter`.

## 3. Source Run Smoke Test

Command:

```powershell
python -m worktrace.main
```

Acceptance:

- First launch shows the privacy notice.
- The collector does not start before the notice is accepted.
- After acceptance, the collector starts.
- The UI renders without errors.
- Closing the main window hides WorkTrace to the tray.
- From the tray menu: show, pause/resume, and exit all work.
- On exit, the currently open activity record is closed (no `end_time IS NULL` row remains).

## 4. Core Functional Manual Test

At minimum, verify:

- Normal activity records are created and persisted after the 30-second threshold.
- Idle records are produced after the idle threshold.
- Paused records are produced while recording is paused.
- Exclusion-rule matches are recorded as anonymous `已排除窗口` time blocks (no real title/path stored).
- Project creation from the Project Rules page.
- Folder project rule matching against a known local path.
- Keyword project rule matching against app/process/title metadata.
- Manual project correction on a selected session or detail activity.
- Session note auto-save (no separate save button; user text is persisted).
- Excel export from the Statistics/Export page.
- Clear all local data from Settings using the exact confirmation text.
- Recovery of an unclosed record after an abnormal exit (startup recovery closes `end_time IS NULL` rows).
- Single-instance collector protection: a second UI instance does not start a second collector.

## 5. Resource Detection Manual Test

At minimum, verify:

- Office/WPS document title is recognized as `office_document`.
- PDF viewer title is classified correctly.
- Browser tab is recognized as `browser_tab`.
- IDE file path is recognized as `ide_file`.
- A known full local file path is used as the resource anchor.
- A title-only file window falls back to the folder-rule index.
- The folder-rule index fallback only accepts a path when unambiguous.
- An ambiguous file name (same name under multiple active projects) is not forcibly classified.

## 6. Packaging Test

Command:

```powershell
python -m PyInstaller --noconfirm --clean WorkTrace.spec
```

Acceptance:

- `dist\WorkTrace.exe` is generated.
- Double-clicking `dist\WorkTrace.exe` launches the app.
- The first-run privacy notice appears normally.
- `schema.sql` is correctly bundled (the app initializes the database without a "schema not found" error).
- The `open_files_helper` path works in packaged mode (`WorkTrace.exe --open-files-helper` re-entry).
- The app does not request administrator privileges.

## 7. Installer Test

Command (run after section 6, since the installer wraps `dist\WorkTrace.exe`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1
```

Acceptance:

- `dist\WorkTrace-Setup.exe` is generated.
- Double-clicking the installer installs to `%LOCALAPPDATA%\Programs\WorkTrace`.
- A current-user Start Menu shortcut is created.
- The installed app launches successfully.
- The installer does not write under `Program Files`.
- The installer does not request administrator privileges.

## 8. Privacy Regression

Explicitly verify (these are the same guarantees documented in README.md):

- 不截屏。
- 不录屏。
- 不记录键盘。
- 不主动读取正文。
- 不上传数据。
- 剪贴板记录默认关闭。
- 命中排除规则的窗口只保存匿名时间块（不保存真实标题/路径）。
- 打包版和源码版在以上各项行为一致。

In English, for reviewers: no screenshots, no screen recording, no keyboard logging, no active body-content reading, no data upload, clipboard recording off by default, exclusion-rule matches store only anonymous time blocks, and the packaged build behaves identically to the source-run build.

## 9. Release Blockers

Any of the following failures is a release blocker and must be resolved before tagging the release:

- `pytest` fails.
- The app cannot be started from source.
- Packaging (`python -m PyInstaller --noconfirm --clean WorkTrace.spec`) fails.
- The installer (`scripts\build_windows_installer.ps1`) fails to build or install.
- Collection starts before the first-run privacy notice is accepted.
- An exclusion-rule match leaks a real window title or file path.
- Exiting from the tray leaves an open activity record (`end_time IS NULL`).
- Clearing local data leaves the database in a state that cannot be re-initialized.
- The packaged build cannot find `schema.sql` or the `open_files_helper` entry point.
- The documented build steps in `README.md` do not match the actual commands in this checklist.
