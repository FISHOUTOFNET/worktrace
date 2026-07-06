# WorkTrace Current State

> **Default entry point for AI tools and developers.** Read this file first.
> It is a one-screen snapshot of what WorkTrace ships today. For architecture
> decisions see [`ui-webview-migration.md`](ui-webview-migration.md); for the
> full per-phase history see
> [`history/webview-phases.md`](history/webview-phases.md).

## Current Shipped State

- WebView (`pywebview` + Microsoft Edge WebView2 Runtime) is the only
  shipping UI. The legacy `worktrace/ui` package has been deleted; there is
  no Tkinter fallback. Start with `python -m worktrace.main`. Missing
  WebView2 Runtime is a blocking error with a clear Chinese install prompt;
  WorkTrace never auto-downloads it.
- Closing the WebView main window exits WorkTrace and runs runtime shutdown.
  No tray hide-to-background lifecycle is currently shipped.
- The first-run privacy notice gate is **fail-closed**: the collector and
  folder-index worker must NOT start before the notice is accepted.
- `AppRuntime.initialize()` only performs DB init, single-instance lock,
  and recovery — it does NOT start the folder-index worker.
- The unified entry `app_api.start_collection_after_privacy_gate()` is
  the ONLY startup path for the folder-index worker AND the collector.
  It enforces the first-run notice read, the start ordering (background
  workers before collector), and the fail-closed payload in one place.
- `start_background_workers()` / `start_collector()` are runtime-internal
  helpers exported by `app_api` for the unified entry to call; the WebView
  bridge and `webview_main` MUST NOT call them directly. `toggle_pause` and
  `accept_first_run_notice` route startup through the unified entry and do
  NOT duplicate the gate read, start ordering, or fail-closed message.
- Both API and bridge layers collapse failures to stable Chinese messages
  and never return full paths, passphrases, salt, ciphertext, payload, SQL,
  or tracebacks. Full per-phase chronology lives in
  [`history/webview-phases.md`](history/webview-phases.md).

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
- **Settings / Privacy**: read-only safety-status plus clipboard capture
  toggle plus encrypted backup export / manifest preview / import
  (replace-only) / clear-all-local-data plus the first-run privacy notice
  gate + read-only "view privacy notice" entry. Shows storage model,
  clipboard-capture on/off, export directory configured yes/no,
  encrypted-backup import-in-progress flag, first-run notice accepted state.
  Import + clear-all leave WorkTrace paused; clear-all runs inside a
  destructive reset guard. The first-run gate is fail-closed (`webview_main`
  and `toggle_pause` never start the collector until accepted).

## Supported Timeline Write Operations

- Project reclassification of a session; session-note editing.
- Single-activity `start_time` / `end_time` correction (incl. session-level);
  single-activity split into two closed activities; two-activity merge of
  adjacent same-project / same-resource / same-status / same-source activities.
- Single-activity hide / soft delete; single-activity restore (un-hide +
  un-soft-delete).
- Batch project reassignment of multiple closed activities; batch note
  overwrite on multiple closed activities.
- Correction shell: a read-only context + navigation workspace reusing the
  above single/batch capabilities; unified, stabilized Timeline status /
  error semantics.

## Project Rules Capability Matrix

- Read project-grouped folder / keyword rule list; enable / disable existing
  folder / keyword rules; keyword + folder rule create / edit / delete.
- user project create / edit / enable-disable / archive.
- Single-rule impact preview for folder / keyword rules (display-safe counts +
  up to 20 sample rows; no raw window title / file path / note).
- Safe single-rule backfill for folder / keyword rules (≤ 100 updates per
  call; skips manual / hidden / deleted / in-progress / non-normal;
  `too_many_matches` writes nothing).
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
  semantics: live eligibility, `live_state`, display span identity, live
  clock fields, `<30s` borrowed-anchor/current-only display policy,
  `persisted_open` overlay, and the surface visibility flags consumed by
  page ViewModels. It never writes the DB; finished short-activity
  merge/drop remains collector/lifecycle-owned persistence.
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
