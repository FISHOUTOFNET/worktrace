# WorkTrace Current State

> **Default entry point for AI tools and developers.** Read this file first.
> It is a one-screen snapshot of what WorkTrace ships today. For architecture
> decisions see [`architecture.md`](../architecture.md); history:
> [`history/webview-phases.md`](history/webview-phases.md).

## Current Shipped State

- WebView (`pywebview` + Microsoft Edge WebView2 Runtime) is the only
  shipping UI; no Tkinter fallback. Start with `python -m worktrace.main`.
  Missing WebView2 Runtime is a blocking Chinese prompt; no auto-download.
- Closing the WebView main window exits WorkTrace and runs runtime shutdown.
  No tray hide-to-background lifecycle is currently shipped.
- The first-run privacy notice gate is **fail-closed**: the collector and
  folder-index worker must NOT start before the notice is accepted.
- `AppRuntime.initialize()` only performs DB init, single-instance lock,
  and recovery. `app_api.start_collection_after_privacy_gate()` is the ONLY
  startup path for folder-index worker + collector and owns notice read,
  worker-before-collector ordering, and fail-closed payload. Runtime helper
  starts are not bridge or `webview_main` entry points.
- API/bridge failures collapse to stable Chinese messages and never return
  full paths, passphrases, salt, ciphertext, payload, SQL, or tracebacks.

## Migrated Pages

- **Overview**: KPIs (date / total / projects / classified /
  uncategorized), current activity, recent activities, error banner,
  pause/resume, auto-refresh.
- **Timeline / Time Details**: date navigation, daily total, session list,
  per-session activity details, read-only rendering hardened for real-run
  reliability, plus the editing / correction capabilities listed below.
- **Statistics / Export**: read-only summary cards, grouped tables (by
  project / by app / by status), export preview, CSV export write, and
  hardened save dialog / packaging / static contract.
- **Project Rules**: project-grouped rule list showing project name /
  description, project enabled state, special `排除规则` marker, folder
  rules, keyword rules, rule enabled state, and folder recursion scope.
  Current write capabilities are listed in the Project Rules matrix below.
- **Settings / Privacy**: safety status, clipboard capture toggle, encrypted
  backup export / manifest preview / replace-only import / clear-all, plus
  privacy notice view/gate. Import + clear-all leave WorkTrace paused; the
  first-run gate is fail-closed.

## Supported Timeline Write Operations

- Project reclassification of a session; session-note editing.
- Single-activity time correction (incl. session-level), split, and merge of
  adjacent same-project / same-resource / same-status / same-source rows.
- Single-activity hide / soft delete; single-activity restore (un-hide +
  un-soft-delete).
- Batch project reassignment of multiple closed activities; batch note
  overwrite on multiple closed activities.
- Correction shell: a read-only context + navigation workspace reusing the
  above single/batch capabilities; unified, stabilized Timeline status /
  error semantics.

## Project Rules Capability Matrix

- Read project-grouped folder / keyword rules; enable / disable existing
  rules; keyword + folder rule create / edit / delete.
- user project create / edit / enable-disable / archive.
- Single-rule impact preview (display-safe counts + up to 20 rows; no raw
  title / path / note) and safe backfill (≤ 100 updates; skips manual /
  hidden / deleted / in-progress / non-normal; `too_many_matches` writes none).
- Automatic application of enabled rules to eligible activities (skips manual
  / hidden / deleted / in-progress / disabled rules / archived projects).
- Selected-rule batch preview / apply / enable / disable (≤ 20 rules; batch
  apply ≤ 100 updates, all-or-nothing).
- Special `排除规则` boundary enforced (system / special projects rejected
  for lifecycle writes; enabling `排除规则` is never allowed).

## Statistics / Export Capability

- Read-only statistics summary (closed, non-hidden, non-deleted activities)
  with date-range validation (≤ 31 days).
- **CSV export write**: native save dialog, display-safe CSV (UTF-8 BOM,
  Chinese headers, formula-injection escaping). Returns basename only; never
  the full path, window title, file path, note, or clipboard.

## Explicitly Unsupported Capabilities

- Excel / PDF / timesheet-template export; folder opening; auto-open of the
  exported file; auto-submit of a timesheet.
