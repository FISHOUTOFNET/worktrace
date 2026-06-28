# WorkTrace WebView UI Migration

This document holds the **architecture decisions and migration principles** for
the WebView UI, plus a one-screen **current migration status summary**. The
full per-phase history (Phase 0A → Phase 5G "Implemented Scope" / "Not
Implemented" sections) lives in
[`docs/history/webview-phases.md`](history/webview-phases.md). For a quick
"what is shipped today" snapshot, read
[`docs/current-state.md`](current-state.md).

## Status

- Current phase: **5G (Project lifecycle foundation + in-phase
  hardening)**. Phase 5G opens four project-level Project Rules write
  capabilities on existing user projects: creating a user project,
  editing an existing user project's name / description, enabling /
  disabling an existing user project, and archiving an existing user
  project. The API / bridge / frontend three layers are wired through
  the stable `create_project_for_rules` / `update_project_for_rules` /
  `set_project_enabled_for_rules` / `archive_project_for_rules` facades
  with input validation (true int excluding bool, true bool, true str
  with trim), stable error codes (`invalid_input` / `not_found` /
  `system_project` / `duplicate_project` / `operation_failed`), Chinese
  error mapping at the bridge, narrow payloads, independent frontend
  state keys per project lifecycle write path, display-safe `editable`
  / `can_toggle` / `can_archive` / `is_system` flags on the Project
  Rules read projection, and explicit Project Rules page boundary copy.
  System / special projects (`created_by == "system"`, `未归类`,
  `排除规则`) are rejected for all four project lifecycle writes.
  Archive only sets `is_archived` and triggers the same three cache
  invalidation hooks as `set_project_enabled`. Create / update check
  for duplicate project names and collapse SQLite `IntegrityError` to
  `duplicate_project`. Phase 5G also ships the in-phase hardening
  regression locks (API/service system-project rejection,
  duplicate-name collapse, archive cache invalidation mirroring
  `set_project_enabled`, sensitive-field boundaries; bridge bool-as-int
  rejection, consistent error mapping, narrow payload, no cross-API
  pollution with keyword / folder rule writes, `delete_project` never
  exposed; frontend DOM anchors, state isolation, CSS scoping,
  no-forbidden-features, packaging inclusion) in the same phase rather
  than splitting into a separate 5G.1. It preserves the Phase 5B / 5B.1
  existing folder / keyword rule enable/disable path and its hardening,
  the Phase 5C keyword rule creation path, the Phase 5C.1 keyword
  creation hardening, the Phase 5D keyword rule deletion path, the
  Phase 5D.1 keyword deletion hardening, the Phase 5E folder rule CRUD
  foundation, the Phase 5E.1 folder rule CRUD hardening, and the Phase
  5F keyword rule edit foundation + in-phase hardening. Hard delete
  project, folder rule conflict preview, folder rule backfill,
  automatic rules, batch operations, schema changes, frontend
  frameworks / Node, browser storage, and network requests remain out
  of scope.
- Default UI: WebView (`pywebview` + Microsoft Edge WebView2 Runtime). It is
  the only shipping UI; there is no Tkinter fallback.
- Migrated pages: Overview (Phase 1), Timeline / Time Details (read-only in
  Phase 2, hardened in Phase 2.1, editing added across Phase 3A / 3B.x /
  3C.x), Statistics / Export (read-only in Phase 4A / 4A.1, CSV export write
  in Phase 4B, hardened in Phase 4B.1), Project Rules (read-only in Phase
  5A, hardened in 5A.1, existing folder / keyword rule enable/disable in
  Phase 5B, hardened in Phase 5B.1, keyword rule creation foundation in
  Phase 5C, keyword creation hardening in Phase 5C.1, keyword rule deletion
  foundation in Phase 5D, keyword deletion hardening in Phase 5D.1, folder
  rule CRUD foundation in Phase 5E, folder rule CRUD hardening in Phase
  5E.1, keyword rule edit foundation + in-phase hardening in Phase 5F,
  project lifecycle foundation + in-phase hardening in Phase 5G).
- Unmigrated pages: Settings / Privacy / Encrypted Backup (still legacy
  Tkinter code kept for reference; not a supported runtime path).
- Detailed phase-by-phase scope, data semantics, and "not implemented" lists
  for every phase are in [`docs/history/webview-phases.md`](history/webview-phases.md).

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
  feature pages (Rules, Settings) can be reference-migrated one page at a
  time. It is not a supported runtime path: tests must not assert that
  Tkinter is the default UI, and no code path may start it automatically.

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

- Plain HTML/CSS/JS is enough to exercise the bridge and render the pages. A
  framework is not needed to prove the migration path.
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

## 7. Migration Order (Summary)

The migration is phased so each step is independently shippable. Each phase's
full scope is in [`docs/history/webview-phases.md`](history/webview-phases.md);
the high-level order is:

- Phase 0A / 0B / 0C — design boundary, minimal WebView shell, and
  PyInstaller / installer / WebView2 Runtime packaging verification.
  **Completed.**
- Phase 1 — default WebView entry + Overview full migration + no Tkinter
  fallback. **Completed.**
- Phase 2 / 2.1 — Timeline read-only migration and validation hardening.
  **Completed.**
- Phase 3A / 3A.1 — Timeline basic editing (project reclassification,
  session-note editing) and hardening. **Completed.**
- Phase 3B.1 / 3B.1.1 — single-activity time correction foundation and
  hardening. **Completed.**
- Phase 3B.2 / 3B.2.1 — single-activity split foundation and hardening.
  **Completed.**
- Phase 3B.3 / 3B.3.1 — two-activity merge foundation and hardening.
  **Completed.**
- Phase 3B.4 / 3B.4.1 — single-activity hide / soft delete foundation and
  hardening. **Completed.**
- Phase 3B.5A / 3B.5B / 3B.5B.1 — correction action consolidation and the
  correction shell (read-only context + navigation workspace). **Completed.**
- Phase 3B.6 / 3B.6.1 — batch project editing foundation and hardening.
  **Completed.**
- Phase 3B.7 / 3B.7.1 — batch note editing foundation and hardening.
  **Completed.**
- Phase 3B.8 / 3B.8.1 — single-activity restore foundation and hardening.
  **Completed.**
- Phase 3B.9 / 3B.9.1 — correction shell consolidation and hardening.
  **Completed.**
- Phase 3C / 3C.1 — Timeline UI release stabilization and hardening.
  **Completed.**
- Phase 4A / 4A.1 — Statistics / Export read-only migration and hardening.
  **Completed.**
- Phase 4B — Export actions foundation (CSV export only). **Completed.**
- Phase 4B.1 — CSV export hardening / native save dialog + packaging
  validation. **Completed.**
- Phase 5A — Project Rules read-only foundation. **Completed.**
- Phase 5A.1 — Project Rules read-only hardening / regression. **Completed.**
- Phase 5B — Project Rules rule enable/disable foundation for existing
  folder / keyword rules only. **Completed.**
- Phase 5B.1 — Project Rules rule enable/disable hardening (regression-only
  follow-up to Phase 5B). **Completed.**
- Phase 5C — Project Rules keyword rule creation foundation (one new keyword
  rule on an existing rule-target project). **Completed.**
- Phase 5C.1 — Project Rules keyword creation hardening (regression-only
  follow-up to Phase 5C). **Completed.**
- Phase 5D — Project Rules keyword rule delete foundation (delete one
  existing keyword rule). **Completed.**
- Phase 5D.1 — Project Rules keyword deletion hardening (regression-only
  follow-up to Phase 5D). **Completed.**
- Phase 5E — Project Rules folder rule CRUD foundation (create / edit /
  delete one existing folder rule). **Completed.**
- Phase 5E.1 — Project Rules folder rule CRUD hardening (regression-only
  follow-up to Phase 5E). **Completed.**
- Phase 5F — Project Rules keyword rule edit foundation + in-phase
  hardening (edit the keyword text of one existing keyword rule).
  **Completed.**
- Phase 5G — Project Rules project lifecycle foundation + in-phase
  hardening (create a user project, edit an existing user project's
  name / description, enable / disable an existing user project,
  archive an existing user project). **Completed.**
- Phase 5D+ — remaining Project Rules write workflows (hard delete
  project, conflict preview, backfill, automatic rules, batch
  operations). Not started.
- Phase 6 — Settings / Privacy / Encrypted Backup. Not started.
- Cleanup — remove the legacy Tkinter UI, reached only after all feature
  pages are at parity in the WebView UI.

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
  `pywebview` produces a clear error message instead of an `ImportError`.
- Heavy optional dependencies stay lazy: `openpyxl` is imported only during
  Excel export, and Windows process-inspection dependencies are imported
  only when the real Windows adapter reads the foreground window.

## Entry Points

- `python -m worktrace.main` — starts the WebView UI (default, Phase 1).
- `python -m worktrace.main --webview` — accepted as a no-op compatibility
  flag. It does not change behavior; both `main([])` and
  `main(["--webview"])` start the WebView UI.
- `python -m worktrace.webview_main` — equivalent direct WebView entry
  point, retained for development convenience.
- `WorkTrace.exe` (packaged) — defaults to the WebView UI. The PyInstaller
  entry script forwards to `worktrace.main.main`, which defaults to WebView.

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
  via the registry pre-flight and shows a clear Chinese install prompt.
- WorkTrace never auto-downloads the WebView2 Runtime. Users install it
  manually from Microsoft.
- If the registry check passes but pywebview still fails to initialize
  (e.g. corrupt install), the exception is caught and the same clear
  message is shown. WorkTrace exits with a non-zero code; it does not fall
  back to Tkinter.
