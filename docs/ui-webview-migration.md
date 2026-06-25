# WorkTrace Optional WebView UI Migration

## Status

- Current phase: 0C (packaging, installer, and WebView2 validation).
- Default UI: Tkinter / CustomTkinter (unchanged).
- This document is a spike plan, not a commitment to ship a WebView UI.
- The WebView entry point `python -m worktrace.main --webview` is an opt-in spike;
  the default `python -m worktrace.main` is unchanged.

## 1. Why A WebView Spike

The current Tkinter / CustomTkinter UI has run into recurring limitations around
layout control, styling, refresh behavior, and widget fidelity. Before committing
to a full frontend rewrite, WorkTrace needs a low-risk spike to confirm whether an
embedded WebView shell can coexist with the existing Python backend and the
existing PyInstaller / per-user installer distribution chain.

The spike is intentionally narrow: validate the shell, the JS-Python bridge, the
runtime lifecycle, and the packaging path. It does not migrate any page and does
not remove Tkinter.

## 2. Why pywebview In Phase 0 (Not Tauri)

Phase 0 uses `pywebview` because:

- It is a Python library, so the spike stays inside the existing Python process and
  the existing `AppRuntime` lifecycle. No second language toolchain is introduced.
- It reuses the existing `worktrace.api` facade directly through a Python bridge,
  with no HTTP server required.
- It keeps the dependency surface small and inspectable for PyInstaller.
- It does not require Rust, Node, or a separate frontend build pipeline.

Tauri is rejected for Phase 0 because:

- It introduces Rust and a Node-based frontend build chain, which conflicts with
  the current Python-only distribution and the v0.2 boundary of no new
  administrator-permission or network requirement.
- It changes the packaging story (separate Tauri bundle) before the WebView shell
  has even been proven against the existing installer.
- It is a larger commitment than a spike should make.

Tauri may be revisited as a separate later-version decision if the WebView spike
succeeds and a full migration is approved. It is not part of Phase 0A/0B/0C.

## 3. Why The Python Backend And worktrace.api Stay

The spike preserves the existing single-process, multi-thread architecture:

```
UI (WebView)  ──> Python bridge ──> worktrace.api ──> worktrace.services ──> worktrace.db
                                          │
        collector thread ──> worktrace.collector
```

- `worktrace.api` is already the only layer the Tkinter UI may import. The WebView
  bridge reuses the same boundary, so no new backend access path is opened.
- `AppRuntime` already owns the collector thread, folder-index worker,
  single-instance lock, recovery, and shutdown. The WebView entry point reuses it
  instead of duplicating lifecycle logic.
- Keeping the backend unchanged means collector, state machine, activity service,
  and secure backup service behavior is not touched by the spike.

## 4. Why No React / Vite / Vue Yet

Phase 0 does not introduce a JavaScript framework or build toolchain because:

- The spike only validates the shell, bridge, runtime, and packaging. A framework
  is not needed to prove those.
- Adding Vite/React/Vue would add a Node build dependency, a build step, and
  bundle-output path management before the packaging path is proven.
- Plain HTML/CSS/JS is enough to exercise the bridge and confirm resource paths
  work in both development and PyInstaller-packaged runs.

A framework may be chosen later, after Phase 0C confirms packaging stability. It
is a separate decision and is not pre-committed by this document.

## 5. Why No Local HTTP Server First

Phase 0 does not introduce a local HTTP/FastAPI server because:

- `pywebview` exposes Python callables to JS directly through a JS bridge, so no
  HTTP listener is needed for the spike.
- A local server opens a listening port, which adds a network surface and a
  port-conflict risk that the v0.2 boundary explicitly wants to avoid.
- A server would also complicate the PyInstaller packaging and the
  no-administrator-permission requirement.

If a server is ever needed for a later phase, it must be re-evaluated against the
v0.2 boundary. It is not part of Phase 0A/0B/0C.

## 6. What Phase 0 Validates

Phase 0 only validates:

- the WebView shell can open a window;
- the JS-Python bridge can call `worktrace.api` and receive JSON-serializable
  results;