- Hard delete project; raw folder-rule conflict preview (raw
  `preview_folder_rule_conflicts` NOT exposed to WebView; 5I reuses
  display-safe `rule_impact_service` helpers); raw / unbounded batch
  backfill; automatic-rule on/off UI toggle. These remain future backlog.
- Settings write actions intentionally unsupported for v0.2 (not deferred):
  save settings, `set_setting_value`, arbitrary file / folder dialog,
  export path setting. Only CSV save and `.wtbackup` save / open remain.
- Batch hide / batch delete / batch restore; permanent delete; undo stack;
  batch time / batch split / batch merge; note append / merge; auto-rule
  creation; global overlap detection.
- AI, server, payment, license, token, subscription, login, cloud sync, OCR,
  screenshots, screen recording, keyboard logging, automatic startup.
- Tray hide-to-background lifecycle or tray menu operation.
- Any DB schema change during development; `schema.sql` is the single source
  of truth. No Project Rules phase changed the schema.

## Architecture Boundary

```
WebView ──> bridge ──> worktrace.api ──> worktrace.services
  view_model_service (page ViewModel projection/materialization layer)
  activity_display_model_service (Activity Display Model / live display semantics owner)
    activity_display_policy / activity_live_clock / activity_display_span / activity_row_overlay
  live_display_service (low-level display-safe helper functions)
  activity_lifecycle_service (open-row command facade)
  activity_service (CRUD)
  collector ──> activity_lifecycle_service
```

Frontend JS: local classic scripts under `worktrace/webview_ui/js/` via
plain `<script src>` tags. No ES modules, bundler, Node/build step,
browser storage, or network requests. Bridge imports `worktrace.api` only
(enforced by `tests/test_ui_backend_boundary.py`).

- **`activity_display_model_service`** is the sole owner of live display
  semantics. Its focused sibling modules own policy, live clock, display
  span, and row overlay internals; together they decide live eligibility,
  `live_state`, display span identity, live clock fields, `<30s`
  borrowed-anchor/current-only display policy, `persisted_open` overlay,
  and the surface visibility flags consumed by page ViewModels. They never
  write the DB; finished short-activity merge/drop remains
  collector/lifecycle-owned persistence.
- **`view_model_service`** is the sole constructor of Overview / Timeline /
  Details / Refresh State page ViewModels from a single snapshot sample. It
  owns page projection/materialization only: DB list payloads, display-only
  fallback rows when the Activity Display Model permits them, KPI base
  fields, and JSON-safe page envelopes. It does not decide live display
  semantics independently.
- **`activity_lifecycle_service`** is the sole open-row command facade
  (collector / recovery / clipboard / midnight / shutdown); post-close
  inference is centralised in `finalize_closed_activity_ids`. The 30-second
  persistence threshold and the clipboard force-persist `STATUS_NORMAL`
  restriction are enforced INSIDE the facade; callers cannot bypass them.
- **`live_display_service`** provides low-level display-safe helper functions
  used by the Activity Display Model and refresh/current-summary paths:
  stable live identity helpers, current-activity summary helpers,
  classification helpers, and refresh-revision computation. It is not the
  page live-display model owner.
- **`App.liveRuntime`** is the frontend accepted runtime. The local ticker is
  DOM-only and renders `display_base_seconds + current_elapsed_now`; it must
  not call the bridge, write the DB, or derive live seconds from structural
  page caches.

## Privacy Boundary

- No registration, no network, no admin rights, no screenshots / recording /
  keyboard logging. Active window metadata only (app, process, window
  title, local file path hint, start/end time, duration, status, project,
  notes). No reading of document / email / webpage / browser-history bodies.
- Clipboard text recording is off by default; when enabled it stores copied
  text locally only and auto-clears entries older than 30 days. The
  clipboard toggle only controls this flag; the page never displays
  clipboard content.
- `.wtbackup` is a local encrypted file; WorkTrace never uploads it; the
  passphrase is not recoverable.

## Common Test Commands

- `python scripts/run_affected_tests.py` — affected tests (default; pure
  stdlib, maps changed paths to a finite pytest target set).
- `pytest` — full suite (cross-cutting changes, pre-push, release
  validation).
- Local paths: DB at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`; logs at
  `%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`; default exports at
  `Documents\WorkTrace Exports`.
