# WorkTrace Current State

> **Default entry point for AI tools and developers.** Read this file first.
> It is a snapshot of what WorkTrace ships today. For architecture decisions
> see [`architecture.md`](../architecture.md); history:
> [`history/webview-phases.md`](history/webview-phases.md).

## Current Shipped State

- WebView (`pywebview` + Microsoft Edge WebView2 Runtime) is the only
  shipping UI; no Tkinter fallback. Start with `python -m worktrace.main`.
- Closing the WebView main window exits WorkTrace and runs runtime shutdown.
- The installation privacy notice gate is fail-closed: collector, folder-index
  scanning, and clipboard capture cannot start before the current notice is
  accepted. Backup replacement and clear-all preserve installation consent but
  always leave WorkTrace paused and clipboard capture disabled.
- `AppRuntime` owns all long-lived sensitive runtime components. API/bridge
  failures collapse to stable Chinese messages and never return full paths,
  passphrases, ciphertext, SQL, or tracebacks.

## Migrated Pages

- **Overview**: canonical daily KPIs, current activity, recent activities,
  anonymous standalone excluded intervals, pause/resume, and auto-refresh.
- **Timeline / Time Details**: date navigation, daily total, canonical session
  list, per-session activity summaries, project/note editing for safe persisted
  open normal sessions, and the closed-session correction operations below.
- **Statistics / Export**: canonical summary cards and grouped tables, closed
  export preview, and CSV export guarded by an export-record revision.
- **Project Rules**: intentionally compact project-grouped list with project
  create/edit/delete, rule create/delete, folder rules, keyword rules, special
  `排除规则` marker, and recursion scope.
- **Settings / Privacy**: safety status, clipboard capture toggle, encrypted
  backup export/manifest/import, clear-all, and privacy notice view/gate.

## Supported Timeline Write Operations

- Project reclassification and session-note editing.
- Persisted open normal sessions permit project and note edits only; their
  natural duration and structural actions remain read-only until closed.
- Closed sessions support time correction, split, adjacent merge, copy, hide,
  and single-activity hide where the canonical capability flags allow it.
- Every Timeline write uses projection identity, durable revision, request
  receipt, operation ledger, replay, and authoritative post-state.

## Project Rules Shipping UI

The shipping UI deliberately exposes only common workflows:

- read project-grouped folder and keyword rules;
- create/edit/delete user projects;
- create/delete folder and keyword rules;
- create rules for the special `排除规则` project.

The UI intentionally does **not** expose rule enable/disable, rule editing,
project archive/enable-disable, rule-impact preview, history backfill, or batch
rule operations. These are low-frequency maintenance capabilities whose UI
state and cognitive cost would materially complicate the primary workflow.
Their absence is intentional and is not a frontend defect.

## Internal / API Project Rules Capabilities

The following backend/API capabilities remain available for tests, maintenance,
or future product decisions, but are not part of the shipping UI contract:

- enable/disable existing rules and edit folder/keyword rules;
- project enable-disable and archive;
- display-safe single-rule impact preview and bounded history backfill;
- selected-rule batch preview/apply/enable/disable;
- automatic application of enabled rules to eligible activities;
- special-project lifecycle and exclusion-rule policy enforcement.

Batch history application is first-rule-wins, bounded by unique activity IDs,
and all-or-nothing inside one `BEGIN IMMEDIATE` transaction.

## Statistics / Export Capability

- Read-only canonical statistics for closed, non-hidden, non-deleted entries,
  with inclusive date ranges of at most 31 days.
- `project_count` counts only concrete projects actually present in the range;
  “未归类” and anonymous “已排除” remain display buckets, not projects.
- CSV export uses the exact accepted closed-record `export_revision`; natural
  growth of an open activity cannot invalidate a closed-data export.
- CSV is UTF-8 BOM with Chinese headers and formula-injection escaping. Only
  the basename is returned to the UI.

## Explicitly Unsupported Capabilities

- Excel / PDF / timesheet-template export; folder opening; auto-open or
  auto-submit after export.
- Hard project delete, raw/unbounded rule backfill, automatic-rule global UI
  toggle, and the internal Project Rules maintenance capabilities listed above.
- Arbitrary settings writes, arbitrary file/folder dialog, and export-path
  setting. Only CSV save and `.wtbackup` save/open are shipping.
- Batch hide/delete/restore, permanent delete, general undo stack, batch time,
  batch split/merge, note append/merge, automatic rule creation, and global
  overlap detection.
- AI, server, payment, license, login, cloud sync, OCR, screenshots, screen
  recording, keyboard logging, automatic startup, and tray lifecycle.
- Schema migration support during development; `schema.sql` is the source of
  truth for the current cutover database.

## Architecture Boundary

```text
WebView -> bridge -> worktrace.api -> worktrace.services
  view_model_hardening_service (cross-surface metrics / structure revision adapter)
    view_model_service (page projection/materialization owner)
      activity_display_model_service (live display semantics owner)
  report_projection_snapshot_service (canonical report query)
  report_revision_service (structure/export revision semantics)
  report_session_operation_service + report_session_edit_service (mutation ledger)
  assignment_command_service (assignment write/retry boundary)
  privacy_gate_service + AppRuntime (sensitive runtime ownership)
  activity_lifecycle_service (open-row command facade)
  collector -> activity_lifecycle_service
```

Frontend JS uses local classic scripts only. `App.requestCoordinator` owns
request generations, shared read Promises, and database-replacement `dataEpoch`.
The heartbeat compares `structure_revision`; natural live seconds are rendered
by the DOM-only local ticker and do not request a full page reload.

- Canonical report facts are built only by
  `report_projection_snapshot_service`; Statistics, export, Overview, Timeline,
  and Details do not create competing report attribution models.
- `view_model_service` remains the page projection/materialization owner.
  `view_model_hardening_service` only corrects cross-surface metric/revision
  semantics and safe open-edit capability flags.
- All Timeline writes remain ledger operations with idempotent request receipts.
- Automatic and batch assignment commands share
  `assignment_command_service`; transient inference failures are marked using
  the existing assignment row and retried in bounded batches.

## Privacy Boundary

- No registration, network upload, admin rights, screenshots, recording, or
  keyboard logging. WorkTrace records active-window metadata and optional local
  clipboard text only after installation consent.
- Clipboard capture is off by default and cannot be enabled before consent.
- Folder-index scanning and collector start use the same privacy gate.
- `.wtbackup` is a local encrypted file. Business-data replacement does not
  replace the current installation's privacy acceptance.

## Common Test Commands

- `python scripts/run_affected_tests.py`
- `python -m compileall worktrace`
- `pytest`
- `node --test tests/webview/*.test.js`
- Failed CI publishes a one-day compact `pytest-diagnostics` artifact for exact
  failure identification without retaining the full pytest output.
- Local paths: DB at `%LOCALAPPDATA%\WorkTrace\data\worktrace.db`; logs at
  `%LOCALAPPDATA%\WorkTrace\logs\worktrace.log`; default exports at
  `Documents\WorkTrace Exports`.
