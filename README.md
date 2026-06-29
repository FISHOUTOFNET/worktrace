# WorkTrace v0.1 Lite

WorkTrace is a lightweight Windows local work-trace and CSV export helper. It
runs as a portable desktop app, records active-window metadata locally,
helps classify time into projects, and exports display-safe CSV activity
records.

> **Current state**: WebView Phase 6C is the latest shipped phase (Settings
> / Privacy encrypted backup export + manifest preview foundation). Project
> Rules now supports project-grouped folder / keyword rules, existing-rule
> enable / disable, keyword create / edit / delete, folder rule create /
> edit / delete, user project create / edit / enable-disable / archive,
> single-rule impact preview + safe single-rule backfill for folder /
> keyword rules, automatic application of enabled rules to newly produced /
> just-closed eligible activities, and selected-rule batch preview / apply
> / enable / disable. The Settings / Privacy page surfaces a read-only
> safety-status snapshot (storage model, clipboard capture on/off, export
> directory configured yes/no, encrypted-backup import-in-progress flag),
> opens the clipboard capture toggle write, and opens encrypted backup
> export + manifest preview through native file dialogs. The toggle writes
> `clipboard_capture_enabled` through a narrow bridge facade; the backup
> export writes an encrypted `.wtbackup` file via a native save dialog;
> the manifest preview reads only the non-sensitive manifest fields via a
> native open file dialog. Both API and bridge layers collapse failures to
> stable Chinese messages and never return full paths, passphrases, salt,
> ciphertext, payload, SQL, or tracebacks. Phase 6C does not read or
> display clipboard content. Encrypted backup import, save settings,
> clear-all-local-data, and arbitrary file/folder dialogs remain
> unsupported in WebView and arrive in later phases. Hard delete project,
> raw folder-rule conflict preview, raw / unbounded batch backfill, and
> the automatic-rule on/off UI toggle also remain unsupported. The
> canonical one-screen snapshot of what ships today is
> [`docs/current-state.md`](docs/current-state.md). The full per-phase
> history is [`docs/history/webview-phases.md`](docs/history/webview-phases.md).
> AI assistants: read [`docs/ai-context-guide.md`](docs/ai-context-guide.md)
> before touching the repo.

## Core Capabilities

- WebView desktop UI (`pywebview` + Microsoft Edge WebView2 Runtime) is the
  default and only shipping UI; no Tkinter fallback.
- SQLite local storage at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`.
- Background collector thread using pywin32/psutil on Windows; idle, paused,
  excluded, normal, and error activity states.
- First-run privacy notice before any collection starts.
- Project creation, manual assignment, notes, soft delete; file / folder /
  keyword project rules including the special local `排除规则`.
- Overview page (KPIs, current activity, recent activities, pause toggle).
- Timeline / Time Details page with editing: project reclassification,
  session-note editing, single-activity time correction / split / merge /
  hide / soft delete / restore, batch project and batch note editing, and a
  read-only correction shell.
- Statistics / Export page: read-only summary cards and grouped tables, plus
  CSV export (display-safe, UTF-8 BOM, no raw window title / file path /
  note). Excel / PDF / timesheet export are not supported.
- Project Rules page: project-grouped folder / keyword rule list with
  project / rule enabled state and the special local `排除规则`. Current
  capabilities: enable / disable existing folder / keyword rules; keyword
  rule create / edit / delete; folder rule create / edit / delete; user
  project create / edit / enable-disable / archive; single-rule impact
  preview (folder + keyword, display-safe counts + ≤ 20 sample rows);
  safe single-rule backfill (folder + keyword, capped at 100 updates per
  call, manual records preserved); automatic application of enabled rules
  to newly produced / just-closed eligible activities; selected-rule batch
  preview / apply / enable / disable (≤ 20 rules, batch apply capped at
  100 total updates, all-or-nothing). The special `排除规则` boundary is
  enforced. Unsupported: hard delete project, raw folder-rule conflict
  preview, raw / unbounded batch backfill, and the automatic-rule on/off
  UI toggle. Phase-by-phase chronology is archived in
  [`docs/history/webview-phases.md`](docs/history/webview-phases.md).
- Collector heartbeat and startup recovery for unclosed records; single-
  instance collector protection.

## Privacy And Permissions

无需注册。无需联网。无需管理员权限。不截屏。不录屏。不记录键盘。不主动读取
正文。不上传数据。命中排除规则的窗口只保存匿名时间块。复制文字记录默认关
闭；开启后仅本地保存复制到剪贴板的文本，并自动清理 30 天前的复制文字。
自动记录需由用户整理归类后再作为正式工时依据。

WorkTrace records the current application name, process name, window title,
identifiable local file path, local folder-rule file-name/path indexes,
start time, end time, duration, status, project, and notes. It does not
actively read Word/PDF/webpage/email body content, browser history, cookies,
passwords, camera, or microphone data.

## Portable Usage

Install dependencies in a Python 3.11+ environment:

```powershell
pip install -r requirements.txt
```

Start the app:

```powershell
python -m worktrace.main
```

The first launch shows the privacy notice. The collector starts only after
the notice is accepted. Closing the WebView window exits WorkTrace cleanly.

## Windows Packaging

Packaging is optional and relies on extra build dependencies that are not
part of the runtime requirements. Install the runtime dependencies first,
then add the build dependencies only when packaging:

```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Build the single-file executable:

```powershell
python -m PyInstaller --noconfirm --clean WorkTrace.spec
```

Build the per-user installer (run after the single-file executable has been
built, since the installer wraps `dist\WorkTrace.exe` as its payload):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1
```

Build outputs: `dist\WorkTrace.exe` (single-file application) and
`dist\WorkTrace-Setup.exe` (current-user installer). The installer copies
WorkTrace to `%LOCALAPPDATA%\Programs\WorkTrace`, creates a current-user
Start Menu shortcut, installs per-user only, and does not request
administrator privileges. Build artifacts (`build/`, `dist/`, generated
`.spec` files other than `WorkTrace.spec`) must not be committed to Git.

## Release Validation

Before a Windows release, use
[`docs/release-validation.md`](docs/release-validation.md) as the v0.1 Lite
release-candidate baseline. Run `pytest`, require GitHub Actions CI to pass,
and validate both the PyInstaller exe and the per-user installer.

## v0.2 Boundary And Local Security

The next-version boundary is documented in
[`docs/v0.2-boundary.md`](docs/v0.2-boundary.md). The Phase 1A / 1B local
security design (independent crypto foundation, DPAPI keyring, encrypted
`.wtbackup` export/import) is documented in
[`docs/v0.2-local-security-design.md`](docs/v0.2-local-security-design.md).
A `.wtbackup` file is a local encrypted file created on the user's request;
WorkTrace never uploads it. The backup passphrase is chosen by the user and
is not recoverable if forgotten. Import is replace-only and never damages
the current database on a wrong passphrase or corrupted backup.

## Tests

Tests run without requiring a real Windows foreground window and use
`worktrace.platforms.fake_adapter.FakeAdapter`.

### Local Test Strategy

The suite has grown past 2000 cases, so running the full `pytest` on every
small change is wasteful. Default to the affected-test runner for day-to-day
iteration; reserve the full suite for cross-cutting changes, pre-push, and
release validation.

```powershell
# Day-to-day: run only the tests affected by the current workspace changes
# (staged + unstaged vs HEAD). Pure standard library; no new dependencies.
python scripts/run_affected_tests.py

# Print the detected changed files and selected targets without running pytest
python scripts/run_affected_tests.py --list

# Print the final pytest command without executing it
python scripts/run_affected_tests.py --print-only

# Explicit full-suite fallback
python scripts/run_affected_tests.py --all

# Only consider staged changes; or diff against a custom base ref
python scripts/run_affected_tests.py --staged
python scripts/run_affected_tests.py --base HEAD

# Pass extra pytest arguments after --
python scripts/run_affected_tests.py -- --maxfail=1 -q
```

The runner maps changed source / docs / packaging paths to a conservative,
finite set of pytest targets. When nothing changed it runs a light smoke set
(startup imports, WebView bridge boundary, WebView static-contract suite) plus
the `import worktrace.webview_main` import smoke — it never silently runs the
full suite. PyInstaller and the per-user installer are **not** part of the
affected runner; they remain manual release-validation steps.

### Targeted and Full Test Commands

```powershell
# Single point of failure / known-failing tests from the last run
pytest --lf

# A specific test file or test case
pytest tests/test_timeline_service.py
pytest tests/test_timeline_service.py::TestClassName::test_case

# Full suite — use for core cross-cutting changes, pre-push, or release
# validation. Also runs in GitHub Actions CI.
pytest
```

## Local Paths

- Database: `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`
- Logs: `%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`
- Optional COM path catalog: `%LOCALAPPDATA%\WorkTrace\com_path_catalog.json`
- Default exports: `Documents\WorkTrace Exports`

`schema.sql` is the single source of truth for the local database structure.
The project is in pre-release development, so old databases are not
guaranteed to be compatible; if the schema changes, delete the local
database file or use the Settings page to clear and rebuild all data.

## Current Limitations

- Windows is the intended production platform; non-Windows runs use the fake
  adapter.
- No service, driver, cloud sync, login, AI, OCR, screenshots, screen
  recording, or automatic startup.
- Settings / Privacy page migrated to WebView in Phase 6A as a read-only
  status foundation, extended in Phase 6B with the clipboard capture
  toggle write, and extended in Phase 6C with encrypted backup export +
  manifest preview (storage model, clipboard capture on/off, export
  directory configured yes/no, encrypted-backup import-in-progress flag,
  plus the toggle, plus the backup export + manifest preview). Phase 6C
  does not read or display clipboard content; the toggle only controls
  whether local clipboard recording is enabled. Encrypted backup import,
  save settings, clear-all-local-data, and arbitrary file/folder dialogs
  remain unsupported in WebView and arrive in later phases.
- Hard delete project; raw folder-rule conflict preview; raw / unbounded
  batch backfill; automatic-rule enable / disable toggle in the UI; Excel /
  PDF / timesheet export; folder opening; and auto-submit are not
  supported. (Phase 5I ships automatic rules application + selected-rule
  batch preview / apply / enable / disable foundation, on top of the
  Phase 5H single-rule impact preview + safe single-rule backfill.)
