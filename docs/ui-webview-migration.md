# WorkTrace WebView UI Migration

## Status

- Current phase: 1 (Overview page fully migrated; WebView is the default and
  only shipping UI).
- Default UI: WebView (`pywebview` + Microsoft Edge WebView2 Runtime).
- The legacy Tkinter / CustomTkinter UI under `worktrace/ui` is retained only
  as legacy code pending removal. It is **not** a supported runtime path and
  must not be started by the default entry point.
- `python -m worktrace.main` starts the WebView UI. `python -m worktrace.main
  --webview` is accepted as a no-op compatibility flag and does not change
  behavior.
- The packaged `WorkTrace.exe` defaults to the WebView UI.

## 1. Phase 1 Is A Destructive Migration

Phase 1 changes the default UI from Tkinter / CustomTkinter to WebView. This
is a breaking change:

- **No fallback to Tkinter.** The default entry point
  (`worktrace.main.main`) delegates to `worktrace.webview_main.main` and does
  not import or instantiate the legacy `worktrace.ui.app.WorkTraceApp`. If
  the WebView backend fails to start, WorkTrace exits with a non-zero code;
  it does not attempt to start the Tkinter UI.
- **Missing WebView2 Runtime is a blocking runtime prerequisite.** On Windows,
  WorkTrace detects the WebView2 Runtime through the EdgeUpdate registry keys.
  If the runtime is missing, WorkTrace prints a clear Chinese install prompt
  and exits with a non-zero code. It never auto-downloads the runtime and it
  never falls back to Tkinter.
- **Legacy Tkinter code may remain only temporarily for reference/removal.**
  The `worktrace/ui` package is kept in the source tree so the remaining
  feature pages (Timeline, Statistics/Export, Rules, Settings) can be
  reference-migrated one page at a time. It is not a supported runtime path:
  tests must not assert that Tkinter is the default UI, and no code path may
  start it automatically.

## 2. Why pywebview

Phase 1 uses `pywebview` because:

- It is a Python library, so the UI stays inside the existing Python process
  and the existing `AppRuntime` lifecycle. No second language toolchain is
  introduced.
- It reuses the existing `worktrace.api` facade directly through a Python
  bridge, with no HTTP server required.
- It keeps the dependency surface small and inspectable for PyInstaller.
- It does not require Rust, Node, or a separate frontend build pipeline.

Tauri is rejected because it introduces Rust and a Node-based frontend build
chain, which conflicts with the current Python-only distribution and the v0.2
boundary of no new administrator-permission or network requirement.

## 3. Why The Python Backend And worktrace.api Stay

The migration preserves the existing single-process, multi-thread
architecture:

```
UI (WebView)  ──> Python bridge ──> worktrace.api ──> worktrace.services ──> worktrace.db
                                          │
        collector thread ──> worktrace.collector
```

- `worktrace.api` is the only layer the UI may import. The WebView bridge
  reuses the same boundary, so no new backend access path is opened.
- `AppRuntime` already owns the collector thread, folder-index worker,
  single-instance lock, recovery, and shutdown. The WebView entry point
  reuses it instead of duplicating lifecycle logic.
- Keeping the backend unchanged means collector, state machine, activity
  service, and secure backup service behavior is not touched by the
  migration.

## 4. Why No React / Vite / Vue

The migration does not introduce a JavaScript framework or build toolchain
because:

- Plain HTML/CSS/JS is enough to exercise the bridge and render the Overview
  page. A framework is not needed to prove the migration path.
- Adding Vite/React/Vue would add a Node build dependency, a build step, and
  bundle-output path management that the current distribution does not have.
- Keeping the frontend framework-free keeps the PyInstaller packaging story
  unchanged.

A framework may be chosen later as a separate decision. It is not
pre-committed by this document.

## 5. Why No Local HTTP Server

The migration does not introduce a local HTTP/FastAPI server because:

- `pywebview` exposes Python callables to JS directly through a JS bridge, so
  no HTTP listener is needed.
- A local server opens a listening port, which adds a network surface and a
  port-conflict risk that the v0.2 boundary explicitly wants to avoid.
- A server would also complicate the PyInstaller packaging and the
  no-administrator-permission requirement.

## 6. WebView UI Must Only Call worktrace.api Through The Bridge

The WebView UI layer (`worktrace.webview_ui`) follows the same backend
boundary as the legacy Tkinter UI:

- `worktrace.webview_ui.bridge` may import `worktrace.api` and nothing else
  from the backend. It must not import `worktrace.services`,
  `worktrace.db`, `worktrace.collector`, `worktrace.security`, or
  `worktrace.runtime`.
- The bridge must not return tracebacks to JS. It returns plain result or
  error objects (`{"ok": false, "error": "操作失败"}`).
- The bridge must not log window titles, file paths, notes, or copied text.
- The WebView entry point (`worktrace.webview_main`) may import
  `AppRuntime`, `config`, and `db` initialization helpers, mirroring how
  `worktrace.main` is structured. The bridge may not.