- `AppRuntime` initialize / start_collector / shutdown work from the WebView entry
  point;
- static resources (HTML/CSS/JS) resolve correctly in development and in a
  PyInstaller-packaged build;
- WebView2 Runtime availability is detected, with a clear error or fallback when
  it is missing;
- the per-user installer still installs without administrator privileges when the
  WebView entry point is present.

Phase 0 does not validate any feature page. Overview, Timeline, Statistics,
Rules, and Settings are out of scope for Phase 0.

## 7. Tkinter UI Remains The Default Fallback

- `python -m worktrace.main` continues to start the existing Tkinter UI.
- The packaged `WorkTrace.exe` continues to default to the Tkinter UI.
- The WebView entry point (`python -m worktrace.webview_main`) is a separate,
  opt-in spike entry point. It is not the default in Phase 0.
- If the WebView spike hits a stop-loss condition, the Tkinter UI remains the
  shipping UI and the WebView code can be deleted without affecting users.

## 8. WebView UI Must Only Call worktrace.api Through The Bridge

The WebView UI layer (`worktrace.webview_ui`) follows the same backend boundary as
the Tkinter UI:

- `worktrace.webview_ui.bridge` may import `worktrace.api` and nothing else from
  the backend. It must not import `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.security`, or `worktrace.runtime`.
- The bridge must not return tracebacks to JS. It returns plain result or error
  objects.
- The bridge must not log window titles, file paths, notes, or copied text.
- The WebView entry point (`worktrace.webview_main`) may import `AppRuntime`,
  `config`, and `db` initialization helpers, mirroring how `worktrace.main` is
  structured. The bridge may not.

This is enforced by `tests/test_ui_backend_boundary.py`.

## 9. Migration Order

The migration is phased so each step is independently revertible:

- Phase 0A: design and boundary preparation (this document, placeholder
  `worktrace/webview_ui` package, boundary tests). No WebView page, no entry
  point change. **Completed.**
- Phase 0B: minimal WebView shell. A window opens, the bridge calls
  `worktrace.api`, and `AppRuntime` lifecycle is exercised. Only the Overview
  page shows real data; other pages show a migration placeholder. **Completed.**
- Phase 0C: PyInstaller / installer / WebView2 Runtime packaging verification.
  Confirm the packaged exe and the per-user installer work with the WebView entry
  point, including the WebView2-missing fallback. **Completed.**
- Phase 1: Overview page.
- Phase 2: Timeline read-only.
- Phase 3: Timeline editing.
- Phase 4: Statistics / Export.
- Phase 5: Rules.
- Phase 6: Settings / Privacy / Encrypted Backup.
- Phase 7: remove the old Tkinter UI. This phase is only reached after all feature
  pages are at parity in the WebView UI.

Phases 1-6 keep the Tkinter UI as the default. Phase 7 is the only phase that
removes Tkinter, and only after parity validation.

## 10. Stop-Loss Conditions

The spike is abandoned or re-scoped if any of the following cannot be resolved:

- PyInstaller build is unstable when bundling `pywebview` and the WebView
  resources.
- The per-user installer cannot install under a normal user account with the
  WebView entry point present.
- WebView2 Runtime is missing on a target machine and WorkTrace cannot show a
  clear error or fall back to the Tkinter UI.
- The JS-Python bridge is unstable (calls drop, callbacks leak, or types corrupt
  across the boundary).
- Closing the WebView window leaves the collector thread, folder-index worker, or
  database lock resident.
- Static resource paths differ between the development run and the packaged run
  and cannot be unified.
- Windows 10 startup fails with no diagnosis or fix path.

On stop-loss, the Tkinter UI remains the shipping UI and the WebView code is
deleted. No user-facing behavior changes.

## 11. Explicit Non-Goals For Phase 0A

Phase 0A does not include:

- field-level encryption (that is Phase 1C of the v0.2 local security work);
- SQLCipher;
- AI, server, payment, license, token, or subscription features;
- any change to the database schema;
- any change to collector, state machine, activity service, or secure backup
  service behavior;
