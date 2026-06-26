# WorkTrace WebView UI Migration

## Status

- Current phase: 3B.6 (Overview fully migrated; Timeline read-only page
  migrated and hardened; Timeline basic editing — project reclassification
  and session-note editing — implemented and hardened; Timeline time
  correction foundation — single-activity start/end time editing —
  implemented and hardened; Timeline activity split foundation — single
  closed activity split into two closed activities — implemented and
  hardened; Timeline activity merge foundation — two closed activities
  merged into one — implemented and hardened; Timeline hide / soft delete
  foundation — single closed activity hide and soft delete — implemented
  and hardened; Timeline correction action consolidation — per-activity
  actions grouped into edit / merge / danger groups with unified
  dirty-state guards, refresh semantics, and section labels — implemented;
  Timeline correction shell / advanced edit layout — a read-only context
  + navigation shell inside the Timeline page that reuses the existing
  single project / note / time / split / merge / hide / delete capability
  without adding any new backend write semantics — implemented;
  Timeline correction shell hardening — navigation, auto-refresh,
  dirty-state, selected-session-disappear, display-safe field boundary,
  click-to-locate, and close / reset path stabilization — implemented;
  Timeline batch project editing foundation — the first batch write
  capability: multiple closed activities in the correction shell can be
  reassigned to one project via an atomic transaction with rowcount guard
  and full rollback, rejecting in-progress / hidden / deleted activities —
  implemented; WebView is the default and only shipping UI).
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
  exits with a clear install prompt. **Completed.**
- Phase 2: **Timeline read-only migration.** The Timeline / Time Details
  page is migrated as a read-only page: date navigation (prev/today/next),
  daily total duration, current activity summary, session list with project
  name / time range / duration / status / event count, per-session activity
  detail view (time range, duration, app name, resource type, resource
  display name, project name, status), empty state, loading state, in-page
  error banner, and auto-refresh when the Timeline page is active. No
  editing, correction, reclassification, note modification, or deletion is
  exposed. **Completed.**
- Phase 2.1: **Timeline read-only validation hardening.** Hardens the
  Phase 2 Timeline page so it is reliable, readable, secure, and
  maintainable under real user use. Specifically: the bridge
  `resource_name` no longer falls back to the raw `window_title` column
  (it uses a safe chain `resource_display_name` →
  `activity_display_name` → `app_name` → `process_name` → `"未知"`); the
  bridge passes through an explicit `is_in_progress` flag (set by the
  timeline service before projecting a display `end_time` for open
  activities) so the frontend can mark open records distinctly; the
  frontend uses request tokens to prevent stale bridge
  responses from overwriting newer data; the frontend preserves the
  selected session across auto-refresh and clears it gracefully if it
  disappears; the frontend keeps the previously loaded data visible when
  a refresh fails; long resource/project names are truncated with safe
  tooltips; the layout remains usable on narrow viewports. No editing,
  correction, reclassification, note modification, or deletion is
  introduced. **Completed.**
- Phase 3A: **Timeline basic editing.** Adds minimal write capability to
  the Timeline page: project reclassification (move all activities in a
  session to a different project, including "未归类") and session-note
  editing (write/overwrite/delete the note keyed by
  `(report_date, first_activity_id)`). Both write paths go through
  `worktrace.api` → `worktrace.services` with explicit input validation.
  The bridge exposes `list_projects_for_timeline`,
  `update_timeline_project`, and `update_timeline_note`; it returns generic
  errors without tracebacks or sensitive raw fields. The frontend provides
  a project `<select>`, a note `<textarea>` with character counter, and
  save/cancel buttons with saving/error/success states. On save success
  the Timeline refreshes locally; on save failure the original data is
  preserved. Time editing, session split/merge, deletion, batch editing,
  auto-rule creation, and complex correction pages are explicitly out of
  scope. **Completed.**
- Phase 3A.1: **Timeline basic editing hardening.** No new features.
  Hardens the Phase 3A editing path so it is more stable, safer, and
  clearer under real use. Specifically: the API rejects `bool` inputs for
  `activity_ids`, `project_id`, and `first_activity_id` (Python treats
  `bool` as an `int` subclass, so `True` would otherwise coerce to `1`);
  the bridge adds a lightweight `YYYY-MM-DD` shape check on
  `report_date` and rejects `bool` for `project_id` and `activity_ids`
  elements; the frontend updates the `editingSession` baseline on save
  success so the dirty state clears, auto-refresh repopulates the edit
  panel with the new server-returned baseline, and Cancel after save does
  not revert to pre-save values; `updateNoteCount` disables the save
  button and shows a red counter when the note exceeds the 2000-character
  limit; `setEditSaving(false)` re-applies the length guard; the edit
  panel has narrow-viewport responsive rules; documentation is cleaned up
  to stop describing the Timeline as "read-only". Time editing, session
  split/merge, deletion, batch editing, auto-rule creation, and complex
  correction pages remain out of scope.
- Phase 3B.1: **Timeline time correction foundation.** Implements the
  minimal usable time-correction capability: single-activity
  `start_time` / `end_time` editing with strict validation,
  `duration_seconds` recomputation, in-progress rejection,
  single-activity session-level time correction, post-save Timeline
  refresh with session regroup / cross-day projection handling, and
  independent saving states for project/note and time edits. Multi-
  activity session whole-time correction, session split/merge, deletion,
  batch editing, auto-rule creation, and complex correction pages remain
  out of scope. **Completed.**
- Phase 3B.1.1: **Timeline time correction hardening.** No new features.
  Hardens the Phase 3B.1 time-correction path so it is more stable and
  predictable under real use. Specifically: the service-layer
  `update_activity_time` now checks `cur.rowcount` and raises if 0 rows
  were updated (defense against race conditions where the activity is
  deleted or reopened between API validation and the write); the API
  layer catches this and raises `TimelineTimeEditError("invalid_id")` so
  the bridge returns a clear message instead of silently succeeding; the
  frontend `saveSessionTime` now resets `timeSaving` on success (the save
  button was previously left disabled after a successful session-level
  time save); `refreshTimelineAfterEdit` no longer calls
  `setEditSaving(false)` so the project/note, session-time, and
  per-activity-time save flows are fully decoupled; each caller resets
  its own saving state before refreshing. Multi-activity session
  whole-time correction, session split/merge, deletion, batch editing,
  auto-rule creation, complex correction pages, and overlap detection
  remain out of scope. **Completed.**
- Phase 3B.2: **Timeline activity split foundation.** Implements the
  minimal usable single-activity split: a single closed activity is split
  at a user-supplied split point into two closed activities. The original
  activity keeps its id and becomes the front half
  `[start_time, split_time)`; a new activity is inserted as the back half
  `[split_time, end_time)`. Both `duration_seconds` are precisely
  recomputed. The new activity inherits `app_name`, `process_name`,
  `window_title`, `file_path_hint`, `status`, `source`, `is_hidden`,
  `auto_classified`, `manual_override`, and `project_id` from the
  original; it does **not** inherit the `note` field. Manual and auto
  `activity_project_assignment` rows are copied; `activity_resource`
  associations are copied. The `project_session_note` keyed by
  `(report_date, first_activity_id)` is **not** auto-copied to the new
  back-half activity — the original note stays with the original key.
  Single-activity session-level split is supported (equivalent to
  splitting that activity); multi-activity session-level split is
  rejected with a clear Chinese message. In-progress and deleted
  activities are rejected. The split is atomic: any failure rolls back
  and leaves the original activity unchanged. Split-time validation
  requires strict `YYYY-MM-DD HH:MM:SS` format with
  `start_time < split_time < end_time`. After a successful split the
  Timeline is refreshed; if the selected session regroups or disappears
  the selection is cleared gracefully. Merge, delete/hide, batch
  editing, auto-rule creation, complex correction pages, multi-activity
  session whole-split, and overlap detection remain out of scope.
  **Completed.**