This is enforced by `tests/test_ui_backend_boundary.py`.

## 7. Migration Order

The migration is phased so each step is independently shippable:

- Phase 0A: design and boundary preparation (placeholder
  `worktrace/webview_ui` package, boundary tests). **Completed.**
- Phase 0B: minimal WebView shell. A window opens, the bridge calls
  `worktrace.api`, and `AppRuntime` lifecycle is exercised. Only the
  Overview page shows real data; other pages show a migration placeholder.
  **Completed.**
- Phase 0C: PyInstaller / installer / WebView2 Runtime packaging
  verification. **Completed.**
- Phase 1: **Default WebView entry + Overview full migration + no Tkinter
  fallback.** The default `python -m worktrace.main` starts the WebView UI;
  the packaged `WorkTrace.exe` defaults to the WebView UI; the legacy
  `--webview` flag is a no-op; the Overview page is a production page
  (collector status, pause/resume, today's date, total/classified/
  uncategorized duration, project count, current activity summary, recent
  sessions, auto-refresh, in-page error banner); missing WebView2 Runtime
  exits with a clear install prompt. **Current phase.**
- Phase 2: Timeline read-only.
- Phase 3: Timeline editing.
- Phase 4: Statistics / Export.
- Phase 5: Rules.
- Phase 6: Settings / Privacy / Encrypted Backup.
- Phase 7: remove the legacy Tkinter UI. This is a cleanup phase reached
  after all feature pages are at parity in the WebView UI. It is not a
  fallback dependency: Phases 1–6 ship with WebView as the only supported
  runtime UI.

## 8. Stop-Loss Conditions

The migration is re-scoped if any of the following cannot be resolved:

- PyInstaller build is unstable when bundling `pywebview` and the WebView
  resources.
- The per-user installer cannot install under a normal user account with the
  WebView entry point as the default.
- WebView2 Runtime is missing on a target machine and WorkTrace cannot show
  a clear error and exit cleanly.
- The JS-Python bridge is unstable (calls drop, callbacks leak, or types
  corrupt across the boundary).
- Closing the WebView window leaves the collector thread, folder-index
  worker, or database lock resident.
- Static resource paths differ between the development run and the packaged
  run and cannot be unified.
- Windows 10 startup fails with no diagnosis or fix path.

On stop-loss, the release is blocked until the issue is resolved. There is
no automatic Tkinter fallback: the Tkinter UI is legacy code, not a
supported runtime path.

## 9. Security Boundary

The migration keeps the existing local-first security posture:

- All HTML, CSS, and JS resources are local files bundled with the app. No
  remote resources are loaded.
- The WebView does not access the internet. No `http://` or `https://`
  external links appear in frontend resources. No CDN, no Google Fonts, no
  remote scripts.
- The frontend does not store sensitive data in `localStorage` or
  `sessionStorage`. The bridge is the only data path.
- The bridge does not return tracebacks to JS. It returns a generic error
  object.
- The bridge does not log window titles, file paths, notes, or copied text.
  It logs only operation name, result, and exception type, matching the
  existing logging-hygiene rules.
- The bridge does not import `worktrace.security` directly; encrypted backup
  access goes through `worktrace.api.backup_api`.

## Dependency Handling

`pywebview>=5.0` is declared in `requirements.txt`. It is the WebView
backend used by the default UI entry point.

- `pywebview` is imported lazily inside
  `worktrace.webview_main._check_pywebview_available`, so a missing
  `pywebview` produces a clear error message instead of an `ImportError`
  traceback.
- `customtkinter` remains in `requirements.txt` and is still bundled by
  `WorkTrace.spec` (`collect_all('customtkinter')`) because the legacy
  `worktrace.ui` package is still present in the source tree. The default
  WebView runtime path does not import `customtkinter`.
- Phase 0C confirmed `pywebview` bundles cleanly under PyInstaller
  (`collect_all('webview')`) and the per-user installer builds without
  administrator privileges.

## Entry Points

- `python -m worktrace.main` — starts the WebView UI (default, Phase 1).
- `python -m worktrace.main --webview` — accepted as a no-op compatibility
  flag. It does not change behavior; both `main([])` and
  `main(["--webview"])` start the WebView UI.
- `python -m worktrace.webview_main` — equivalent direct WebView entry
  point, retained for development convenience.
- `WorkTrace.exe` (packaged) — defaults to the WebView UI. The PyInstaller
  entry script forwards to `worktrace.main.main`, which defaults to WebView.

## Phase 1 Implemented Scope

Phase 1 made the WebView UI the default and only shipping UI:

- `worktrace/main.py` delegates to `worktrace.webview_main.main()` by
  default. It no longer imports or instantiates
  `worktrace.ui.app.WorkTraceApp`. The `--webview` flag is accepted as a
  no-op compatibility flag.