- any removal or replacement of the Tkinter UI;
- any change to the default `python -m worktrace.main` entry point;
- Tauri, Rust, Node, Vite, React, or Vue;
- network access or CDN dependencies;
- administrator-permission requirements.

## 12. Security Boundary

The WebView spike keeps the existing local-first security posture:

- All HTML, CSS, and JS resources are local files bundled with the app. No remote
  resources are loaded.
- The WebView does not access the internet. No `http://` or `https://` external
  links appear in frontend resources. No CDN, no Google Fonts, no remote scripts.
- The frontend does not store sensitive data in `localStorage` or
  `sessionStorage`. The bridge is the only data path.
- The bridge does not return tracebacks to JS. It returns a generic error object.
- The bridge does not log window titles, file paths, notes, or copied text. It
  logs only operation name, result, and exception type, matching the existing
  logging-hygiene rules.
- The bridge does not import `worktrace.security` directly; encrypted backup
  access goes through `worktrace.api.backup_api`.

## Dependency Handling

`pywebview>=5.0` was added to `requirements.txt` in Phase 0B. It is the only
new runtime dependency introduced by the WebView spike.

- The Tkinter-only path (`python -m worktrace.main`) does not import `pywebview`
  at module load time; `pywebview` is imported lazily inside
  `worktrace.webview_main._check_pywebview_available`, so a missing `pywebview`
  does not break the default Tkinter entry point.
- If the spike is abandoned, removing `pywebview` from `requirements.txt` and
  deleting `worktrace/webview_ui/` and `worktrace/webview_main.py` restores the
  Tkinter-only build with no other changes.
- Phase 0C confirmed `pywebview` bundles cleanly under PyInstaller
  (`collect_all('webview')`) and the per-user installer builds without
  administrator privileges.

## Entry Points

- `python -m worktrace.main` — existing Tkinter UI (default, unchanged).
- `python -m worktrace.main --webview` — WebView spike entry point (Phase 0C).
  Delegates to `worktrace.webview_main.main()`. The `--webview` flag is the
  single opt-in; without it the Tkinter UI starts.
- `python -m worktrace.webview_main` — equivalent direct WebView entry point,
  retained for development convenience.
- `WorkTrace.exe` (packaged) — defaults to Tkinter. `WorkTrace.exe --webview`
  starts the WebView shell; the PyInstaller entry script forwards `--webview`
  to `worktrace.main.main`.

## Phase 0B Implemented Scope

Phase 0B implemented the minimal shell only:

- `worktrace/webview_ui/bridge.py` — `WebViewBridge` with `get_status`,
  `toggle_pause`, `get_overview`, `get_recent_activities`, and
  `get_timeline_placeholder`. The bridge only imports `worktrace.api`.
- `worktrace/webview_ui/index.html`, `app.js`, `styles.css` — local frontend
  resources with no external links, no CDN, no Google Fonts, and no browser
  storage APIs.
- `worktrace/webview_main.py` — entry point that reuses `AppRuntime`,
  `config`, and `app_api`, creates the bridge, and starts pywebview. Importing
  the module does not start the GUI.

The Overview page shows real data: collector status, pause/resume button, today's
date, total duration, project count, current activity summary, and up to 20
recent sessions. The page auto-refreshes every 8 seconds.

The Timeline, Statistics/Export, Project Rules, and Settings/Privacy pages show a
migration placeholder. They are not migrated in Phase 0B.

## Phase 0B Not Implemented

The following are explicitly not implemented in Phase 0B and remain on the old
Tkinter UI:

- Timeline (read-only and editing);
- Statistics and Excel export;
- Project rules creation, editing, enable/disable;
- Settings, privacy notice, clipboard toggle, clear data;
- Encrypted `.wtbackup` export/import;
- Tray icon;
- Single-instance UI behavior (the WebView entry point does not add a second
  tray; the collector single-instance lock is still enforced by `AppRuntime`).

## Phase 0C Implemented Scope

