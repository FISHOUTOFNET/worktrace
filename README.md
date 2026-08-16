# WorkTrace v0.1 Lite

WorkTrace is a lightweight Windows local work-trace and CSV export helper. It
runs as a portable desktop app, records active-window metadata locally,
helps classify time into projects, and exports display-safe CSV activity
records.

> **Current state**: WebView (`pywebview` + Microsoft Edge WebView2 Runtime)
> is the only shipping UI — no Tkinter fallback, and the legacy
> `worktrace/ui` package has been deleted. Shipped behavior includes the
> fail-closed first-run privacy notice gate (collector and folder-index
> worker never start before acceptance), project rules with automatic
> application of enabled rules to eligible activities, encrypted `.wtbackup`
> backup export / manifest preview / import (replace-only), CSV export,
> and Timeline editing (project reclassification, time correction / split /
> merge, hide / soft delete / restore, batch project + note edits). The
> canonical one-screen snapshot of what ships today is
> [`docs/current-state.md`](docs/current-state.md); the full per-phase
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
  hide / soft delete / restore, batch project + batch note editing, and a
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
the notice is accepted. Closing the WebView window hides it to the Windows
notification area while collection continues. Use **退出 WorkTrace** from the
tray menu for a complete graceful shutdown.

## Windows Packaging

Local Windows packaging supports Python 3.11+ and Inno Setup 6.3.0+.
Install the normal build dependencies without forcing the CI baseline:

```powershell
python -m pip install -r requirements-dev.txt
```

Then run the canonical release build entry point:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_release.ps1
```

The release script checks only the supported Python minimum, builds the
single-file executable with PyInstaller in an isolated temporary
`build\release-staging\...` directory, publishes the versioned portable
executable to `dist\`, and builds the versioned installer from that staged
binary. `dist\` is therefore a publication boundary rather than a PyInstaller
work directory. The installer build verifies that the discovered `ISCC.exe`
is Inno Setup 6.3.0 or newer before compiling the original
`installer\WorkTrace.iss`; it does not rewrite a generated copy of the
installer source. The compiled installer is also checked directly to confirm
that it embeds the canonical 有迹 icon resource.

CI deliberately remains stricter for reproducibility: its verified baseline
uses Python 3.11.9, the checked-in `constraints-release.txt`, and Inno Setup
6.7.3. Those versions define the CI reference environment, not the only
supported local build environment.

Canonical release outputs are exactly `dist\Trace-<version>.exe` and
`dist\Trace-Setup-<version>.exe`. Unversioned release aliases such as
`dist\Trace.exe` and `dist\Trace-Setup.exe`, plus historical `WorkTrace*.exe`
release artifacts, are retired and removed by canonical release builds. The
installed application is still named `Trace.exe`; Inno Setup applies that
installed filename independently of the versioned release package filename.
Fresh installs go to `%LOCALAPPDATA%\Programs\Trace`, create the current-user
Start Menu shortcut `有迹`, install per-user only, and do not request
administrator privileges. Build artifacts under `build/` and `dist/` must not
be committed to Git.

If the portable release already exists and only the installer must be rebuilt,
pass that versioned executable explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1 -ExePath "dist\Trace-<version>.exe"
```

## Release Validation

Before a Windows release, use
[`docs/release-validation.md`](docs/release-validation.md) as the release-candidate baseline. Require the full non-benchmark Python suite and GitHub Actions CI to pass, and validate both the PyInstaller executable and the per-user installer lifecycle.

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

Local test selection is explicit. There is no changed-file/affected-test dependency map and no separate machine-readable test policy or inventory gate. Pytest owns collection and marker validation; `pytest.ini` enables strict markers. Standard CI remains the regression backstop and always runs the complete non-benchmark Python suite.

```powershell
# Known failure or owner
python -m pytest --lf
python -m pytest tests/test_timeline_service.py
python -m pytest tests/test_timeline_service.py::TestClassName::test_case

# Fast marker-covered feedback
python -m pytest -m "unit and not slow"

# Cross-layer/static contract feedback
python -m pytest -m contract
python -m pytest -m "webview_static and contract"
python -m pytest -m "live_display and contract"
python -m pytest -m "collector_runtime and integration"
python -m pytest -m "security_privacy"

# Full Standard-CI Python correctness surface
python -m pytest -m "not benchmark"
```

Use the narrowest explicit target that gives useful feedback during iteration. Use the full non-benchmark suite for DB/schema, collector/runtime, live display, privacy/security, recovery/concurrency, broad architecture changes, pre-push confidence, and release validation. Performance benchmarks and installer lifecycle acceptance stay in their dedicated workflows.

Test maintenance rules live in [`docs/testing/test-governance.md`](docs/testing/test-governance.md). Shared helpers live under `tests/support/`: use small domain factories for repeated setup, keep scenarios readable, and avoid large fixtures that hide behavior.

This project does **not** currently enable parallel pytest. The `parallel_safe` and `serial` markers remain planning labels only.

## Local Paths

- Database: `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`.
- Logs: `%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`.
- Optional COM path catalog: `%LOCALAPPDATA%\WorkTrace\com_path_catalog.json`.
- Default exports: `Documents\WorkTrace Exports`.

`schema.sql` is the single source of truth for the local database structure.
The project is in pre-release development, so old databases are not
guaranteed to be compatible; if the schema changes, delete the local
database file or use the Settings page to clear and rebuild all data.

## Current Limitations

- Windows is the intended production platform; non-Windows runs use the fake
  adapter.
- No service, driver, cloud sync, login, AI, OCR, screenshots, screen
  recording, or automatic startup.
- Settings / Privacy page exposes a read-only safety-status snapshot
  (storage model, clipboard capture on/off, export directory configured
  yes/no, encrypted-backup import-in-progress flag, first-run notice
  accepted state), a clipboard capture toggle write, encrypted backup
  export + manifest preview through native file dialogs, encrypted backup
  import (replace-only via native `.wtbackup` open dialog) +
  clear-all-local-data (explicit Chinese confirmation literal), and the
  first-run privacy notice gate (blocking overlay; user must accept before
  the collector starts) plus a read-only "view privacy notice" entry.
  The first-run gate is fail-closed: `webview_main` and `toggle_pause`
  never start the collector while the notice is unaccepted. The clipboard
  toggle only controls whether local clipboard recording is enabled; the
  page never reads or displays clipboard content. Encrypted backup import
  and clear-all-local-data both leave WorkTrace paused so the user can
  verify the post-replacement state before manually resuming recording;
  clear-all-local-data runs inside a destructive reset guard that blocks
  collector writes during the DB replacement. Save settings,
  `set_setting_value`, arbitrary file/folder dialogs, and export path
  setting are intentionally unsupported for v0.2 (not deferred).
- Hard delete project; raw folder-rule conflict preview; raw / unbounded
  batch backfill; automatic-rule enable / disable toggle in the UI; Excel /
  PDF / timesheet export; folder opening; and auto-submit are not
  supported. (Automatic rules application + selected-rule batch preview /
  apply / enable / disable and the single-rule impact preview + safe
  single-rule backfill foundation already ship; the items above remain
  backlog.)