- `worktrace/webview_main.py` is the default entry point. When the WebView2
  Runtime is missing on Windows, it prints a clear Chinese install prompt
  and exits with a non-zero code. When `pywebview` is missing, it prints a
  clear install prompt and exits with a non-zero code. It never starts the
  Tkinter UI.
- `worktrace/webview_ui/runtime_check.py` detects the WebView2 Runtime via
  the EdgeUpdate registry keys on Windows. It never downloads anything,
  never raises, and returns `unknown` on non-Windows so tests are not
  blocked. The missing-runtime message only prompts the user to install the
  WebView2 Runtime from Microsoft; it does not mention Tkinter, fallback, or
  any `继续使用默认` wording.
- `worktrace/webview_ui/bridge.py` exposes `get_status`, `toggle_pause`,
  `get_overview`, `get_recent_activities`, and `get_timeline_placeholder`.
  The Overview methods are the production data path for the Overview page.
- `worktrace/webview_ui/index.html`, `app.js`, `styles.css` — local frontend
  resources with no external links, no CDN, no Google Fonts, and no browser
  storage APIs. The Overview page shows:
  - collector status (记录中 / 已暂停 / 采集器未运行 / 状态异常);
  - a pause/resume toggle button;
  - today's date;
  - today's total duration;
  - today's classified duration;
  - today's uncategorized duration;
  - today's project count;
  - the current activity summary or `当前活动：无`;
  - up to 20 recent sessions with project name, time range, status, and
    duration;
  - an in-page error banner that surfaces bridge errors without exposing
    tracebacks;
  - auto-refresh every 8 seconds.

The Timeline, Statistics/Export, Project Rules, and Settings/Privacy pages
show a migration placeholder. They are not migrated in Phase 1.

## Phase 1 Not Implemented

The following are explicitly not implemented in Phase 1 and remain on the
legacy Tkinter UI (which is legacy code pending removal, not a supported
runtime path):

- Timeline (read-only and editing);
- Statistics and Excel export;
- Project rules creation, editing, enable/disable;
- Settings, privacy notice, clipboard toggle, clear data;
- Encrypted `.wtbackup` export/import;
- Tray icon;
- Single-instance UI behavior (the WebView entry point does not add a
  tray; the collector single-instance lock is still enforced by
  `AppRuntime`).

## Legacy Tkinter UI Handling

The `worktrace/ui` package is retained in the source tree as legacy code
pending removal:

- The default runtime path (`worktrace.main.main`) does not import or
  instantiate `WorkTraceApp`.
- Documentation does not promise a Tkinter fallback.
- Tests do not assert that Tkinter is the default UI.
- Tests that previously verified the Tkinter default entry now verify the
  WebView default entry.
- The legacy code is not a supported runtime path. It exists only so the
  remaining feature pages can be reference-migrated one page at a time.
- No dual entry, automatic fallback, configuration switch, or UI selector is
  added for backwards compatibility.

## WebView2 Runtime Handling Strategy

- Windows 11 ships with the Evergreen WebView2 Runtime preinstalled; most
  Windows 11 machines need no action.
- Some Windows 10 machines do not have the runtime. WorkTrace detects this
  via the registry pre-flight and shows:
  "WorkTrace 需要 Microsoft Edge WebView2 Runtime 才能启动，但未检测到该运行时。请从 Microsoft 官方渠道下载并安装 Microsoft Edge WebView2 Runtime，然后重新启动 WorkTrace。"
- WorkTrace never auto-downloads the WebView2 Runtime. Users install it
  manually from Microsoft.
- If the registry check passes but pywebview still fails to initialize
  (e.g. corrupt install), the exception is caught and the same clear
  message is shown. WorkTrace exits with a non-zero code; it does not fall
  back to Tkinter.

## Phase 0C.1 Installer Script Hardening

Phase 0C surfaced one release-validation blocker that did not stop the
packaging spike but did stop the standard installer command from passing
directly:

- `scripts/build_windows_installer.ps1` sets `$ErrorActionPreference = "Stop"`
  globally. PyInstaller writes INFO logs to stderr, and PowerShell wraps
  native-command stderr as `NativeCommandError`, which under `Stop` becomes
  a terminating error. The script therefore falsely failed even when
  PyInstaller exited 0.

Phase 0C.1 fixed this without weakening global error handling:

- The global `$ErrorActionPreference = "Stop"` is retained so
  `Resolve-Path`, `Get-Command`, `New-Item`, and `Get-Item` failures still
  terminate.
- Around the native PyInstaller call, the script saves the old preference,
  locally sets `$ErrorActionPreference = "Continue"`, invokes PyInstaller,
  captures `$LASTEXITCODE`, and restores the preference in a `finally`
  block.
- A non-zero `$LASTEXITCODE` still throws.

Stop-loss conclusion after Phase 0C.1:

- The standard installer command
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1`
  passes directly.
- Static invariants are guarded by `tests/test_windows_installer_script.py`.
