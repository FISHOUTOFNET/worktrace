# WorkTrace Architecture Contract

This document records the current architecture contract for WorkTrace. For the
one-screen shipped-behavior snapshot, start with
[`docs/current-state.md`](docs/current-state.md). Historical WebView migration
phases live under [`docs/history/webview-phases.md`](docs/history/webview-phases.md).

## Product Boundary

WorkTrace is a local Windows work-trace and timesheet helper. It runs without
registration, network access, cloud sync, administrator privileges, a Windows
service, a driver, automatic startup, screenshots, screen recording, OCR, or
keyboard logging.

The current public export capability in the WebView UI is display-safe CSV
export. Excel, PDF, and timesheet-template export are not current public
WebView export capabilities.

The shipping UI is WebView-only (`pywebview` + Microsoft Edge WebView2
Runtime). The legacy `worktrace/ui` package has been deleted. There is no
Tkinter fallback. Closing the WebView main window exits WorkTrace and runs
runtime shutdown; no tray hide-to-background lifecycle is currently shipped.

## Runtime Shape

```text
WebView UI
  └─ bridge mixins under worktrace.webview_ui
      └─ worktrace.api facades
          └─ worktrace.services
              ├─ page ViewModel projection
              ├─ Activity Display Model semantics
              ├─ activity lifecycle commands
              ├─ DB/report services
              └─ collector-facing services
```

`worktrace.webview_ui` may reach backend behavior only through `worktrace.api`.
Bridge modules must not import `worktrace.services`, `worktrace.db`,
`worktrace.collector`, `worktrace.security`, `worktrace.runtime`, or
`worktrace.config` directly. This is enforced by
`tests/test_ui_backend_boundary.py`.

`worktrace.webview_main` owns application startup: resolve paths, initialize
logging, initialize `AppRuntime`, register it with `app_api`, start the
privacy-gated runtime entry, run the WebView loop, and call
`runtime.shutdown()` when the WebView loop exits.

## Startup And Privacy Gate

The first-run privacy notice gate is fail-closed. The collector and
folder-index worker must not start before the notice is accepted.

`app_api.start_collection_after_privacy_gate()` is the unified startup entry
for background workers and collector startup. It owns the first-run notice
read, fail-closed payload, and ordering of background workers before the
collector. `webview_main`, bridge methods, and frontend code must not duplicate
that logic.

`AppRuntime.initialize()` performs DB initialization, single-instance lock, and
recovery. It does not start the folder-index worker or collector directly.

## Activity Lifecycle Boundary

`activity_lifecycle_service` is the sole open-row command facade. Collector,
recovery, clipboard force-persist, midnight split, shutdown, and close-all
paths must route open-row lifecycle changes through this facade.

The 30-second persistence threshold is enforced inside
`activity_lifecycle_service.persist_open_activity_if_ready()`. Callers must
pass elapsed seconds but must not independently decide persistence eligibility
as the final authority.

Clipboard force-persist goes through
`activity_lifecycle_service.force_persist_open_activity_for_clipboard()` and is
restricted to `STATUS_NORMAL` inside the facade.

Post-close project inference is centralized through
`finalize_closed_activity_ids()` so closed-row convergence is consistent across
collector, recovery, shutdown, and manual lifecycle paths.

## Collector Boundary

The collector and `CollectorStateMachine` own activity observation and hard
session boundaries. `AutoActivityRecorder` owns the current runtime activity,
project ownership pending state, and finalization of the current activity.

Short-activity persistence is collector/lifecycle-owned:

- A normal activity shorter than 30 seconds is not persisted as its own DB row.
- If it ends with a legal closed normal anchor and no hard boundary blocks
  absorption, its seconds may merge into that anchor.
- If no legal anchor exists, it is dropped.
- Display-only borrowed-anchor projection must never write the DB.

Hard boundaries include pause, stop, shutdown, time jump, midnight, idle,
excluded, error, privacy, secure import, and first-run-gate boundaries. These
boundaries prevent stale project ownership or pending seconds from crossing
session semantics.

## Activity Display Model Boundary

`activity_display_model_service` is the sole owner of live display semantics.
It decides:

- live eligibility;
- `live_state` (`current_only_pending`, `borrowed_anchor_pending`,
  `persisted_open`, `status_only`, `suppressed`);
- display span identity;
- live clock fields;
- display base policy;
- borrowed-anchor/current-only `<30s` display policy;
- `persisted_open` overlay semantics;
- surface visibility for Recent, Timeline, Details, and KPI projection.

It never writes the DB. It builds display-safe JSON payloads only.

`live_display_service` is not the page live-display model owner. It provides
low-level display-safe helper functions used by the Activity Display Model and
refresh/current-summary paths: stable live identity, display-safe field
extraction, current-activity summary helpers, classification helpers,
persisted-open helper functions, and refresh-revision computation.

`view_model_service` is the sole page ViewModel projection/materialization
layer. It calls the Activity Display Model once per request from a single
snapshot sample, then assembles Overview / Timeline / Details / Refresh State
payloads. It may project or materialize live rows only from Activity Display
Model spans. It must not independently decide live display semantics.

## Live Time Formula

The frontend has one accepted runtime: `App.liveRuntime`.

Every tickable live target must render from:

```text
display_seconds = display_base_seconds + current_elapsed_now
```

Current Activity uses base `0`. Recent, Timeline, Details, and KPI targets use
their own static display base plus the same current elapsed source.

`App.applyLocalTicker()` is DOM-only. It must not call the bridge, write the DB,
start or stop the collector, or derive live seconds from structural caches such
as `lastOverviewSnapshot`, `lastRecentData`, `lastTimelineData`, or
`lastSessionDetailsViewModel`.

Natural elapsed growth must not force a heavy page refresh. Structural changes,
such as live state handoff or page structure changes, flow through
`refresh_revision` / `live_state_revision` / `page_structure_revision`.

## DB / Report Boundary

`timeline_service`, `statistics_service`, and `export_service` are DB/report
layers. They must not read `current_activity_snapshot`, import
`activity_display_model_service`, or invoke live projection helpers. Report
outputs are based on persisted DB rows, not frontend live runtime state.

The WebView Statistics / Export page exposes display-safe CSV export through
the controlled export path. Export results return basenames only and must not
surface raw local paths, SQL, tracebacks, clipboard content, or internal
exception messages.

## Frontend Boundary

Frontend resources are local classic scripts under `worktrace/webview_ui/js/`
loaded by plain `<script src>` tags. There is no ES module pipeline, bundler,
Node build step, remote script, CDN, external link dependency, browser storage,
or network request requirement.

Page payloads may be rendered only after proving compatibility with the
accepted live runtime. Incompatible payloads request a refresh instead of
mixing stale runtime state with new structural payloads.

## Test Boundary

Use these default validation commands for architecture-contract cleanup:

```powershell
python scripts/comment_hygiene.py --check
python scripts/test_inventory.py --check
python scripts/run_affected_tests.py
pytest tests/test_display_model_anti_regression.py tests/test_ui_backend_boundary.py tests/test_release_docs.py -q
```

Run full `pytest` for collector/lifecycle/display-model behavior changes,
DB/schema changes, release validation, or pre-push validation.