- Phase 3B.2.1: **Timeline activity split hardening.** No new features.
  Hardens the Phase 3B.2 split write path: adds a defensive
  ``lastrowid <= 0`` guard after the new-activity INSERT (raises
  ``ValueError`` and rolls back the transaction so the original activity
  is unchanged); clarifies the ``created_at`` / ``updated_at`` inheritance
  semantics (the new activity gets the write time for both, not the
  original's timestamps); fixes the ``_validate_activity_id_for_split``
  docstring to accurately reflect that the in-progress check is performed
  in the caller (not the validator); adds tests for no-assignment
  inheritance, auto-assignment inheritance, ``created_at`` not copied,
  INSERT failure rollback, assignment-copy failure rollback, and
  resource-copy failure rollback. **Completed.**
- Phase 3B.3: **Timeline activity merge foundation.** Implements the
  minimal usable two-activity merge: two closed, adjacent, same-project /
  same-resource / same-status / same-source activities are merged into
  one. The earlier activity (by ``start_time``, then ``id``) keeps its
  ``id`` and ``start_time``; its ``end_time`` is extended to the later
  activity's ``end_time`` and its ``duration_seconds`` is precisely
  recomputed. The later activity is soft-deleted (``is_deleted = 1``),
  not physically removed. The earlier activity's ``note`` is preserved;
  the later activity's ``note`` is **not** copied or concatenated.
  ``project_session_note`` is **not** migrated. Assignment and resource
  rows are left in place (no complex merge). Only two activities can be
  merged per call; arbitrary-length batch merge and multi-activity
  session whole-merge are rejected. In-progress and deleted activities
  are rejected. The merge is atomic: any failure rolls back and leaves
  both activities unchanged. After a successful merge the Timeline is
  refreshed; if the selected session regroups or disappears the selection
  is cleared gracefully. Delete/hide, batch editing, auto-rule creation,
  complex correction pages, and overlap detection remain out of scope.
  **Completed.**
- Phase 3B.3.1: **Timeline activity merge hardening.** Hardens the
  Phase 3B.3 merge write path with no new features. Confirms the
  transaction boundary covers both the kept-activity UPDATE and the
  later-activity soft-delete; confirms both UPDATEs raise on rowcount 0
  and roll back; confirms an exception during the soft-delete UPDATE
  rolls back via the ``with get_connection()`` context manager so no
  partial write survives. Adds explicit tests for excluded-vs-non-excluded
  rejection (rejected by the resource-identity check because excluded
  activities always carry ``system:excluded``), no-partial-write for
  every rejection path (different project / resource / status / source /
  gap-too-large), kept-fields-unchanged on validation failure, soft-delete
  exception rollback, and the full service-ValueError → API-error-code
  mapping table. Restates that in-progress is determined by the raw DB
  ``end_time IS NULL`` column, not the projected display value. Delete /
  hide, batch editing, auto-rule creation, complex correction pages,
  overlap detection, arbitrary-length merge, and multi-activity session
  whole-merge remain out of scope. **Completed.**
- Phase 3B.4: **Timeline hide / soft delete foundation.** Implements the
  minimal usable single-activity hide and soft delete. Hide sets
  ``activity_log.is_hidden = 1``; soft delete sets ``is_deleted = 1``.
  Neither physically deletes the row or touches assignment / resource /
  note / session-note rows. Single-activity session-level hide / soft
  delete is supported (semantically equivalent to operating on that
  activity); multi-activity session whole-hide / whole-delete is rejected
  with a clear Chinese message directing the user to per-activity
  editing. In-progress activities (raw ``end_time IS NULL``) cannot be
  hidden or deleted. Hide is idempotent; soft delete is not. After a
  successful write the Timeline is refreshed; if the selected session
  regroups or disappears the selection is cleared gracefully. Batch
  hide, batch delete, undo / restore, permanent delete, auto-rule
  creation, complex correction pages, and overlap detection remain out
  of scope. No new DB schema. **Completed.**
- Phase 3B.4.1: **Timeline hide / soft delete hardening.** Hardens the
  Phase 3B.4 hide / soft delete write path and frontend interaction with
  no new features. Confirms the service-layer ``hide_activity`` /
  ``soft_delete_activity`` invariants at the lowest layer: idempotent
  hide (second hide succeeds), non-idempotent soft delete (second soft
  delete raises ``ValueError``), in-progress soft-delete rejection,
  ``is_hidden`` / ``is_deleted`` independence (hide leaves
  ``is_deleted = 0``; soft delete leaves ``is_hidden`` unchanged),
  core-field preservation (start / end / duration / project / note /
  status / source), assignment / resource / session-note preservation,
  and no physical row removal. Confirms the bridge-layer multi-activity
  and invalid-input guards short-circuit before invoking the API write
  path (no round-trip). Restates that in-progress is determined by the
  raw DB ``end_time IS NULL`` column, not the projected display value.
  Restates that delete confirmation is a soft-delete confirmation, not a
  permanent-delete confirmation. Batch hide, batch delete, undo /
  restore, permanent delete, auto-rule creation, complex correction
  pages, overlap detection, and multi-activity session whole-hide /
  whole-delete remain out of scope. No new DB schema. **Completed.**
- Phase 3B.5A: **Timeline correction action consolidation.** This is a
  consolidation / polish / consistency phase, **not** a feature expansion.
  No new backend write capability, no new DB schema, no new actions. The
  per-activity correction actions already implemented in Phase 3B.1 /
  3B.2 / 3B.3 / 3B.4 (编辑时间, 拆分, 与下一条合并, 隐藏, 删除) are
  grouped into three visually distinct action groups with a stable order:
  edit group (编辑时间 → 拆分) → merge group (与下一条合并) → danger
  group (隐藏 → 删除). The merge action now carries the same
  ``isEditDirty()`` guard and row-id consistency check as hide / delete,
  so every action that triggers a Timeline refresh refuses while there
  are unsaved project / note / time / split inputs. The session-level
  edit panel section labels are unified (项目与备注 / 时间修正 / 拆分 /
  可见性). Destructive-action copy is unified: hide succeeds with "已隐藏"
  and fails with "隐藏失败"; delete succeeds with "已删除" and fails with
  "删除失败"; the delete confirmation still makes clear this is a soft
  delete (本阶段不会物理删除数据). Dirty-state refusal is unified to
  "请先保存或取消当前编辑". ``clearEditPanel`` continues to reset all
  transient action state; ``populateEditPanel`` continues to populate
  all correction sections. Auto-refresh continues to preserve dirty
  inputs and to re-apply in-flight saving state to the refreshed
  buttons. Batch edit, batch hide, batch delete, undo / restore,
  permanent delete, auto-rule creation, complex correction page,
  overlap detection, multi-activity session whole-hide / whole-delete,
  and arbitrary-length merge remain out of scope. No new DB schema.
  **Completed.**
- Phase 3B: Timeline advanced editing (batch editing foundation,
  correction page) — Phase 3B.6 batch project reassignment foundation
  implemented; other batch operations (batch hide / batch delete / batch
  time / batch split / batch merge) and the wider correction page remain
  not yet started.
- Phase 4: Statistics / Export.
- Phase 5: Rules.
- Phase 6: Settings / Privacy / Encrypted Backup.
- Cleanup: remove the legacy Tkinter UI. This is a cleanup phase reached
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
  `get_overview`, `get_recent_activities`, `get_timeline`, and
  `get_timeline_session_details`. The Overview methods are the production
  data path for the Overview page; the Timeline methods are the production
  data path for the read-only Timeline page (Phase 2). As of Phase 3A the
  bridge also exposes `list_projects_for_timeline`,
  `update_timeline_project`, and `update_timeline_note` for minimal
  Timeline editing (project reclassification and session-note editing).
  The bridge does not expose time editing, session split/merge, deletion,
  batch editing, auto-rule creation, or complex correction.
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

The Statistics/Export, Project Rules, and Settings/Privacy pages show a
migration placeholder. They are not migrated in Phase 2.

## Phase 2 Implemented Scope

Phase 2 migrated the Timeline / Time Details page as a read-only page:

- `worktrace/webview_ui/bridge.py` adds two read-only Timeline methods:
  - `get_timeline(date=None)` — returns the date, total duration, current
    activity summary, and a list of project sessions. Each session includes
    `session_id`, `project_name`, `project_description`, `start_time`,
    `end_time`, `duration`, `status`, `event_count`, `is_uncategorized`, and
    `activity_ids`.
  - `get_timeline_session_details(activity_ids, report_date=None)` —
    returns activity detail rows for a session. Each row exposes
    display-safe fields only: `start_time`, `end_time`, `duration`,
    `app_name`, `resource_type`, `resource_name`, `project_name`, and
    `status`. Raw window titles, file paths, and notes are not surfaced.
- `worktrace/webview_ui/index.html` — the Timeline section is a production
  page, not a placeholder. It includes:
  - date navigation (prev / today / next buttons + date display);
  - daily total duration;
  - current activity summary;
  - a session list (master) and a detail list (detail) side by side;
  - an in-page error banner;
  - a loading indicator;
  - an empty-state message.
- `worktrace/webview_ui/app.js` — adds Timeline loading, rendering, date
  navigation, session-detail loading, and auto-refresh logic:
  - `loadTimeline(date)` calls `get_timeline` and renders the session list;
  - `loadSessionDetails(activityIds, date)` calls
    `get_timeline_session_details` and renders activity detail rows;
  - `shiftDate(dateStr, days)` computes the prev/next date;
  - `refreshAll` also refreshes the Timeline when it is the active page;
  - session list HTML is built as a complete string before replacing
    `innerHTML` to avoid flicker;
  - the selected session is preserved across auto-refresh;
  - no edit, correction, reclassify, note-modification, or delete handlers
    are present.
- `worktrace/webview_ui/styles.css` — adds Timeline page styles: date
  navigation buttons, summary card, master-detail layout, session items,
  detail items, empty state, loading state, and responsive stacking.

## Phase 2 Not Implemented

The following are explicitly not implemented in Phase 2 and remain on the
legacy Tkinter UI (which is legacy code pending removal, not a supported
runtime path):

- Timeline editing (split, merge, time correction);
- Project reclassification from the Timeline;
- Note modification from the Timeline;
- Activity deletion from the Timeline;
- Statistics and Excel export;
- Project rules creation, editing, enable/disable;
- Settings, privacy notice, clipboard toggle, clear data;
- Encrypted `.wtbackup` export/import;
- Tray icon;
- Single-instance UI behavior (the WebView entry point does not add a
  tray; the collector single-instance lock is still enforced by
  `AppRuntime`).

## Phase 2.1 Implemented Scope

Phase 2.1 hardens the Phase 2 Timeline read-only page. It does **not**
introduce editing, correction, reclassification, note modification, or
deletion. The hardening is scoped to reliability, readability, security,
and maintainability under real user use.

### Bridge hardening (`worktrace/webview_ui/bridge.py`)

- `get_timeline_session_details` no longer uses
  `format_activity_display_name` to build `resource_name`. That helper
  falls back to the raw `window_title` column, which can contain full
  file paths, URLs, or email subjects. The bridge now uses a local
  `_safe_resource_display_name(row)` helper that walks the safe chain
  `resource_display_name` → `activity_display_name` → `app_name` →
  `process_name` → `"未知"`, skipping `window_title`, `file_path_hint`,
  and `note` entirely.
- `get_timeline` exposes `is_in_progress` on each session so the frontend
  can mark open sessions distinctly. The flag is not derived from the
  displayed `end_time`: the timeline service marks `is_in_progress` before
  projecting or replacing an open activity's `end_time` for display, and
  the API/bridge pass this explicit flag through. Consumers must not infer
  in-progress state from the displayed `end_time`, because open activities
  may carry a projected display `end_time`.
- `get_timeline_session_details` exposes `is_in_progress` on each
  activity row, using the same explicit flag from the timeline service.
- The bridge output remains JSON-serializable and continues to return
  `{"ok": false, "error": "操作失败"}` on exceptions without surfacing
  tracebacks or internal exception details.
- The bridge still imports only `worktrace.api` and `worktrace.formatters`
  helpers; it does not import `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.security`, `worktrace.runtime`, or
  `worktrace.config`.

### Frontend hardening (`worktrace/webview_ui/app.js`)

- `timelineRequestToken` guards `loadTimeline` and `refreshTimeline` so
  a stale bridge response cannot overwrite newer data when the user
  rapidly switches dates.
- `detailsRequestToken` guards `loadSessionDetails` so a stale detail
  response cannot overwrite a newer session's details.
- `lastTimelineData` caches the last successfully rendered Timeline
  payload. On refresh failure, the page keeps showing the prior data
  alongside the error banner, instead of clearing the list.
- The selected session is preserved across auto-refresh by matching
  `session_id`. If the session disappears (e.g. it ended and was
  re-grouped), the selection clears gracefully without throwing.
- In-progress sessions and activities get the `in-progress` CSS class.
- The time range for in-progress items shows `HH:MM-进行中` instead of
  `HH:MM-` (empty end).
- Long resource/project names use the existing `text-overflow: ellipsis`
  rule and now carry a `title` attribute with the same safe display name
  so the user can read the full name on hover. The tooltip is built with
  `escapeHtml` to avoid attribute injection.

### Frontend state lifecycle

- All new state-tracking variables (`timelineRequestToken`,
  `detailsRequestToken`, `lastTimelineData`) are in-memory only. They are
  not persisted to `localStorage` or `sessionStorage`. The frontend does
  not store any sensitive data in browser storage APIs.
- `loadSessionDetails` no longer flashes an empty panel on refresh; it
  keeps the previous details visible while the new data loads.
- `renderSessionDetails` shows `暂无详情` (instead of `暂无活动`) when a
  session has no detail rows, so the empty state is unambiguous.
- The Recent Activities list on the Overview page also uses the
  `formatTimeRange` helper so in-progress recent sessions show
  `HH:MM-进行中`.

### Layout hardening (`worktrace/webview_ui/index.html`, `styles.css`)

- The Timeline details panel ships with an initial `暂无详情` empty-state
  child so the panel is never visually empty on first load.
- `.timeline-item.in-progress` and `.detail-item.in-progress` get a blue
  tint so the user can tell the current open record from closed history
  at a glance.
- On narrow viewports (`max-width: 900px`), `.detail-item` switches to a
  single-column grid and `.timeline-item` stacks vertically so long
  resource names wrap instead of stretching the layout horizontally.
- `.timeline-item-time`, `.detail-item-time`, and `.recent-item-time`
  use `word-break: keep-all` so the `进行中` tag stays on one line.

## Phase 2.1 Not Implemented

The following are explicitly not implemented in Phase 2.1 and remain on
the legacy Tkinter UI (which is legacy code pending removal, not a
supported runtime path):

- Timeline editing (split, merge, time correction);
- Project reclassification from the Timeline;
- Note modification from the Timeline;
- Activity deletion from the Timeline;
- Statistics and Excel export;
- Project rules creation, editing, enable/disable;
- Settings, privacy notice, clipboard toggle, clear data;
- Encrypted `.wtbackup` export/import;
- Tray icon;
- Single-instance UI behavior (the WebView entry point does not add a
  tray; the collector single-instance lock is still enforced by
  `AppRuntime`).

Phase 2.1 is not Phase 3. It does not introduce any write capability.

## Phase 3A Implemented Scope

Phase 3A adds minimal write capability to the Timeline page: project
reclassification and session-note editing. It does **not** implement time
editing, session split/merge, deletion, batch editing, auto-rule creation,
or a complex correction page.

### Data semantics

- **Project reclassification** operates on all `activity_ids` in a session.
  All activities move together to the target project, matching the legacy
  Tkinter `update_session_project` behavior. The write is a manual
  assignment (`manual=True`), so it overwrites both auto-recommended and
  prior manual assignments via `ON CONFLICT DO UPDATE` in
  `activity_project_assignment`.
- **"未归类"** is represented by the existing system `UNCATEGORIZED_PROJECT`
  row id (surfaced via `list_selectable_projects`). It is a real project
  row, not a `None` sentinel. The frontend selects it from the project
  list; it never passes a free-form `project_id`.
- **Session note** is stored in `project_session_note` keyed by
  `(report_date, first_activity_id)`, the same model the legacy Tkinter
  Timeline uses. `first_activity_id` is the first activity id of the
  session (`activity_ids[0]`). Whitespace-only notes delete the existing
  note row (matching `set_session_note` behavior). Legitimate newlines
  inside the note are preserved.
- **Session regrouping after write:** after a project reclassification,
  sessions may regroup (e.g. two sessions for the same project may merge).
  The frontend handles the case where the previously selected `session_id`
  disappears by clearing the selection gracefully, reusing the Phase 2.1
  logic.

### API layer (`worktrace/api/timeline_api.py`)

- `reclassify_timeline_session_project(activity_ids, project_id)` —
  validates `activity_ids` (non-empty list of positive ints, each
  referencing an existing non-deleted activity; deduplicates), validates
  `project_id` (positive int referencing an existing project), then calls
  `timeline_service.update_session_project`. Raises `ValueError` on any
  invalid input; no partial write.
- `update_timeline_session_note(report_date, first_activity_id, note)` —
  validates `report_date` (`YYYY-MM-DD`), `first_activity_id` (positive
  int, existing non-deleted activity), `note` (string, length ≤
  `TIMELINE_NOTE_MAX_LENGTH` = 2000), then calls
  `timeline_service.update_session_note`. Raises `ValueError` on any
  invalid input.
- Both methods go through `worktrace.api` → `worktrace.services` only. The
  API layer does not depend on WebView or UI code.

### Bridge layer (`worktrace/webview_ui/bridge.py`)

- `list_projects_for_timeline()` — returns
  `{"ok": true, "projects": [{"id", "name", "description"}]}` from
  `project_api.list_selectable_projects()`. Includes the "未归类" system
  project. Only display-safe fields are surfaced.
- `update_timeline_project(activity_ids, project_id)` — validates
  `activity_ids` via `_coerce_activity_ids` (list of positive ints,
  deduplicated), validates `project_id` (int), calls
  `timeline_api.reclassify_timeline_session_project`. Returns
  `{"ok": true}` on success or `{"ok": false, "error": "..."}` on failure.
  `ValueError` from the API is caught and returned as a generic
  `"操作失败"` error without echoing the underlying message.
- `update_timeline_note(activity_ids, note, report_date)` — validates
  `activity_ids`, `note` (string, length ≤ 2000), `report_date` (non-empty
  string), uses `ids[0]` as `first_activity_id`, calls
  `timeline_api.update_timeline_session_note`. Returns the same
  success/error shape.
- The bridge imports only `worktrace.api` and `worktrace.formatters`. It
  does not import `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.security`, `worktrace.runtime`, or
  `worktrace.config`.
- Bridge errors never include tracebacks, exception class names, SQL error
  messages, file paths, window titles, clipboard content, or the note's
  old value. Logs record only the operation name, result, and exception
  type.
- The `get_timeline` session dict now also includes `project_id`,
  `first_activity_id`, and `session_note` (the user-authored note, which
  is the editing target — not captured metadata).

### Frontend (`worktrace/webview_ui/index.html`, `app.js`, `styles.css`)

- The Timeline details area includes an edit panel (`#timeline-edit-panel`)
  with:
  - a project `<select>` (`#edit-project-select`) populated from
    `list_projects_for_timeline()`;
  - a note `<textarea>` (`#edit-note-text`) with a character counter
    (`#edit-note-count`, `0 / 2000`);
  - save (`#edit-save-btn`) and cancel (`#edit-cancel-btn`) buttons;
  - a status area (`#edit-status`) for success/error messages.
- `populateEditPanel(session)` loads the session's current `project_id`
  into the select and `session_note` into the textarea. Projects are
  loaded lazily on first use and cached.
- `isEditDirty()` checks whether the user has unsaved changes so
  auto-refresh does not overwrite them.
- `saveEdit()` calls `update_timeline_project` and/or `update_timeline_note`
  (only the changed fields), shows a saving state (`保存中…`), and on
  success refreshes the Timeline via `refreshTimelineAfterEdit()`. On
  failure it keeps the original data in the form and shows a Chinese
  error message. It never shows tracebacks.
- `cancelEdit()` reverts the form to the session's original values.
- The frontend still uses no CDN, no external links, no Google Fonts, no
  `localStorage`/`sessionStorage`, and no traceback display logic.
- No time editing, split, merge, delete, batch edit, or auto-rule UI is
  present.

### Tests

- `tests/test_timeline_api_editing.py` — 18 API tests covering validation
  (empty ids, nonexistent ids, invalid project_id, invalid date, note
  length), successful writes, multi-activity consistency, note overwrite,
  whitespace-only deletion, newline preservation, and re-reading the
  timeline after a write.
- `tests/test_webview_bridge_editing.py` — 21 bridge tests covering
  JSON-serializability, successful writes, invalid input, generic error
  responses without tracebacks/sensitive fields, and the bridge import
  boundary.
- `tests/test_webview_resources.py` — 12 new frontend resource tests
  covering the edit panel DOM, project select, note textarea, save/cancel
  buttons, absence of forbidden edit handlers, saving state, save-failure
  data preservation, save-success timeline refresh, and edit panel styles.
  The old `test_app_js_timeline_has_no_edit_buttons` test was replaced
  with `test_app_js_timeline_has_no_forbidden_edit_handlers` to reflect
  that Phase 3A allows project reclassification and note editing but
  still forbids time editing, split, merge, delete, batch edit, and
  auto-rule creation.

## Phase 3A Not Implemented

The following are explicitly not implemented in Phase 3A and remain out
of scope until Phase 3B:

- Time editing (start time, end time);
- Session split;
- Session merge;
- Activity/session deletion;
- Batch editing;
- Auto-rule creation;
- Complex correction page;
- Statistics and Excel export;
- Project rules creation, editing, enable/disable;
- Settings, privacy notice, clipboard toggle, clear data;
- Encrypted `.wtbackup` export/import;
- Tray icon;
- Single-instance UI behavior (the WebView entry point does not add a
  tray; the collector single-instance lock is still enforced by
  `AppRuntime`).

Phase 3A is not Phase 3B. It does not introduce time editing, split,
merge, delete, batch editing, or auto-rule creation.

## Phase 3A.1 Implemented Scope

Phase 3A.1 is a hardening phase. It adds **no new features**. It makes the
Phase 3A basic editing path more stable, safer, and clearer under real
use.

### API layer hardening (`worktrace/api/timeline_api.py`)

- `_validate_activity_ids`, `_validate_project_id`, and
  `_validate_first_activity_id` now explicitly reject `bool` inputs.
  Python treats `bool` as a subclass of `int`, so without this guard
  `True` would coerce to `1` and `False` to `0`, potentially targeting
  an unintended project or activity id.
- The `reclassify_timeline_session_project` docstring now states
  explicitly that no partial writes are ever performed: if any
  `activity_id` is missing or deleted the whole call raises before any
  database write occurs.

### Bridge layer hardening (`worktrace/webview_ui/bridge.py`)

- `_coerce_activity_ids` rejects `bool` elements so `True`/`False` are
  not coerced to `1`/`0`.
- `update_timeline_project` rejects `bool` for `project_id` before the
  `int()` coercion.
- `update_timeline_note` adds a lightweight `YYYY-MM-DD` shape check
  (`_DATE_SHAPE_RE`) on `report_date` at the bridge layer. The API
  layer still performs the full `date.fromisoformat` validation; the
  bridge guard just gives the user a clearer `"日期无效"` message
  instead of the generic `"操作失败"` when the date string is obviously
  malformed.
- Bridge errors still never include tracebacks, exception class names,
  SQL error messages, file paths, window titles, clipboard content, or
  the note's old value.

### Frontend hardening (`worktrace/webview_ui/app.js`)

- **Save-success baseline update:** on save success, `saveEdit()` now
  updates `editingSession.project_id` and `editingSession.session_note`
  to the saved values before refreshing. This clears the dirty state
  (`isEditDirty()` returns `false`), so the subsequent auto-refresh
  repopulates the edit panel with the new server-returned baseline,
  and Cancel after save no longer reverts to the pre-save values.
- **Note-length overflow guard:** `updateNoteCount()` now disables the
  save button and applies a red `edit-note-count-over` CSS class when
  the note exceeds `NOTE_MAX_LENGTH` (2000). The user gets immediate
  feedback instead of an error on click.
- **`setEditSaving(false)` re-applies the length guard:** when a save
  finishes (success or failure), `setEditSaving(false)` calls
  `updateNoteCount()` so the save button stays disabled if the note is
  over the limit.
- **`populateEditPanel` ordering fix:** `updateNoteCount()` is now
  called after `saveBtn.disabled = false`, so the length check has the
  final say on the button state instead of being overridden.
- No time editing, split, merge, delete, batch edit, or auto-rule UI is
  introduced.

### CSS hardening (`worktrace/webview_ui/styles.css`)

- `.edit-note-count-over` styles the character counter in red when the
  note exceeds the 2000-character limit.
- The `@media (max-width: 900px)` block now wraps the edit actions row
  and gives the note textarea a `min-height: 60px` so the panel remains
  usable on narrow viewports.

### Documentation cleanup

- The README no longer says "Timeline editing, correction, and
  reclassification are not yet available in the WebView UI." It now
  describes the Phase 3A basic editing capability and the Phase 3A.1
  hardening.
- This document's Status and Migration Order sections now list Phase 3A
  as **Completed** and Phase 3A.1 as the **Current phase**.

## Phase 3A.1 Not Implemented

Phase 3A.1 does not introduce any new editing capability. The following
remain out of scope until Phase 3B:

- Time editing (start time, end time);
- Session split;
- Session merge;
- Activity/session deletion;
- Batch editing;
- Auto-rule creation;
- Complex correction page.

## Phase 3B.1 Implemented Scope

Phase 3B.1 implements the **minimal usable time-correction foundation**
for the WebView Timeline. It is the first phase that allows the user to
modify activity times.

### Data Semantics

- Activity time correction updates `start_time`, `end_time`, and
  `duration_seconds` on a single `activity_log` row.
- `start_time` and `end_time` must be `YYYY-MM-DD HH:MM:SS` strings.
- `start_time < end_time` (zero and negative durations are rejected).
- `duration_seconds` is recomputed from the new range by the service
  layer; the API never accepts a caller-supplied duration.
- Deleted activities (`is_deleted = 1`) cannot be edited.
- In-progress activities (`end_time IS NULL`) cannot be edited. The
  check reads the raw DB `end_time`, not the projected display value.
  The service-layer UPDATE includes `WHERE end_time IS NOT NULL` as a
  defensive guard against racing calls.
- Cross-day activities are handled by `timeline_service` projection
  (`_split_calendar_report_rows`); the API, bridge, and frontend never
  copy cross-day records. An activity modified to span midnight is
  automatically split across the correct `report_date`(s) on the next
  Timeline read.
- Overlap detection is **not** performed in Phase 3B.1; it is deferred
  to a later phase.

### Session-Level Time Correction

- A session is an aggregate of one or more activities; it is not an
  independent DB record.
- Phase 3B.1 supports whole-session time correction only when the
  session resolves to a single activity (after deduplication). The
  write is equivalent to `update_timeline_activity_time` on that
  activity.
- Multi-activity sessions raise `TimelineTimeEditError("multi_activity")`.
  The frontend shows a clear Chinese hint directing the user to
  per-activity editing instead.

### API Layer

- `update_timeline_activity_time(activity_id, start_time, end_time)`:
  validates and applies a single-activity time correction.
- `update_timeline_session_time(activity_ids, start_time, end_time)`:
  validates and applies a session-level time correction; multi-activity
  sessions raise `TimelineTimeEditError("multi_activity")`.
- `TimelineTimeEditError(ValueError)` carries a stable `code` attribute
  (`invalid_id`, `invalid_time`, `in_progress`, `multi_activity`) that
  the bridge maps to Chinese user-facing messages. Internal field names,
  ids, and SQL details never leak.
- All validation completes before any write; no partial writes are
  possible.

### Bridge Layer

- `update_timeline_activity_time(activity_id, start_time, end_time)`:
  bridge method that only calls `worktrace.api.timeline_api`.
- `update_timeline_session_time(activity_ids, start_time, end_time)`:
  bridge method that only calls `worktrace.api.timeline_api`. The
  multi-activity check is performed at the bridge layer so the user
  gets a clear message without a round-trip through the API.
- Bridge-level datetime shape check (`YYYY-MM-DD HH:MM:SS`) gives a
  clearer `"时间无效"` message before the API's full validation.
- Error results return `{"ok": false, "error": "<chinese message>"}`;
  tracebacks, SQL errors, file paths, window titles, and notes are
  never surfaced.
- The bridge still does not import `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.runtime`, `worktrace.security`, or
  `worktrace.config`.

### Frontend

- The edit panel has a "时间修正" section with `datetime-local` inputs
  for start/end time and a "保存时间" button.
- For single-activity, closed sessions: the inputs are enabled and
  pre-filled with the session's times.
- For multi-activity sessions: the inputs are hidden and a hint is
  shown: "多活动 session 暂不支持整体时间修改，请在活动详情中修改单条
  活动时间。"
- For in-progress sessions: the inputs are hidden and a hint is shown:
  "进行中记录暂不支持时间修正。"
- Each activity detail row has an "编辑时间" button (disabled for
  in-progress activities) that opens an inline time editor with
  `datetime-local` inputs, save/cancel buttons, and a status area.
  Only one inline editor can be open at a time.
- `datetime-local` ↔ backend format conversion uses fixed-format
  string replacement (space ↔ T), not `Date` parsing (which would
  interpret as local time and shift values).
- Independent saving states: `timeSaving` (session-level),
  `activityTimeSaving` (per-activity), and `editSaving` (project/note)
  are separate so the three save flows do not pollute each other.
- On save success: the baseline is updated, dirty state clears, and
  the Timeline is refreshed. The current date and selected session are
  preserved when possible; if the session regroups or crosses day
  boundaries and the selected session disappears, the selection and
  edit panel are cleared gracefully.
- On save failure: the user's input is preserved, the saving state is
  cleared, and a Chinese error message is shown. No traceback is
  displayed.
- Auto-refresh does not overwrite unsaved time edits (session-level or
  per-activity) — the `isEditDirty` check covers time inputs.

## Phase 3B.1 Not Implemented

The following remain out of scope until a later phase:

- Multi-activity session whole-time correction;
- Session split;
- Session merge;
- Activity/session deletion;
- Batch editing;
- Auto-rule creation;
- Complex correction page;
- Overlap detection between activities on the same timeline.

## Phase 3B.1.1 Hardening Details

Phase 3B.1.1 is a hardening phase. It adds **no new features**. It
strengthens the Phase 3B.1 time-correction write path so it is more
stable, safe, and predictable under real use.

### Service Layer

- `activity_service.update_activity_time` now checks `cur.rowcount`
  after the atomic UPDATE. If 0 rows were updated (the activity was
  deleted or reopened between API validation and the write — a race
  condition), it raises `ValueError` instead of silently succeeding.
  The UPDATE still includes `WHERE id = ? AND is_deleted = 0 AND
  end_time IS NOT NULL` as a defensive guard.

### API Layer

- `update_timeline_activity_time` and `update_timeline_session_time`
  wrap the service call in `try/except ValueError`. If the service
  raises (0 rows updated), the API raises
  `TimelineTimeEditError("invalid_id")` so the bridge returns a clear
  Chinese message instead of a silent success.

### Frontend

- `saveSessionTime` now calls `setTimeSaving(false)` on the success
  path before `refreshTimelineAfterEdit()`. Previously the saving
  state was never reset on success, leaving the "保存时间" button
  permanently disabled with "保存中…" text after a successful
  session-level time save.
- `refreshTimelineAfterEdit` no longer calls `setEditSaving(false)`.
  Each caller now resets its own saving state before refreshing:
  `saveEdit` resets `editSaving`, `saveSessionTime` resets
  `timeSaving`, and `saveActivityTime` resets `activityTimeSaving`.
  This decouples the three independent save flows so a refresh
  triggered by one save path cannot prematurely reset the saving
  state of another.
- `saveEdit` success path now calls `setEditSaving(false)` before
  `refreshTimelineAfterEdit()` (previously relied on the refresh
  function to do this).

### What Phase 3B.1.1 Does Not Change

- No new DB schema.
- No new features (no split, merge, delete, batch edit, auto-rule, or
  complex correction page).
- No overlap detection (still deferred).
- No change to the `is_in_progress` semantics (still based on raw DB
  `end_time IS NULL`, not projected display values).
- No change to the bridge import boundary.
- No change to the privacy/security boundary.

## Phase 3B.2 Implemented Scope

Phase 3B.2 implements the **minimal usable single-activity split
foundation** for the WebView Timeline. It is the first phase that allows
the user to split an activity into two.

### Data Semantics

- Split operates on a single closed `activity_log` row.
- The original activity is updated to `[start_time, split_time)` and
  keeps its `id`. A new activity is inserted as
  `[split_time, end_time)` and gets a new `id`.
- Both `duration_seconds` are precisely recomputed as the second
  difference between the respective start/end times. The two durations
  sum to the original duration.
- `split_time` must be a strict `YYYY-MM-DD HH:MM:SS` string with
  `start_time < split_time < end_time`. `T` separators, timezone
  suffixes, missing seconds, and natural-language times are rejected.
  `split_time` equal to `start_time` or `end_time` is rejected.
- Deleted activities (`is_deleted = 1`) cannot be split.
- In-progress activities (`end_time IS NULL`) cannot be split. The
  check reads the raw DB `end_time`, not the projected display value.
- The new activity inherits: `app_name`, `process_name`,
  `window_title`, `file_path_hint`, `status`, `source`, `is_hidden`,
  `auto_classified`, `manual_override`, `project_id`, `created_at`,
  `updated_at`. It does **not** inherit the `note` field (the activity
  `note` column is not copied; the system primarily uses
  `project_session_note` keyed by `(report_date, first_activity_id)`).
- `activity_project_assignment` rows (manual and auto) are copied to
  the new activity id. The new activity therefore inherits the original
  effective project classification; it does not become uncategorized
  unless the original was uncategorized.
- `activity_resource` rows are copied to the new activity id so the
  back-half retains the original resource display name and identity.
- `project_session_note` keyed by `(report_date, first_activity_id)` is
  **not** auto-copied. If the original activity was the
  `first_activity_id` of a session, the note stays with the original
  key (the front half). The back half does not receive a session note.
- The split is atomic: the UPDATE and INSERT (plus assignment/resource
  copies) run in a single transaction. If any step fails the whole
  operation rolls back and the original activity is left unchanged. No
  half-split state is ever persisted.
- Cross-day activities are handled by `timeline_service` projection on
  the next Timeline read; the split itself does not project cross-day
  slices.
- Overlap detection is **not** performed in Phase 3B.2; it is deferred
  to a later phase.

### Session-Level Split

- A session is an aggregate of one or more activities; it is not an
  independent DB record.
- Phase 3B.2 supports session-level split only when the session
  resolves to a single activity (after deduplication). The write is
  equivalent to `split_timeline_activity` on that activity.
- Multi-activity sessions raise `TimelineSplitError("multi_activity")`.
  The frontend shows: "多活动 session 暂不支持整体拆分，请在活动详情中
  拆分单条活动".

### Service Layer (`worktrace/services/activity_service.py`)

- `split_activity(activity_id, split_time) -> dict` — performs the
  atomic split. Returns `{"original_activity_id": int,
  "new_activity_id": int}`. Raises `ValueError` on invalid input or
  race conditions (0 rows updated). The UPDATE includes `WHERE id = ?
  AND is_deleted = 0 AND end_time IS NOT NULL` as a defensive guard.

### API Layer (`worktrace/api/timeline_api.py`)

- `split_timeline_activity(activity_id, split_time)` — validates and
  applies a single-activity split.
- `split_timeline_session(activity_ids, split_time)` — validates and
  applies a session-level split; multi-activity sessions raise
  `TimelineSplitError("multi_activity")`.
- `TimelineSplitError(ValueError)` carries a stable `code` attribute
  (`invalid_id`, `invalid_time`, `outside_range`, `in_progress`,
  `multi_activity`, `operation_failed`) that the bridge maps to Chinese
  user-facing messages. Internal field names, ids, and SQL details never
  leak.
- All validation completes before any write; no partial writes are
  possible.

### Bridge Layer (`worktrace/webview_ui/bridge.py`)

- `split_timeline_activity(activity_id, split_time)` — bridge method
  that only calls `worktrace.api.timeline_api`.
- `split_timeline_session(activity_ids, split_time)` — bridge method
  that only calls `worktrace.api.timeline_api`.
- Bridge-level datetime shape check (`YYYY-MM-DD HH:MM:SS`) gives a
  clearer `"拆分时间无效"` message before the API's full validation.
- Success returns `{"ok": true, "original_activity_id": int,
  "new_activity_id": int}`.
- Error results return `{"ok": false, "error": "<chinese message>"}`.
  Error mapping:
  - `invalid_time` / `outside_range` → `"拆分时间无效"`
  - `in_progress` → `"进行中记录暂不支持拆分"`
  - `multi_activity` → `"多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动"`
  - all other failures → `"操作失败"`
- Tracebacks, SQL errors, file paths, window titles, clipboard content,
  and notes are never surfaced.
- The bridge still does not import `worktrace.services`,
  `worktrace.db`, `worktrace.collector`, `worktrace.runtime`,
  `worktrace.security`, or `worktrace.config`.

### Frontend

- The edit panel has a "拆分时段" section with a `datetime-local` input
  for the split point and a "拆分" button.
- For single-activity, closed sessions: the split input is enabled and
  pre-filled with the midpoint of the session's start/end times
  (computed via `Date.UTC` to avoid local-timezone shifts).
- For multi-activity sessions: the split input is hidden and a hint is
  shown: "多活动 session 暂不支持整体拆分，请在活动详情中拆分单条活动。"
- For in-progress sessions: the split input is hidden and a hint is
  shown: "进行中记录暂不支持拆分。"
- Each closed activity detail row has a "拆分" button (disabled for
  in-progress activities) that opens an inline split editor with a
  `datetime-local` input, save/cancel buttons, and a status area. Only
  one inline editor (split or time) can be open at a time per activity.
- `datetime-local` ↔ backend format conversion uses fixed-format
  string replacement (space ↔ T), not `Date` string parsing (which
  would interpret as local time and shift values).
- Independent saving states: `sessionSplitSaving` (session-level),
  `activitySplitSaving` (per-activity), `editSaving` (project/note),
  `timeSaving` (session-level time), `activityTimeSaving` (per-activity
  time) are all separate so the save flows do not pollute each other.
- On save success: the saving state is reset, the inline editor is
  closed, and the Timeline is refreshed. The current date and selected
  session are preserved when possible; if the session regroups or the
  selected session disappears the selection and edit panel are cleared
  gracefully.
- On save failure: the user's input is preserved, the saving state is
  cleared, and a Chinese error message is shown. No traceback is
  displayed.
- Auto-refresh does not overwrite unsaved split edits (session-level or
  per-activity) — the `isEditDirty` check covers split inputs.

### Privacy and Security Boundary

- The split feature does not expose `window_title`, `file_path_hint`,
  `full_path`, clipboard content, tracebacks, SQL errors, internal
  exception details, or the note's old value.
- Notes, resource names, paths, and window titles are not written to
  logs.
- No browser storage is used to persist split drafts.
- No external resources or network dependencies are introduced.
- The bridge continues to access the backend only through
  `worktrace.api`.

## Phase 3B.2 Not Implemented

The following remain out of scope until a later phase:

- Multi-activity session whole-split;
- Session merge;
- Activity/session deletion or hide;
- Batch editing;
- Auto-rule creation;
- Complex correction page;
- Overlap detection between activities on the same timeline.

## Phase 3B.2.1 Hardening Scope

Phase 3B.2.1 is a **hardening phase only** — it adds no new features. It
strengthens the Phase 3B.2 split write path so that failure modes are more
predictable and the transaction boundary is fully defensible.

### Service Layer Hardening

- **``lastrowid`` guard**: after the INSERT that creates the new back-half
  activity, the service checks ``lastrowid <= 0``. If the INSERT did not
  return a valid row id (should not happen under normal sqlite3 operation),
  the service raises ``ValueError`` so the transaction rolls back and the
  original activity is restored. No assignment or resource copy proceeds
  against a non-existent activity id.
- **``created_at`` / ``updated_at`` semantics clarified**: the new
  activity's ``created_at`` and ``updated_at`` are both set to the current
  write time (``now_str()``), NOT copied from the original. The new row is
  a new record. The original activity's ``updated_at`` is refreshed to the
  write time (its ``end_time`` and ``duration_seconds`` changed); its
  ``created_at`` is untouched. The docstring now documents this explicitly.
- **No-assignment inheritance**: if the original activity has no
  ``activity_project_assignment`` row, the split does NOT create a spurious
  assignment for the new activity. This matches the original state.
- **Auto-assignment inheritance**: automatic (non-manual) assignments are
  copied with ``is_manual=0`` and the original ``source`` (e.g.
  ``keyword_rule``) preserved. This was already implemented in Phase 3B.2
  but is now explicitly tested.

### API Layer Hardening

- **``_validate_activity_id_for_split`` docstring fixed**: the docstring
  previously claimed it raises ``in_progress``, but the implementation
  only checks existence and deleted state. The in-progress check is
  deliberately performed in ``split_timeline_activity`` /
  ``split_timeline_session`` after the validator returns, because those
  callers also need to fetch the activity row for the split-range check.
  The docstring now accurately reflects this.

### Transaction Rollback Verification

Phase 3B.2.1 adds explicit tests verifying that every write step inside
``split_activity`` rolls back on failure:

- **UPDATE rowcount == 0** (race condition): already tested in Phase 3B.2.
- **INSERT ``lastrowid <= 0``**: new test verifies the guard fires, the
  transaction rolls back, and the original activity is unchanged.
- **INSERT raises** (e.g. constraint error): new test verifies the
  transaction rolls back, no new activity is persisted, and the original
  activity's ``end_time`` / ``duration_seconds`` are restored.
- **Assignment copy raises**: new test verifies the transaction rolls back,
  no new activity or half-created assignment is persisted, and the
  original activity is unchanged.
- **Resource copy raises**: new test verifies the transaction rolls back,
  no new activity or half-created resource is persisted, and the original
  activity is unchanged.

### What Phase 3B.2.1 Does NOT Change

- No new features, no new UI controls, no new API methods.
- No DB schema changes.
- No change to the bridge layer or frontend.
- No change to the privacy/security boundary.
- No change to the field inheritance semantics (``note`` still not copied,
  ``project_session_note`` still not auto-copied, project/resource still
  inherited).
- Multi-activity session whole-split, merge, delete/hide, batch editing,
  auto-rule creation, complex correction pages, and overlap detection
  remain out of scope.

## Phase 3B.3 Implemented Scope

Phase 3B.3 implements the **minimal usable two-activity merge foundation**
for the WebView Timeline. It is the first phase that allows the user to
merge two activities into one.

### Data Semantics

- Merge operates on exactly two closed `activity_log` rows. The API
  accepts a list of exactly two activity ids; arbitrary-length batch
  merge is rejected with `TimelineMergeError("invalid_selection")`.
- The earlier activity (by `start_time`, then `id`) is the **kept**
  activity. The later activity is the **merged** (soft-deleted) activity.
- The kept activity's `start_time` is unchanged. Its `end_time` is
  extended to the merged activity's `end_time`. Its `duration_seconds` is
  precisely recomputed as `merged_end - kept_start` in seconds.
- The kept activity's `created_at` is untouched. Its `updated_at` is
  refreshed to the write time.
- The merged activity is soft-deleted (`is_deleted = 1`,
  `updated_at` refreshed). It is **not** physically removed. Timeline
  reads exclude it via `is_deleted = 0` filtering.
- Both activities must satisfy all preconditions:
  - Both exist and are not deleted (`is_deleted = 0`).
  - Both are closed (raw DB `end_time IS NOT NULL`). The in-progress
    check reads the raw DB `end_time`, not the projected display value.
  - Both have the same effective `project_id`. Different projects are
    rejected with `TimelineMergeError("different_project")`.
  - Both have the same resource `identity_key` (from `activity_resource`).
    Different resources are rejected with
    `TimelineMergeError("different_resource")`.
  - Both have the same `status` and `source`. Different status/source is
    rejected with `TimelineMergeError("incompatible_activity")`.
  - The two activities must not overlap (overlap is rejected with
    `TimelineMergeError("invalid_time")`).
  - The two activities must be adjacent or within
    `MERGE_GAP_TOLERANCE_SECONDS` (2 seconds). A larger gap is rejected
    with `TimelineMergeError("not_adjacent")`. The tolerance accounts
    for real collector data where close/create may introduce a 1–2
    second gap; long gaps are never swallowed.
- The kept activity's `note` is preserved. The merged activity's `note`
  is **not** copied or concatenated.
- `project_session_note` keyed by `(report_date, first_activity_id)` is
  **not** migrated. If the merged activity was a `first_activity_id`,
  the note row remains keyed to the (now-deleted) activity id. Phase
  3B.3 does not perform session-note merge.
- `activity_project_assignment` and `activity_resource` rows belonging
  to the merged activity are left in place (not physically deleted). No
  complex assignment/resource merge is performed. The kept activity's
  rows are unchanged.
- The merge is atomic: both UPDATEs (kept end_time/duration and merged
  soft-delete) run in a single transaction. If any step fails the whole
  operation rolls back and both activities are left unchanged. No
  half-merge state is ever persisted.
- Cross-day adjacent activities are supported: the merge itself does
  not project cross-day slices; `timeline_service` projection on the
  next Timeline read handles the display.

### Race-Condition Safety

- The kept-activity UPDATE uses
  `WHERE id = ? AND is_deleted = 0 AND end_time IS NOT NULL`. If the
  rowcount is 0 (the activity was deleted or re-opened between validation
  and write), the service raises `ValueError` and the transaction rolls
  back.
- The merged-activity soft-delete UPDATE uses the same WHERE guard. If
  the rowcount is 0, the service raises `ValueError` and the transaction
  rolls back (the kept-activity UPDATE is also rolled back).
- Both race-condition failures map to
  `TimelineMergeError("operation_failed")` at the API layer and
  `"操作失败"` at the bridge layer.

### API Layer

- `merge_timeline_activities(activity_ids: list[int]) -> dict` is the
  production write path. It validates the input list, delegates to
  `activity_service.merge_activities`, and maps service-layer
  `ValueError` codes to stable `TimelineMergeError` codes.
- Stable error codes: `invalid_selection`, `invalid_id`, `in_progress`,
  `different_project`, `different_resource`, `incompatible_activity`,
  `not_adjacent`, `invalid_time`, `operation_failed`.
- The API does not return raw rows, `window_title`, `file_path_hint`,
  `note`, or any internal field. It returns
  `{"kept_activity_id": int, "merged_activity_id": int}`.

### Bridge Layer

- `WebViewBridge.merge_timeline_activities(activity_ids)` is the only
  frontend-facing entry point. It calls
  `timeline_api.merge_timeline_activities` and maps error codes to
  Chinese messages.
- Bridge error messages: `请选择两个活动进行合并`, `操作失败`,
  `进行中记录暂不支持合并`, `项目不同，暂不支持合并`,
  `资源不同，暂不支持合并`, `活动类型不同，暂不支持合并`,
  `活动时间不连续，暂不支持合并`, `时间无效`.
- The bridge does not return tracebacks, SQL errors, file paths, window
  titles, notes, or clipboard data. Unknown errors collapse to
  `"操作失败"`.

### Frontend UI

- Each activity detail row gets a "与下一条合并" button that merges the
  current activity with the next activity in the detail list.
- The button is disabled when: there is no next activity, either
  activity is in-progress, or the activity id is missing. The backend
  re-validates all merge preconditions.
- The merge saving state (`mergeSaving` / `mergingActivityId`) is
  independent from the project/note, time, and split saving states so
  the flows do not pollute each other.
- On success: the saving state is reset, "已合并" is shown briefly, and
  the Timeline is refreshed. If the selected session regroups or
  disappears the selection is cleared gracefully.
- On failure: the saving state is reset, "合并失败" is shown, and the
  detail list is left intact. No traceback is displayed.
- Auto-refresh preserves an in-flight merge: if the merge button's
  activity is still present after refresh, the saving state is
  re-applied; if it disappeared, the merge state is reset.
- No delete, batch, auto-rule, or complex-correction controls are
  introduced.

### Privacy / Security

- The merge does not expose `window_title`, `file_path_hint`,
  `full_path`, `clipboard`, tracebacks, SQL errors, or internal
  exception details.
- Notes, resource names, paths, and window titles are not written to
  logs.
- No browser storage is used to persist merge drafts.
- No external resources or network dependencies are introduced.
- The bridge continues to access the backend only through
  `worktrace.api`.

## Phase 3B.3 Not Implemented

The following remain out of scope until a later phase:

- Arbitrary-length batch merge (more than two activities);
- Multi-activity session whole-merge;
- Activity/session deletion or hide;
- Batch editing;
- Auto-rule creation;
- Complex correction page;
- Overlap detection between activities on the same timeline (the merge
  itself rejects overlap between the two activities being merged, but
  global overlap detection is not implemented).

## Phase 3B.3.1 Hardening

Phase 3B.3.1 is a **hardening-only** phase. It introduces no new features,
no new DB schema, no new UI controls, and no changes to the merge data
semantics. It confirms the Phase 3B.3 write path is stable, safe, and
semantically clear, and adds explicit regression tests for the edge cases
the foundation tests did not exercise.

### Transaction Boundary

- The kept-activity UPDATE and the later-activity soft-delete run inside
  the same ``with get_connection() as conn:`` block in
  ``activity_service.merge_activities``. The sqlite3 connection context
  manager commits on normal exit and rolls back on any exception.
- The kept-activity UPDATE guards its WHERE clause with
  ``id = ? AND is_deleted = 0 AND end_time IS NOT NULL``. If the rowcount
  is 0 (race condition: the activity was deleted or re-opened between
  validation and write), the service raises
  ``ValueError("activity_merge_update_affected_zero_rows")`` and the
  transaction rolls back.
- The later-activity soft-delete UPDATE uses the same WHERE guard. If the
  rowcount is 0, the service raises the same ``ValueError`` and the
  transaction rolls back (the kept-activity UPDATE is also rolled back).
- If the soft-delete UPDATE raises an arbitrary exception (e.g. a
  ``sqlite3.OperationalError`` from a mid-transaction database failure),
  the exception propagates out of ``merge_activities`` and the
  ``with get_connection()`` context manager rolls back the transaction.
  No partial write (kept end_time extended but later activity still live)
  survives. The service does not wrap the soft-delete in its own
  try/except; it relies on the connection context manager for rollback.

### Validation Order And Excluded Activities

- The service checks resource identity (``activity_resource.identity_key``)
  before status/source. Excluded activities are always anonymised to
  ``system:excluded`` (see ``resource_service._enforce_anonymous_if_excluded``
  and ``make_system_resource``), which differs from a normal activity's
  file-based identity_key. Therefore an excluded-vs-non-excluded merge is
  rejected with ``different_resource`` — a stronger and earlier guard that
  covers the excluded boundary without needing a separate status check.
- The in-progress determination reads the raw DB ``end_time IS NULL``
  column, not the projected display ``end_time`` value. This is consistent
  with the rest of the activity-editing flows.

### Added Hardening Tests

- ``test_merge_excluded_vs_non_excluded_rejected`` — excluded activity
  (``system:excluded``) vs normal activity rejected with
  ``different_resource``.
- ``test_merge_no_partial_write_on_different_resource`` /
  ``test_merge_no_partial_write_on_different_status`` /
  ``test_merge_no_partial_write_on_different_source`` /
  ``test_merge_no_partial_write_on_gap_too_large`` — each rejection path
  leaves both activities' ``start_time`` / ``end_time`` / ``is_deleted``
  unchanged.
- ``test_merge_kept_fields_unchanged_on_validation_failure`` — on a
  validation failure the kept activity's ``start_time`` / ``end_time`` /
  ``duration_seconds`` / ``updated_at`` are all unchanged.
- ``test_service_merge_soft_delete_exception_rolls_back`` — a
  ``sqlite3.OperationalError`` raised by the soft-delete UPDATE propagates
  and the transaction rolls back: the kept ``end_time`` returns to its
  original value and the later activity is NOT soft-deleted.
- ``test_api_maps_all_service_value_error_codes`` — table-driven test
  verifying every service ``ValueError`` code (including an unknown code)
  maps to the documented stable ``TimelineMergeError`` code.

### Not Implemented (Restated)

Phase 3B.3.1 does not implement and does not start:

- Delete / hide as an independent feature;
- Batch editing;
- Auto-rule creation;
- Complex correction page;
- Overlap detection (global, across the whole timeline);
- Arbitrary-length merge (more than two activities per call);
- Multi-activity session whole-merge.

## Phase 3B.4 Implemented Scope

Phase 3B.4 implements the **minimal usable single-activity hide / soft
delete foundation** for the WebView Timeline. It is the first phase that
allows the user to remove an activity from the default Timeline view
without physically deleting the underlying row.

### Data Semantics

- **Hide** sets `activity_log.is_hidden = 1` for a single closed
  activity. The row is not physically deleted. Hidden activities do not
  appear in the default Timeline (`include_hidden=False`). They remain
  accessible via the legacy / debug `include_hidden=True` read path.
- **Soft delete** sets `activity_log.is_deleted = 1` for a single closed
  activity. The row is not physically deleted. Soft-deleted activities do
  not appear in the Timeline. `is_deleted = 1` is the same flag already
  used as an internal write semantic by the Phase 3B.3 merge (the later
  activity in a merge is soft-deleted).
- Neither operation modifies `start_time`, `end_time`,
  `duration_seconds`, `project_id`, `note`, `status`, or `source`.
- Neither operation deletes `activity_project_assignment`,
  `activity_resource`, or `project_session_note` rows. They are record-
  level visibility flags only.
- Neither operation migrates `project_session_note`. If the hidden /
  deleted activity was a `first_activity_id`, the note row remains keyed
  to that activity id. Phase 3B.4 does not perform session-note
  migration.
- **Hide is idempotent**: hiding an already-hidden activity succeeds (the
  UPDATE still matches the row because `is_deleted = 0` and
  `end_time IS NOT NULL`).
- **Soft delete is NOT idempotent**: deleting an already-deleted activity
  fails with `TimelineVisibilityError("invalid_id")` (the activity is
  treated as missing).
- The activity must exist and must not already be deleted
  (`is_deleted = 0`).
- The activity must be closed (raw DB `end_time IS NOT NULL`). The
  in-progress check reads the raw DB `end_time`, not the projected
  display value. An open activity may carry a projected display
  `end_time`; consumers must not infer in-progress state from the
  displayed `end_time`.
- The write is a single atomic UPDATE with a `WHERE id = ? AND
  is_deleted = 0 AND end_time IS NOT NULL` guard. No partial writes are
  possible.

### Session-Level Semantics

- `hide_timeline_session(activity_ids)` and
  `soft_delete_timeline_session(activity_ids)` accept a session's full
  activity id list. The list is validated and deduplicated.
- After deduplication, **exactly one** id must remain. The call is then
  equivalent to `hide_timeline_activity` / `soft_delete_timeline_activity`
  on that single activity.
- A multi-activity session (more than one id after dedup) raises
  `TimelineVisibilityError("multi_activity_hide")` or
  `TimelineVisibilityError("multi_activity_delete")` respectively. The
  frontend must direct the user to per-activity editing instead.
- The single activity is re-checked for in-progress state at the API
  layer before the write.

### Race-Condition Safety

- Both `hide_activity` and `soft_delete_activity` use
  `WHERE id = ? AND is_deleted = 0 AND end_time IS NOT NULL`. If the
  rowcount is 0 (the activity was deleted or re-opened between
  validation and write), the service raises `ValueError` and no write
  occurs.
- Both race-condition failures map to
  `TimelineVisibilityError("operation_failed")` at the API layer and
  `"操作失败"` at the bridge layer.

### API Layer

- `hide_timeline_activity(activity_id: int) -> None` is the production
  hide write path.
- `soft_delete_timeline_activity(activity_id: int) -> None` is the
  production soft-delete write path.
- `hide_timeline_session(activity_ids: list[int]) -> None` and
  `soft_delete_timeline_session(activity_ids: list[int]) -> None` are
  the session-level entry points.
- Stable error codes: `invalid_id`, `in_progress`,
  `multi_activity_hide`, `multi_activity_delete`, `operation_failed`.
- `TimelineVisibilityError(ValueError)` is the stable exception class.
- `activity_id` must be a positive integer; `bool` is rejected (it is a
  subclass of `int`). Session-level `activity_ids` must be a non-empty
  list of positive integers; `bool` elements are rejected.
- The API does not return raw rows, `window_title`, `file_path_hint`,
  `note`, or any internal field. It returns `None` on success.

### Bridge Layer

- `WebViewBridge.hide_timeline_activity(activity_id)`,
  `soft_delete_timeline_activity(activity_id)`,
  `hide_timeline_session(activity_ids)`, and
  `soft_delete_timeline_session(activity_ids)` are the frontend-facing
  entry points. They call only `worktrace.api.timeline_api`.
- Success returns `{"ok": true}`.
- Failure returns `{"ok": false, "error": "<chinese message>"}`.
- Bridge error messages: `操作失败` (invalid_id / operation_failed /
  unknown), `进行中记录暂不支持隐藏或删除` (in_progress),
  `多活动 session 暂不支持整体隐藏，请在活动详情中逐条处理`
  (multi_activity_hide),
  `多活动 session 暂不支持整体删除，请在活动详情中逐条处理`
  (multi_activity_delete).
- The bridge does not return tracebacks, SQL errors, file paths, window
  titles, notes, or clipboard data. Unknown error codes collapse to
  `"操作失败"`.
- The bridge does not import `worktrace.services`, `worktrace.db`,
  `worktrace.collector`, `worktrace.runtime`, `worktrace.security`, or
  `worktrace.config`.

### Frontend UI

- Each closed activity detail row gets a "隐藏" (hide) button and a
  "删除" (delete) button. The delete button carries a red accent so the
  user can tell the destructive action apart. Both are disabled for
  in-progress activities.
- The delete flow uses `window.confirm("确定从 Timeline 删除这条记录
  吗？本阶段不会物理删除数据。")` to avoid accidental deletion. The
  hint text explicitly states the data is not physically deleted.
- The session-level edit panel gets a "隐藏 / 删除" section with
  "隐藏此 session" and "删除此 session" buttons. For a single-activity
  session these are enabled; for a multi-activity session they are
  replaced by the hint "多活动 session 暂不支持整体隐藏/删除，请在活
  动详情中逐条处理。". For an in-progress session they are replaced by
  the hint "进行中记录暂不支持隐藏或删除。".
- The hide saving state (`hideSaving` / `hidingActivityId`) and delete
  saving state (`deleteSaving` / `deletingActivityId`) are independent
  from each other and from the project/note, time, split, and merge
  saving states so the flows do not pollute each other.
- On success: the saving state is reset, "已隐藏" / "已删除" is shown
  briefly, and the Timeline is refreshed. If the selected session
  regroups or disappears the selection is cleared gracefully.
- On failure: the saving state is reset, the Chinese error message is
  shown, and the detail list is left intact. No traceback is displayed.
- Auto-refresh preserves an in-flight hide / delete: if the activity is
  still present after refresh, the saving state is re-applied; if it
  disappeared, the state is reset.
- If `isEditDirty()` returns true (unsaved project / note / time / split
  inputs), hide / delete is refused with "请先保存或取消当前编辑" so the
  refresh does not wipe unsaved edits.
- No batch, restore, permanent-delete, auto-rule, or complex-correction
  controls are introduced.

### Privacy / Security

- The hide / delete flows do not expose `window_title`,
  `file_path_hint`, `full_path`, `clipboard`, tracebacks, SQL errors,
  or internal exception details.
- Notes, resource names, paths, and window titles are not written to
  logs.
- No browser storage is used to persist hide / delete drafts.
- No external resources or network dependencies are introduced.
- The bridge continues to access the backend only through
  `worktrace.api`.

## Phase 3B.4 Not Implemented

The following remain out of scope until a later phase:

- Batch hide (hiding more than one activity per call);
- Batch delete (soft-deleting more than one activity per call);
- Undo / restore (reverting a hide or soft delete);
- Permanent delete (physically removing the DB row);
- Auto-rule creation;
- Complex correction page;
- Overlap detection between activities on the same timeline;
- Multi-activity session whole-hide / whole-delete;
- Session-note migration when the hidden / deleted activity was a
  `first_activity_id`.

## Phase 3B.4.1 Implemented Scope

Phase 3B.4.1 is a **hardening-only** phase. It introduces **no new
features** — no batch hide, no batch delete, no undo / restore, no
permanent delete, no auto-rule, no complex correction page, no overlap
detection, and no multi-activity session whole-hide / whole-delete. It
strengthens the Phase 3B.4 hide / soft delete write path and frontend
interaction so visibility changes are more predictable, safer, and
semantically clearer.

### Service-Layer Hardening

The service-layer ``hide_activity`` / ``soft_delete_activity``
invariants are now directly covered by tests at the lowest layer (not
just through the API / bridge facade):

- **Idempotent hide**: ``hide_activity`` called twice on the same closed
  activity succeeds both times. The ``WHERE id = ? AND is_deleted = 0
  AND end_time IS NOT NULL`` clause matches an already-hidden row, so
  the second UPDATE refreshes ``updated_at`` and returns rowcount 1.
- **Non-idempotent soft delete**: ``soft_delete_activity`` called twice
  on the same activity raises ``ValueError`` on the second call. The
  ``WHERE id = ? AND is_deleted = 0 AND end_time IS NOT NULL`` clause
  excludes an already-deleted row, so the second UPDATE returns rowcount
  0 and the service raises ``ValueError``.
- **In-progress soft-delete rejection**: ``soft_delete_activity`` on an
  in-progress activity (raw ``end_time IS NULL``) raises ``ValueError``
  (the WHERE clause excludes ``end_time IS NULL``).
- **``is_hidden`` / ``is_deleted`` independence**: ``hide_activity``
  leaves ``is_deleted`` at 0; ``soft_delete_activity`` leaves
  ``is_hidden`` unchanged (if the activity was previously hidden,
  ``is_hidden`` stays 1 after a soft delete).
- **Core-field preservation**: neither operation modifies
  ``start_time``, ``end_time``, ``duration_seconds``, ``project_id``,
  ``note``, ``status``, or ``source``.
- **Assignment / resource preservation**: neither operation deletes
  ``activity_project_assignment`` or ``activity_resource`` rows.
- **No physical row removal**: neither operation removes the row from
  ``activity_log``; the row is still retrievable by direct id lookup.

### Bridge-Layer Hardening

The bridge-layer guards are confirmed to short-circuit before invoking
the API write path, giving the user an immediate clear message without
a needless round-trip:

- A multi-activity session hide / soft delete returns the dedicated
  Chinese message without calling ``timeline_api.hide_timeline_session``
  / ``timeline_api.soft_delete_timeline_session``.
- An invalid activity id (non-positive, ``bool``, non-int) returns
  ``"操作失败"`` without calling the API write path.
- A non-list ``activity_ids`` argument returns ``"操作失败"`` without
  calling the API write path.

### In-Progress Semantics Restated

In-progress is determined by the **raw DB ``end_time IS NULL`` column**,
not the projected display value. An open activity may carry a projected
display ``end_time`` for the Timeline view; consumers must not infer
in-progress state from the displayed ``end_time``. Both the API-layer
``_validate_activity_id_for_visibility`` and the service-layer WHERE
clause read the raw ``end_time``.

### Delete Confirmation Semantics Restated

The delete confirmation is a **soft-delete confirmation**, not a
permanent-delete confirmation. The frontend uses
``window.confirm("确定从 Timeline 删除这条记录吗？本阶段不会物理删除数据。")``
so the user is explicitly told the data is not physically removed.
Confirm cancel does not call the bridge, does not enter the saving
state, and does not refresh the Timeline.

## Phase 3B.4.1 Not Implemented

Phase 3B.4.1 does not implement and does not start:

- Batch hide (hiding more than one activity per call);
- Batch delete (soft-deleting more than one activity per call);
- Undo / restore (reverting a hide or soft delete);
- Permanent delete (physically removing the DB row);
- Auto-rule creation;
- Complex correction page;
- Overlap detection (global, across the whole timeline);
- Multi-activity session whole-hide / whole-delete;
- Session-note migration when the hidden / deleted activity was a
  `first_activity_id`;
- Any new DB schema.

## Phase 3B.5A Implemented Scope

Phase 3B.5A is a **consolidation / polish / consistency** phase. It does
**not** add any new backend write capability, any new DB schema, or any
new correction action. It only reorganizes and unifies the correction
actions already implemented in Phase 3B.1 / 3B.2 / 3B.3 / 3B.4 so the
user experience, state handling, error handling, and documentation
semantics are consistent across project / note / time / split / merge /
hide / delete.

Frontend UI grouping (`worktrace/webview_ui/app.js`,
`worktrace/webview_ui/styles.css`):

- The five per-activity correction buttons are wrapped in three action
  groups inside the existing `.detail-item-actions` container:
  - `.detail-action-edit-group` — `编辑时间`, `拆分`;
  - `.detail-action-merge-group` — `与下一条合并`;
  - `.detail-action-danger-group` — `隐藏`, `删除`.
- The action order is stable: `编辑时间 → 拆分 → 与下一条合并 → 隐藏 →
  删除`.
- The merge button carries an indigo accent so it reads as a distinct
  structural operation, separate from the plain edit buttons and from
  the destructive hide / delete buttons.
- The danger group has a red-tinted left border so destructive actions
  are visually separated from edits and merge.
- Narrow-viewport rules allow each group's buttons to wrap together
  while the groups themselves can flow to the next line.

Frontend state management (`worktrace/webview_ui/app.js`):

- The independent saving states (`editSaving`, `timeSaving`,
  `activityTimeSaving`, `sessionSplitSaving`, `activitySplitSaving`,
  `mergeSaving`, `hideSaving`, `deleteSaving`) are preserved without
  over-abstraction.
- `saveActivityMerge` now carries the same `isEditDirty()` guard and
  row-id consistency check as `saveActivityHide` / `saveActivityDelete`,
  so every action that triggers a Timeline refresh refuses while there
  are unsaved project / note / time / split inputs.
- All action success paths reset the saving state before calling
  `refreshTimelineAfterEdit()`; failure paths reset the saving state and
  keep the detail list visible.
- `clearEditPanel()` continues to reset all transient action state.
- `populateEditPanel()` continues to populate all correction sections.
- Auto-refresh continues to preserve dirty inputs and to re-apply
  in-flight saving state to the refreshed buttons.

Destructive-action copy (`worktrace/webview_ui/app.js`):

- Hide: button `隐藏`, success `已隐藏`, failure `隐藏失败`.
- Delete: button `删除`, success `已删除`, failure `删除失败`.
- Delete confirmation: `确定从 Timeline 删除这条记录吗？本阶段不会物理删除数据。`
- Dirty-state refusal (hide / delete / merge): `请先保存或取消当前编辑`.
- Multi-activity session hints remain clear: split / time / hide / delete
  each direct the user to per-activity editing; merge rejects
  multi-activity session whole-merge.

Correction-section labels (`worktrace/webview_ui/index.html`):

- The session-level edit panel sections are labeled consistently:
  `项目与备注`, `时间修正`, `拆分`, `可见性`.
- The visibility section hint restates both the hide and soft-delete
  semantics: `隐藏后将从默认 Timeline 隐藏；删除为软删除，本阶段不会物理删除数据。`

Bridge / API boundary:

- No new bridge method, no new API method, no new service method.
- The bridge continues to import only `worktrace.api` /
  `worktrace.formatters`; it does not import `services` / `db` /
  `collector` / `security` / `runtime` / `config`.
- Bridge error payloads continue to return generic Chinese messages
  without tracebacks, SQL errors, `window_title`, `file_path_hint`,
  `full_path`, `clipboard`, or `note` old values.

## Phase 3B.5A Not Implemented

Phase 3B.5A does not implement and does not start:

- Batch edit (editing more than one activity or session per call);
- Batch hide (hiding more than one activity per call);
- Batch delete (soft-deleting more than one activity per call);
- Undo / restore (reverting a hide, soft delete, split, merge, or time
  correction);
- Permanent delete (physically removing the DB row);
- Auto-rule creation;
- Complex correction page (a dedicated multi-step correction UI);
- Global overlap detection (across the whole timeline);
- Multi-activity session whole-hide / whole-delete;
- Arbitrary-length merge (more than two activities per call);
- Any new backend write capability;
- Any new DB schema;
- Any new third-party UI library;
- Any dropdown / menu component that would significantly increase test
  complexity (the phase keeps the button-based UI, only adding group
  wrappers and style cleanup).

## Phase 3B.5B Implemented Scope

Phase 3B.5B is a **correction shell / advanced edit layout foundation**
phase. It adds a hidden correction workspace *shell* inside the Timeline
page (`#page-timeline`), inside the `#timeline-details` column, after the
existing `#timeline-edit-panel`. The shell is a **read-only context +
navigation layout**: it summarizes the currently selected session and its
activities using display-safe fields only, and guides the user back to the
existing single project / note / time / split / merge / hide / delete
controls. It does **not** add any new backend write capability, any new
DB schema, any new bridge / API / service method, or any new correction
action. It does **not** implement batch editing.

The shell is **not** a new top-level sidebar nav item. The sidebar
navigation remains exactly `概览 / 时间详情 / 统计与导出 / 项目规则 /
设置与隐私`. Opening the shell keeps the user inside the Timeline page.

HTML (`worktrace/webview_ui/index.html`):

- A `#timeline-correction-shell` container (class `correction-shell`,
  `hidden` by default) is placed inside `#timeline-details`, after
  `#timeline-edit-panel`.
- The shell header carries the title `高级纠错`, a subtitle
  (`#correction-shell-subtitle`), and a close button
  (`#correction-shell-close-btn`) labeled `返回时间详情`.
- The shell has a status area (`#correction-shell-status`), a context
  area (`#correction-shell-context`), an activity summary area
  (`#correction-shell-activities`), and an action guidance area
  (`#correction-shell-actions`).
- A session-level entry button `打开高级纠错`
  (`#open-correction-shell-btn`) is added to the edit-panel header
  actions. No per-activity `打开纠错` entry is required by this phase.

CSS (`worktrace/webview_ui/styles.css`):

- `.correction-shell` and its sub-regions (`.correction-shell-header`,
  `.correction-shell-title`, `.correction-shell-subtitle`,
  `.correction-shell-context`, `.correction-shell-activities`,
  `.correction-shell-actions`, `.correction-shell-close-btn`) are styled
  consistently with the existing Timeline card / edit-panel style.
- `.correction-shell[hidden]` is `display: none`.
- When the shell is open, a `shell-open` class on `.timeline-details`
  de-emphasizes (opacity) the edit panel and details list so the shell
  reads as the focus area. The elements are **not** removed, because the
  shell only guides the user back to the existing controls.
- `.detail-item.shell-target` briefly highlights a detail row when the
  user clicks the corresponding shell activity row.
- Narrow-viewport rules stack the shell header and activity rows
  vertically. No external fonts / icons are used.

Frontend state (`worktrace/webview_ui/app.js`):

- New shell state variables (`correctionShellOpen`,
  `correctionShellSessionId`, `correctionShellActivityId`,
  `correctionShellMode`) are declared separately from the existing
  `editSaving` / `timeSaving` / `activityTimeSaving` /
  `sessionSplitSaving` / `activitySplitSaving` / `mergeSaving` /
  `hideSaving` / `deleteSaving` states so shell state never pollutes
  them.
- Helpers: `getSelectedSession()`, `getCurrentDetailActivities()`,
  `setCorrectionShellStatus(message, isError)`,
  `resetCorrectionShellState()`,
  `renderCorrectionShell(session, activities, mode, activityId)`,
  `highlightDetailRow(activityId)`, `openCorrectionShell(mode,
  activityId)`, `closeCorrectionShell()`.
- `openCorrectionShell` refuses to open while `isEditDirty()` is true
  (refusal text `请先保存或取消当前编辑`) and requires a selected
  session. An activity-level open additionally requires the activity id
  to still exist in the current detail list.
- `closeCorrectionShell` resets shell state but **preserves**
  `selectedSessionId` so the user returns to the same session.
- `resetCorrectionShellState` hides the shell DOM, removes the
  `shell-open` class, clears the shell status / context / activities /
  actions areas, and resets all shell state variables.
- `clearEditPanel()` calls `resetCorrectionShellState()` so a stale
  shell does not leak into the next session.
- Date navigation (`goPrevDay` / `goNextDay` / `goToday`) closes the
  shell so the shell context does not carry across dates.
- `selectTimelineSession` closes the shell when the user switches to a
  different session.
- `showTimeline` refreshes the shell context when the shell is open and
  the selected session still exists (and the panel is not dirty); it
  resets the shell state when the selected session disappears (via
  `clearEditPanel`).
- `renderCorrectionShell` only uses display-safe fields
  (`project_name`, `project_description`, `start_time`, `end_time`,
  `duration`, `event_count`, `status`, `is_in_progress`, and the
  display-safe activity fields already rendered into the detail rows:
  `activity_id`, time range, `resource_name`, `resource_type`,
  `app_name`, `duration`). It never reads raw `window_title`,
  `file_path_hint`, `full_path`, `clipboard`, or note internals. It
  reuses the existing `formatTimeRange` helper and does **not** parse
  backend times with `new Date(string)`.
- The shell activity rows are click-to-locate: clicking a row scrolls to
  and highlights the corresponding `.detail-item` row so the user can
  use the existing per-activity action buttons. No write is performed
  from the shell.
- The shell action area only renders guidance text; it does **not**
  render its own write buttons. It reiterates that hide / delete are
  soft operations (`本阶段不会物理删除数据`).

Bridge / API boundary:

- No new bridge method, no new API method, no new service method, no new
  DB schema.
- The bridge continues to import only `worktrace.api` /
  `worktrace.formatters`; it does not import `services` / `db` /
  `collector` / `security` / `runtime` / `config`.
- The shell reads only from the already-loaded `currentSessions` and
  the already-rendered detail rows; it makes no new bridge call.
- Bridge error payloads continue to return generic Chinese messages
  without tracebacks, SQL errors, `window_title`, `file_path_hint`,
  `full_path`, `clipboard`, or `note` old values.

## Phase 3B.5B Not Implemented

Phase 3B.5B does not implement and does not start:

- Batch edit (editing more than one activity or session per call);
- Batch hide (hiding more than one activity per call);
- Batch delete (soft-deleting more than one activity per call);
- Undo / restore (reverting a hide, soft delete, split, merge, or time
  correction);
- Permanent delete (physically removing the DB row);
- Auto-rule creation;
- Global overlap detection (across the whole timeline);
- Multi-activity session whole-hide / whole-delete;
- Arbitrary-length merge (more than two activities per call);
- Any new backend write capability;
- Any new DB schema;
- Any new bridge / API / service method;
- Any new third-party UI library;
- Any new top-level sidebar nav item (the shell is internal to the
  Timeline page);
- Any URL routing or browser-storage-based state;
- Any per-activity `打开纠错` entry (only the session-level `打开高级纠错`
  entry is required by this phase).

## Phase 3B.5B.1 Implemented Scope

Phase 3B.5B.1 is a **hardening-only** phase for the 3B.5B correction shell.
It stabilizes the shell on navigation, auto-refresh, dirty-state, selected
session disappearance, display-safe field boundaries, click-to-locate, and
the close / reset paths. It does **not** add any new feature, any new
backend write capability, any new DB schema, any new bridge / API / service
method, or any new correction action. It does **not** implement batch
editing.

Hardening points (`worktrace/webview_ui/app.js`):

- `openCorrectionShell` keeps its dirty-state open guard (`isEditDirty()`
  → refusal text `请先保存或取消当前编辑`). The refusal does **not** clear
  `selectedSessionId`, does **not** clear the edit panel / inputs, and does
  not change the selected session. It still requires the selected session
  to exist in `currentSessions` (via `getSelectedSession`).
- `closeCorrectionShell` hides the shell, resets shell-only state, and
  **preserves** `selectedSessionId`. It triggers no refresh and performs no
  write.
- `resetCorrectionShellState` clears shell-only state only; it does **not**
  reset the edit / time / split / merge / hide / delete saving states
  (those are owned by `clearEditPanel`). It also cancels any pending
  highlight timer so a close / reset never leaves a dangling timer.
- `clearEditPanel`, date navigation (`goPrevDay` / `goNextDay` /
  `goToday`), and `selectTimelineSession` (on session switch) continue to
  reset shell state; `showTimeline` resets shell state when the selected
  session disappears (via `clearEditPanel`).
- Auto-refresh: `showTimeline` re-renders the shell context only when the
  shell is open, the selected session still exists, **and** the panel is
  not dirty. A dirty edit is never overwritten; if the selected session
  disappears the shell is closed.
- Shell state (`correctionShellOpen`, `correctionShellSessionId`,
  `correctionShellActivityId`, `correctionShellMode`,
  `correctionShellHighlightTimer`) remains independent of the existing
  `editSaving` / `timeSaving` / `activityTimeSaving` / `sessionSplitSaving`
  / `activitySplitSaving` / `mergeSaving` / `hideSaving` / `deleteSaving`
  states.

Rendering hardening (`renderCorrectionShell`):

- Only display-safe fields are rendered (session: `project_name`,
  `project_description`, `start_time`, `end_time`, `duration`,
  `event_count`, `status`, `is_in_progress`; activity: `activity_id`,
  `time_range`, `resource_name`, `resource_type`, `app_name`,
  `project_name`, `duration`, `is_in_progress`). It never reads raw
  `window_title`, `file_path_hint`, `full_path`, `clipboard`, note
  internals, traceback, SQL errors, or exception messages.
- All dynamic values go through `escapeHtml`; no unescaped external /
  dynamic value is injected via `innerHTML`. Backend times reuse the
  existing `formatTimeRange` helper; `new Date(string)` is never used.
- Shell activity rows carry a distinct `data-correction-activity-id`
  attribute (so they cannot be confused with the real `.detail-item`
  rows). Only a numeric `activity_id` is rendered as a click-to-locate
  target; an invalid / missing id is rendered as a non-clickable `.is-static`
  row.
- An empty activity list shows `暂无活动详情…` without throwing. An
  in-progress session / activity is marked `进行中`; no projected end_time
  is shown as a real closed end_time.
- The action guidance reiterates that hide / delete are soft operations
  (`本阶段不会物理删除数据`) and guides the user back to the existing
  per-activity / session-level controls. No batch / restore / permanent
  delete wording is shown.

Click-to-locate hardening (`highlightDetailRow`):

- Clicking a shell activity row only looks up the existing
  `#timeline-details-list .detail-item[data-activity-id="..."]` row and
  scrolls to / highlights it. It calls **no** bridge method and performs
  no write (no hide / delete / merge / split / time / project / note
  save). It does not switch date or session and does not change
  `selectedSessionId`.
- A stale target (the detail row is gone) shows a safe status message
  (`该活动已不在当前详情中…`) and returns; it never throws.
- The highlight uses a transient `.detail-item-highlight` class on top of
  the persistent `.shell-target` locator. A **single tracked timer**
  (`correctionShellHighlightTimer`) is cleared before each new schedule,
  so repeated clicks never accumulate timers or throw. The timer is also
  cancelled on shell reset.

CSS (`worktrace/webview_ui/styles.css`):

- `.correction-shell[hidden]` remains `display: none`.
- `.detail-item.detail-item-highlight` is a noticeable but not harsh
  transient flash; `.correction-shell-activity-row.is-static` de-emphasizes
  non-clickable rows. Narrow-viewport rules continue to stack the shell
  header and activity rows and keep buttons from overflowing. No external
  fonts / icons / resources are used. Phase 3B.5A action-group styles are
  untouched.

Bridge / API boundary:

- No new bridge method, no new API method, no new service method, no new
  DB schema. The bridge continues to import only `worktrace.api` /
  `worktrace.formatters`.

## Phase 3B.5B.1 Not Implemented

Phase 3B.5B.1 does not implement and does not start:

- Batch edit / batch hide / batch delete;
- Undo / restore;
- Permanent delete;
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge;
- Multi-activity session whole-hide / whole-delete;
- Any new backend write capability;
- Any new DB schema;
- Any new bridge / API / service method;
- Any new correction action.

## Phase 3B.6 Implemented Scope

Phase 3B.6 implements the **first batch write capability** in the WebView
Timeline: **batch project reassignment**. Multiple closed activities
selected in the correction shell (Phase 3B.5B shell) can be reassigned to a
single target project in one operation. This is the **only** batch write
capability introduced in this phase; it is **not** a general batch editing
phase.

Backend write path:

- Service layer (`worktrace/services/activity_service.py`):
  `batch_update_activity_project(activity_ids, project_id) -> int`.
  Validates the activity id list (must be a list, dedup to ≥ 2, each item a
  positive int, reject bool, reject > `MAX_BATCH_PROJECT_EDIT_ACTIVITIES`
  (= 100)), validates the target project (positive int, reject bool, exists,
  not archived, enabled), validates every activity (exists, `is_deleted = 0`,
  `is_hidden = 0`, raw DB `end_time IS NOT NULL` i.e. closed — in-progress
  rejected), then performs a single atomic transaction: UPDATEs each
  activity's effective project consistent with the existing single-edit
  `update_activity_project` / `update_activities_project` semantics (writes
  both `activity_log.project_id` and `activity_project_assignment` rows with
  `is_manual = 1` / `source = 'manual'` / `confidence = 100`, matching the
  manual override semantics), refreshes `updated_at`, applies a rowcount
  guard (any UPDATE affecting 0 rows raises and rolls back), and returns the
  updated activity count. Any validation or write failure rolls back the
  whole transaction so no partial project assignment is left behind. Service
  raises stable `ValueError(code)` codes: `invalid_activity_ids`,
  `batch_too_large`, `invalid_project`, `activity_not_found`,
  `activity_deleted`, `activity_hidden`, `activity_in_progress`,
  `project_update_failed`.
- API layer (`worktrace/api/timeline_api.py`):
  `batch_update_timeline_activities_project(activity_ids, project_id) -> dict`
  returns `{"updated_count": n}`. Defines `TimelineBatchProjectError(ValueError)`
  with stable codes: `invalid_selection`, `batch_too_large`,
  `invalid_project`, `in_progress`, `hidden_activity`, `operation_failed`.
  Service error codes are mapped: `invalid_activity_ids` /
  `activity_not_found` / `activity_deleted` → `invalid_selection`;
  `batch_too_large` → `batch_too_large`; `invalid_project` →
  `invalid_project`; `activity_in_progress` → `in_progress`;
  `activity_hidden` → `hidden_activity`; anything else →
  `operation_failed`. The API never returns raw rows, raw field values,
  tracebacks, SQL errors, or internal exception text.
- Bridge layer (`worktrace/webview_ui/bridge.py`):
  `batch_update_timeline_activities_project(activity_ids, project_id) ->
  dict` returns `{"ok": true, "updated_count": n}` on success and
  `{"ok": false, "error": "<中文错误>"}` on failure. The bridge imports
  only `worktrace.api` / `worktrace.formatters`; it does **not** import
  `services` / `db` / `collector` / `runtime` / `security` / `config`.
  Chinese error message mapping via `_BATCH_PROJECT_ERROR_MESSAGES`:
  `invalid_selection` → `请选择至少两个活动`; `batch_too_large` →
  `一次最多修改 100 条活动`; `invalid_project` → `请选择有效的项目`;
  `in_progress` → `进行中记录暂不支持批量修改`; `hidden_activity` →
  `隐藏记录暂不支持批量修改`; `operation_failed` / unknown → `操作失败`.
  The bridge rejects bool ids and bool project_id at the boundary, never
  returns tracebacks / SQL / `window_title` / `file_path_hint` /
  `full_path` / `clipboard` / note values, and falls back to the generic
  `操作失败` message on any unexpected exception.

Frontend (`worktrace/webview_ui/index.html` / `app.js` / `styles.css`):

- The Phase 3B.5B correction shell gains a dedicated `批量项目重分类`
  section. The section is rendered inside the shell (advanced edit layout),
  not as a new sidebar nav item, and not on the simple detail panel.
- Each eligible shell activity row carries a `correction-shell-activity-checkbox`
  with `data-batch-activity-id`. In-progress activities render with a
  disabled checkbox (and the `is-in-progress` class); non-numeric / `.is-static`
  rows render with a disabled checkbox. Only the current rendered shell
  activity list is selectable.
- Selection state: `selectedBatchActivityIds` (a map of id → true),
  `batchProjectSaving` (bool), `batchProjectTargetId` (project id or null).
  Selection is **never** written to `localStorage` / `sessionStorage`.
- Controls: `全选当前可修改活动` / `清空选择` toggle buttons, a
  `已选择 N 条` count, a target project `<select>` (reusing the existing
  project list cache), and a `批量设置项目` save button. The save button is
  disabled when fewer than 2 activities are selected or no target project is
  chosen. Saving disables the checkboxes / select / buttons.
- Dirty-state guard: `saveBatchProject` refuses while `isEditDirty()` is
  true with `请先保存或取消当前编辑`; it does **not** clear the detail
  list or the selection.
- Save flow: stale selected ids are pruned on every render and re-checked
  against the currently rendered shell rows before the bridge call. On
  success, the selection is cleared and the Timeline is refreshed (the
  selected session is preserved when possible; if the session regroups or
  disappears, the shell is safely closed). On failure, the selection and
  detail list are preserved and a Chinese error is shown without exposing
  tracebacks.
- State boundaries: `clearEditPanel`, `resetCorrectionShellState`,
  `closeCorrectionShell`, `selectTimelineSession` (on switch), and date
  navigation (`goPrevDay` / `goNextDay` / `goToday`) all clear the batch
  selection and reset `batchProjectSaving`. Auto-refresh re-renders the
  batch rows only when the shell is open and not dirty, and prunes stale
  selected ids automatically; it never overwrites the selection while a
  save is in flight. When the selected session disappears, the shell is
  closed and the selection is cleared.
- CSS: the batch section reuses the existing shell styling; checkboxes,
  count, project select, save button, and saving / disabled states are
  clearly indicated; narrow-viewport rules keep the project select and
  button from overflowing. No external fonts / icons / resources are
  used. Phase 3B.5A action-group styles and the Phase 3B.5B shell layout
  are untouched.

Privacy / safety:

- The shell activity rows continue to use display-safe fields only (no raw
  `window_title` / `file_path_hint` / `full_path` / clipboard / note
  internals). The batch save status area never displays tracebacks, SQL
  errors, raw field values, or note old values.
- The bridge returns only `ok` / `updated_count` / `error` (a Chinese
  message); no raw rows are returned to the frontend.
- The WebView bridge boundary is unchanged: the bridge imports only
  `worktrace.api` / `worktrace.formatters`.

DB schema: **no new schema**. The batch write reuses the existing
`activity_project_assignment` and `activity_log.project_id` columns and
the existing single-edit `update_activity_project` /
`update_activities_project` write semantics.

## Phase 3B.6 Not Implemented

Phase 3B.6 does not implement and does not start:

- Batch note editing;
- Batch hide / batch delete (single hide / soft delete from Phase 3B.4
  remains the only visibility write);
- Batch time correction;
- Batch split;
- Batch merge;
- Undo / restore;
- Permanent delete (the existing delete remains a soft delete);
- Auto-rule creation;
- Global overlap detection;
- Arbitrary-length merge (Phase 3B.3 two-activity merge remains the only
  merge);
- Multi-activity session whole-hide / whole-delete;
- Any new DB schema;
- Any React / Vue / Vite / Node dependency;
- Any local HTTP server;
- Any CDN / external JS / CSS / font / Google Fonts usage;
- Any `localStorage` / `sessionStorage` usage;
- Any Tkinter fallback path.

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