Phase 0C validated the packaging and distribution chain for the optional
WebView entry point:

- `WorkTrace.spec` bundles `worktrace/webview_ui/index.html`, `app.js`,
  `styles.css` and collects `pywebview` via `collect_all('webview')`. The
  existing `schema.sql`, `open_files_helper.py`, `customtkinter`, and
  `win32timezone` entries are retained.
- `python -m worktrace.main --webview` routes to the WebView entry point. The
  default `python -m worktrace.main` (no flag) still starts the Tkinter UI.
- `scripts/pyinstaller_entry.py` forwards `--webview` to `worktrace.main.main`,
  so the packaged `WorkTrace.exe --webview` starts the WebView shell.
- `worktrace/webview_ui/runtime_check.py` detects the WebView2 Runtime via the
  EdgeUpdate registry keys on Windows. It never downloads anything, never raises,
  and returns `unknown` on non-Windows so tests are not blocked.
- When the runtime is missing, `worktrace.webview_main.main` prints a clear
  Chinese message and exits with code 2 instead of showing a traceback.

### WebView2 Runtime Handling Strategy

- Windows 11 ships with the Evergreen WebView2 Runtime preinstalled; most Windows
  11 machines need no action.
- Some Windows 10 machines do not have the runtime. WorkTrace detects this via
  the registry pre-flight and shows:
  "此功能需要 Microsoft Edge WebView2 Runtime。请安装 WebView2 Runtime，或继续使用默认 Tkinter UI。"
- WorkTrace never auto-downloads the WebView2 Runtime. Users install it manually
  from Microsoft, or simply continue using the default Tkinter UI.
- If the registry check passes but pywebview still fails to initialize (e.g.
  corrupt install), the exception is caught and the same clear message is shown.

### Phase 0C Stop-Loss Judgment

Phase 0C passes the stop-loss conditions:

- PyInstaller build succeeds with `webview_ui` resources and `pywebview` bundled.
- The per-user installer builds without administrator privileges.
- The WebView2 Runtime missing case produces a clear error message, not a crash.
- The `--webview` flag is forwarded through the packaged entry script.
- The default Tkinter entry point is unchanged.

### Phase 0C.1 Installer Script Hardening (Stop-Loss Supplement)

Phase 0C surfaced one release-validation blocker that did not stop the
packaging spike but did stop the standard installer command from passing
directly:

- `scripts/build_windows_installer.ps1` sets `$ErrorActionPreference = "Stop"`
  globally. PyInstaller writes INFO logs to stderr, and PowerShell wraps
  native-command stderr as `NativeCommandError`, which under `Stop` becomes a
  terminating error. The script therefore falsely failed even when PyInstaller
  exited 0, and Phase 0C worked around it by running an equivalent PyInstaller
  command directly.

Phase 0C.1 fixed this without weakening global error handling:

- The global `$ErrorActionPreference = "Stop"` is retained so
  `Resolve-Path`, `Get-Command`, `New-Item`, and `Get-Item` failures still
  terminate.
- Around the native PyInstaller call, the script saves the old preference,
  locally sets `$ErrorActionPreference = "Continue"`, invokes PyInstaller,
  captures `$LASTEXITCODE`, and restores the preference in a `finally` block.
- A non-zero `$LASTEXITCODE` still throws.

Stop-loss conclusion after Phase 0C.1:

- 0C.1 fixed installer script stderr handling.
- The standard installer command
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_installer.ps1`
  now passes directly.
- It is no longer necessary to bypass the script and run an equivalent
  PyInstaller command by hand.
- Static invariants are guarded by `tests/test_windows_installer_script.py`.

### Next Step

Phase 0C passes. The next step is **WebView Phase 1: Overview page migration**
(moving the real Overview data rendering fully into the WebView, replacing the
current minimal shell Overview).

If Phase 0C had failed, the recommendation would have been to pause the WebView
migration, record the failure reason, and either fix Tkinter or re-evaluate
Tauri. Since it passes, no rollback of the `pywebview` dependency is needed.
